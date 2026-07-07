"""Data-access layer — datastore-agnostic.

The rest of the platform depends only on the `Repository` protocol, never on a
concrete database. `get_repository()` returns the Postgres/Supabase adapter
when `DATABASE_URL` (or `SUPABASE_DB_URL`) is configured AND the psycopg driver
is installed; otherwise it falls back to the in-memory adapter so the app runs
identically with no database attached.

To go live on Supabase:
  1. Run db/migrations/0001_initial_schema.sql in the Supabase SQL editor.
  2. Add `psycopg[binary]` to requirements.txt.
  3. Set DATABASE_URL to the Supabase connection-pooler URI (port 6543,
     transaction mode — serverless-friendly).
No other code changes are needed.
"""

from __future__ import annotations

import logging
import os

from .repository import Repository
from .memory import InMemoryRepository

log = logging.getLogger("data")

_REPO: Repository | None = None


def _database_url() -> str:
    return (os.environ.get("DATABASE_URL")
            or os.environ.get("SUPABASE_DB_URL") or "").strip()


def get_repository() -> Repository:
    global _REPO
    if _REPO is not None:
        return _REPO
    url = _database_url()
    if url:
        try:
            from .postgres import PostgresRepository
            _REPO = PostgresRepository(url)
            log.info("Data layer: PostgreSQL/Supabase repository active.")
            return _REPO
        except Exception as e:  # driver missing or connect failed → safe fallback
            log.warning("DATABASE_URL set but Postgres repo unavailable (%s); "
                        "falling back to in-memory.", e)
    _REPO = InMemoryRepository()
    return _REPO


def is_durable() -> bool:
    return get_repository().durable


__all__ = ["Repository", "get_repository", "is_durable"]
