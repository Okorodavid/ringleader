"""The investigator. Two providers share one protocol:

  * rules  - deterministic, offline, free. Calls the graph tools in a fixed order and scores every
             account in the cluster with an explainable rule. Used by tests, evals, and as the no-key demo.
  * gemini - an LLM (Gemini free tier) that chooses which tools to call and must finish by calling
             submit_findings with the same structured schema.

Both yield a stream of events so the UI can show the investigation as it happens. Both end with a
Case written to the graph. Neither can change an account: actions are proposals until a human approves.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any, Iterator

from . import db, cases, tools
from .config import settings

NEW_ACCOUNT_DAYS = 21
FLAG_THRESHOLD = 6
MAX_STEPS = 14

Q_NOW = "MATCH (t:Transaction) RETURN max(t.ts) AS now"


def graph_now() -> datetime:
    """The dataset's notion of now: the latest transaction. Keeps age maths stable for synthetic data."""
    rows = db.read(Q_NOW).rows
    raw = rows[0][0] if rows and rows[0][0] else None
    if raw:
        return datetime.fromisoformat(raw)
    return datetime.now(timezone.utc)


def _age_days(created_at: str | None, now: datetime) -> float:
    if not created_at:
        return 9999
    return (now - datetime.fromisoformat(created_at)).total_seconds() / 86400


def _ngn(v: float) -> str:
    return f"NGN {v:,.0f}"


# ------------------------------------------------------------------------------------------------
# Event helpers
# ------------------------------------------------------------------------------------------------
def _tool_event(name: str, args: dict[str, Any], result: tools.ToolResult, summary: str) -> dict[str, Any]:
    return {"type": "tool", "name": name, "args": args, "summary": summary, "result": result.to_json(), "ts": time.time()}


def _compact(result: tools.ToolResult, limit: int = 40) -> dict[str, Any]:
    """Trim tool output before it goes to an LLM: cap list sizes and drop raw path blobs."""
    def trim(v: Any) -> Any:
        if isinstance(v, list):
            return [trim(x) for x in v[:limit]] + ([f"... {len(v) - limit} more"] if len(v) > limit else [])
        if isinstance(v, dict):
            return {k: trim(x) for k, x in v.items() if k != "path"}
        return v
    return trim(dict(result))


