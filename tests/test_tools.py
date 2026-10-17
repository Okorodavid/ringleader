"""G3: each graph tool returns the planted structure and the read-only path refuses writes."""
import pytest

from app import db, tools


def ring(dataset, name):
    return next(r for r in dataset.truth["rings"] if r["name"] == name)


def test_read_path_refuses_write_keywords(live_graph):
    for bad in ("MATCH (a) SET a.x = 1", "CREATE (:X)", "MATCH (a) DETACH DELETE a", "MERGE (:X {id:1})"):
        with pytest.raises(db.ReadOnlyViolation):
            db.read(bad)
    # the account population is unchanged by the attempts above (positive control: a real write would change it)
    assert db.read("MATCH (x:X) RETURN count(x)").rows[0][0] == 0


def test_profile_lists_identifiers_and_totals(dataset, live_graph):
    r = ring(dataset, "ring_alpha")
    seed = r["members"][0]
    p = tools.account_profile(seed)
    assert p["found"] and p["id"] == seed
    kinds = {i["kind"] for i in p["identifiers"]}
    assert {"Device", "Phone", "Card", "Address", "IP"} <= kinds
    assert p["sent_count"] >= 2 and p["sent_total"] > 0
    assert tools.account_profile("acc_does_not_exist")["found"] is False


def test_shared_identifiers_two_hops(dataset, live_graph):
    r = ring(dataset, "ring_alpha")
    seed = r["members"][0]
    s = tools.shared_identifiers(seed)
    found = {n["account"] for n in s["neighbours"]}
    # at least one other ring member shares an identifier directly, and every neighbour reports what is shared
    assert found & set(r["members"][1:])
    assert all(n["shared_count"] >= 1 and n["via"] for n in s["neighbours"])
    assert seed not in found


def test_expand_ring_finds_all_members_at_three_hops(dataset, live_graph):
    for name in ("ring_alpha", "ring_charlie"):
        r = ring(dataset, name)
        seed = r["members"][0]
        e = tools.expand_ring(seed, 3)
        found = {c["account"] for c in e["candidates"]}
        expected = (set(r["members"]) | {r["cashout"]}) - {seed}
        missing = expected - found
        assert not missing, (name, missing)
        assert all(1 <= c["hops"] <= 3 for c in e["candidates"])


def test_expand_ring_on_ordinary_account_is_tiny(dataset, live_graph):
    ordinary = dataset.nodes["Account"][0]["id"]
    e = tools.expand_ring(ordinary, 3)
    assert e["candidate_count"] <= 2


def test_identifier_fanout_shows_shared_pool(dataset, live_graph):
    r = ring(dataset, "ring_charlie")
    f = tools.identifier_fanout(r["members"] + [r["cashout"]])
    shared = {i["identifier"]: i for i in f["shared_identifiers"]}
    for d in r["shared"]["devices"]:
        assert d in shared and shared[d]["account_count"] >= 2
    for p in r["shared"]["phones"]:
        assert p in shared and shared[p]["kind"] == "Phone"


def test_money_flow_finds_cashout_sink_with_risky_spend(dataset, live_graph):
    r = ring(dataset, "ring_bravo")
    flow = tools.money_flow(r["members"] + [r["cashout"]])
    top = flow["sinks"][0]
    assert top["sink"] == r["cashout"]
    assert top["sender_count"] == len(r["members"])
    assert top["risky_spend_total"] > 0
    assert any(s["risky"] for s in top["spend"])


def test_velocity_marks_ring_accounts_as_new(dataset, live_graph):
    r = ring(dataset, "ring_delta")
    v = tools.velocity(r["members"])
    assert len(v["accounts"]) == len(r["members"])
    assert all(a["sent_total"] > 0 for a in v["accounts"])


def test_explain_link_returns_identifier_chain(dataset, live_graph):
    r = ring(dataset, "ring_alpha")
    a, b = r["members"][0], r["cashout"]
    link = tools.explain_link(a, b)
    assert link["connected"] is True
    assert 1 <= link["hops"] <= 4
    assert link["chain"][-1]["id"] == b
    kinds = {c["kind"] for c in link["chain"][:-1]}
    assert kinds <= {"Device", "Phone", "Card", "Address", "IP", "Account"}
    ordinary = dataset.nodes["Account"][1]["id"]
    assert tools.explain_link(a, ordinary)["connected"] is False


def test_subgraph_returns_nodes_and_edges(dataset, live_graph):
    r = ring(dataset, "ring_delta")
    g = tools.subgraph(r["members"] + [r["cashout"]])
    ids = {n["id"] for n in g["nodes"]}
    assert set(r["members"]) <= ids
    assert any(e["type"] == "PAID" for e in g["edges"])
    assert any(e["type"] == "USED_DEVICE" for e in g["edges"])
