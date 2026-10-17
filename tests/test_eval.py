"""G6: on the frozen eval set the graph investigator beats the one-hop baseline on recall,
and keeps precision at or above 0.9. Numbers are measured here, not copied from anywhere."""
import json

from app import evaluate


def test_eval_set_is_frozen_and_matches_generator():
    frozen = evaluate.load_eval_set()
    assert frozen == evaluate.make_eval_set(7), "evals/cases.json drifted from the generator; regenerate deliberately"
    kinds = {c["kind"] for c in frozen}
    assert kinds == {"ring", "household", "ordinary"}
    assert len(frozen) >= 20


def test_graph_beats_baseline(live_graph):
    report = evaluate.evaluate("rules")
    s = report["summary"]
    print(json.dumps(s, indent=1))
    assert s["graph"]["ring_recall"] >= 0.8
    assert s["graph"]["ring_precision"] >= 0.9
    assert s["graph"]["ring_recall"] > s["baseline"]["ring_recall"]
    assert s["graph"]["verdict_accuracy"] > s["baseline"]["verdict_accuracy"]
    # the baseline flags households (it cannot tell a shared tablet from a shared burner phone)
    hh = [r for r in report["rows"] if r["kind"] == "household"]
    assert all(r["graph"]["verdict"] == "benign" for r in hh)
    assert any(r["baseline"]["flagged_n"] > 0 for r in hh)