# ------------------------------------------------------------------------------------------------
# Rules investigator
# ------------------------------------------------------------------------------------------------
def investigate_rules(seed: str) -> Iterator[dict[str, Any]]:
    yield {"type": "start", "seed": seed, "provider": "rules"}
    now = graph_now()

    profile = tools.account_profile(seed)
    if not profile.get("found"):
        yield {"type": "error", "message": f"account {seed} not found"}
        return
    yield _tool_event("account_profile", {"account_id": seed}, profile,
                      f"{profile['name']}, opened {profile['created_at'][:10]}, {len(profile['identifiers'])} identifiers, "
                      f"sent {_ngn(profile['sent_total'])} in {profile['sent_count']} transactions")

    shared = tools.shared_identifiers(seed)
    yield _tool_event("shared_identifiers", {"account_id": seed}, shared,
                      f"{len(shared['neighbours'])} accounts share an identifier with {seed}")

    expanded = tools.expand_ring(seed, 3)
    cluster = [seed] + [c["account"] for c in expanded["candidates"]]
    yield _tool_event("expand_ring", {"account_id": seed, "max_identifier_hops": 3}, expanded,
                      f"{len(cluster) - 1} accounts reachable within 3 identifier hops")

    fanout = tools.identifier_fanout(cluster)
    yield _tool_event("identifier_fanout", {"account_ids": cluster}, fanout,
                      f"{len(fanout['shared_identifiers'])} identifiers are used by two or more accounts in the cluster")

    vel = tools.velocity(cluster)
    yield _tool_event("velocity", {"account_ids": cluster}, vel,
                      f"age and money totals for {len(vel['accounts'])} accounts")

    flow = tools.money_flow(cluster)
    sinks = flow["sinks"]
    top = sinks[0] if sinks else None
    yield _tool_event("money_flow", {"account_ids": cluster}, flow,
                      (f"money converges on {top['sink']} from {top['sender_count']} accounts, {_ngn(top['total'])}"
                       if top else "no transfers between cluster accounts"))

    prior = tools.prior_cases(cluster)
    yield _tool_event("prior_cases", {"account_ids": cluster}, prior,
                      f"{len(prior['cases'])} earlier cases touch this cluster")

    # ---- scoring ------------------------------------------------------------------------------
    cluster_set = set(cluster)
    shared_by_account: dict[str, list[dict[str, Any]]] = {a: [] for a in cluster}
    for ident in fanout["shared_identifiers"]:
        users_in_cluster = [u for u in ident["users"] if u in cluster_set]
        if len(users_in_cluster) >= 2:
            for u in users_in_cluster:
                shared_by_account[u].append(ident)
    vel_by_account = {v["account"]: v for v in vel["accounts"]}

    cashout = None
    if top and ((top["sender_count"] >= 3 and top["total"] >= 100_000) or top.get("risky_spend_total", 0) > 0):
        cashout = top

    scored: list[dict[str, Any]] = []
    for acc in cluster:
        v = vel_by_account.get(acc, {})
        age = _age_days(v.get("created_at"), now)
        shared_ids = shared_by_account[acc]
        reasons: list[str] = []
        score = 0.0
        if shared_ids:
            pts = 2 * min(len(shared_ids), 3)
            score += pts
            kinds = sorted({s["kind"].lower() for s in shared_ids})
            reasons.append(f"shares {len(shared_ids)} identifier(s) ({', '.join(kinds)}) with other cluster accounts")
        if age <= NEW_ACCOUNT_DAYS:
            score += 3
            reasons.append(f"account is {age:.0f} days old")
        if cashout and acc in cashout["senders"]:
            score += 3
            reasons.append(f"sent money to cash-out account {cashout['sink']}")
        if cashout and acc == cashout["sink"]:
            score += 4
            reasons.append(f"received {_ngn(cashout['total'])} from {cashout['sender_count']} cluster accounts")
            if cashout.get("risky_spend_total", 0) > 0:
                score += 1
                reasons.append(f"spent {_ngn(cashout['risky_spend_total'])} at crypto, gift-card or electronics merchants")
        role = "seed" if acc == seed else ("cashout" if cashout and acc == cashout["sink"] else "member")
        scored.append({"id": acc, "role": role, "score": score, "reasons": reasons, "age_days": round(age, 1),
                       "status": v.get("status"), "flagged": score >= FLAG_THRESHOLD})

    flagged = [s for s in scored if s["flagged"]]
    yield {"type": "thought", "text": f"Scored {len(scored)} accounts; {len(flagged)} at or above {FLAG_THRESHOLD}."}

    # explain two of the longer links for the record
    explain_targets = sorted((s for s in flagged if s["id"] != seed), key=lambda s: -s["score"])[:2]
    for target in explain_targets:
        link = tools.explain_link(seed, target["id"])
        chain = " -> ".join(f"{c['kind']}:{c['id']}" for c in link.get("chain", [])) if link["connected"] else "no path"
        yield _tool_event("explain_link", {"account_a": seed, "account_b": target["id"]}, link,
                          f"{seed} to {target['id']}: {chain}")

    if len(flagged) >= 3:
        verdict = "ring"
        confidence = min(0.98, 0.55 + 0.04 * len(flagged) + (0.2 if cashout else 0))
    elif flagged:
        verdict = "uncertain"
        confidence = 0.5
    else:
        verdict = "benign"
        confidence = 0.85 if len(cluster) <= 6 else 0.7

    if verdict == "ring":
        summary = (f"{len(flagged)} connected accounts form a ring around {seed}. They share "
                   f"{len(fanout['shared_identifiers'])} identifiers"
                   + (f" and funnel {_ngn(cashout['total'])} into {cashout['sink']}, which cashes out at risky merchants." if cashout else "."))
    elif verdict == "benign":
        summary = (f"{seed} is linked to {len(cluster) - 1} account(s) but the links look like a household: "
                   f"long-standing accounts, small mutual transfers, no cash-out sink.")
    else:
        summary = f"{len(flagged)} account(s) look suspicious but the cluster is too small to call a ring."

    members = [{"id": s["id"], "role": s["role"], "score": s["score"], "reason": "; ".join(s["reasons"])} for s in flagged]
    evidence = [{"id": i["identifier"], "kind": i["kind"], "note": f"used by {i['account_count']} accounts"}
                for i in fanout["shared_identifiers"][:12]]
    actions = []
    for s in flagged:
        if s["status"] == "active":
            actions.append({"type": "freeze", "target": s["id"], "reason": "; ".join(s["reasons"])})
    for s in scored:
        if not s["flagged"] and s["score"] >= 4 and s["age_days"] <= NEW_ACCOUNT_DAYS and s["status"] == "active":
            actions.append({"type": "monitor", "target": s["id"], "reason": "; ".join(s["reasons"])})

    findings = {"verdict": verdict, "confidence": round(confidence, 2), "summary": summary, "members": members,
                "evidence": evidence, "proposed_actions": actions, "scored": scored,
                "prior_cases": prior["cases"], "cluster": cluster}
    yield {"type": "findings", "findings": findings}


