"""G5: no account changes until a human approves; after approval the named accounts are frozen."""
from app import agent, cases, db


def _reactivate(ids):
    """Test fixture only: put accounts back to active so the gate measures this run, not an earlier one."""
    db.write("MATCH (a:Account) WHERE a.id IN $ids SET a.status = 'active'", {"ids": ids})


def test_freeze_only_after_approval(dataset, live_graph):
    ring = dataset.truth["rings"][3]
    _reactivate(ring["members"] + [ring["cashout"]])
    events = list(agent.investigate(ring["members"][0], provider="rules"))
    case = next(e for e in events if e["type"] == "case")["case"]
    freezes = [a for a in case["actions"] if a["type"] == "freeze"]
    targets = [a["target"] for a in freezes]
    assert targets
    # positive control: before approval every target is still active
    assert set(cases.account_status(targets).values()) == {"active"}

    # reject one, approve the rest
    rejected = freezes[0]
    cases.decide(case["id"], [rejected["id"]], who="analyst@example.com", approve=False)
    assert cases.account_status([rejected["target"]])[rejected["target"]] == "active"

    approved = [a["id"] for a in freezes[1:]]
    result = cases.decide(case["id"], approved, who="analyst@example.com", approve=True)
    assert len(result["applied"]) == len(approved)
    statuses = cases.account_status(targets)
    assert statuses[rejected["target"]] == "active"
    assert all(statuses[a["target"]] == "frozen" for a in freezes[1:])

    after = cases.get_case(case["id"])
    by_id = {a["id"]: a for a in after["actions"]}
    assert by_id[rejected["id"]]["status"] == "rejected"
    for aid in approved:
        assert by_id[aid]["status"] == "approved"
        assert by_id[aid]["approved_by"] == "analyst@example.com"
        assert by_id[aid]["approved_at"]
    # approving the same ids again is a no-op (they are no longer pending)
    again = cases.decide(case["id"], approved, who="someone-else", approve=True)
    assert again["applied"] == []


def test_unapproved_case_leaves_everything_active(dataset, live_graph):
    ring = dataset.truth["rings"][1]
    ids = ring["members"] + [ring["cashout"]]
    _reactivate(ids)
    events = list(agent.investigate(ring["members"][3], provider="rules"))
    case = next(e for e in events if e["type"] == "case")["case"]
    assert [a for a in case["actions"] if a["type"] == "freeze"]
    assert set(cases.account_status(ids).values()) == {"active"}
