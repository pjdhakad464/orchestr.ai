from __future__ import annotations

import asyncio
import hashlib

from app.models import EntityCandidate, EntityQuery, EvidenceItem, SearchResponse
from app.services.official_link_resolver import OfficialLinkResolver
from app.services.scoring import HeuristicScoringEngine
from app.services.tmdb_client import TmdbClient, TmdbUnavailableError


class MediaResolver:
    MEDIA_TYPES = [
        ("movie", "Movie"),
        ("tv_show", "TV Show"),
        ("tv_network", "TV Network"),
    ]

    SUPPORTED_PLATFORMS = ["Facebook", "Instagram", "YouTube", "X/Twitter", "TikTok", "Wikipedia", "IMDb"]
    MAJOR_STUDIOS = {
        "warner bros. pictures",
        "warner bros",
        "universal pictures",
        "paramount pictures",
        "walt disney pictures",
        "pixar",
        "marvel studios",
        "20th century studios",
        "columbia pictures",
        "sony pictures",
        "sony pictures entertainment",
    }

    def __init__(
        self,
        *,
        tmdb_client: TmdbClient,
        scoring_engine: HeuristicScoringEngine,
        official_link_resolver: OfficialLinkResolver,
    ) -> None:
        self.tmdb_client = tmdb_client
        self.scoring_engine = scoring_engine
        self.official_link_resolver = official_link_resolver

    async def search(self, query: EntityQuery) -> SearchResponse:
        candidates = await self._find_media_candidates(query)
        if not candidates:
            return SearchResponse(
                query=query,
                platform_results=[],
                notes=["No matching media records were found in TMDB for this search."],
            )

        candidates = self.scoring_engine.score_entity_candidates(query, candidates)
        if len(candidates) > 1 and self._needs_disambiguation(candidates):
            return SearchResponse(
                query=query,
                disambiguation_required=True,
                entity_candidates=candidates[:6],
                notes=["Select the title or network that best matches your media search."],
            )

        return await self._discover_profiles(query, candidates[0])

    async def resolve_candidate(self, query: EntityQuery, candidate: EntityCandidate) -> SearchResponse:
        return await self._discover_profiles(query, candidate)

    async def _find_media_candidates(self, query: EntityQuery) -> list[EntityCandidate]:
        media_type = query.entity_type or "movie"
        if media_type == "movie":
            payload = await self.tmdb_client.search_movie(query.name)
            return [self._movie_candidate(item, query) for item in payload.get("results", [])[:8]]
        if media_type == "tv_show":
            payload = await self.tmdb_client.search_tv(query.name)
            return [self._tv_candidate(item, query) for item in payload.get("results", [])[:8]]
        payload = await self.tmdb_client.search_company(query.name)
        return [self._network_candidate(item, query) for item in payload.get("results", [])[:8]]

    async def _discover_profiles(self, query: EntityQuery, entity: EntityCandidate) -> SearchResponse:
        media_kind = entity.source_metadata.get("tmdb_kind")
        media_id = entity.source_metadata.get("tmdb_id")
        raw_links = {platform: [] for platform in self.SUPPORTED_PLATFORMS}
        notes = [
            "TMDB is the primary source for media metadata in this tool.",
            "Social links are shown only when they come from TMDB external IDs or links found on the official website.",
            "Only platform matches above the configured confidence threshold are shown as valid.",
        ]

        if media_kind == "movie":
            details, external_ids, release_dates = await asyncio.gather(
                self.tmdb_client.movie_details(media_id or ""),
                self.tmdb_client.movie_external_ids(media_id or ""),
                self.tmdb_client.movie_release_dates(media_id or ""),
            )
            self._apply_movie_metadata(entity, details, release_dates)
            raw_links = await self._build_media_links(entity, details, external_ids, media_kind)
        elif media_kind == "tv":
            details, external_ids = await asyncio.gather(
                self.tmdb_client.tv_details(media_id or ""),
                self.tmdb_client.tv_external_ids(media_id or ""),
            )
            self._apply_tv_metadata(entity, details)
            raw_links = await self._build_media_links(entity, details, external_ids, media_kind)
        elif media_kind == "company":
            details = await self.tmdb_client.company_details(media_id or "")
            self._apply_company_metadata(entity, details)
            raw_links = await self._build_company_links(entity, details)

        platform_results = []
        for platform in self.SUPPORTED_PLATFORMS:
            platform_results.append(
                self.scoring_engine.score_profile_candidates(query, entity, platform, raw_links.get(platform, []))
            )

        if not any(result.primary for result in platform_results):
            notes.append("No official social links were published in TMDB or on the title's official website.")

        return SearchResponse(
            query=query,
            selected_entity=entity,
            platform_results=platform_results,
            notes=notes,
        )

    async def _build_media_links(
        self,
        entity: EntityCandidate,
        details: dict,
        external_ids: dict,
        media_kind: str,
    ) -> dict[str, list[dict]]:
        links = {platform: [] for platform in self.SUPPORTED_PLATFORMS}
        homepage = details.get("homepage")
        if homepage:
            entity.official_website = homepage
            site_links = await self.official_link_resolver.extract_social_links(homepage, entity.canonical_name)
            for platform, candidates in site_links.items():
                links[platform].extend(candidates)

        if details.get("imdb_id"):
            links["IMDb"].append(self._candidate("IMDb", f"https://www.imdb.com/title/{details['imdb_id']}", entity))
        elif external_ids.get("imdb_id"):
            links["IMDb"].append(self._candidate("IMDb", f"https://www.imdb.com/title/{external_ids['imdb_id']}", entity))

        if external_ids.get("facebook_id"):
            links["Facebook"].append(self._candidate("Facebook", f"https://www.facebook.com/{external_ids['facebook_id']}", entity))
        if external_ids.get("instagram_id"):
            links["Instagram"].append(self._candidate("Instagram", f"https://www.instagram.com/{external_ids['instagram_id']}", entity))
        if external_ids.get("twitter_id"):
            links["X/Twitter"].append(self._candidate("X/Twitter", f"https://x.com/{external_ids['twitter_id']}", entity))

        for network in details.get("networks", []):
            homepage = network.get("homepage")
            if homepage:
                site_links = await self.official_link_resolver.extract_social_links(homepage, network.get("name") or entity.canonical_name)
                for platform, candidates in site_links.items():
                    links[platform].extend(candidates)

        return self._dedupe(links)

    async def _build_company_links(self, entity: EntityCandidate, details: dict) -> dict[str, list[dict]]:
        links = {platform: [] for platform in self.SUPPORTED_PLATFORMS}
        homepage = details.get("homepage")
        if homepage:
            entity.official_website = homepage
            site_links = await self.official_link_resolver.extract_social_links(homepage, entity.canonical_name)
            for platform, candidates in site_links.items():
                links[platform].extend(candidates)
        return self._dedupe(links)

    def _apply_movie_metadata(self, entity: EntityCandidate, details: dict, release_dates: dict) -> None:
        genres = [genre.get("name") for genre in details.get("genres", []) if genre.get("name")]
        studios = [company.get("name") for company in details.get("production_companies", []) if company.get("name")]
        entity.source_metadata.update(
            {
                "metadata_source": "TMDB",
                "official_website": entity.official_website or details.get("homepage") or "",
                "release_date": details.get("release_date") or entity.source_metadata.get("release_year", ""),
                "genre": ", ".join(genres[:3]),
                "network": ", ".join(studios[:3]),
                "studio_type": self._infer_studio_type(studios),
                "release_type": self._infer_release_type(release_dates),
            }
        )

    def _apply_tv_metadata(self, entity: EntityCandidate, details: dict) -> None:
        genres = [genre.get("name") for genre in details.get("genres", []) if genre.get("name")]
        networks = [network.get("name") for network in details.get("networks", []) if network.get("name")]
        production_companies = [
            company.get("name") for company in details.get("production_companies", []) if company.get("name")
        ]
        studio_names = networks or production_companies
        entity.source_metadata.update(
            {
                "metadata_source": "TMDB",
                "official_website": entity.official_website or details.get("homepage") or "",
                "release_date": details.get("first_air_date") or entity.source_metadata.get("first_air_year", ""),
                "genre": ", ".join(genres[:3]),
                "network": ", ".join(networks[:3]),
                "studio_type": self._infer_studio_type(studio_names),
                "release_type": details.get("type") or "Series",
            }
        )

    def _apply_company_metadata(self, entity: EntityCandidate, details: dict) -> None:
        company_name = details.get("name") or entity.canonical_name
        entity.source_metadata.update(
            {
                "metadata_source": "TMDB",
                "official_website": entity.official_website or details.get("homepage") or "",
                "network": company_name,
                "studio_type": self._infer_studio_type([company_name]),
            }
        )

    def _infer_release_type(self, release_dates: dict) -> str:
        release_entries: list[dict] = []
        us_entries: list[dict] = []
        for result in release_dates.get("results", []):
            entries = result.get("release_dates", [])
            release_entries.extend(entries)
            if result.get("iso_3166_1") == "US":
                us_entries.extend(entries)

        preferred = us_entries or release_entries
        release_types = {entry.get("type") for entry in preferred if entry.get("type")}
        if 3 in release_types:
            return "Wide"
        if 2 in release_types:
            return "Limited"
        if 4 in release_types:
            return "Digital"
        if 6 in release_types:
            return "TV"
        if 5 in release_types:
            return "Physical"
        if 1 in release_types:
            return "Premiere"
        return ""

    def _infer_studio_type(self, studio_names: list[str]) -> str:
        normalized = {name.lower() for name in studio_names if name}
        if not normalized:
            return ""
        if normalized & self.MAJOR_STUDIOS:
            return "Major"
        return "Independent"

    def _movie_candidate(self, item: dict, query: EntityQuery) -> EntityCandidate:
        title = item.get("title") or item.get("original_title") or query.name
        year = (item.get("release_date") or "")[:4]
        description = item.get("overview") or "Movie result from TMDB"
        if year:
            description = f"{description} ({year})"
        return EntityCandidate(
            candidate_id=self._stable_id(f"movie:{item.get('id')}"),
            label=title,
            canonical_name=title,
            description=description,
            source_url=f"https://www.themoviedb.org/movie/{item.get('id')}",
            source_domain="www.themoviedb.org",
            entity_type_hint="movie",
            source_metadata={"tmdb_id": str(item.get("id")), "tmdb_kind": "movie", "release_year": year},
            score=10,
            evidence=[EvidenceItem(summary="Matched via TMDB movie search", weight=10)],
        )

    def _tv_candidate(self, item: dict, query: EntityQuery) -> EntityCandidate:
        title = item.get("name") or item.get("original_name") or query.name
        year = (item.get("first_air_date") or "")[:4]
        description = item.get("overview") or "TV show result from TMDB"
        if year:
            description = f"{description} ({year})"
        return EntityCandidate(
            candidate_id=self._stable_id(f"tv:{item.get('id')}"),
            label=title,
            canonical_name=title,
            description=description,
            source_url=f"https://www.themoviedb.org/tv/{item.get('id')}",
            source_domain="www.themoviedb.org",
            entity_type_hint="tv_show",
            source_metadata={"tmdb_id": str(item.get("id")), "tmdb_kind": "tv", "first_air_year": year},
            score=10,
            evidence=[EvidenceItem(summary="Matched via TMDB TV search", weight=10)],
        )

    def _network_candidate(self, item: dict, query: EntityQuery) -> EntityCandidate:
        title = item.get("name") or query.name
        description = "TV network or media company result from TMDB company search"
        origin = item.get("origin_country")
        if origin:
            description = f"{description} ({origin})"
        return EntityCandidate(
            candidate_id=self._stable_id(f"company:{item.get('id')}"),
            label=title,
            canonical_name=title,
            description=description,
            source_url=f"https://www.themoviedb.org/company/{item.get('id')}",
            source_domain="www.themoviedb.org",
            entity_type_hint="tv_network",
            source_metadata={"tmdb_id": str(item.get("id")), "tmdb_kind": "company"},
            score=10,
            evidence=[EvidenceItem(summary="Matched via TMDB company search", weight=10)],
        )

    def _candidate(self, platform: str, url: str, entity: EntityCandidate) -> dict:
        handle = url.rstrip("/").split("/")[-1]
        if platform == "TikTok" and not handle.startswith("@"):
            handle = f"@{handle}"
        return {
            "platform": platform,
            "url": url,
            "handle": handle,
            "display_name": entity.canonical_name,
            "title": f"{entity.canonical_name} {platform}",
            "snippet": "TMDB external ids or official website",
            "source_domain": url.split("/")[2].lower(),
            "account_labels": ["official"],
            "negative_hints": [],
        }

    def _dedupe(self, links: dict[str, list[dict]]) -> dict[str, list[dict]]:
        deduped = {platform: [] for platform in self.SUPPORTED_PLATFORMS}
        for platform, candidates in links.items():
            seen: set[str] = set()
            for candidate in candidates:
                key = candidate["url"].lower()
                if key in seen:
                    continue
                seen.add(key)
                deduped[platform].append(candidate)
        return deduped

    def _needs_disambiguation(self, candidates: list[EntityCandidate]) -> bool:
        if len(candidates) < 2:
            return False
        return candidates[0].score - candidates[1].score < 10

    def _stable_id(self, value: str) -> str:
        return hashlib.sha1(value.encode("utf-8")).hexdigest()[:12]
