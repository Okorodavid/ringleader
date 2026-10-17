"""Graph tools the investigator can call. Every tool is one read-only Cypher query (or two), and every
result carries the exact Cypher that ran so the UI can show it next to the answer.

The queries are the product. Each one crosses at least two relationships; that is where the graph pays.
"""
from __future__ import annotations

from typing import Any

from . import db
from .db import QueryRun

IDENT_RELS = "USED_DEVICE|HAS_PHONE|LIVES_AT|OWNS_CARD|LOGGED_FROM"
RISKY_CATEGORIES = ["crypto", "giftcards", "electronics"]


class ToolResult(dict):
    """A dict with the tool's answer plus the list of queries that produced it."""

    def __init__(self, data: dict[str, Any], queries: list[QueryRun]):
        super().__init__(data)
        self.queries = queries

    def to_json(self) -> dict[str, Any]:
        return {"data": dict(self), "queries": [q.to_json() for q in self.queries]}


# --------------------------------------------------------------------------------------------
# 1. Profile: who is this account and which identifiers does it own
# --------------------------------------------------------------------------------------------
Q_PROFILE = f"""
MATCH (a:Account {{id: $id}})
OPTIONAL MATCH (a)-[r:{IDENT_RELS}]->(x)
RETURN a.id AS id, a.name AS name, a.email AS email, a.created_at AS created_at, a.status AS status,
       a.kyc_level AS kyc_level, a.country AS country,
       collect({{rel: type(r), kind: labels(x)[0], id: x.id, count: r.count}}) AS identifiers
"""

Q_TX_SUMMARY = """
MATCH (a:Account {id: $id})
OPTIONAL MATCH (a)-[:SENT]->(t:Transaction)
WITH a, count(t) AS sent_count, coalesce(sum(t.amount), 0) AS sent_total, min(t.ts) AS first_tx, max(t.ts) AS last_tx
OPTIONAL MATCH (a)<-[:TO]-(r:Transaction)
RETURN sent_count, sent_total, first_tx, last_tx, count(r) AS received_count, coalesce(sum(r.amount), 0) AS received_total
"""


def account_profile(account_id: str) -> ToolResult:
    q1 = db.read(Q_PROFILE, {"id": account_id})
    if not q1.rows:
        return ToolResult({"found": False, "id": account_id}, [q1])
    q2 = db.read(Q_TX_SUMMARY, {"id": account_id})
    profile = q1.as_dicts()[0]
    profile["identifiers"] = [i for i in profile["identifiers"] if i.get("id") is not None]
    profile.update(q2.as_dicts()[0] if q2.rows else {})
    profile["found"] = True
    return ToolResult(profile, [q1, q2])


# --------------------------------------------------------------------------------------------
# 2. Shared identifiers: accounts one identifier away (two hops in the graph)
# --------------------------------------------------------------------------------------------
Q_SHARED = f"""
MATCH (a:Account {{id: $id}})-[:{IDENT_RELS}]->(x)<-[:{IDENT_RELS}]-(b:Account)
WHERE a <> b
WITH b, collect(DISTINCT {{kind: labels(x)[0], id: x.id}}) AS via
RETURN b.id AS account, b.name AS name, b.created_at AS created_at, b.status AS status,
       via, size(via) AS shared_count
ORDER BY shared_count DESC, account
LIMIT 50
"""


def shared_identifiers(account_id: str) -> ToolResult:
    q = db.read(Q_SHARED, {"id": account_id})
    return ToolResult({"seed": account_id, "neighbours": q.as_dicts()}, [q])


# --------------------------------------------------------------------------------------------
# 3. Expand ring: every account reachable through chains of shared identifiers (up to 3 identifier hops)
# --------------------------------------------------------------------------------------------
Q_EXPAND = f"""
MATCH p = (a:Account {{id: $id}})-[:{IDENT_RELS}*2..{{depth}}]-(b:Account)
WHERE a <> b
WITH b, min(length(p)) / 2 AS hops
RETURN b.id AS account, b.name AS name, b.created_at AS created_at, b.status AS status, hops
ORDER BY hops, account
LIMIT 100
"""


def expand_ring(account_id: str, max_identifier_hops: int = 3) -> ToolResult:
    depth = max(1, min(int(max_identifier_hops), 4)) * 2
    q = db.read(Q_EXPAND.replace("{depth}", str(depth)), {"id": account_id})
    members = q.as_dicts()
    return ToolResult({"seed": account_id, "max_identifier_hops": depth // 2, "candidates": members,
                       "candidate_count": len(members)}, [q])


