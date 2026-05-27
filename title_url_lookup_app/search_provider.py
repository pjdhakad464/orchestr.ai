from __future__ import annotations

import hashlib
import html
import re
from urllib.parse import parse_qs, quote, unquote, urlparse

import httpx

from title_url_lookup_app.cache import TTLCache
from title_url_lookup_app.config import settings
from title_url_lookup_app.search_models import SearchResult


class SearchProviderUnavailableError(RuntimeError):
    """Raised when the search provider cannot be used."""


class DuckDuckGoSearchProvider:
    def __init__(self, timeout_seconds: int, cache: TTLCache) -> None:
        self.timeout_seconds = timeout_seconds
        self.cache = cache
        contact = settings.wikimedia_contact or "local-app"
        user_agent = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/133.0.0.0 Safari/537.36 "
            f"TitleUrlLookupApp/0.1 ({contact})"
        )
        self.client = httpx.AsyncClient(
            timeout=self.timeout_seconds,
            follow_redirects=True,
            limits=httpx.Limits(max_keepalive_connections=20, max_connections=40),
            headers={
                "User-Agent": user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            },
        )

    async def search(self, query: str, *, limit: int = 10) -> list[SearchResult]:
        cache_key = self._cache_key(query, limit)
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached  # type: ignore[return-value]

        params = {"q": query, "kl": "us-en"}
        try:
            response = await self.client.get("https://html.duckduckgo.com/html/", params=params)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise SearchProviderUnavailableError(
                f"Public web search failed with HTTP {exc.response.status_code}."
            ) from exc
        except httpx.ConnectError as exc:
            raise SearchProviderUnavailableError("Public web search failed: could not connect.") from exc
        except httpx.TimeoutException as exc:
            raise SearchProviderUnavailableError("Public web search timed out.") from exc
        except httpx.HTTPError as exc:
            raise SearchProviderUnavailableError(f"Public web search failed: {exc.__class__.__name__}.") from exc

        results = _parse_duckduckgo_results(response.text, limit=limit)
        self.cache.set(cache_key, results)
        return results

    def _cache_key(self, query: str, limit: int) -> str:
        digest = hashlib.sha1(f"ddg:{query}:{limit}".encode("utf-8")).hexdigest()
        return f"ddg:{digest}"


class WikimediaSearchProvider:
    def __init__(self, timeout_seconds: int, cache: TTLCache) -> None:
        self.timeout_seconds = timeout_seconds
        self.cache = cache
        contact = settings.wikimedia_contact or "local-app"
        user_agent = f"TitleUrlLookupApp/0.1 ({contact})"
        self.client = httpx.AsyncClient(
            timeout=self.timeout_seconds,
            limits=httpx.Limits(max_keepalive_connections=20, max_connections=40),
            headers={
                "User-Agent": user_agent,
                "Api-User-Agent": user_agent,
                "Accept": "application/json",
                "From": contact,
            },
        )

    async def search(self, query: str, *, limit: int = 10) -> list[SearchResult]:
        cache_key = self._cache_key(query, limit)
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached  # type: ignore[return-value]

        normalized_query = _normalize_query(query)
        try:
            results = await self._search_wikidata(normalized_query, limit)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 403:
                results = await self._search_wikipedia_fallback(normalized_query, limit)
            else:
                raise SearchProviderUnavailableError(
                    f"Live search failed: Wikimedia returned HTTP {exc.response.status_code}."
                ) from exc
        except httpx.ConnectError as exc:
            raise SearchProviderUnavailableError(
                "Live search failed: could not connect to Wikimedia. Check your internet connection."
            ) from exc
        except httpx.TimeoutException as exc:
            raise SearchProviderUnavailableError("Live search failed: Wikimedia request timed out. Try again in a moment.") from exc
        except httpx.HTTPError as exc:
            raise SearchProviderUnavailableError(f"Live search failed: {exc.__class__.__name__}.") from exc

        self.cache.set(cache_key, results)
        return results

    async def _search_wikidata(self, normalized_query: str, limit: int) -> list[SearchResult]:
        params = {
            "action": "wbsearchentities",
            "format": "json",
            "language": "en",
            "type": "item",
            "limit": limit,
            "search": normalized_query,
        }
        response = await self.client.get("https://www.wikidata.org/w/api.php", params=params)
        response.raise_for_status()

        payload = response.json()
        search_hits = payload.get("search", [])
        entity_ids = [item.get("id") for item in search_hits if item.get("id")]
        sitelinks = await self._fetch_sitelinks(entity_ids)

        results: list[SearchResult] = []
        for position, item in enumerate(search_hits, start=1):
            entity_id = item.get("id", "")
            label = item.get("label", "")
            description = item.get("description", "")
            enwiki_title = sitelinks.get(entity_id)
            if enwiki_title:
                url = f"https://en.wikipedia.org/wiki/{quote(enwiki_title.replace(' ', '_'))}"
                source_domain = "en.wikipedia.org"
            else:
                url = f"https://www.wikidata.org/wiki/{entity_id}"
                source_domain = "www.wikidata.org"

            results.append(
                SearchResult(
                    title=label,
                    url=url,
                    snippet=description,
                    source_domain=source_domain,
                    position=position,
                    metadata={"wikidata_id": entity_id},
                )
            )
        return results

    async def _search_wikipedia_fallback(self, normalized_query: str, limit: int) -> list[SearchResult]:
        params = {
            "action": "query",
            "format": "json",
            "list": "search",
            "srsearch": normalized_query,
            "srlimit": limit,
            "utf8": 1,
        }
        response = await self.client.get("https://en.wikipedia.org/w/api.php", params=params)
        response.raise_for_status()
        payload = response.json()
        search_hits = payload.get("query", {}).get("search", [])
        results: list[SearchResult] = []
        for position, item in enumerate(search_hits, start=1):
            title = item.get("title", "")
            page_url = f"https://en.wikipedia.org/wiki/{quote(title.replace(' ', '_'))}"
            results.append(
                SearchResult(
                    title=title,
                    url=page_url,
                    snippet=_strip_html(item.get("snippet", "")),
                    source_domain=urlparse(page_url).netloc.lower(),
                    position=position,
                    metadata={},
                )
            )
        return results

    async def _fetch_sitelinks(self, entity_ids: list[str]) -> dict[str, str]:
        if not entity_ids:
            return {}

        cache_key = self._cache_key("sitelinks:" + "|".join(entity_ids), len(entity_ids))
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached  # type: ignore[return-value]

        params = {
            "action": "wbgetentities",
            "format": "json",
            "ids": "|".join(entity_ids),
            "props": "sitelinks",
            "sitefilter": "enwiki",
        }
        try:
            response = await self.client.get("https://www.wikidata.org/w/api.php", params=params)
            response.raise_for_status()
        except httpx.HTTPError:
            return {}
        payload = response.json()
        entities = payload.get("entities", {})
        sitelinks: dict[str, str] = {}
        for entity_id, entity_payload in entities.items():
            enwiki = entity_payload.get("sitelinks", {}).get("enwiki")
            if enwiki and enwiki.get("title"):
                sitelinks[entity_id] = enwiki["title"]

        self.cache.set(cache_key, sitelinks)
        return sitelinks

    def _cache_key(self, query: str, limit: int) -> str:
        digest = hashlib.sha1(f"{query}:{limit}".encode("utf-8")).hexdigest()
        return f"wikimedia:{digest}"


