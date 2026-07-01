from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field

from app.cache import TTLCache
from app.config import settings
from app.models import EntityQuery, SearchResponse, BulkSearchResponse, BulkLookupResult
from app.services.factory import build_entity_resolver, build_media_resolver

class SocialDiscoveryService:
    """
    Unified facade service for social media account discovery and verification.
    Uses the underlying EntityResolver and MediaResolver.
    """
    
    def __init__(self, cache: TTLCache | None = None) -> None:
        self.cache = cache or TTLCache(ttl_seconds=settings.cache_ttl_seconds)
        self.entity_resolver = build_entity_resolver(self.cache)
        self.media_resolver = build_media_resolver(self.cache)

    async def discover(self, query: EntityQuery) -> SearchResponse:
        """Finds likely official social profiles for a celebrity, company, show, or movie."""
        if query.entity_type in {"tv_show", "movie"}:
            # Utilize MediaResolver (which specializes in movie/TV lookups via TMDB)
            # MediaResolver has a search method or equivalent. Let's fall back to EntityResolver if not fully mapped.
            try:
                # MediaResolver uses query, so let's resolve
                res = await self.media_resolver.search(query)
                return res
            except AttributeError:
                pass
        
        return await self.entity_resolver.search(query)

    async def bulk_discover(self, queries: list[EntityQuery], progress_cb: Any = None) -> BulkSearchResponse:
        """Runs batch profile discovery across multiple queries."""
        results = []
        total = len(queries)
        for idx, query in enumerate(queries):
            try:
                res = await self.discover(query)
                if res.selected_entity:
                    results.append(BulkLookupResult(
                        query=query,
                        selected_entity=res.selected_entity,
                        resolution_status="resolved" if not res.disambiguation_required else "ambiguous",
                        platform_results=res.platform_results,
                        notes=res.notes
                    ))
                else:
                    results.append(BulkLookupResult(
                        query=query,
                        resolution_status="not_found",
                        notes=res.notes
                    ))
            except Exception as e:
                results.append(BulkLookupResult(
                    query=query,
                    resolution_status="not_found",
                    notes=[f"Lookup error: {str(e)}"]
                ))
            
            if progress_cb:
                progress_cb(idx + 1, total)

        return BulkSearchResponse(
            results=results,
            notes=["Bulk profile discovery completed using unified heuristics."]
        )
