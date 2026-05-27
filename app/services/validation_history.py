from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

from app.config import BASE_DIR, settings
from app.models import ValidationHistoryEntry, WorkbookValidationArtifact


_DB_LOCK = Lock()


def _history_db_path() -> Path:
    configured = (settings.validation_history_db or "").strip()
    if configured:
        return Path(configured)
    return BASE_DIR / "data" / "validation_history.sqlite3"


def _history_output_root() -> Path:
    configured = (settings.validation_output_dir or "").strip()
    if configured:
        return Path(configured)
    return BASE_DIR / "validated_runs"


def _connect() -> sqlite3.Connection:
    db_path = _history_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    return connection


def _ensure_schema() -> None:
    with _DB_LOCK:
        with _connect() as connection:
            connection.execute(
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
            connection.commit()


def record_validation_run(
    artifact: WorkbookValidationArtifact,
    original_filename: str,
    run_by: str = "",
    client_ip: str = "",
) -> ValidationHistoryEntry:
    _ensure_schema()

    timestamp = datetime.now().astimezone()
    saved_dir = _history_output_root() / timestamp.strftime("%Y-%m-%d") / artifact.validation_id
    saved_dir.mkdir(parents=True, exist_ok=True)
    saved_path = saved_dir / Path(artifact.filename).name
    saved_path.write_bytes(artifact.file_bytes)

    entry = ValidationHistoryEntry(
        validation_id=artifact.validation_id,
        created_at=timestamp,
        original_filename=Path(original_filename).name,
        validated_filename=Path(artifact.filename).name,
        saved_path=str(saved_path),
        saved_dir=str(saved_dir),
        issue_count=artifact.issue_count,
        run_by=(run_by or "").strip(),
        client_ip=(client_ip or "").strip(),
    )

    with _DB_LOCK:
        with _connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO validation_history (
                    validation_id,
                    created_at,
                    original_filename,
                    validated_filename,
                    saved_path,
                    saved_dir,
                    issue_count,
                    run_by,
                    client_ip
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry.validation_id,
                    entry.created_at.astimezone(timezone.utc).isoformat(),
                    entry.original_filename,
                    entry.validated_filename,
                    entry.saved_path,
                    entry.saved_dir,
                    entry.issue_count,
                    entry.run_by,
                    entry.client_ip,
                ),
            )
            connection.commit()

    return entry


def list_validation_runs(limit: int | None = None) -> list[ValidationHistoryEntry]:
    _ensure_schema()
    max_rows = limit if limit and limit > 0 else settings.validation_history_limit
    with _DB_LOCK:
        with _connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    validation_id,
                    created_at,
                    original_filename,
                    validated_filename,
                    saved_path,
                    saved_dir,
                    issue_count,
                    run_by,
                    client_ip
                FROM validation_history
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (max_rows,),
            ).fetchall()
    return [_row_to_entry(row) for row in rows]


def get_validation_run(validation_id: str) -> ValidationHistoryEntry | None:
    _ensure_schema()
    with _DB_LOCK:
        with _connect() as connection:
            row = connection.execute(
                """
                SELECT
                    validation_id,
                    created_at,
                    original_filename,
                    validated_filename,
                    saved_path,
                    saved_dir,
                    issue_count,
                    run_by,
                    client_ip
                FROM validation_history
                WHERE validation_id = ?
                """,
                (validation_id,),
            ).fetchone()
    if row is None:
        return None
    return _row_to_entry(row)


def load_saved_validation_file(validation_id: str) -> tuple[bytes, str] | None:
    entry = get_validation_run(validation_id)
    if entry is None:
        return None
    file_path = Path(entry.saved_path)
    if not file_path.exists():
        return None
    return file_path.read_bytes(), entry.validated_filename


def _row_to_entry(row: sqlite3.Row) -> ValidationHistoryEntry:
    return ValidationHistoryEntry(
        validation_id=row["validation_id"],
        created_at=datetime.fromisoformat(row["created_at"]),
        original_filename=row["original_filename"],
        validated_filename=row["validated_filename"],
        saved_path=row["saved_path"],
        saved_dir=row["saved_dir"],
        issue_count=int(row["issue_count"]),
        run_by=row["run_by"],
        client_ip=row["client_ip"],
    )
