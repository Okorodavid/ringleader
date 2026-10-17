"""Gate runner: runs one named pytest subset and prints the success marker only when it passes.

Usage: python scripts/gate.py <generator|seed|tools|agent|approval|eval|api|gemini|readme>
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

GATES = {
    "generator": ["tests/test_generator.py"],
    "seed": ["tests/test_seed.py"],
    "tools": ["tests/test_tools.py"],
    "agent": ["tests/test_agent_rules.py"],
    "approval": ["tests/test_approval.py"],
    "eval": ["tests/test_eval.py"],
    "api": ["tests/test_api.py"],
    "gemini": ["tests/test_gemini_live.py"],
    "readme": ["tests/test_readme.py"],
}


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in GATES:
        print("usage: gate.py <" + "|".join(GATES) + ">", file=sys.stderr)
        return 2
    name = sys.argv[1]
    cmd = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-rs", *GATES[name]]
    proc = subprocess.run(cmd, cwd=ROOT)
    if proc.returncode != 0:
        print(f"GATE FAILED {name} (pytest exit {proc.returncode})")
        return 1
    print(f"GATE OK {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
