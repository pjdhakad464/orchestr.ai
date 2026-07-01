from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any
from pydantic import BaseModel, Field

from app.engine.pipeline import PipelineEngine, Pipeline

class ScheduledJob(BaseModel):
    job_id: str
    pipeline_name: str
    cron_expr: str
    interval_seconds: int
    inputs: dict[str, Any] = Field(default_factory=dict)
    last_run: str | None = None
    next_run: str | None = None
    active: bool = True

class PipelineScheduler:
    def __init__(self) -> None:
        self.jobs: dict[str, ScheduledJob] = {}

    def schedule_interval_job(
        self,
        job_id: str,
        pipeline_name: str,
        interval_seconds: int,
        inputs: dict[str, Any]
    ) -> None:
        """Schedules a pipeline execution to run at repeated intervals."""
        job = ScheduledJob(
            job_id=job_id,
            pipeline_name=pipeline_name,
            cron_expr="",
            interval_seconds=interval_seconds,
            inputs=inputs,
            next_run=datetime.now(timezone.utc).isoformat()
        )
        self.jobs[job_id] = job

    async def start_monitoring(self) -> None:
        """Starts background loop to execute scheduled jobs."""
        engine = PipelineEngine()
        while True:
            now = datetime.now(timezone.utc)
            for job in list(self.jobs.values()):
                if not job.active:
                    continue
                
                next_run_dt = datetime.fromisoformat(job.next_run) if job.next_run else now
                if now >= next_run_dt:
                    job.last_run = now.isoformat()
                    # Calculate next run
                    from datetime import timedelta
                    next_run_dt = now + timedelta(seconds=job.interval_seconds)
                    job.next_run = next_run_dt.isoformat()
                    
                    # Run background task
                    template = PipelineEngine.get_template(job.pipeline_name)
                    if template:
                        asyncio.create_task(
                            engine.execute_run(template, job.inputs, run_by="scheduler")
                        )
            await asyncio.sleep(5)