# --------------------------------------------------------------------------------------------
# 4. Identifier fan-out: how many accounts touch each identifier (a phone used by five accounts is the tell)
# --------------------------------------------------------------------------------------------
Q_FANOUT = f"""
MATCH (a:Account)-[:{IDENT_RELS}]->(x)
WHERE a.id IN $ids
WITH DISTINCT x
MATCH (x)<-[:{IDENT_RELS}]-(u:Account)
WITH x, collect(DISTINCT u.id) AS users
WHERE size(users) >= 2
RETURN x.id AS identifier, labels(x)[0] AS kind, size(users) AS account_count, users
ORDER BY account_count DESC, identifier
LIMIT 100
"""


def identifier_fanout(account_ids: list[str]) -> ToolResult:
    q = db.read(Q_FANOUT, {"ids": list(account_ids)})
    return ToolResult({"shared_identifiers": q.as_dicts()}, [q])


# --------------------------------------------------------------------------------------------
# 5. Velocity: how new each account is and how much money moved through it
# --------------------------------------------------------------------------------------------
Q_VELOCITY = """
MATCH (a:Account)
WHERE a.id IN $ids
OPTIONAL MATCH (a)-[:SENT]->(t:Transaction)
WITH a, count(t) AS sent_count, coalesce(sum(t.amount), 0) AS sent_total
OPTIONAL MATCH (a)<-[:TO]-(r:Transaction)
RETURN a.id AS account, a.created_at AS created_at, a.kyc_level AS kyc_level, a.status AS status,
       sent_count, sent_total, count(r) AS received_count, coalesce(sum(r.amount), 0) AS received_total
ORDER BY account
"""


def velocity(account_ids: list[str]) -> ToolResult:
    q = db.read(Q_VELOCITY, {"ids": list(account_ids)})
    return ToolResult({"accounts": q.as_dicts()}, [q])


# --------------------------------------------------------------------------------------------
# 6. Money flow: where does money from this set of accounts converge (fan-in to a cash-out account)
# --------------------------------------------------------------------------------------------
Q_SINKS = """
MATCH (s:Account)-[:SENT]->(t:Transaction)-[:TO]->(d:Account)
WHERE s.id IN $ids AND NOT d.id IN $ids_excluded
WITH d, collect(DISTINCT s.id) AS senders, sum(t.amount) AS total, count(t) AS tx_count
RETURN d.id AS sink, d.name AS name, d.status AS status, d.created_at AS created_at,
       size(senders) AS sender_count, senders, total, tx_count
ORDER BY sender_count DESC, total DESC
LIMIT 10
"""

Q_SPEND = """
MATCH (a:Account {id: $id})-[:SENT]->(t:Transaction)-[:AT]->(m:Merchant)
WITH m.category AS category, count(t) AS tx_count, sum(t.amount) AS total
RETURN category, tx_count, total, category IN $risky AS risky
ORDER BY total DESC
"""


def money_flow(account_ids: list[str], exclude_self: bool = False) -> ToolResult:
    ids = list(account_ids)
    q = db.read(Q_SINKS, {"ids": ids, "ids_excluded": ids if exclude_self else []})
    sinks = q.as_dicts()
    queries = [q]
    for sink in sinks[:3]:
        qs = db.read(Q_SPEND, {"id": sink["sink"], "risky": RISKY_CATEGORIES})
        sink["spend"] = qs.as_dicts()
        sink["risky_spend_total"] = round(sum(r["total"] for r in sink["spend"] if r["risky"]), 2)
        queries.append(qs)
    return ToolResult({"sinks": sinks}, queries)


# --------------------------------------------------------------------------------------------
# 7. Explain link: the shortest chain of shared identifiers between two accounts
# --------------------------------------------------------------------------------------------
Q_PATH = f"""
MATCH (a:Account {{id: $a}}), (b:Account {{id: $b}})
MATCH p = (a)-[:{IDENT_RELS}*2..8]-(b)
RETURN p
ORDER BY length(p)
LIMIT 1
"""


def explain_link(account_a: str, account_b: str) -> ToolResult:
    q = db.read(Q_PATH, {"a": account_a, "b": account_b})
    if not q.rows:
        return ToolResult({"from": account_a, "to": account_b, "connected": False, "path": None}, [q])
    path = q.rows[0][0]
    steps = []
    nodes = path["nodes"]
    for i in range(1, len(nodes)):
        n = nodes[i]
        steps.append({"kind": n["labels"][0], "id": n["props"].get("id"), "name": n["props"].get("name")})
    return ToolResult({"from": account_a, "to": account_b, "connected": True, "hops": len(path["edges"]) // 2,
                       "path": path, "chain": steps}, [q])


