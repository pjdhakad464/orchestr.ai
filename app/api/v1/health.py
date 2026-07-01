from __future__ import annotations

from fastapi import APIRouter
from app.api.schemas import APIResponse

router = APIRouter()

@router.get("/status", response_model=APIResponse)
async def status():
    """Gets the current status of the platform components."""
    import os
    return APIResponse(
        status="success",
        message="DataOps metadata operations platform online.",
        data={
            "environment": "Vercel" if os.environ.get("VERCEL") == "1" else "Local/VPS",
            "version": "1.0.0"
        }
    )
