import pytest

from app.models import EntityCandidate, EntityQuery
from app.services.media_resolver import MediaResolver
from app.services.scoring import HeuristicScoringEngine


class FakeTmdbClient:
    async def movie_details(self, movie_id):
        return {
            "id": movie_id,
            "homepage": "https://www.barbiethemovie.com",
            "imdb_id": "tt1517268",
            "release_date": "2023-07-21",
            "genres": [{"name": "Comedy"}, {"name": "Adventure"}],
            "production_companies": [{"name": "Warner Bros. Pictures"}],
            "networks": [],
        }

    async def movie_external_ids(self, movie_id):
        return {
            "instagram_id": "barbiethemovie",
            "facebook_id": "barbiethemovie",
            "twitter_id": "barbiethemovie",
            "imdb_id": "tt1517268",
        }

    async def movie_release_dates(self, movie_id):
        return {
            "results": [
                {
                    "iso_3166_1": "US",
                    "release_dates": [{"type": 3}],
                }
            ]
        }

    async def tv_details(self, tv_id):
        return {"id": tv_id, "homepage": "", "networks": [], "genres": [], "production_companies": []}

    async def tv_external_ids(self, tv_id):
        return {}

    async def company_details(self, company_id):
        return {"id": company_id, "homepage": "", "name": "Test Network"}


class FakeOfficialLinkResolver:
    async def extract_social_links(self, website_url: str, entity_name: str):
        return {
            "Facebook": [],
            "Instagram": [],
            "YouTube": [
                {
                    "platform": "YouTube",
                    "url": "https://youtube.com/@BarbieMovie",
                    "handle": "@BarbieMovie",
                    "display_name": entity_name,
                    "title": f"{entity_name} YouTube",
                    "snippet": "Linked from official website",
                    "source_domain": "youtube.com",
                    "account_labels": ["official"],
                    "negative_hints": [],
                }
            ],
            "X/Twitter": [],
            "TikTok": [],
            "Wikipedia": [],
            "IMDb": [],
        }


def movie_entity() -> EntityCandidate:
    return EntityCandidate(
        candidate_id="movie-1",
        label="Barbie",
        canonical_name="Barbie",
        description="Movie result from TMDB (2023)",
        source_url="https://www.themoviedb.org/movie/346698",
        source_domain="www.themoviedb.org",
        entity_type_hint="movie",
        source_metadata={"tmdb_id": "346698", "tmdb_kind": "movie", "release_year": "2023"},
        score=90,
    )


@pytest.mark.asyncio
async def test_media_resolver_prefers_tmdb_and_official_site_metadata():
    resolver = MediaResolver(
        tmdb_client=FakeTmdbClient(),
        scoring_engine=HeuristicScoringEngine(),
        official_link_resolver=FakeOfficialLinkResolver(),
    )

    response = await resolver.resolve_candidate(
        EntityQuery(name="Barbie", entity_type="movie"),
        movie_entity(),
    )

    selected = response.selected_entity
    assert selected is not None
    assert selected.source_metadata["metadata_source"] == "TMDB"
    assert selected.source_metadata["release_type"] == "Wide"
    assert selected.source_metadata["studio_type"] == "Major"
    assert selected.source_metadata["genre"] == "Comedy, Adventure"
    assert selected.source_metadata["release_date"] == "2023-07-21"
    assert selected.source_metadata["network"] == "Warner Bros. Pictures"
    assert selected.official_website == "https://www.barbiethemovie.com"

    instagram = next(result for result in response.platform_results if result.platform == "Instagram")
    youtube = next(result for result in response.platform_results if result.platform == "YouTube")

    assert instagram.primary is not None
    assert instagram.primary.url == "https://www.instagram.com/barbiethemovie"
    assert youtube.primary is not None
    assert youtube.primary.url == "https://youtube.com/@BarbieMovie"


@pytest.mark.asyncio
async def test_media_resolver_reports_missing_socials_cleanly():
    class EmptyOfficialLinkResolver:
        async def extract_social_links(self, website_url: str, entity_name: str):
            return {platform: [] for platform in MediaResolver.SUPPORTED_PLATFORMS}

    class SparseTmdbClient(FakeTmdbClient):
        async def movie_details(self, movie_id):
            return {
                "id": movie_id,
                "homepage": "",
                "imdb_id": "",
                "release_date": "2023-07-21",
                "genres": [],
                "production_companies": [],
                "networks": [],
            }

        async def movie_external_ids(self, movie_id):
            return {}

    resolver = MediaResolver(
        tmdb_client=SparseTmdbClient(),
        scoring_engine=HeuristicScoringEngine(),
        official_link_resolver=EmptyOfficialLinkResolver(),
    )

    response = await resolver.resolve_candidate(
        EntityQuery(name="Barbie", entity_type="movie"),
        movie_entity(),
    )

    assert any("no official social links were published" in note.lower() for note in response.notes)
