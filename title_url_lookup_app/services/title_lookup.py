from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import unquote, urlparse

from title_url_lookup_app.cache import TTLCache
from title_url_lookup_app.config import settings
from title_url_lookup_app.models import (
    BulkTitleLookupResponse,
    SiteLookupResult,
    TitleLookupQuery,
    TitleLookupResponse,
    TitleType,
    TitleUrlCandidate,
)
from title_url_lookup_app.search_models import SearchResult
from title_url_lookup_app.search_provider import (
    DuckDuckGoSearchProvider,
    SearchProviderUnavailableError,
    WikimediaSearchProvider,
)
from title_url_lookup_app.services.imdb_dataset import ImdbDatasetLookupError, ImdbDatasetLookupService


class SearchProvider(Protocol):
    async def search(self, query: str, *, limit: int = 10) -> list[SearchResult]:
        ...


@dataclass(frozen=True)
class SiteDefinition:
    key: str
    label: str


SITE_DEFINITIONS = (
    SiteDefinition(key="wikipedia", label="Wikipedia"),
    SiteDefinition(key="rottentomatoes", label="Rotten Tomatoes"),
    SiteDefinition(key="imdb", label="IMDb"),
    SiteDefinition(key="metacritic", label="Metacritic"),
)

MOVIE_HINTS = {"movie", "film", "feature"}
TV_HINTS = {"tv", "television", "series", "show", "miniseries", "mini", "season"}


