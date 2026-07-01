from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Callable, Any
from pydantic import BaseModel, Field

from app.engine.state import PipelineState, StepResult, save_pipeline_state
from app.engine.steps import PipelineSteps

class PipelineStep(BaseModel):
    name: str
    handler_name: str  # maps to PipelineSteps method
    timeout_seconds: int = 120
    retry_count: int = 0
    inputs: dict[str, Any] = Field(default_factory=dict)

class Pipeline(BaseModel):
    name: str
    steps: list[PipelineStep] = Field(default_factory=list)

class PipelineEngine:
    def __init__(self) -> None:
        self.handlers = {
            "load_excel": PipelineSteps.load_excel,
            "validate_workbook": PipelineSteps.validate_workbook,
            "enrich_imdb": PipelineSteps.enrich_imdb,
            "detect_duplicates": PipelineSteps.detect_duplicates,
            "compare_excel": PipelineSteps.compare_excel,
            "score_health": PipelineSteps.score_health,
            "detect_anomalies": PipelineSteps.detect_anomalies,
        }

    async def execute_run(self, pipeline: Pipeline, initial_inputs: dict[str, Any], run_by: str = "", run_id: str | None = None) -> PipelineState:
        """Executes a pipeline sequence step-by-step asynchronously and saves progress state."""
        r_id = run_id or str(uuid.uuid4())
        state = PipelineState(
            run_id=r_id,
            pipeline_name=pipeline.name,
            status="running",
            run_by=run_by
        )
        
        # Initialize step results mapping
        for step in pipeline.steps:
            state.step_results[step.name] = StepResult(
                step_name=step.name,
                status="pending",
                started_at=datetime.now(timezone.utc).isoformat()
            )
            
        save_pipeline_state(state)

        # Context passing between steps
        context = dict(initial_inputs)

        total_steps = len(pipeline.steps)
        for idx, step in enumerate(pipeline.steps):
            state.current_step = step.name
            state.progress_pct = round((idx / total_steps) * 100, 1)
            
            step_res = state.step_results[step.name]
            step_res.status = "running"
            step_res.started_at = datetime.now(timezone.utc).isoformat()
            save_pipeline_state(state)

            handler = self.handlers.get(step.handler_name)
            if not handler:
                err_msg = f"Step handler '{step.handler_name}' not registered in engine."
                step_res.status = "failed"
                step_res.error = err_msg
                state.status = "failed"
                state.error = err_msg
                state.completed_at = datetime.now(timezone.utc).isoformat()
                save_pipeline_state(state)
                return state

            # Merge step inputs with dynamic context keys
            step_inputs = dict(step.inputs)
            for k, v in step_inputs.items():
                if isinstance(v, str) and v.startswith("$.context."):
                    context_key = v.split("$.context.")[1]
                    step_inputs[k] = context.get(context_key)

            # Also pass the general context down if keys are absent
            for k, v in context.items():
                if k not in step_inputs:
                    step_inputs[k] = v

            try:
                # Execute step with timeout
                output = await asyncio.wait_for(
                    handler(step_inputs),
                    timeout=float(step.timeout_seconds)
                )
                
                step_res.status = "completed"
                step_res.completed_at = datetime.now(timezone.utc).isoformat()
                step_res.output = output
                
                # Merge outputs back into general context
                context.update(output)
                
            except Exception as e:
                err_msg = f"Error running step '{step.name}': {str(e)}"
                step_res.status = "failed"
                step_res.error = err_msg
                state.status = "failed"
                state.error = err_msg
                state.completed_at = datetime.now(timezone.utc).isoformat()
                save_pipeline_state(state)
                return state

        state.progress_pct = 100.0
        state.status = "completed"
        state.completed_at = datetime.now(timezone.utc).isoformat()
        save_pipeline_state(state)
        return state

    @staticmethod
    def get_template(name: str) -> Pipeline | None:
        """Returns standard pipeline configurations."""
        templates = {
            "imdb_enrichment": Pipeline(
                name="IMDb Enrichment & Health Audit",
                steps=[
                    PipelineStep(name="Load Spreadsheet", handler_name="load_excel"),
                    PipelineStep(name="Enrich IMDb Metadata", handler_name="enrich_imdb"),
                    PipelineStep(name="Compute Health Metrics", handler_name="score_health"),
                    PipelineStep(name="Audit Anomaly Flags", handler_name="detect_anomalies")
                ]
            ),
            "full_qa_validation": Pipeline(
                name="Metadata Quality Assurance & Schema Validation",
                steps=[
                    PipelineStep(name="Load Spreadsheet", handler_name="load_excel"),
                    PipelineStep(name="Verify Content Schema", handler_name="validate_workbook"),
                    PipelineStep(name="Audit Duplicate Records", handler_name="detect_duplicates"),
                    PipelineStep(name="Compute Health Score", handler_name="score_health")
                ]
            ),
            "side_by_side_comparison": Pipeline(
                name="Excel Spreadsheets Comparison Diff",
                steps=[
                    PipelineStep(name="Compare Workbooks", handler_name="compare_excel")
                ]
            )
        }
        return templates.get(name)
