from __future__ import annotations

from fastapi import APIRouter, HTTPException, Form
from app.api.schemas import APIResponse
from app.services.taxonomy_classifier import TaxonomyClassifier
from app.cache import TTLCache
from app.config import settings

router = APIRouter()
cache = TTLCache(ttl_seconds=settings.cache_ttl_seconds)
classifier = TaxonomyClassifier(cache)

@router.post("/taxonomy/classify", response_model=APIResponse)
async def classify_taxonomy(
    title: str = Form(...),
    instagram: str = Form(None)
):
    """Classifies a title/entity name into category/sub-categories using heuristic classifiers."""
    try:
        res = await classifier.classify(title, instagram)
        return APIResponse(
            status="success",
            message="Entity taxonomy classification completed.",
            data=res
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