class TitleUrlLookupService:
    def __init__(
        self,
        ddg_provider: SearchProvider | None = None,
        wiki_provider: SearchProvider | None = None,
        imdb_dataset_lookup: ImdbDatasetLookupService | None = None,
    ) -> None:
        cache = TTLCache(settings.cache_ttl_seconds)
        self.ddg_provider = ddg_provider or DuckDuckGoSearchProvider(settings.request_timeout_seconds, cache)
        self.wiki_provider = wiki_provider or WikimediaSearchProvider(settings.request_timeout_seconds, cache)
        self.imdb_dataset_lookup = imdb_dataset_lookup or ImdbDatasetLookupService()

    async def lookup_title(self, query: TitleLookupQuery) -> TitleLookupResponse:
        tasks = [self._lookup_site(site, query) for site in SITE_DEFINITIONS]
        results = await asyncio.gather(*tasks)

        notes: list[str] = []
        if any(result.status == "uncertain" for result in results):
            notes.append("Some sites returned close alternatives. Adding a year or choosing movie vs TV will tighten the match.")
        if not any(result.primary for result in results):
            notes.append("No strong title matches were found on the requested sites.")

        return TitleLookupResponse(query=query, results=results, notes=notes)

    async def lookup_titles(self, queries: list[TitleLookupQuery]) -> BulkTitleLookupResponse:
        entries = await asyncio.gather(*(self.lookup_title(query) for query in queries))
        notes: list[str] = []
        uncertain_count = sum(1 for entry in entries if any(result.status == "uncertain" for result in entry.results))
        if uncertain_count:
            notes.append(f"{uncertain_count} title lookups include at least one uncertain site match.")
        return BulkTitleLookupResponse(entries=entries, notes=notes)

    async def _lookup_site(self, site: SiteDefinition, query: TitleLookupQuery) -> SiteLookupResult:
        try:
            if site.key == "imdb":
                candidates = self._lookup_imdb_candidates(query)
                if not candidates:
                    return SiteLookupResult(
                        site_key=site.key,
                        site_label=site.label,
                        notes=["No matching title page was found in the IMDb dataset."],
                    )

                top_candidate = candidates[0]
                status = self._result_status(query, candidates)
                notes = []
                if status == "uncertain":
                    notes.append("The best IMDb dataset match is close, but another title scored similarly.")

                return SiteLookupResult(
                    site_key=site.key,
                    site_label=site.label,
                    status=status,
                    primary=top_candidate,
                    alternates=candidates[1:4],
                    notes=notes,
                )
            if site.key == "wikipedia":
                search_query = self._build_wikipedia_query(query)
                raw_results = await self.wiki_provider.search(search_query, limit=8)
            else:
                queries = self._build_site_queries(site.key, query)
                batches = await asyncio.gather(*(self.ddg_provider.search(item, limit=8) for item in queries))
                raw_results = [candidate for batch in batches for candidate in batch]
        except (SearchProviderUnavailableError, ImdbDatasetLookupError) as exc:
            return SiteLookupResult(
                site_key=site.key,
                site_label=site.label,
                notes=[str(exc)],
            )

        candidates = self._rank_candidates(site.key, query, raw_results)
        if not candidates:
            return SiteLookupResult(
                site_key=site.key,
                site_label=site.label,
                notes=["No matching title page was found."],
            )

        top_candidate = candidates[0]
        status = self._result_status(query, candidates)
        notes = []
        if status == "uncertain":
            notes.append("The best match is close, but another candidate scored similarly.")

        return SiteLookupResult(
            site_key=site.key,
            site_label=site.label,
            status=status,
            primary=top_candidate,
            alternates=candidates[1:4],
            notes=notes,
        )

    def _lookup_imdb_candidates(self, query: TitleLookupQuery) -> list[TitleUrlCandidate]:
        matches = self.imdb_dataset_lookup.lookup_title(query)
        candidates: list[TitleUrlCandidate] = []
        for match in matches:
            display_title = match.display_title
            if match.start_year:
                display_title = f"{display_title} ({match.start_year})"
            canonical_url = _canonicalize_site_url("imdb", match.url) or match.url.rstrip("/")
            candidates.append(
                TitleUrlCandidate(
                    url=canonical_url,
                    canonical_url=canonical_url,
                    result_title=display_title,
                    snippet=f"{match.title_type} | original title: {match.original_title or match.display_title}",
                    score=match.score,
                    matched_on=match.matched_on,
                )
            )
        return candidates

    def _build_wikipedia_query(self, query: TitleLookupQuery) -> str:
        terms = [query.title]
        if query.year:
            terms.append(query.year)
        if query.title_type == "movie":
            terms.append("film")
        elif query.title_type == "tv":
            terms.append("television series")
        return " ".join(term for term in terms if term.strip())

    def _build_site_queries(self, site_key: str, query: TitleLookupQuery) -> list[str]:
        base_terms = [f'"{query.title}"']
        if query.year:
            base_terms.append(query.year)
        if query.title_type == "movie":
            base_terms.append("movie")
        elif query.title_type == "tv":
            base_terms.append("tv series")

        base = " ".join(base_terms)
        if site_key == "imdb":
            return [f"{base} site:imdb.com/title"]
        if site_key == "rottentomatoes":
            if query.title_type == "movie":
                return [f"{base} site:rottentomatoes.com/m"]
            if query.title_type == "tv":
                return [f"{base} site:rottentomatoes.com/tv"]
            return [
                f"{base} site:rottentomatoes.com/m",
                f"{base} site:rottentomatoes.com/tv",
            ]
        if site_key == "metacritic":
            if query.title_type == "movie":
                return [f"{base} site:metacritic.com/movie"]
            if query.title_type == "tv":
                return [f"{base} site:metacritic.com/tv"]
            return [
                f"{base} site:metacritic.com/movie",
                f"{base} site:metacritic.com/tv",
            ]
        return [base]

    def _rank_candidates(
        self,
        site_key: str,
        query: TitleLookupQuery,
        raw_results: list[SearchResult],
    ) -> list[TitleUrlCandidate]:
        deduped: dict[str, TitleUrlCandidate] = {}
        for result in raw_results:
            canonical_url = _canonicalize_site_url(site_key, result.url)
            if not canonical_url:
                continue

            score, matched_on = _score_candidate(site_key, query, result, canonical_url)
            if score < 35:
                continue

            candidate = TitleUrlCandidate(
                url=canonical_url,
                canonical_url=canonical_url,
                result_title=_clean_result_title(site_key, result.title),
                snippet=result.snippet,
                score=round(score, 2),
                matched_on=matched_on,
            )
            existing = deduped.get(canonical_url)
            if existing is None or candidate.score > existing.score:
                deduped[canonical_url] = candidate

        return sorted(deduped.values(), key=lambda item: (-item.score, item.url))

    def _result_status(self, query: TitleLookupQuery, candidates: list[TitleUrlCandidate]) -> str:
        top = candidates[0]
        runner_up = candidates[1] if len(candidates) > 1 else None
        if top.score >= 68 and (runner_up is None or top.score - runner_up.score >= 8):
            return "found"
        if top.score >= 55 and query.year:
            return "found"
        if top.score >= 45:
            return "uncertain"
        return "not_found"


