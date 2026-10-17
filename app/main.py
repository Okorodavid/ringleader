"""HTTP API and static UI. One process: FastAPI serves the JSON API and the web/ folder."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import agent, cases, db, seed, tools
from .config import settings

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"

app = FastAPI(title="Ringleader", version="0.1.0")


class InvestigateBody(BaseModel):
    account_id: str = Field(min_length=1, max_length=64)
    provider: str | None = None


class DecisionBody(BaseModel):
    action_ids: list[str] = Field(min_length=1)
    who: str = Field(default="analyst", max_length=120)
    approve: bool = True


class SeedBody(BaseModel):
    reset: bool = False


@app.get("/api/health")
def health() -> dict[str, Any]:
    ok = db.ping()
    out = {"ok": ok, "graph": settings.graph_name, "provider": settings.provider,
           "gemini_configured": bool(settings.gemini_api_key), "host": settings.falkordb_host,
           "port": settings.falkordb_port, "ssl": settings.falkordb_ssl,
           "username_set": bool(settings.falkordb_username), "password_set": bool(settings.falkordb_password)}
    if not ok:
        out["error"] = db.last_error  # connection failure reason, never the credentials themselves
    return out


@app.get("/api/stats")
def stats() -> dict[str, Any]:
    if not db.ping():
        raise HTTPException(503, "FalkorDB unreachable")
    counts = seed.graph_counts()
    frozen = db.read("MATCH (a:Account {status: 'frozen'}) RETURN count(a)").rows[0][0]
    open_cases = db.read("MATCH (c:Case {status: 'pending_review'}) RETURN count(c)").rows[0][0]
    return {"counts": counts, "frozen_accounts": frozen, "open_cases": open_cases}


Q_ALERTS = """
MATCH (a:Account)-[:SENT]->(t:Transaction)-[:TO]->(d:Account)
WITH d, count(DISTINCT a) AS senders, sum(t.amount) AS total
WHERE senders >= 2
MATCH (d)-[:SENT]->(o:Transaction)-[:AT]->(m:Merchant)
WHERE m.category IN $risky
WITH d, senders, total, sum(o.amount) AS risky_out
MATCH (s:Account)-[:SENT]->(:Transaction)-[:TO]->(d)
WITH d, senders, total, risky_out, collect(DISTINCT s)[0] AS sample
RETURN sample.id AS account, sample.name AS name, sample.created_at AS created_at, sample.status AS status,
       d.id AS paid_to, senders AS fan_in, total AS fan_in_total, risky_out,
       'fan-in to ' + d.id + ' which spends at cash-out merchants' AS reason
ORDER BY risky_out DESC
LIMIT 12
"""

Q_ALERTS_SHARED = """
MATCH (x)<-[:USED_DEVICE|HAS_PHONE]-(a:Account)
WITH x, collect(DISTINCT a) AS accs
WHERE size(accs) >= 3
WITH x, accs[0] AS sample, size(accs) AS n
RETURN sample.id AS account, sample.name AS name, sample.created_at AS created_at, sample.status AS status,
       x.id AS identifier, labels(x)[0] AS kind, n AS account_count,
       labels(x)[0] + ' ' + x.id + ' is used by ' + toString(n) + ' accounts' AS reason
ORDER BY n DESC
LIMIT 12
"""


@app.get("/api/alerts")
def alerts() -> dict[str, Any]:
    """The analyst's queue: accounts that tripped a cheap rule. The investigator does the real work."""
    if not db.ping():
        raise HTTPException(503, "FalkorDB unreachable")
    fan_in = db.read(Q_ALERTS, {"risky": tools.RISKY_CATEGORIES})
    shared = db.read(Q_ALERTS_SHARED)
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for row in fan_in.as_dicts():
        if row["account"] not in seen:
            seen.add(row["account"])
            out.append({**row, "rule": "fan_in_cashout"})
    for row in shared.as_dicts():
        if row["account"] not in seen:
            seen.add(row["account"])
            out.append({**row, "rule": "shared_identifier"})
    # a couple of benign-looking seeds so the demo can show a "no ring" verdict
    for row in db.read("MATCH (a:Account)-[:LIVES_AT]->(ad:Address)<-[:LIVES_AT]-(b:Account) "
                       "WHERE a.created_at < '2025-06-01' AND a < b "
                       "RETURN a.id AS account, a.name AS name, a.created_at AS created_at, a.status AS status, "
                       "'shares address ' + ad.id + ' with ' + b.id AS reason ORDER BY account LIMIT 3").as_dicts():
        if row["account"] not in seen:
            seen.add(row["account"])
            out.append({**row, "rule": "shared_address"})
    return {"alerts": out, "queries": [fan_in.to_json(), shared.to_json()]}


