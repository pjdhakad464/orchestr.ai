from __future__ import annotations

from typing import Protocol

from app.models import EntityCandidate, EntityQuery, PlatformResult, SearchResult


class SearchProvider(Protocol):
    async def search(self, query: str, *, limit: int = 10) -> list[SearchResult]:
        ...


class PlatformAdapter(Protocol):
    platform: str

    def build_queries(self, query: EntityQuery, entity: EntityCandidate) -> list[str]:
        ...

    def extract_candidates(self, results: list[SearchResult]) -> list[dict]:
        ...


class ScoringEngine(Protocol):
    def score_entity_candidates(
        self, query: EntityQuery, candidates: list[EntityCandidate]
    ) -> list[EntityCandidate]:
        ...

    def score_profile_candidates(
        self,
        query: EntityQuery,
        entity: EntityCandidate,
        platform: str,
        raw_candidates: list[dict],
    ) -> PlatformResult:
        ...
