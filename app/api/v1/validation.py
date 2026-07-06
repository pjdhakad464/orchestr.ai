from __future__ import annotations

import openpyxl
from pathlib import Path
from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from fastapi.responses import StreamingResponse

from app.api.schemas import APIResponse
from app.models import ValidationRuleSet
from app.services.workbook_validator import validate_loaded_workbook
from app.services.validation_history import record_validation_run, get_validation_run, load_saved_validation_file
import json
import uuid

router = APIRouter()

@router.post("/validate", response_model=APIResponse)
async def validate_file(
    file: UploadFile = File(...),
    run_by: str = Form("REST API"),
    rules: str = Form(None)  # optional rules JSON string
):
    """Uploads and validates a spreadsheet against specified validation rules."""
    try:
        # Load workbook
        wb = openpyxl.load_workbook(file.file)
        
        # Load rules
        if rules:
            try:
                ruleset = ValidationRuleSet.model_validate(json.loads(rules))
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"Invalid rules JSON: {str(e)}")
        else:
            # Fallback to default BDR rules
            from app.config import BASE_DIR
            rules_path = BASE_DIR / "data" / "bdr_qa_rules.json"
            if rules_path.exists():
                with open(rules_path, "r", encoding="utf-8") as f:
                    ruleset = ValidationRuleSet.model_validate(json.load(f))
            else:
                ruleset = ValidationRuleSet(rules=[])

        # Validate
        artifact = validate_loaded_workbook(wb, file.filename, ruleset.rules)
        
        # Save output and record history
        entry = record_validation_run(artifact, file.filename, run_by=run_by)
        
        wb.close()
        return APIResponse(
            status="success",
            message="Workbook validation completed successfully.",
            data={
                "validation_id": entry.validation_id,
                "issues_found": entry.issue_count,
                "download_url": entry.download_path,
                "issues": [issue.model_dump() for issue in artifact.issues[:100]] # Limit preview
            }
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Validation failed: {str(e)}")

@router.get("/validate/{validation_id}", response_model=APIResponse)
async def get_validation(validation_id: str):
    """Retrieves validation summary and details by run ID."""
    entry = get_validation_run(validation_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Validation run not found.")
    return APIResponse(
        status="success",
        message="Validation details retrieved.",
        data=entry.model_dump()
    )

@router.get("/validate/{validation_id}/download")
async def download_validated_file(validation_id: str):
    """Downloads the validated spreadsheet workbook containing highlighted finding highlights."""
    res = load_saved_validation_file(validation_id)
    if not res:
        raise HTTPException(status_code=404, detail="Validated workbook file not found.")
    
    file_bytes, filename = res
    # Stream from memory: no leaked temp file, works on read-only serverless FS.
    import io
    return StreamingResponse(
        io.BytesIO(file_bytes),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