@app.get("/api/accounts/{account_id}")
def account(account_id: str) -> dict[str, Any]:
    p = tools.account_profile(account_id)
    if not p.get("found"):
        raise HTTPException(404, "account not found")
    return p.to_json()


@app.get("/api/graph")
def graph_view(ids: str) -> dict[str, Any]:
    account_ids = [i.strip() for i in ids.split(",") if i.strip()][:150]
    if not account_ids:
        raise HTTPException(400, "ids required")
    return tools.subgraph(account_ids).to_json()


@app.get("/api/tools/{name}")
def run_tool(name: str, account_id: str | None = None, account_ids: str | None = None,
             account_a: str | None = None, account_b: str | None = None, max_identifier_hops: int = 3) -> dict[str, Any]:
    """Direct access to each investigator tool, for the explorer panel and for judges."""
    if name not in tools.TOOLS:
        raise HTTPException(404, "unknown tool")
    params = tools.TOOLS[name]["params"]
    args: dict[str, Any] = {}
    if "account_id" in params:
        args["account_id"] = account_id or ""
    if "account_ids" in params:
        args["account_ids"] = [i.strip() for i in (account_ids or "").split(",") if i.strip()]
    if "account_a" in params:
        args["account_a"], args["account_b"] = account_a or "", account_b or ""
    if "max_identifier_hops" in params:
        args["max_identifier_hops"] = max_identifier_hops
    return tools.call(name, args).to_json()


def _sse(events) -> StreamingResponse:
    def gen():
        try:
            for event in events:
                yield f"event: {event['type']}\ndata: {json.dumps(event, default=str)}\n\n"
        except Exception as exc:  # noqa: BLE001 - surface the failure in the stream instead of a dropped socket
            yield f"event: error\ndata: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"
        yield "event: done\ndata: {}\n\n"
    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/investigate")
def investigate(body: InvestigateBody):
    """Run an investigation and stream its steps as server-sent events. The last event carries the case."""
    if not db.ping():
        raise HTTPException(503, "FalkorDB unreachable")
    provider = (body.provider or settings.provider).lower()
    if provider not in ("rules", "gemini"):
        raise HTTPException(400, "provider must be rules or gemini")
    return _sse(agent.investigate(body.account_id, provider=provider))


@app.post("/api/investigate/sync")
def investigate_sync(body: InvestigateBody) -> dict[str, Any]:
    """Same investigation without streaming: returns every event. Handy for scripts and tests."""
    if not db.ping():
        raise HTTPException(503, "FalkorDB unreachable")
    events = list(agent.investigate(body.account_id, provider=(body.provider or settings.provider).lower()))
    return {"events": events}


@app.get("/api/cases")
def list_cases() -> dict[str, Any]:
    return {"cases": cases.list_cases()}


@app.get("/api/cases/{case_id}")
def get_case(case_id: str) -> dict[str, Any]:
    case = cases.get_case(case_id)
    if case is None:
        raise HTTPException(404, "case not found")
    return case


@app.post("/api/cases/{case_id}/decide")
def decide(case_id: str, body: DecisionBody) -> dict[str, Any]:
    if cases.get_case(case_id) is None:
        raise HTTPException(404, "case not found")
    return cases.decide(case_id, body.action_ids, who=body.who, approve=body.approve)


@app.post("/api/seed")
def reseed(body: SeedBody) -> dict[str, Any]:
    if not db.ping():
        raise HTTPException(503, "FalkorDB unreachable")
    if body.reset:
        seed.reset()
    return seed.load()


@app.get("/")
def index() -> FileResponse:
    return FileResponse(WEB / "index.html")


app.mount("/static", StaticFiles(directory=WEB), name="static")
