from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Literal, Any
from pydantic import BaseModel, Field

from app.database import get_connection

class StepResult(BaseModel):
    step_name: str
    status: Literal["pending", "running", "completed", "failed"]
    started_at: str
    completed_at: str | None = None
    output: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None

class PipelineState(BaseModel):
    run_id: str
    pipeline_name: str
    status: Literal["pending", "running", "completed", "failed", "cancelled"] = "pending"
    progress_pct: float = 0.0
    current_step: str = ""
    step_results: dict[str, StepResult] = Field(default_factory=dict)
    started_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    completed_at: str | None = None
    error: str | None = None
    run_by: str = ""

def save_pipeline_state(state: PipelineState) -> None:
    """Saves pipeline run state into the pipeline_runs SQLite database."""
    try:
        with get_connection("pipeline_runs.sqlite3") as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO pipeline_runs (
                    run_id, pipeline_name, status, progress_pct, current_step,
                    step_results, started_at, completed_at, error, run_by
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    state.run_id,
                    state.pipeline_name,
                    state.status,
                    state.progress_pct,
                    state.current_step,
                    json.dumps({k: v.model_dump() for k, v in state.step_results.items()}),
                    state.started_at,
                    state.completed_at,
                    state.error,
                    state.run_by
                )
            )
            conn.commit()
    except Exception:
        pass

def get_pipeline_state(run_id: str) -> PipelineState | None:
    """Retrieves pipeline run state by ID."""
    try:
        with get_connection("pipeline_runs.sqlite3") as conn:
            row = conn.execute(
                "SELECT * FROM pipeline_runs WHERE run_id = ?",
                (run_id,)
            ).fetchone()
            if row:
                steps_data = json.loads(row["step_results"])
                step_results = {k: StepResult.model_validate(v) for k, v in steps_data.items()}
                return PipelineState(
                    run_id=row["run_id"],
                    pipeline_name=row["pipeline_name"],
                    status=row["status"],
                    progress_pct=row["progress_pct"],
                    current_step=row["current_step"],
                    step_results=step_results,
                    started_at=row["started_at"],
                    completed_at=row["completed_at"],
                    error=row["error"],
                    run_by=row["run_by"]
                )
    except Exception:
        pass
    return None

def list_pipeline_runs(limit: int = 50) -> list[PipelineState]:
    """Lists all recent pipeline executions."""
    runs = []
    try:
        with get_connection("pipeline_runs.sqlite3") as conn:
            rows = conn.execute(
                "SELECT * FROM pipeline_runs ORDER BY started_at DESC LIMIT ?",
                (limit,)
            ).fetchall()
            for row in rows:
                steps_data = json.loads(row["step_results"])
                step_results = {k: StepResult.model_validate(v) for k, v in steps_data.items()}
                runs.append(PipelineState(
                    run_id=row["run_id"],
                    pipeline_name=row["pipeline_name"],
                    status=row["status"],
                    progress_pct=row["progress_pct"],
                    current_step=row["current_step"],
                    step_results=step_results,
                    started_at=row["started_at"],
                    completed_at=row["completed_at"],
                    error=row["error"],
                    run_by=row["run_by"]
                ))
    except Exception:
        pass
    return runs