# --------------------------------------------------------------------------------------------
# 8. Prior cases: has anyone in this set been investigated before (memory that compounds)
# --------------------------------------------------------------------------------------------
Q_PRIOR = """
MATCH (c:Case)-[r:SEED|IMPLICATES]->(a:Account)
WHERE a.id IN $ids
WITH c, collect(DISTINCT a.id) AS accounts
RETURN c.id AS case_id, c.verdict AS verdict, c.confidence AS confidence, c.status AS status,
       c.opened_at AS opened_at, c.summary AS summary, accounts
ORDER BY opened_at DESC
LIMIT 10
"""


def prior_cases(account_ids: list[str]) -> ToolResult:
    q = db.read(Q_PRIOR, {"ids": list(account_ids)})
    return ToolResult({"cases": q.as_dicts()}, [q])


# --------------------------------------------------------------------------------------------
# 9. Subgraph for the canvas: accounts, their identifiers, and the money between them
# --------------------------------------------------------------------------------------------
Q_SUBGRAPH_IDENT = f"""
MATCH (a:Account)-[r:{IDENT_RELS}]->(x)
WHERE a.id IN $ids
RETURN a, r, x
"""

Q_SUBGRAPH_MONEY = """
MATCH (s:Account)-[:SENT]->(t:Transaction)-[:TO]->(d:Account)
WHERE s.id IN $ids AND d.id IN $ids
RETURN s.id AS src, d.id AS dst, count(t) AS tx_count, sum(t.amount) AS total
"""


def subgraph(account_ids: list[str]) -> ToolResult:
    ids = list(account_ids)
    q1 = db.read(Q_SUBGRAPH_IDENT, {"ids": ids})
    q2 = db.read(Q_SUBGRAPH_MONEY, {"ids": ids})
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []
    seen = set()
    for a, r, x in q1.rows:
        for n in (a, x):
            nid = n["props"]["id"]
            if nid not in nodes:
                nodes[nid] = {"id": nid, "kind": n["labels"][0], "label": n["props"].get("name") or n["props"].get("street") or nid,
                              "status": n["props"].get("status"), "created_at": n["props"].get("created_at")}
        key = (a["props"]["id"], r["type"], x["props"]["id"])
        if key not in seen:
            seen.add(key)
            edges.append({"src": key[0], "dst": key[2], "type": r["type"], "count": r["props"].get("count", 1)})
    for row in q2.as_dicts():
        edges.append({"src": row["src"], "dst": row["dst"], "type": "PAID", "count": row["tx_count"], "total": row["total"]})
    return ToolResult({"nodes": list(nodes.values()), "edges": edges}, [q1, q2])


# --------------------------------------------------------------------------------------------
# Registry used by both investigators and the API
# --------------------------------------------------------------------------------------------
TOOLS: dict[str, dict[str, Any]] = {
    "account_profile": {
        "fn": account_profile,
        "description": "Profile of one account: identity fields, every identifier it owns (devices, phones, cards, addresses, IPs) and its transaction totals.",
        "params": {"account_id": "string"},
    },
    "shared_identifiers": {
        "fn": shared_identifiers,
        "description": "Accounts that share at least one identifier with this account (two hops: account -> identifier <- account). Returns which identifiers are shared.",
        "params": {"account_id": "string"},
    },
    "expand_ring": {
        "fn": expand_ring,
        "description": "Every account reachable from this one through chains of shared identifiers, up to max_identifier_hops (default 3). Use it to find the whole cluster, not just direct neighbours.",
        "params": {"account_id": "string", "max_identifier_hops": "integer"},
    },
    "identifier_fanout": {
        "fn": identifier_fanout,
        "description": "For a set of accounts, list each identifier that is used by two or more accounts and who uses it. A phone or device used by many accounts is the strongest ring signal.",
        "params": {"account_ids": "array of string"},
    },
    "velocity": {
        "fn": velocity,
        "description": "Account age, KYC level, and money in and out for a set of accounts. New accounts moving large sums quickly is a bust-out signal.",
        "params": {"account_ids": "array of string"},
    },
    "money_flow": {
        "fn": money_flow,
        "description": "Where money sent by these accounts converges: receiving accounts ranked by how many of the given accounts paid them, plus what the top receivers spend on (crypto, gift cards and electronics are cash-out categories).",
        "params": {"account_ids": "array of string"},
    },
    "explain_link": {
        "fn": explain_link,
        "description": "The shortest chain of shared identifiers connecting two accounts. Use it to justify why an account belongs to the ring.",
        "params": {"account_a": "string", "account_b": "string"},
    },
    "prior_cases": {
        "fn": prior_cases,
        "description": "Earlier investigations that touched any of these accounts, with their verdicts. Check this before deciding; precedent matters.",
        "params": {"account_ids": "array of string"},
    },
}


def call(name: str, args: dict[str, Any]) -> ToolResult:
    spec = TOOLS[name]
    return spec["fn"](**args)
