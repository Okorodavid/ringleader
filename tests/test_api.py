"""G7: the HTTP API serves alerts, runs an investigation end to end, persists the case, and approves actions."""
import json

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client(live_graph):
    return TestClient(app)


def test_health_and_stats(client):
    h = client.get("/api/health").json()
    assert h["ok"] is True
    s = client.get("/api/stats").json()
    assert s["counts"]["node:Account"] >= 400


def test_alerts_queue_includes_ring_seeds(client, dataset):
    body = client.get("/api/alerts").json()
    alerts = body["alerts"]
    assert alerts and body["queries"][0]["cypher"]
    ring_ids = set(dataset.truth["ring_member_ids"])
    assert any(a["account"] in ring_ids for a in alerts)
    assert any(a["rule"] == "shared_address" for a in alerts)
    assert all(a["reason"] for a in alerts)


def test_tool_endpoint_and_graph_view(client, dataset):
    ring = dataset.truth["rings"][2]
    r = client.get("/api/tools/expand_ring", params={"account_id": ring["members"][0]}).json()
    assert r["data"]["candidate_count"] >= len(ring["members"]) - 1
    assert r["queries"][0]["cypher"].startswith("MATCH")
    g = client.get("/api/graph", params={"ids": ",".join(ring["members"][:4])}).json()
    assert g["data"]["nodes"] and g["data"]["edges"]
    assert client.get("/api/tools/nope").status_code == 404
    assert client.get("/api/accounts/acc_missing").status_code == 404


def test_streaming_investigation_then_approve(client, dataset):
    ring = dataset.truth["rings"][2]
    seed_id = ring["members"][4]
    with client.stream("POST", "/api/investigate", json={"account_id": seed_id, "provider": "rules"}) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        raw = "".join(resp.iter_text())
    events = []
    for block in raw.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        if lines.get("data") and lines["data"] != "{}":
            events.append(json.loads(lines["data"]))
    types = [e["type"] for e in events]
    assert types[0] == "start" and "findings" in types and types[-1] == "case"
    tool_names = [e["name"] for e in events if e["type"] == "tool"]
    assert {"expand_ring", "money_flow", "prior_cases"} <= set(tool_names)
    case = events[-1]["case"]
    assert case["verdict"] == "ring"
    assert client.get(f"/api/cases/{case['id']}").json()["id"] == case["id"]
    assert any(c["id"] == case["id"] for c in client.get("/api/cases").json()["cases"])

    pending = [a["id"] for a in case["actions"] if a["type"] == "freeze"][:2]
    targets = [a["target"] for a in case["actions"] if a["id"] in pending]
    before = {a["id"]: a["status"] for a in client.get(f"/api/cases/{case['id']}").json()["members"]}
    assert all(before[t] in ("active", "frozen") for t in targets)
    d = client.post(f"/api/cases/{case['id']}/decide", json={"action_ids": pending, "who": "judge", "approve": True}).json()
    assert {row["account"] for row in d["applied"]} == set(targets)
    after = {m["id"]: m["status"] for m in client.get(f"/api/cases/{case['id']}").json()["members"]}
    assert all(after[t] == "frozen" for t in targets)
    assert client.post("/api/cases/nope/decide", json={"action_ids": ["x"]}).status_code == 404


def test_index_serves_ui(client):
    r = client.get("/")
    assert r.status_code == 200 and "<title>" in r.text