# ------------------------------------------------------------------------------------------------
# Gemini investigator
# ------------------------------------------------------------------------------------------------
SYSTEM_PROMPT = """You are a fraud ring investigator for a payments company. You are given one suspicious
account id. Your job: decide whether it belongs to a fraud ring, name every account in the ring, and
propose actions. You can only learn about accounts through the graph tools; never invent accounts.

Protocol (follow it, in this order, then decide):
1. account_profile on the seed.
2. expand_ring on the seed (max_identifier_hops 3) to find the whole cluster of accounts connected
   through shared devices, phones, cards, addresses and IPs.
3. identifier_fanout on the cluster to see which identifiers are shared and by whom.
4. velocity on the cluster to see account ages and money totals.
5. money_flow on the cluster to see whether money converges on a cash-out account and what it spends on.
6. prior_cases on the cluster.
7. explain_link from the seed to one or two of the strongest members so the case file has the path.
8. Call submit_findings exactly once with your decision.

How to judge. A fraud ring looks like: several accounts created within days of each other, sharing
phones/devices/cards (not just one address), funnelling money into one account that spends at crypto,
gift-card or electronics merchants. A benign household looks like: long-standing accounts that share a
home address and one tablet, with small transfers between family members and ordinary merchant spend.
Do not flag household members. Flag only accounts with at least two independent signals.

Every member you flag needs a concrete reason citing identifiers or transfers that the tools returned.
Propose a freeze for every flagged account, and monitor for new accounts you are unsure about."""

FINDINGS_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["ring", "benign", "uncertain"]},
        "confidence": {"type": "number", "description": "0 to 1"},
        "summary": {"type": "string", "description": "Two or three sentences an analyst can read."},
        "members": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "role": {"type": "string", "enum": ["seed", "member", "cashout"]},
                    "score": {"type": "number", "description": "0 to 10, your strength of belief"},
                    "reason": {"type": "string"},
                },
                "required": ["id", "role", "score", "reason"],
            },
        },
        "evidence": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"id": {"type": "string"}, "kind": {"type": "string"}, "note": {"type": "string"}},
                "required": ["id", "kind"],
            },
        },
        "proposed_actions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": ["freeze", "monitor"]},
                    "target": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["type", "target", "reason"],
            },
        },
    },
    "required": ["verdict", "confidence", "summary", "members", "evidence", "proposed_actions"],
}


def _gemini_declarations():
    from google.genai import types

    def schema_for(params: dict[str, str]) -> dict[str, Any]:
        props = {}
        for name, kind in params.items():
            if kind == "array of string":
                props[name] = {"type": "array", "items": {"type": "string"}}
            elif kind == "integer":
                props[name] = {"type": "integer"}
            else:
                props[name] = {"type": "string"}
        required = [n for n in params if n != "max_identifier_hops"]
        return {"type": "object", "properties": props, "required": required}

    decls = [types.FunctionDeclaration(name=name, description=spec["description"], parameters=schema_for(spec["params"]))
             for name, spec in tools.TOOLS.items()]
    decls.append(types.FunctionDeclaration(
        name="submit_findings",
        description="Finish the investigation with a structured verdict. Call exactly once, last.",
        parameters=FINDINGS_SCHEMA,
    ))
    return [types.Tool(function_declarations=decls)]


def _validate_findings(f: dict[str, Any]) -> dict[str, Any]:
    out = {
        "verdict": f.get("verdict") if f.get("verdict") in ("ring", "benign", "uncertain") else "uncertain",
        "confidence": max(0.0, min(1.0, float(f.get("confidence", 0.5)))),
        "summary": str(f.get("summary", "")),
        "members": [], "evidence": [], "proposed_actions": [],
    }
    for m in f.get("members", []) or []:
        if m.get("id"):
            out["members"].append({"id": str(m["id"]), "role": m.get("role", "member"), "score": float(m.get("score", 0)),
                                   "reason": str(m.get("reason", ""))})
    for e in f.get("evidence", []) or []:
        if e.get("id"):
            out["evidence"].append({"id": str(e["id"]), "kind": str(e.get("kind", "")), "note": str(e.get("note", ""))})
    for a in f.get("proposed_actions", []) or []:
        if a.get("target") and a.get("type") in ("freeze", "monitor"):
            out["proposed_actions"].append({"type": a["type"], "target": str(a["target"]), "reason": str(a.get("reason", ""))})
    return out


