"""Load the generated dataset into FalkorDB. Idempotent: every row goes through MERGE in batches,
so running it twice leaves the graph unchanged. Ground truth is never written."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from . import db
from .generator import Dataset, build

BATCH = 300

NODE_KEYS = {
    "Account": "id", "Device": "id", "Phone": "id", "Address": "id", "Card": "id", "IP": "id",
    "Merchant": "id", "Transaction": "id",
}
EDGE_ENDPOINTS = {
    "USED_DEVICE": ("Account", "Device"),
    "HAS_PHONE": ("Account", "Phone"),
    "LIVES_AT": ("Account", "Address"),
    "OWNS_CARD": ("Account", "Card"),
    "LOGGED_FROM": ("Account", "IP"),
    "SENT": ("Account", "Transaction"),
    "TO": ("Transaction", "Account"),
    "AT": ("Transaction", "Merchant"),
}


def _chunks(rows: list[dict[str, Any]]):
    for i in range(0, len(rows), BATCH):
        yield rows[i:i + BATCH]


def ensure_indexes() -> None:
    g = db.graph()
    wanted = [(label, "id") for label in NODE_KEYS] + [("Account", "status")]
    for label, prop in wanted:
        try:
            g.create_node_range_index(label, prop)
        except Exception as exc:  # noqa: BLE001 - creating an index that exists raises; anything else is real
            if "already indexed" not in str(exc).lower():
                raise


def load(ds: Dataset | None = None, seed: int = 7) -> dict[str, Any]:
    ds = ds or build(seed)
    started = time.perf_counter()
    ensure_indexes()
    stats = {"nodes_created": 0, "relationships_created": 0, "properties_set": 0}
    for label, rows in ds.nodes.items():
        for chunk in _chunks(rows):
            run = db.write(
                f"UNWIND $rows AS r MERGE (n:{label} {{id: r.id}}) SET n += r",
                {"rows": chunk},
            )
            for k in stats:
                stats[k] += run.meta.get(k, 0)
    for rel, rows in ds.edges.items():
        src_label, dst_label = EDGE_ENDPOINTS[rel]
        for chunk in _chunks(rows):
            run = db.write(
                f"UNWIND $rows AS r "
                f"MATCH (a:{src_label} {{id: r.src}}), (b:{dst_label} {{id: r.dst}}) "
                f"MERGE (a)-[e:{rel}]->(b) "
                f"SET e.first_seen = r.first_seen, e.last_seen = r.last_seen, e.count = r.count",
                {"rows": chunk},
            )
            for k in stats:
                stats[k] += run.meta.get(k, 0)
    # alerts: the queue the analyst sees. Deterministic: the first member of each ring plus a few decoys.
    stats["elapsed_s"] = round(time.perf_counter() - started, 1)
    stats["counts"] = graph_counts()
    return stats


def graph_counts() -> dict[str, int]:
    out: dict[str, int] = {}
    for label in NODE_KEYS:
        out[f"node:{label}"] = db.read(f"MATCH (n:{label}) RETURN count(n)").rows[0][0]
    for rel in EDGE_ENDPOINTS:
        out[f"edge:{rel}"] = db.read(f"MATCH ()-[e:{rel}]->() RETURN count(e)").rows[0][0]
    return out


def reset() -> None:
    """Drop the whole graph. Used by tests and the reseed endpoint."""
    try:
        db.graph().delete()
    except Exception as exc:  # noqa: BLE001 - a missing graph is fine
        if "Invalid graph operation on empty key" not in str(exc) and "ERR" not in str(exc):
            raise


if __name__ == "__main__":
    import sys
    if "--reset" in sys.argv:
        reset()
    result = load()
    print(json.dumps(result, indent=1, sort_keys=True))
