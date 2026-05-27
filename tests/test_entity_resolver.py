import pytest

from app.cache import TTLCache
from app.models import EntityQuery, SearchResult
from app.services.entity_resolver import EntityResolver
from app.services.scoring import HeuristicScoringEngine


class FakeSearchProvider:
    def __init__(self, query_map):
        self.query_map = query_map

    async def search(self, query: str, *, limit: int = 10):
        return self.query_map.get(query, [])[:limit]


class FakeOfficialLinkResolver:
    async def discover(self, entity):
        return {platform: [] for platform in EntityResolver.SUPPORTED_PLATFORMS}


@pytest.mark.asyncio
async def test_search_requires_disambiguation_for_close_entity_scores():
    provider = FakeSearchProvider(
        {
            '"Avatar" movie': [
                SearchResult(
                    title="Avatar (2009 film)",
                    url="https://en.wikipedia.org/wiki/Avatar_(2009_film)",
                    snippet="2009 epic science fiction film",
                    source_domain="en.wikipedia.org",
                    metadata={"wikidata_id": "Q1"},
                ),
                SearchResult(
                    title="Avatar: The Last Airbender",
                    url="https://en.wikipedia.org/wiki/Avatar:_The_Last_Airbender",
                    snippet="American animated fantasy television series",
                    source_domain="en.wikipedia.org",
                    metadata={"wikidata_id": "Q2"},
                ),
            ],
            "Avatar": [
                SearchResult(
                    title="Avatar (2009 film)",
                    url="https://en.wikipedia.org/wiki/Avatar_(2009_film)",
                    snippet="2009 epic science fiction film",
                    source_domain="en.wikipedia.org",
                    metadata={"wikidata_id": "Q1"},
                ),
                SearchResult(
                    title="Avatar: The Last Airbender",
                    url="https://en.wikipedia.org/wiki/Avatar:_The_Last_Airbender",
                    snippet="American animated fantasy television series",
                    source_domain="en.wikipedia.org",
                    metadata={"wikidata_id": "Q2"},
                ),
            ],
        }
    )
    resolver = EntityResolver(
        search_provider=provider,
        scoring_engine=HeuristicScoringEngine(),
        official_link_resolver=FakeOfficialLinkResolver(),
        cache=TTLCache(900),
    )

    response = await resolver.search(EntityQuery(name="Avatar", entity_type="movie"))
    assert response.disambiguation_required is True
    assert len(response.entity_candidates) >= 2
    assert response.entity_candidates[0].label != response.entity_candidates[1].label
