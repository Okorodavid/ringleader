"""Shared fixtures. Tests that need a live FalkorDB are skipped (not passed) when none is reachable,
so a gate that depends on the database fails loudly through pytest's exit code when it is skipped."""
import json
from pathlib import Path

import pytest

from app import db, seed
from app.generator import build

ROOT = Path(__file__).resolve().parent.parent


def pytest_configure(config):
    config.addinivalue_line("markers", "db: needs a live FalkorDB")


@pytest.fixture(scope="session")
def dataset():
    return build(7)


@pytest.fixture(scope="session")
def live_graph(dataset):
    """A FalkorDB graph loaded with the seed-7 dataset. Loads once per test session."""
    if not db.ping():
        pytest.fail("FalkorDB is not reachable; set FALKORDB_HOST/PORT/PASSWORD in .env")
    counts = seed.graph_counts()
    expected = dataset.counts()
    if any(counts.get(k, 0) < v for k, v in expected.items()):
        seed.load(dataset)
    return db.graph()
