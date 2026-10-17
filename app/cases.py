"""Case persistence and the human approval gate.

A Case is written when an investigation finishes. It links the seed account, every implicated account
(with the reason and score), the identifiers used as evidence, and the actions the investigator proposes.
Proposed actions are inert until a human approves them; only then does an account's status change.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from . import db


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


Q_CREATE_CASE = """
CREATE (c:Case {id: $id, opened_at: $opened_at, seed: $seed, verdict: $verdict, confidence: $confidence,
                summary: $summary, status: 'pending_review', provider: $provider, trace: $trace})
WITH c
MATCH (s:Account {id: $seed})
CREATE (c)-[:SEED]->(s)
RETURN c.id AS id
"""

Q_IMPLICATE = """
MATCH (c:Case {id: $case_id})
UNWIND $members AS m
MATCH (a:Account {id: m.id})
CREATE (c)-[:IMPLICATES {reason: m.reason, score: m.score, role: m.role}]->(a)
RETURN count(a) AS linked
"""

Q_EVIDENCE = """
MATCH (c:Case {id: $case_id})
UNWIND $evidence AS e
MATCH (x {id: e.id})
CREATE (c)-[:EVIDENCE {kind: e.kind, note: e.note}]->(x)
RETURN count(x) AS linked
"""

Q_PROPOSE = """
MATCH (c:Case {id: $case_id})
UNWIND $actions AS act
CREATE (c)-[:PROPOSES]->(:Action {id: act.id, type: act.type, target: act.target, reason: act.reason,
                                  status: 'pending', proposed_at: $ts})
RETURN count(act) AS proposed
"""


def save_case(seed: str, findings: dict[str, Any], trace: list[dict[str, Any]], provider: str) -> str:
    case_id = "case_" + uuid.uuid4().hex[:8]
    db.write(Q_CREATE_CASE, {
        "id": case_id, "opened_at": _now(), "seed": seed, "verdict": findings["verdict"],
        "confidence": float(findings.get("confidence", 0)), "summary": findings.get("summary", ""),
        "provider": provider, "trace": json.dumps(trace),
    })
    members = [{"id": m["id"], "reason": m.get("reason", ""), "score": float(m.get("score", 0)), "role": m.get("role", "member")}
               for m in findings.get("members", [])]
    if members:
        db.write(Q_IMPLICATE, {"case_id": case_id, "members": members})
    evidence = [{"id": e["id"], "kind": e.get("kind", ""), "note": e.get("note", "")} for e in findings.get("evidence", [])]
    if evidence:
        db.write(Q_EVIDENCE, {"case_id": case_id, "evidence": evidence})
    actions = []
    for i, a in enumerate(findings.get("proposed_actions", [])):
        actions.append({"id": f"{case_id}_a{i + 1}", "type": a["type"], "target": a["target"], "reason": a.get("reason", "")})
    if actions:
        db.write(Q_PROPOSE, {"case_id": case_id, "actions": actions, "ts": _now()})
    return case_id


Q_LIST = """
MATCH (c:Case)
OPTIONAL MATCH (c)-[:IMPLICATES]->(a:Account)
OPTIONAL MATCH (c)-[:PROPOSES]->(x:Action)
RETURN c.id AS id, c.opened_at AS opened_at, c.seed AS seed, c.verdict AS verdict, c.confidence AS confidence,
       c.summary AS summary, c.status AS status, c.provider AS provider,
       count(DISTINCT a) AS implicated, count(DISTINCT x) AS actions,
       size([y IN collect(DISTINCT x) WHERE y.status = 'pending']) AS pending_actions
ORDER BY opened_at DESC
LIMIT 50
"""

Q_GET = """
MATCH (c:Case {id: $id})
OPTIONAL MATCH (c)-[r:IMPLICATES]->(a:Account)
WITH c, collect({id: a.id, name: a.name, status: a.status, reason: r.reason, score: r.score, role: r.role}) AS members
OPTIONAL MATCH (c)-[e:EVIDENCE]->(x)
WITH c, members, collect({id: x.id, kind: e.kind, note: e.note}) AS evidence
OPTIONAL MATCH (c)-[:PROPOSES]->(act:Action)
RETURN c.id AS id, c.opened_at AS opened_at, c.seed AS seed, c.verdict AS verdict, c.confidence AS confidence,
       c.summary AS summary, c.status AS status, c.provider AS provider, c.trace AS trace, members, evidence,
       collect({id: act.id, type: act.type, target: act.target, reason: act.reason, status: act.status,
                approved_by: act.approved_by, approved_at: act.approved_at}) AS actions
"""


def list_cases() -> list[dict[str, Any]]:
    return db.read(Q_LIST).as_dicts()


def get_case(case_id: str) -> dict[str, Any] | None:
    rows = db.read(Q_GET, {"id": case_id}).as_dicts()
    if not rows:
        return None
    case = rows[0]
    case["members"] = [m for m in case["members"] if m.get("id")]
    case["evidence"] = [e for e in case["evidence"] if e.get("id")]
    case["actions"] = [a for a in case["actions"] if a.get("id")]
    try:
        case["trace"] = json.loads(case["trace"]) if case.get("trace") else []
    except json.JSONDecodeError:
        case["trace"] = []
    return case


Q_APPROVE = """
MATCH (c:Case {id: $case_id})-[:PROPOSES]->(x:Action {status: 'pending'})
WHERE x.id IN $action_ids
SET x.status = 'approved', x.approved_by = $who, x.approved_at = $ts
WITH x
MATCH (a:Account {id: x.target})
SET a.status = CASE x.type WHEN 'freeze' THEN 'frozen' WHEN 'monitor' THEN 'monitored' ELSE a.status END
RETURN x.id AS action_id, x.type AS type, a.id AS account, a.status AS status
"""

Q_REJECT = """
MATCH (c:Case {id: $case_id})-[:PROPOSES]->(x:Action {status: 'pending'})
WHERE x.id IN $action_ids
SET x.status = 'rejected', x.approved_by = $who, x.approved_at = $ts
RETURN x.id AS action_id, x.target AS account
"""

Q_CLOSE_IF_DONE = """
MATCH (c:Case {id: $case_id})
OPTIONAL MATCH (c)-[:PROPOSES]->(x:Action {status: 'pending'})
WITH c, count(x) AS pending
SET c.status = CASE WHEN pending = 0 THEN 'closed' ELSE 'pending_review' END
RETURN c.status AS status, pending
"""


def decide(case_id: str, action_ids: list[str], who: str, approve: bool) -> dict[str, Any]:
    q = Q_APPROVE if approve else Q_REJECT
    run = db.write(q, {"case_id": case_id, "action_ids": list(action_ids), "who": who, "ts": _now()})
    status = db.write(Q_CLOSE_IF_DONE, {"case_id": case_id}).as_dicts()
    return {"applied": run.as_dicts(), "case_status": status[0]["status"] if status else None,
            "query": run.to_json()}


Q_ACCOUNT_STATUS = "MATCH (a:Account) WHERE a.id IN $ids RETURN a.id AS id, a.status AS status ORDER BY id"


def account_status(ids: list[str]) -> dict[str, str]:
    return {r["id"]: r["status"] for r in db.read(Q_ACCOUNT_STATUS, {"ids": list(ids)}).as_dicts()}
