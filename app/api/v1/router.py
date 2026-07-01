from __future__ import annotations

from fastapi import APIRouter
from app.api.v1.health import router as health_router
from app.api.v1.validation import router as validation_router
from app.api.v1.enrichment import router as enrichment_router
from app.api.v1.social import router as social_router
from app.api.v1.taxonomy import router as taxonomy_router
from app.api.v1.comparison import router as comparison_router
from app.api.v1.pipelines import router as pipelines_router

router = APIRouter()

# Include all sub-routers
router.include_router(health_router, tags=["Health"])
router.include_router(validation_router, tags=["Validation"])
router.include_router(enrichment_router, tags=["IMDb Enrichment"])
router.include_router(social_router, tags=["Social Discovery"])
router.include_router(taxonomy_router, tags=["Taxonomy Classification"])
router.include_router(comparison_router, tags=["Excel Comparison"])
router.include_router(pipelines_router, tags=["Pipeline Orchestrator"])
