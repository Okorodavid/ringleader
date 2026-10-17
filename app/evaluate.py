"""Frozen eval: a fixed list of seed accounts with the expected flagged set, scored for the graph
investigator and for a one-hop attribute baseline (flag everything that shares a direct identifier).

Metrics per case: recall and precision of flagged accounts against ground truth. The ground truth comes
from the generator, which the graph never sees.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import agent, tools
from .generator import build

ROOT = Path(__file__).resolve().parent.parent
EVAL_PATH = ROOT / "evals" / "cases.json"


def make_eval_set(seed: int = 7) -> list[dict[str, Any]]:
    ds = build(seed)
    cases: list[dict[str, Any]] = []
    for ring in ds.truth["rings"]:
        expected = sorted(set(ring["members"]) | {ring["cashout"]})
        for pick in (0, len(ring["members"]) // 2):
            cases.append({"id": f"{ring['name']}_m{pick}", "seed": ring["members"][pick], "kind": "ring",
                          "expected_verdict": "ring", "expected_members": expected})
        cases.append({"id": f"{ring['name']}_cashout", "seed": ring["cashout"], "kind": "ring",
                      "expected_verdict": "ring", "expected_members": expected})
    for i, hh in enumerate(ds.truth["households"]):
        cases.append({"id": f"household_{i}", "seed": hh[0], "kind": "household",
                      "expected_verdict": "benign", "expected_members": []})
    for i in (0, 50, 120, 200, 300):
        cases.append({"id": f"ordinary_{i}", "seed": ds.nodes["Account"][i]["id"], "kind": "ordinary",
                      "expected_verdict": "benign", "expected_members": []})
    return cases


def load_eval_set() -> list[dict[str, Any]]:
    return json.loads(EVAL_PATH.read_text())


def _prf(flagged: set[str], expected: set[str]) -> tuple[float, float]:
    if not expected:
        return (1.0 if not flagged else 0.0), (1.0 if not flagged else 0.0)
    hit = len(flagged & expected)
    return hit / len(expected), hit / max(1, len(flagged))


def run_graph_investigator(case: dict[str, Any], provider: str = "rules") -> dict[str, Any]:
    findings = None
    for e in agent.investigate(case["seed"], provider=provider):
        if e["type"] == "findings":
            findings = e["findings"]
    if findings is None:
        return {"flagged": [], "verdict": "error"}
    return {"flagged": sorted(m["id"] for m in findings["members"]), "verdict": findings["verdict"]}


def run_baseline(case: dict[str, Any]) -> dict[str, Any]:
    """One-hop attribute matching, the thing a flat lookup or similarity search would do:
    flag the seed and every account that shares a direct identifier with it."""
    neigh = tools.shared_identifiers(case["seed"])["neighbours"]
    flagged = sorted({case["seed"]} | {n["account"] for n in neigh}) if neigh else []
    return {"flagged": flagged, "verdict": "ring" if len(flagged) >= 3 else "benign"}


def evaluate(provider: str = "rules", cases: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    cases = cases or load_eval_set()
    rows = []
    for case in cases:
        expected = set(case["expected_members"])
        g = run_graph_investigator(case, provider)
        b = run_baseline(case)
        g_r, g_p = _prf(set(g["flagged"]), expected)
        b_r, b_p = _prf(set(b["flagged"]), expected)
        rows.append({
            "id": case["id"], "kind": case["kind"], "seed": case["seed"],
            "expected_verdict": case["expected_verdict"], "expected_n": len(expected),
            "graph": {"verdict": g["verdict"], "flagged_n": len(g["flagged"]), "recall": round(g_r, 3), "precision": round(g_p, 3),
                      "verdict_ok": g["verdict"] == case["expected_verdict"]},
            "baseline": {"verdict": b["verdict"], "flagged_n": len(b["flagged"]), "recall": round(b_r, 3), "precision": round(b_p, 3),
                         "verdict_ok": b["verdict"] == case["expected_verdict"]},
        })
    ring_rows = [r for r in rows if r["kind"] == "ring"]

    def mean(key: str, sub: str, subset: list[dict[str, Any]]) -> float:
        return round(sum(r[sub][key] for r in subset) / max(1, len(subset)), 3)

    summary = {
        "cases": len(rows),
        "graph": {"ring_recall": mean("recall", "graph", ring_rows), "ring_precision": mean("precision", "graph", ring_rows),
                  "verdict_accuracy": round(sum(r["graph"]["verdict_ok"] for r in rows) / len(rows), 3)},
        "baseline": {"ring_recall": mean("recall", "baseline", ring_rows), "ring_precision": mean("precision", "baseline", ring_rows),
                     "verdict_accuracy": round(sum(r["baseline"]["verdict_ok"] for r in rows) / len(rows), 3)},
    }
    return {"provider": provider, "summary": summary, "rows": rows}


if __name__ == "__main__":
    import sys
    if "--make" in sys.argv:
        EVAL_PATH.parent.mkdir(exist_ok=True)
        EVAL_PATH.write_text(json.dumps(make_eval_set(), indent=1))
        print(f"wrote {EVAL_PATH}")
    else:
        provider = sys.argv[1] if len(sys.argv) > 1 else "rules"
        report = evaluate(provider)
        print(json.dumps(report["summary"], indent=1))
        for r in report["rows"]:
            print(f"{r['id']:<22} graph r={r['graph']['recall']:.2f} p={r['graph']['precision']:.2f} {r['graph']['verdict']:<9} | "
                  f"baseline r={r['baseline']['recall']:.2f} p={r['baseline']['precision']:.2f} {r['baseline']['verdict']}")
        out = ROOT / "evals" / f"report_{provider}.json"
        out.write_text(json.dumps(report, indent=1))
        print(f"wrote {out}")
