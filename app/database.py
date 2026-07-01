from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any
import json

from app.config import BASE_DIR, settings

_DB_LOCK = Lock()

def get_db_path(db_name: str) -> Path:
    """Returns the absolute path to a SQLite database by name."""
    import os
    is_vercel = os.environ.get("VERCEL") == "1"
    
    if is_vercel:
        return Path(f"/tmp/{db_name}")
        
    data_dir = BASE_DIR / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / db_name

def get_connection(db_name: str) -> sqlite3.Connection:
    """Gets a thread-safe connection to the specified database."""
    path = get_db_path(db_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    return conn

def init_databases() -> None:
    """Initializes all necessary databases and tables."""
    with _DB_LOCK:
        # 1. Validation History Database
        with get_connection("validation_history.sqlite3") as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS validation_history (
                    validation_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    original_filename TEXT NOT NULL,
                    validated_filename TEXT NOT NULL,
                    saved_path TEXT NOT NULL,
                    saved_dir TEXT NOT NULL,
                    issue_count INTEGER NOT NULL,
                    run_by TEXT NOT NULL DEFAULT '',
                    client_ip TEXT NOT NULL DEFAULT ''
                )
                """
            )
            conn.commit()

        # 2. Pipeline Runs Database
        with get_connection("pipeline_runs.sqlite3") as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS pipeline_runs (
                    run_id TEXT PRIMARY KEY,
                    pipeline_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    progress_pct REAL NOT NULL DEFAULT 0.0,
                    current_step TEXT NOT NULL DEFAULT '',
                    step_results TEXT NOT NULL DEFAULT '{}',
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    error TEXT,
                    run_by TEXT NOT NULL DEFAULT ''
                )
                """
            )
            conn.commit()

        # 3. Metadata Cache Database
        with get_connection("metadata_cache.sqlite3") as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS general_cache (
                    cache_key TEXT PRIMARY KEY,
                    cache_value TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                )
                """
            )
            conn.commit()