def _score_candidate(
    site_key: str,
    query: TitleLookupQuery,
    result: SearchResult,
    canonical_url: str,
) -> tuple[float, list[str]]:
    query_normalized = _normalize_text(query.title)
    query_tokens = set(query_normalized.split())
    cleaned_title = _clean_result_title(site_key, result.title)
    combined_text = _normalize_text(" ".join([cleaned_title, result.snippet, unquote(canonical_url)]))
    title_normalized = _normalize_text(cleaned_title)
    slug_normalized = _normalize_text(unquote(urlparse(canonical_url).path))

    score = 0.0
    matched_on: list[str] = []

    if query_normalized == title_normalized:
        score += 72
        matched_on.append("exact title match")
    elif query_normalized in title_normalized:
        score += 58
        matched_on.append("title phrase in result title")
    elif query_normalized in combined_text:
        score += 46
        matched_on.append("title phrase in result text")
    else:
        coverage = _token_coverage(query_tokens, set(combined_text.split()))
        score += coverage * 34
        if coverage:
            matched_on.append(f"{int(round(coverage * 100))}% title token coverage")

    slug_coverage = _token_coverage(query_tokens, set(slug_normalized.split()))
    if query_normalized in slug_normalized:
        score += 18
        matched_on.append("url slug matches title")
    else:
        score += slug_coverage * 10

    if result.position:
        score += max(0, 11 - result.position)

    if query.year:
        years = _extract_years(" ".join([cleaned_title, result.snippet, canonical_url]))
        if query.year in years:
            score += 20
            matched_on.append(f"year {query.year} matched")
        elif years:
            score -= 10

    inferred_type = _infer_title_type(site_key, canonical_url, f"{cleaned_title} {result.snippet}")
    if query.title_type != "any":
        if inferred_type == query.title_type:
            score += 12
            matched_on.append(f"{query.title_type} signal matched")
        elif inferred_type != "any":
            score -= 9

    if site_key == "wikipedia":
        if query.title_type == "movie" and "_film" in canonical_url.lower():
            score += 10
        if query.title_type == "tv" and (
            "television_series" in canonical_url.lower() or "_tv_series" in canonical_url.lower()
        ):
            score += 10

    if site_key == "imdb" and re.search(r"/title/tt\d+", canonical_url):
        score += 10
    if site_key == "rottentomatoes" and re.search(r"/(m|tv)/[^/]+$", canonical_url):
        score += 10
    if site_key == "metacritic" and re.search(r"/(movie|tv)/[^/]+$", canonical_url):
        score += 10

    return score, matched_on


def _canonicalize_site_url(site_key: str, url: str) -> str | None:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]

    path = parsed.path or "/"
    if site_key == "wikipedia":
        if host != "en.wikipedia.org":
            return None
        if not path.startswith("/wiki/") or "disambiguation" in path.lower():
            return None
        return f"https://{host}{path}"

    if site_key == "imdb":
        match = re.search(r"/title/(tt\d+)", path, flags=re.IGNORECASE)
        if not match:
            return None
        return f"https://{host}/title/{match.group(1).lower()}"

    if site_key == "rottentomatoes":
        match = re.search(r"/(m|tv)/([^/?#]+)", path, flags=re.IGNORECASE)
        if not match:
            return None
        return f"https://{host}/{match.group(1).lower()}/{match.group(2)}"

    if site_key == "metacritic":
        match = re.search(r"/(movie|tv)/([^/?#]+)", path, flags=re.IGNORECASE)
        if not match:
            return None
        return f"https://{host}/{match.group(1).lower()}/{match.group(2)}"

    return None


def _clean_result_title(site_key: str, title: str) -> str:
    cleaned = " ".join(title.split())
    replacements = {
        "imdb": [r"\s*-\s*IMDb\s*$"],
        "rottentomatoes": [r"\s*\|\s*Rotten Tomatoes\s*$"],
        "metacritic": [r"\s*-\s*Metacritic\s*$"],
    }
    for pattern in replacements.get(site_key, []):
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(
        r"\s+(reviews|review|details|credits|cast & crew|technical specifications)\s*$",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    return cleaned.strip()


def _normalize_text(value: str) -> str:
    lowered = value.casefold()
    lowered = re.sub(r"[^a-z0-9]+", " ", lowered)
    return re.sub(r"\s+", " ", lowered).strip()


def _extract_years(value: str) -> set[str]:
    return set(re.findall(r"\b(?:19|20)\d{2}\b", value))


def _token_coverage(needle: set[str], haystack: set[str]) -> float:
    if not needle:
        return 0.0
    return len(needle & haystack) / len(needle)


def _infer_title_type(site_key: str, canonical_url: str, text: str) -> TitleType:
    lowered = f"{canonical_url} {text}".casefold()
    if site_key == "rottentomatoes":
        if "/tv/" in canonical_url:
            return "tv"
        if "/m/" in canonical_url:
            return "movie"
    if site_key == "metacritic":
        if "/tv/" in canonical_url:
            return "tv"
        if "/movie/" in canonical_url:
            return "movie"
    tokens = set(_normalize_text(lowered).split())
    if tokens & TV_HINTS:
        return "tv"
    if tokens & MOVIE_HINTS:
        return "movie"
    return "any"
