"""G10: the README carries what the hackathon submission requires, and its Cypher claims match the code."""
import re
from pathlib import Path

from app import tools, cases

ROOT = Path(__file__).resolve().parent.parent
README = (ROOT / "README.md").read_text(encoding="utf-8")


def heading(text: str) -> bool:
    return re.search(rf"^#{{1,3}}\s+.*{re.escape(text)}", README, re.IGNORECASE | re.MULTILINE) is not None


def test_required_sections_exist():
    for h in ("Setup", "Graph data model", "Cypher", "Track", "AI", "Limits", "Eval", "Approval"):
        assert heading(h), f"missing section: {h}"


def test_every_product_query_is_documented():
    """Each query the product depends on appears in the README verbatim (first line), so judges read the real thing."""
    product_queries = {
        "account_profile": tools.Q_PROFILE, "shared_identifiers": tools.Q_SHARED, "expand_ring": tools.Q_EXPAND.replace("{depth}", "6"),
        "identifier_fanout": tools.Q_FANOUT, "velocity": tools.Q_VELOCITY, "money_flow": tools.Q_SINKS,
        "explain_link": tools.Q_PATH, "prior_cases": tools.Q_PRIOR, "approve": cases.Q_APPROVE,
    }
    for name, q in product_queries.items():
        first = next(line.strip() for line in q.strip().splitlines() if line.strip())
        assert first in README, f"{name}: README does not contain the query's first line: {first}"


def test_setup_mentions_falkordb_options_and_commands():
    for needle in ("docker run", "falkordb/falkordb", "FalkorDB Cloud", "python -m app.seed", "uvicorn", ".env"):
        assert needle in README, needle


def test_disclosure_and_honesty():
    assert re.search(r"Claude", README) and re.search(r"AI (coding )?assistant|generated with|built with", README, re.IGNORECASE)
    assert "synthetic" in README.lower()
    assert "Track 01" in README or "Track 1" in README
