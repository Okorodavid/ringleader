"""G9: the Gemini-backed investigator completes a live investigation and submits structured findings.
Needs GEMINI_API_KEY (free tier) and a live graph. Fails, never skips, when the key is missing."""
from app import agent
from app.config import settings


def test_gemini_investigates_a_ring_seed(dataset, live_graph):
    assert settings.gemini_api_key, "GEMINI_API_KEY missing; this gate needs the free-tier key in .env"
    ring = dataset.truth["rings"][0]
    seed = ring["members"][0]
    events = list(agent.investigate(seed, provider="gemini"))
    types = [e["type"] for e in events]
    errors = [e for e in events if e["type"] == "error" and not e.get("recoverable")]
    assert not errors, errors
    assert "findings" in types and types[-1] == "case"
    tool_names = [e["name"] for e in events if e["type"] == "tool"]
    assert "expand_ring" in tool_names and "money_flow" in tool_names
    findings = next(e["findings"] for e in events if e["type"] == "findings")
    assert findings["verdict"] in ("ring", "uncertain", "benign")
    assert findings["summary"]
    expected = set(ring["members"]) | {ring["cashout"]}
    flagged = {m["id"] for m in findings["members"]}
    # a real model on the free tier is not deterministic; require the verdict to be ring and recall at least 0.5
    assert findings["verdict"] == "ring", findings["summary"]
    assert len(flagged & expected) / len(expected) >= 0.5, sorted(expected - flagged)
    assert all(m["reason"] for m in findings["members"])
    case = events[-1]["case"]
    assert case["provider"] == "gemini" and case["trace"]
