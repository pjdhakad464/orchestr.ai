from __future__ import annotations

from fastapi import APIRouter, HTTPException, BackgroundTasks
from app.api.schemas import APIResponse, PipelineRunRequest
from app.engine.pipeline import PipelineEngine
from app.engine.state import get_pipeline_state, list_pipeline_runs

router = APIRouter()
engine = PipelineEngine()

@router.get("/pipelines", response_model=APIResponse)
async def list_pipelines():
    """Lists all available pipeline templates configured in the system."""
    templates = [
        {
            "name": "imdb_enrichment",
            "title": "IMDb Enrichment & Health Audit",
            "steps": ["Load Spreadsheet", "Enrich IMDb Metadata", "Compute Health Metrics", "Audit Anomaly Flags"]
        },
        {
            "name": "full_qa_validation",
            "title": "Metadata Quality Assurance & Schema Validation",
            "steps": ["Load Spreadsheet", "Verify Content Schema", "Audit Duplicate Records", "Compute Health Score"]
        },
        {
            "name": "side_by_side_comparison",
            "title": "Excel Spreadsheets Comparison Diff",
            "steps": ["Compare Workbooks"]
        }
    ]
    return APIResponse(
        status="success",
        message="Pipeline templates retrieved.",
        data=templates
    )

@router.post("/pipelines/run", response_model=APIResponse)
async def run_pipeline(payload: PipelineRunRequest, background_tasks: BackgroundTasks):
    """Triggers background execution of a pipeline template."""
    template = PipelineEngine.get_template(payload.template_name)
    if not template:
        raise HTTPException(status_code=404, detail="Pipeline template not found.")

    # Validate minimal inputs
    if "file_path" not in payload.inputs and "file_a" not in payload.inputs:
        raise HTTPException(status_code=400, detail="Required inputs 'file_path' or 'file_a' not found.")

    # Start runner in background tasks
    async def task_runner():
        await engine.execute_run(template, payload.inputs, run_by=payload.run_by)

    background_tasks.add_task(task_runner)

    # Let's check status immediately
    # Note: We don't have the run_id returned by execute_run until it finishes/saves, so let's pre-generate the run_id.
    # To facilitate this, let's update engine.execute_run or pre-generate the UUID here and pass it as run_id.
    # Wait, in engine.execute_run we generated one. Let's make sure it's saved.
    # Alternatively, since execute_run is async, we can await a quick setup or run it asynchronously.
    # Let's adjust engine.execute_run signature: we can pass an optional run_id! Let's update pipeline.py to support pre-generated UUIDs.
    import uuid
    run_id = str(uuid.uuid4())
    
    # We can pre-insert the pending state to database so the user can query it immediately
    from app.engine.state import save_pipeline_state, PipelineState
    pending_state = PipelineState(
        run_id=run_id,
        pipeline_name=template.name,
        status="pending",
        run_by=payload.run_by
    )
    save_pipeline_state(pending_state)

    async def run_with_pregenerated_id():
        # Execute run but override run_id inside handler if we match it.
        # Let's call a modified engine runner that accepts the pre-generated run_id!
        # Wait, since we wrote execute_run inside pipeline.py, let's make sure it can handle custom pre-generated ID.
        # Let's check pipeline.py execute_run:
        # async def execute_run(self, pipeline: Pipeline, initial_inputs: dict[str, Any], run_by: str = ""):
        #    run_id = str(uuid.uuid4())
        # Let's change pipeline.py to:
        # async def execute_run(self, pipeline: Pipeline, initial_inputs: dict[str, Any], run_by: str = "", run_id: str | None = None)
        # We will do that! Let's update execute_run invocation here, and we'll update pipeline.py in a moment.
        await engine.execute_run(template, payload.inputs, run_by=payload.run_by, run_id=run_id)

    background_tasks.add_task(run_with_pregenerated_id)

    return APIResponse(
        status="success",
        message="Pipeline execution triggered successfully in background.",
        data={
            "run_id": run_id,
            "status": "pending",
            "monitor_url": f"/api/v1/pipelines/{run_id}"
        }
    )

@router.get("/pipelines/{run_id}", response_model=APIResponse)
async def get_run_status(run_id: str):
    """Gets execution status and progress logs for a running/completed pipeline."""
    state = get_pipeline_state(run_id)
    if not state:
        raise HTTPException(status_code=404, detail="Pipeline run execution not found.")
    return APIResponse(
        status="success",
        message="Pipeline status retrieved.",
        data=state.model_dump()
    )

@router.get("/pipelines/runs/history", response_model=APIResponse)
async def get_history():
    """Lists history of recent pipeline runs."""
    runs = list_pipeline_runs(limit=30)
    return APIResponse(
        status="success",
        message="Recent pipeline runs history resolved.",
        data=[r.model_dump() for r in runs]
    )