def investigate_gemini(seed: str) -> Iterator[dict[str, Any]]:
    from google import genai
    from google.genai import types
    from google.genai import errors as genai_errors

    if not settings.gemini_api_key:
        yield {"type": "error", "message": "GEMINI_API_KEY is not set; use PROVIDER=rules or add a free key"}
        return
    yield {"type": "start", "seed": seed, "provider": "gemini", "model": settings.gemini_model}
    client = genai.Client(api_key=settings.gemini_api_key)
    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        tools=_gemini_declarations(),
        temperature=0.1,
        tool_config=types.ToolConfig(function_calling_config=types.FunctionCallingConfig(mode="AUTO")),
    )
    contents = [types.Content(role="user", parts=[types.Part.from_text(
        text=f"Investigate account {seed}. Follow the protocol and finish with submit_findings.")])]

    class QuotaExhausted(RuntimeError):
        pass

    def retry_after_seconds(exc: Exception) -> float | None:
        """Pull the server's RetryInfo.retryDelay out of a 429 so we do not retry a daily quota for hours."""
        details = getattr(exc, "details", None) or {}
        try:
            for d in details.get("error", {}).get("details", []):
                if str(d.get("@type", "")).endswith("RetryInfo"):
                    return float(str(d.get("retryDelay", "0s")).rstrip("s"))
        except (AttributeError, ValueError, TypeError):
            return None
        return None

    def generate():
        delay = 5
        for attempt in range(4):
            try:
                return client.models.generate_content(model=settings.gemini_model, contents=contents, config=config)
            except genai_errors.APIError as exc:
                if exc.code == 429:
                    wait = retry_after_seconds(exc)
                    if wait is not None and wait > 120:
                        raise QuotaExhausted(
                            f"Gemini free-tier quota is exhausted for {settings.gemini_model}; the API says retry in "
                            f"{wait / 3600:.1f} h. Use PROVIDER=rules meanwhile.") from exc
                if exc.code in (429, 503) and attempt < 3:
                    time.sleep(delay)
                    delay *= 2
                    continue
                raise

    for step in range(MAX_STEPS):
        try:
            response = generate()
        except QuotaExhausted as exc:
            yield {"type": "error", "message": str(exc)}
            return
        candidate = response.candidates[0] if response.candidates else None
        if candidate is None or candidate.content is None:
            yield {"type": "error", "message": "model returned no content"}
            return
        contents.append(candidate.content)
        calls = [p.function_call for p in (candidate.content.parts or []) if getattr(p, "function_call", None)]
        texts = [p.text for p in (candidate.content.parts or []) if getattr(p, "text", None)]
        for t in texts:
            if t.strip():
                yield {"type": "thought", "text": t.strip()}
        if not calls:
            contents.append(types.Content(role="user", parts=[types.Part.from_text(
                text="You have not called submit_findings. Call it now with your structured decision.")]))
            continue
        response_parts = []
        for call in calls:
            name = call.name
            args = dict(call.args or {})
            if name == "submit_findings":
                findings = _validate_findings(args)
                yield {"type": "findings", "findings": findings}
                return
            if name not in tools.TOOLS:
                response_parts.append(types.Part.from_function_response(name=name, response={"error": f"unknown tool {name}"}))
                continue
            try:
                result = tools.call(name, args)
            except Exception as exc:  # noqa: BLE001 - report the failure to the model and the UI
                yield {"type": "error", "message": f"{name} failed: {exc}", "recoverable": True}
                response_parts.append(types.Part.from_function_response(name=name, response={"error": str(exc)}))
                continue
            yield _tool_event(name, args, result, f"{name} returned {len(result.queries)} query result(s)")
            response_parts.append(types.Part.from_function_response(name=name, response={"result": _compact(result)}))
        contents.append(types.Content(role="user", parts=response_parts))
    yield {"type": "error", "message": f"investigation did not finish within {MAX_STEPS} steps"}


# ------------------------------------------------------------------------------------------------
# Entry point: run, persist, and stream
# ------------------------------------------------------------------------------------------------
def investigate(seed: str, provider: str | None = None) -> Iterator[dict[str, Any]]:
    provider = (provider or settings.provider).lower()
    runner = investigate_gemini if provider == "gemini" else investigate_rules
    trace: list[dict[str, Any]] = []
    findings = None
    for event in runner(seed):
        if event["type"] == "tool":
            trace.append({"type": "tool", "name": event["name"], "args": event["args"], "summary": event["summary"],
                          "queries": [{"cypher": q["cypher"], "params": q["params"], "run_ms": q["run_ms"], "rows": len(q["rows"])}
                                      for q in event["result"]["queries"]]})
        elif event["type"] == "thought":
            trace.append({"type": "thought", "text": event["text"]})
        elif event["type"] == "findings":
            findings = event["findings"]
        yield event
    if findings is not None:
        case_id = cases.save_case(seed, findings, trace, provider)
        yield {"type": "case", "case_id": case_id, "case": cases.get_case(case_id)}
