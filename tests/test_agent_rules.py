"""G4: the offline rule-based investigator finds the ring from one seed and spares the household."""
from app import agent, cases


def run(seed):
    events = list(agent.investigate(seed, provider="rules"))
    findings = next(e["findings"] for e in events if e["type"] == "findings")
    case = next(e for e in events if e["type"] == "case")
    return events, findings, case


def test_ring_seed_finds_most_members(dataset, live_graph):
    for ring in dataset.truth["rings"]:
        seed = ring["members"][1]
        before = cases.account_status(ring["members"] + [ring["cashout"]])
        events, findings, case = run(seed)
        expected = set(ring["members"]) | {ring["cashout"]}
        flagged = {m["id"] for m in findings["members"]}
        recall = len(flagged & expected) / len(expected)
        precision = len(flagged & expected) / max(1, len(flagged))
        assert findings["verdict"] == "ring", (ring["name"], findings["summary"])
        assert recall >= 0.8, (ring["name"], recall, sorted(expected - flagged))
        assert precision >= 0.9, (ring["name"], precision, sorted(flagged - expected))
        assert any(m["role"] == "cashout" for m in findings["members"]), ring["name"]
        assert all(m["reason"] for m in findings["members"])
        # every tool event carries the Cypher that ran
        tool_events = [e for e in events if e["type"] == "tool"]
        assert tool_events and all(q["cypher"] for e in tool_events for q in e["result"]["queries"])
        assert any(e["name"] == "explain_link" for e in tool_events)
        # proposals exist but the investigation itself changed no account status
        assert findings["proposed_actions"]
        assert cases.account_status(ring["members"] + [ring["cashout"]]) == before


def test_household_seed_is_benign(dataset, live_graph):
    for household in dataset.truth["households"]:
        seed = household[0]
        _, findings, _ = run(seed)
        assert findings["verdict"] == "benign", (seed, findings["summary"], findings["members"])
        assert findings["members"] == []
        assert not [a for a in findings["proposed_actions"] if a["type"] == "freeze"]


def test_ordinary_seed_is_benign(dataset, live_graph):
    for props in dataset.nodes["Account"][:5]:
        _, findings, _ = run(props["id"])
        assert findings["verdict"] == "benign"
        assert findings["members"] == []


def test_case_is_persisted_with_members_and_trace(dataset, live_graph):
    ring = dataset.truth["rings"][0]
    _, findings, case_event = run(ring["members"][0])
    case = cases.get_case(case_event["case_id"])
    assert case["verdict"] == "ring"
    assert {m["id"] for m in case["members"]} == {m["id"] for m in findings["members"]}
    assert case["actions"] and all(a["status"] == "pending" for a in case["actions"])
    assert any(step["type"] == "tool" and step["queries"] for step in case["trace"])
    # the next investigation of the same ring sees this case as precedent
    events = list(agent.investigate(ring["members"][2], provider="rules"))
    prior = next(e for e in events if e["type"] == "tool" and e["name"] == "prior_cases")
    assert any(c["case_id"] == case["id"] for c in prior["result"]["data"]["cases"])
