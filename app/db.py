"""FalkorDB access. One client, one graph, and a read-only guard for every query the agent runs."""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any

from falkordb import FalkorDB, Graph, Node, Edge, Path

from .config import settings

# Keywords that must never appear in a read-only query. Checked as whole words, case-insensitive.
_WRITE_WORDS = re.compile(
    r"\b(CREATE|MERGE|DELETE|DETACH|SET|REMOVE|DROP|LOAD\s+CSV)\b",
    re.IGNORECASE,
)


class ReadOnlyViolation(ValueError):
    """Raised when a query submitted through the read-only path contains a write keyword."""


_db: FalkorDB | None = None


def connect() -> FalkorDB:
    global _db
    if _db is None:
        _db = FalkorDB(
            host=settings.falkordb_host,
            port=settings.falkordb_port,
            username=settings.falkordb_username,
            password=settings.falkordb_password,
            ssl=settings.falkordb_ssl,
            socket_connect_timeout=5,
        )
    return _db


def graph(name: str | None = None) -> Graph:
    return connect().select_graph(name or settings.graph_name)


last_error: str | None = None


def ping() -> bool:
    global last_error
    try:
        connect().connection.ping()
        last_error = None
        return True
    except Exception as exc:  # noqa: BLE001 - any failure means not reachable
        last_error = f"{type(exc).__name__}: {exc}"[:300]
        return False


@dataclass
class QueryRun:
    """What one query did: the Cypher text, its params, rows, and timing. Shown verbatim in the UI."""

    cypher: str
    params: dict[str, Any]
    rows: list[list[Any]]
    columns: list[str]
    run_ms: float
    read_only: bool = True
    error: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    def as_dicts(self) -> list[dict[str, Any]]:
        return [dict(zip(self.columns, row)) for row in self.rows]

    def to_json(self) -> dict[str, Any]:
        return {
            "cypher": self.cypher,
            "params": self.params,
            "columns": self.columns,
            "rows": self.rows,
            "run_ms": self.run_ms,
            "read_only": self.read_only,
            "error": self.error,
            "meta": self.meta,
        }


def plain(value: Any) -> Any:
    """Turn FalkorDB result objects into JSON-serialisable values."""
    if isinstance(value, Node):
        return {"_kind": "node", "id": value.id, "labels": list(value.labels), "props": value.properties}
    if isinstance(value, Edge):
        return {
            "_kind": "edge",
            "id": value.id,
            "type": value.relation,
            "src": value.src_node,
            "dst": value.dest_node,
            "props": value.properties,
        }
    if isinstance(value, Path):
        return {
            "_kind": "path",
            "nodes": [plain(n) for n in value.nodes()],
            "edges": [plain(e) for e in value.edges()],
        }
    if isinstance(value, list):
        return [plain(v) for v in value]
    if isinstance(value, dict):
        return {k: plain(v) for k, v in value.items()}
    return value


def _columns(result: Any) -> list[str]:
    cols = []
    for h in result.header or []:
        cols.append(h[1] if isinstance(h, (list, tuple)) else str(h))
    return cols


def read(cypher: str, params: dict[str, Any] | None = None, timeout_ms: int | None = None) -> QueryRun:
    """Run a read-only query. Refuses write keywords, uses GRAPH.RO_QUERY, and times out."""
    if _WRITE_WORDS.search(cypher):
        raise ReadOnlyViolation("write keyword in read-only query")
    params = params or {}
    started = time.perf_counter()
    result = graph().ro_query(cypher, params, timeout=timeout_ms or settings.query_timeout_ms)
    elapsed = (time.perf_counter() - started) * 1000
    return QueryRun(
        cypher=cypher.strip(),
        params=params,
        rows=[plain(row) for row in result.result_set],
        columns=_columns(result),
        run_ms=round(elapsed, 2),
    )


def write(cypher: str, params: dict[str, Any] | None = None) -> QueryRun:
    """Run a write query. Only the seeder and the approval flow call this; the agent never does."""
    params = params or {}
    started = time.perf_counter()
    result = graph().query(cypher, params, timeout=settings.query_timeout_ms * 10)
    elapsed = (time.perf_counter() - started) * 1000
    return QueryRun(
        cypher=cypher.strip(),
        params=params,
        rows=[plain(row) for row in result.result_set],
        columns=_columns(result),
        run_ms=round(elapsed, 2),
        read_only=False,
        meta={
            "nodes_created": result.nodes_created,
            "relationships_created": result.relationships_created,
            "properties_set": result.properties_set,
        },
    )