def _normalize_query(query: str) -> str:
    cleaned = query.replace('"', " ")
    tokens = []
    for token in cleaned.split():
        lowered = token.lower()
        if lowered.startswith("site:"):
            continue
        if lowered in {"official", "website", "imdb", "wikipedia", "or"}:
            continue
        if lowered.startswith("(") or lowered.endswith(")"):
            continue
        tokens.append(token)
    return " ".join(tokens).strip() or cleaned.strip()


def _strip_html(value: str) -> str:
    return value.replace("<span class=\"searchmatch\">", "").replace("</span>", "")


def _parse_duckduckgo_results(payload: str, *, limit: int) -> list[SearchResult]:
    matches = list(
        re.finditer(
            r'<a[^>]+class="result__a"[^>]+href="(?P<href>[^"]+)"[^>]*>(?P<title>.*?)</a>',
            payload,
            flags=re.IGNORECASE | re.DOTALL,
        )
    )
    results: list[SearchResult] = []
    for position, match in enumerate(matches[:limit], start=1):
        raw_href = html.unescape(match.group("href"))
        title = _clean_html_text(match.group("title"))
        snippet = _extract_duckduckgo_snippet(payload, match.end())
        resolved_url = _resolve_duckduckgo_url(raw_href)
        if not resolved_url:
            continue
        results.append(
            SearchResult(
                title=title,
                url=resolved_url,
                snippet=snippet,
                source_domain=urlparse(resolved_url).netloc.lower(),
                position=position,
                metadata={},
            )
        )
    return results


def _extract_duckduckgo_snippet(payload: str, start_index: int) -> str:
    snippet_match = re.search(
        r'<a[^>]+class="result__snippet"[^>]*>(?P<snippet>.*?)</a>|'
        r'<div[^>]+class="result__snippet"[^>]*>(?P<div_snippet>.*?)</div>',
        payload[start_index : start_index + 2000],
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not snippet_match:
        return ""
    snippet = snippet_match.group("snippet") or snippet_match.group("div_snippet") or ""
    return _clean_html_text(snippet)


def _resolve_duckduckgo_url(raw_href: str) -> str | None:
    if raw_href.startswith("//"):
        raw_href = f"https:{raw_href}"
    parsed = urlparse(raw_href)
    if "duckduckgo.com" in parsed.netloc:
        uddg = parse_qs(parsed.query).get("uddg", [])
        if uddg:
            return unquote(uddg[0])
    if parsed.scheme in {"http", "https"}:
        return raw_href
    return None


def _clean_html_text(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", value)
    return " ".join(html.unescape(text).split())
