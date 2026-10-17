"""G1: the synthetic dataset is deterministic, plants rings and households, and keeps ground truth out of graph rows."""
import json

from app.generator import build

EDGE_RELS = {"USED_DEVICE", "HAS_PHONE", "LIVES_AT", "OWNS_CARD", "LOGGED_FROM", "SENT", "TO", "AT"}


def test_same_seed_same_rows():
    a, b = build(7), build(7)
    assert json.dumps({"n": a.nodes, "e": a.edges}, sort_keys=True) == json.dumps({"n": b.nodes, "e": b.edges}, sort_keys=True)
    assert a.truth == b.truth


def test_different_seed_different_rows():
    assert build(7).nodes["Account"] != build(8).nodes["Account"]


def test_rings_and_households_are_planted():
    ds = build(7)
    assert len(ds.truth["rings"]) == 4
    sizes = sorted(len(r["members"]) for r in ds.truth["rings"])
    assert sizes == [5, 6, 9, 12]
    assert len(ds.truth["households"]) == 4
    assert all(3 <= len(h) <= 5 for h in ds.truth["households"])
    # rings and households are disjoint, and both are subsets of the account population
    ids = {a["id"] for a in ds.nodes["Account"]}
    ring_ids, hh_ids = set(ds.truth["ring_member_ids"]), set(ds.truth["household_ids"])
    assert ring_ids <= ids and hh_ids <= ids
    assert not (ring_ids & hh_ids)


def test_ring_members_share_identifiers_and_fan_in_to_cashout():
    ds = build(7)
    dev_edges = {}
    for e in ds.edges["USED_DEVICE"]:
        dev_edges.setdefault(e["dst"], set()).add(e["src"])
    sent = {}
    for e in ds.edges["SENT"]:
        sent[e["dst"]] = e["src"]
    to = {}
    for e in ds.edges["TO"]:
        to.setdefault(e["dst"], set()).add(sent[e["src"]])
    for ring in ds.truth["rings"]:
        members = set(ring["members"])
        # every shared device in the ring pool is used by at least two members
        for d in ring["shared"]["devices"]:
            assert len(dev_edges[d] & (members | {ring["cashout"]})) >= 2, ring["name"]
        # every member sent money to the cash-out account
        assert members <= to[ring["cashout"]], ring["name"]


def test_ground_truth_never_appears_in_graph_rows():
    ds = build(7)
    blob = json.dumps({"n": ds.nodes, "e": ds.edges})
    for word in ("ring_alpha", "ring_bravo", "ring_charlie", "ring_delta", "cashout", "household", "truth"):
        assert word not in blob, word
    for props in ds.nodes["Account"]:
        assert set(props) == {"id", "name", "email", "created_at", "country", "status", "kyc_level"}
        assert props["status"] == "active"


def test_every_edge_endpoint_exists():
    ds = build(7)
    ids = {p["id"] for rows in ds.nodes.values() for p in rows}
    for rel, edges in ds.edges.items():
        assert rel in EDGE_RELS
        for e in edges:
            assert e["src"] in ids and e["dst"] in ids, (rel, e)
