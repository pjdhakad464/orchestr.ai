from __future__ import annotations

from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse
from pathlib import Path
import tempfile
import uuid

from app.api.schemas import APIResponse
from app.services.excel_comparator import ExcelComparator

router = APIRouter()
comparator = ExcelComparator()

@router.post("/compare", response_model=APIResponse)
async def compare_files(
    file_a: UploadFile = File(...),
    file_b: UploadFile = File(...),
    key_columns: str = Form(None)  # comma separated column list
):
    """Compares two spreadsheets cell-by-cell and returns differences."""
    try:
        # Save uploaded files temporarily
        temp_dir = Path(tempfile.gettempdir())
        run_id = str(uuid.uuid4())
        
        path_a = temp_dir / f"compare_a_{run_id}_{file_a.filename}"
        path_b = temp_dir / f"compare_b_{run_id}_{file_b.filename}"
        
        path_a.write_bytes(await file_a.read())
        path_b.write_bytes(await file_b.read())

        keys = [k.strip() for k in key_columns.split(",") if k.strip()] if key_columns else None
        
        # Run comparison
        report = comparator.compare(path_a, path_b, keys)
        
        # Save output comparison file
        out_excel_path = temp_dir / f"diff_report_{run_id}.xlsx"
        comparator.export_to_xlsx(report, out_excel_path)
        
        # Cleanup input temp files
        if path_a.exists(): path_a.unlink()
        if path_b.exists(): path_b.unlink()

        return APIResponse(
            status="success",
            message="Excel-to-Excel comparison completed successfully.",
            data={
                "comparison_id": run_id,
                "summary": {
                    "total_rows_original": report.total_rows_a,
                    "total_rows_new": report.total_rows_b,
                    "added_rows": report.added_rows,
                    "removed_rows": report.removed_rows,
                    "modified_rows": report.modified_rows,
                    "unchanged_rows": report.unchanged_rows
                },
                "download_url": f"/api/v1/compare/{run_id}/download",
                "diffs": [d.model_dump() for d in report.row_diffs[:100]] # Preview limit
            }
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Comparison failed: {str(e)}")

@router.get("/compare/{comparison_id}/download")
async def download_diff_report(comparison_id: str):
    """Downloads the generated comparison Excel diff sheet."""
    temp_dir = Path(tempfile.gettempdir())
    report_path = temp_dir / f"diff_report_{comparison_id}.xlsx"
    if not report_path.exists():
        raise HTTPException(status_code=404, detail="Comparison report file not found or expired.")
        
    return FileResponse(
        path=str(report_path),
        filename=f"Excel_Comparison_Report_{comparison_id[:8]}.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
