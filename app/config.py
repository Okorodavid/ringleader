"""Runtime configuration read from the environment (.env is loaded once here)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _bool(value: str | None, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    falkordb_host: str = os.getenv("FALKORDB_HOST", "localhost")
    falkordb_port: int = int(os.getenv("FALKORDB_PORT", "6379"))
    falkordb_username: str | None = os.getenv("FALKORDB_USERNAME") or None
    falkordb_password: str | None = os.getenv("FALKORDB_PASSWORD") or None
    falkordb_ssl: bool = _bool(os.getenv("FALKORDB_SSL"), False)
    graph_name: str = os.getenv("FALKORDB_GRAPH", "ringleader")
    provider: str = os.getenv("PROVIDER", "rules").strip().lower()
    gemini_api_key: str | None = os.getenv("GEMINI_API_KEY") or None
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-flash-latest")
    port: int = int(os.getenv("PORT", "8000"))
    query_timeout_ms: int = int(os.getenv("QUERY_TIMEOUT_MS", "3000"))


settings = Settings()
