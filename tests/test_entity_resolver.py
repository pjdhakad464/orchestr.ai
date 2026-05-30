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


from unittest.mock import AsyncMock, patch
from app.services.search_provider import SerpApiSearchProvider

@pytest.mark.asyncio
async def test_serpapi_search_provider():
    from app.config import settings
    settings.serpapi_api_key = "test_key"
    settings.serpapi_engine = "google"

    mock_payload = {
        "knowledge_graph": {
            "profiles": [
                {"name": "Twitter", "link": "https://twitter.com/openai", "title": "Twitter"}
            ]
        },
        "organic_results": [
            {
                "title": "OpenAI Website",
                "link": "https://openai.com",
                "snippet": "Artificial intelligence research laboratory"
            }
        ]
    }

    provider = SerpApiSearchProvider(timeout_seconds=5, cache=TTLCache(900))
    
    with patch.object(provider.client, "get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = AsyncMock(
            status_code=200,
            json=lambda: mock_payload,
            raise_for_status=lambda: None
        )

        results = await provider.search("OpenAI", limit=5)
        
        assert len(results) == 2
        assert results[0].title == "Twitter"
        assert results[0].url == "https://twitter.com/openai"
        assert results[0].snippet == "Google knowledge graph social profile"
        assert results[1].title == "OpenAI Website"
        assert results[1].url == "https://openai.com"
        assert results[1].snippet == "Artificial intelligence research laboratory"

