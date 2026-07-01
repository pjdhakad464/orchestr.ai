from __future__ import annotations

from fastapi import APIRouter, HTTPException
from app.api.schemas import APIResponse, SocialDiscoverRequest, SocialBulkDiscoverRequest
from app.services.social_discovery import SocialDiscoveryService
from app.models import EntityQuery

router = APIRouter()
service = SocialDiscoveryService()

@router.post("/social/discover", response_model=APIResponse)
async def discover_social(payload: SocialDiscoverRequest):
    """Discovers official social media profile links for an entity name."""
    try:
        q = EntityQuery(
            name=payload.name,
            entity_type=payload.entity_type,
            profession=payload.profession,
            country=payload.country
        )
        res = await service.discover(q)
        return APIResponse(
            status="success",
            message="Social profile discovery completed.",
            data=res.model_dump()
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/social/discover/bulk", response_model=APIResponse)
async def bulk_discover_social(payload: SocialBulkDiscoverRequest):
    """Batch discovers social media channels across multiple entities."""
    try:
        queries = [
            EntityQuery(
                name=q.name,
                entity_type=q.entity_type,
                profession=q.profession,
                country=q.country
            )
            for q in payload.queries
        ]
        res = await service.bulk_discover(queries)
        return APIResponse(
            status="success",
            message=f"Bulk social discovery completed for {len(queries)} items.",
            data=res.model_dump()
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
