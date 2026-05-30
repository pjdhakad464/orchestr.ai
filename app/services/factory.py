from app.cache import TTLCache
from app.config import settings
from app.services.entity_resolver import EntityResolver
from app.services.media_resolver import MediaResolver
from app.services.official_link_resolver import OfficialLinkResolver
from app.services.scoring import HeuristicScoringEngine
from app.services.search_provider import WikimediaSearchProvider, SerpApiSearchProvider
from app.services.tmdb_client import TmdbClient


def build_entity_resolver(cache: TTLCache) -> EntityResolver:
    if settings.serpapi_api_key:
        provider = SerpApiSearchProvider(
            timeout_seconds=settings.request_timeout_seconds,
            cache=cache,
        )
    else:
        provider = WikimediaSearchProvider(
            timeout_seconds=settings.request_timeout_seconds,
            cache=cache,
        )
    official_link_resolver = OfficialLinkResolver(
        timeout_seconds=settings.request_timeout_seconds,
        cache=cache,
    )
    scoring = HeuristicScoringEngine()
    return EntityResolver(
        search_provider=provider,
        scoring_engine=scoring,
        official_link_resolver=official_link_resolver,
        cache=cache,
    )


def build_media_resolver(cache: TTLCache) -> MediaResolver:
    official_link_resolver = OfficialLinkResolver(
        timeout_seconds=settings.request_timeout_seconds,
        cache=cache,
    )
    scoring = HeuristicScoringEngine()
    tmdb_client = TmdbClient(
        timeout_seconds=settings.request_timeout_seconds,
        cache=cache,
    )
    return MediaResolver(
        tmdb_client=tmdb_client,
        scoring_engine=scoring,
        official_link_resolver=official_link_resolver,
    )
