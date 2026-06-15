from __future__ import annotations

import asyncio
import hashlib
import uuid

from app.cache import TTLCache
from app.interfaces import ScoringEngine, SearchProvider
from app.models import (
    BulkLookupResult,
    BulkSearchResponse,
    EntityCandidate,
    EntityQuery,
    EvidenceItem,
    SearchResponse,
    SearchResult,
    SearchSession,
)
from app.services.official_link_resolver import OfficialLinkResolver


class EntityResolver:
    ENTITY_TYPES = [
        ("company", "Company"),
        ("influencer", "Influencer"),
        ("celebrity", "Celebrity"),
        ("tv_show", "TV Show"),
        ("movie", "Movie"),
        ("game_publisher", "Game Publisher"),
        ("game_developer", "Game Developer"),
        ("other", "Other"),
    ]
    COMPANY_ENTITY_TYPES = [
        ("company", "Company"),
        ("game_publisher", "Game Publisher"),
        ("game_developer", "Game Developer"),
        ("other", "Other"),
    ]
    TALENT_TYPES = [
        ("influencer", "Influencer"),
        ("celebrity", "Celebrity"),
    ]
    TALENT_PROFESSIONS = [
        "Actor",
        "Singer",
        "Footballer",
        "Cricketer",
        "Model",
        "Comedian",
        "YouTuber",
        "Streamer",
        "Dancer",
        "Rapper",
        "TV Host",
        "Creator",
    ]
    SUPPORTED_PLATFORMS = ["Facebook", "Instagram", "YouTube", "X/Twitter", "TikTok", "Wikipedia", "IMDb"]

    def __init__(
        self,
        *,
        search_provider: SearchProvider,
        scoring_engine: ScoringEngine,
        official_link_resolver: OfficialLinkResolver,
        cache: TTLCache,
    ) -> None:
        self.search_provider = search_provider
        self.scoring_engine = scoring_engine
        self.official_link_resolver = official_link_resolver
        self.cache = cache

    async def search(self, query: EntityQuery) -> SearchResponse:
        entity_candidates = await self._find_entity_candidates(query)
        if not entity_candidates:
            return SearchResponse(
                query=query,
                disambiguation_required=False,
                platform_results=[],
                notes=["No likely entities were found for this query."],
            )

        if self._needs_disambiguation(entity_candidates):
            session_id = str(uuid.uuid4())
            self.cache.set(
                f"session:{session_id}",
                SearchSession(session_id=session_id, query=query, candidates=entity_candidates[:6]),
            )
            return SearchResponse(
                query=query,
                session_id=session_id,
                disambiguation_required=True,
                entity_candidates=entity_candidates[:6],
                notes=["Select the entity that best matches your intent before profile discovery runs."],
            )

        return await self._discover_profiles(query, entity_candidates[0])

    async def resolve_from_session(self, *, session_id: str, candidate_id: str) -> SearchResponse:
        session = self.cache.get(f"session:{session_id}")
        if not isinstance(session, SearchSession):
            return SearchResponse(
                query=EntityQuery(name="Session expired"),
                disambiguation_required=False,
                platform_results=[],
                notes=["This search session expired. Please run the search again."],
            )

        selected = next((item for item in session.candidates if item.candidate_id == candidate_id), None)
        if selected is None:
            return SearchResponse(
                query=session.query,
                disambiguation_required=False,
                platform_results=[],
                notes=["The selected entity was not found in the current session."],
            )

        return await self._discover_profiles(session.query, selected)

    async def bulk_search(self, queries: list[EntityQuery], *, max_concurrency: int = 5) -> BulkSearchResponse:
        semaphore = asyncio.Semaphore(max_concurrency)

        async def run(query: EntityQuery) -> BulkLookupResult:
            async with semaphore:
                try:
                    return await self._bulk_lookup(query)
                except Exception as exc:
                    return BulkLookupResult(
                        query=query,
                        resolution_status="not_found",
                        notes=[f"Lookup failed: {exc.__class__.__name__}: {exc}"],
                    )

        results = await asyncio.gather(*(run(query) for query in queries))
        return BulkSearchResponse(
            results=results,
            notes=[
                "Bulk lookup auto-skips ambiguous entities instead of guessing.",
                "Profiles are treated as valid only when confidence is 60 or higher.",
                "Free mode uses Wikimedia data and official website links, so some entities may return fewer platforms.",
            ],
        )

    async def _find_entity_candidates(self, query: EntityQuery) -> list[EntityCandidate]:
        qualifiers = []
        if query.entity_type:
            qualifiers.append(query.entity_type.replace("_", " "))
        if query.profession:
            qualifiers.append(query.profession)
        if query.date_of_birth:
            qualifiers.append(query.date_of_birth)
        if query.country:
            qualifiers.append(query.country)
        qualifier_suffix = f" {' '.join(qualifiers)}" if qualifiers else ""
        search_queries = [f'"{query.name}"{qualifier_suffix}', query.name]

        result_sets = await asyncio.gather(
            *(self.search_provider.search(search_query, limit=6) for search_query in search_queries),
            return_exceptions=True,
        )
        candidates: dict[str, EntityCandidate] = {}

        for results in result_sets:
            if isinstance(results, BaseException):
                continue
            for result in results:
                candidate = self._candidate_from_result(query, result)
                key = self._candidate_key(candidate)
                existing = candidates.get(key)
                if existing is None:
                    candidates[key] = candidate
                    continue
                existing.score += 4
                existing.evidence.extend(candidate.evidence)
                if len(existing.description) < len(candidate.description):
                    existing.description = candidate.description

        scored = self.scoring_engine.score_entity_candidates(query, list(candidates.values()))
        return scored[:6]

    async def _discover_profiles(self, query: EntityQuery, entity: EntityCandidate) -> SearchResponse:
        raw_links_by_platform = await self.official_link_resolver.discover(entity)
        platform_results = []
        for platform in self.SUPPORTED_PLATFORMS:
            raw_candidates = raw_links_by_platform.get(platform, [])
            platform_results.append(
                self.scoring_engine.score_profile_candidates(query, entity, platform, raw_candidates)
            )

        return SearchResponse(
            query=query,
            selected_entity=entity,
            disambiguation_required=False,
            platform_results=platform_results,
            notes=[
                "Confidence is heuristic and should be reviewed before reuse.",
                "This free mode prioritizes Wikimedia data and official website links over paid web search.",
            ],
        )

    async def _bulk_lookup(self, query: EntityQuery) -> BulkLookupResult:
        entity_candidates = await self._find_entity_candidates(query)
        if not entity_candidates:
            return BulkLookupResult(
                query=query,
                resolution_status="not_found",
                notes=["No likely entity was found."],
            )

        if self._needs_disambiguation(entity_candidates):
            return BulkLookupResult(
                query=query,
                selected_entity=entity_candidates[0],
                resolution_status="ambiguous",
                notes=["Multiple strong entity matches were found, so this item was skipped."],
            )

        response = await self._discover_profiles(query, entity_candidates[0])
        return BulkLookupResult(
            query=query,
            selected_entity=response.selected_entity,
            resolution_status="resolved",
            platform_results=response.platform_results,
            notes=response.notes,
        )

    def _candidate_from_result(self, query: EntityQuery, result: SearchResult) -> EntityCandidate:
        label = self._extract_label(result.title)
        evidence = []
        if any(result.source_domain.endswith(domain) for domain in ("wikipedia.org", "wikidata.org", "imdb.com")):
            evidence.append(EvidenceItem(summary="Candidate discovered from a trusted reference", weight=10))
        if query.profession and query.profession.lower() in (result.snippet or "").lower():
            evidence.append(EvidenceItem(summary="Profession hint appears in candidate description", weight=8))
        if query.date_of_birth and query.date_of_birth in (result.snippet or ""):
            evidence.append(EvidenceItem(summary="Date-of-birth hint appears in candidate description", weight=8))

        description = result.snippet or f"Found on {result.source_domain}"
        return EntityCandidate(
            candidate_id=self._stable_id(result.url),
            label=label,
            canonical_name=label,
            description=description,
            source_url=result.url,
            source_domain=result.source_domain,
            wikidata_id=result.metadata.get("wikidata_id"),
            entity_type_hint=query.entity_type,
            country_hint=query.country,
            score=8.0,
            evidence=evidence,
        )

    def _extract_label(self, title: str) -> str:
        for separator in [" | ", " - "]:
            if separator in title:
                first = title.split(separator, 1)[0].strip()
                if first:
                    return first
        return title.strip()

    def _candidate_key(self, candidate: EntityCandidate) -> str:
        if candidate.wikidata_id:
            return candidate.wikidata_id
        normalized_name = "".join(ch.lower() if ch.isalnum() else " " for ch in candidate.label).split()
        return " ".join(normalized_name)

    def _stable_id(self, value: str) -> str:
        return hashlib.sha1(value.encode("utf-8")).hexdigest()[:12]

    def _needs_disambiguation(self, candidates: list[EntityCandidate]) -> bool:
        if len(candidates) < 2:
            return False
        first = candidates[0].score
        second = candidates[1].score
        return first < 70 or (first - second) < 12
