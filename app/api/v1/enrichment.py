from __future__ import annotations

from fastapi import APIRouter, HTTPException
from app.api.schemas import APIResponse, IMDbEnrichRequest, IMDbBulkEnrichRequest
from app.services.imdb_enricher import IMDbEnricher, TitleQuery

router = APIRouter()
enricher = IMDbEnricher()

@router.post("/enrich/imdb", response_model=APIResponse)
async def enrich_imdb_title(payload: IMDbEnrichRequest):
    """Matches a single title and enriches its metadata from IMDb/TMDB/OMDb."""
    try:
        matches = await enricher.match_title(
            title=payload.title,
            year=payload.year,
            content_type=payload.content_type
        )
        if not matches:
            return APIResponse(
                status="success",
                message="No matches found.",
                data={"status": "not_found", "matches": []}
            )

        best_match = matches[0]
        metadata = await enricher.enrich_by_id(best_match.imdb_id)
        
        return APIResponse(
            status="success",
            message="Title match completed.",
            data={
                "status": "matched" if len(matches) == 1 else "multiple_matches",
                "best_match": best_match.model_dump(),
                "metadata": metadata.model_dump() if metadata else None,
                "matches": [m.model_dump() for m in matches]
            }
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/enrich/imdb/bulk", response_model=APIResponse)
async def bulk_enrich_imdb(payload: IMDbBulkEnrichRequest):
    """Runs batch enrichment across a list of title queries."""
    try:
        queries = [TitleQuery(title=q.title, year=q.year, content_type=q.content_type) for q in payload.queries]
        results = await enricher.bulk_enrich(queries)
        return APIResponse(
            status="success",
            message=f"Bulk enrichment completed for {len(queries)} items.",
            data=[r.model_dump() for r in results]
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/enrich/imdb/{imdb_id}", response_model=APIResponse)
async def get_imdb_metadata(imdb_id: str):
    """Enriches metadata for a specific IMDb ID."""
    metadata = await enricher.enrich_by_id(imdb_id)
    if not metadata:
        raise HTTPException(status_code=404, detail="Metadata not found for this IMDb ID.")
    return APIResponse(
        status="success",
        message="Metadata resolved.",
        data=metadata.model_dump()
    )

@router.get("/enrich/imdb/{imdb_id}/episodes", response_model=APIResponse)
async def get_imdb_episodes(imdb_id: str):
    """Gets season/episode count metadata for TV show IDs."""
    data = await enricher.get_episode_counts(imdb_id)
    return APIResponse(
        status="success",
        message="Episode details resolved.",
        data=data.model_dump()
    )
