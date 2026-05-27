from __future__ import annotations

import hashlib
import re
from urllib.parse import urljoin, urlparse

import httpx

from app.cache import TTLCache
from app.config import settings
from app.models import EntityCandidate


SOCIAL_DOMAINS = {
    "Facebook": ("facebook.com",),
    "Instagram": ("instagram.com",),
    "YouTube": ("youtube.com", "youtu.be"),
    "X/Twitter": ("x.com", "twitter.com"),
    "TikTok": ("tiktok.com",),
    "Wikipedia": ("wikipedia.org",),
    "IMDb": ("imdb.com",),
}

WIKIDATA_CLAIMS = {
    "P856": "official_website",
    "P2002": "twitter_username",
    "P2003": "instagram_username",
    "P2013": "facebook_username",
    "P2397": "youtube_channel_id",
    "P7085": "tiktok_username",
    "P345": "imdb_id",
}


class OfficialLinkResolver:
    def __init__(self, timeout_seconds: int, cache: TTLCache) -> None:
        self.timeout_seconds = timeout_seconds
        self.cache = cache
        contact = settings.wikimedia_contact or "local-app"
        user_agent = f"OfficialProfileFinder/0.1 ({contact}) httpx"
        self.client = httpx.AsyncClient(
            timeout=self.timeout_seconds,
            follow_redirects=True,
            limits=httpx.Limits(max_keepalive_connections=20, max_connections=40),
            headers={
                "User-Agent": user_agent,
                "Api-User-Agent": user_agent,
            },
        )

    async def discover(self, entity: EntityCandidate) -> dict[str, list[dict]]:
        links = {platform: [] for platform in SOCIAL_DOMAINS}
        if entity.source_domain.endswith("wikipedia.org"):
            links["Wikipedia"].append(
                self._candidate_from_url("Wikipedia", entity.source_url, "Canonical Wikipedia page", entity.canonical_name)
            )

        claims = await self._fetch_wikidata_claims(entity.wikidata_id) if entity.wikidata_id else {}
        official_website = claims.get("official_website")
        if official_website:
            entity.official_website = official_website

        username_mappings = {
            "Facebook": claims.get("facebook_username"),
            "Instagram": claims.get("instagram_username"),
            "X/Twitter": claims.get("twitter_username"),
            "TikTok": claims.get("tiktok_username"),
        }
        for platform, username in username_mappings.items():
            if username:
                links[platform].append(
                    self._candidate_from_url(
                        platform,
                        self._build_profile_url(platform, username),
                        "Username from Wikidata",
                        entity.canonical_name,
                    )
                )

        youtube_channel_id = claims.get("youtube_channel_id")
        if youtube_channel_id:
            links["YouTube"].append(
                self._candidate_from_url(
                    "YouTube",
                    f"https://www.youtube.com/channel/{youtube_channel_id}",
                    "Channel id from Wikidata",
                    entity.canonical_name,
                )
            )

        imdb_id = claims.get("imdb_id")
        if imdb_id:
            links["IMDb"].append(
                self._candidate_from_url("IMDb", _build_imdb_url(imdb_id), "IMDb id from Wikidata", entity.canonical_name)
            )

        if official_website:
            website_links = await self._extract_social_links_from_website(official_website)
            for platform, urls in website_links.items():
                for url in urls:
                    links[platform].append(
                        self._candidate_from_url(
                            platform,
                            url,
                            "Linked from official website",
                            entity.canonical_name,
                            account_labels=["official"],
                        )
                    )

        for platform in links:
            deduped: dict[str, dict] = {}
            for candidate in links[platform]:
                deduped[candidate["url"].lower()] = candidate
            links[platform] = list(deduped.values())
        return links

    async def extract_social_links(self, website_url: str, entity_name: str) -> dict[str, list[dict]]:
        website_links = await self._extract_social_links_from_website(website_url)
        links = {platform: [] for platform in SOCIAL_DOMAINS}
        for platform, urls in website_links.items():
            for url in urls:
                links[platform].append(
                    self._candidate_from_url(
                        platform,
                        url,
                        "Linked from official website",
                        entity_name,
                        account_labels=["official"],
                    )
                )
        return links

    async def _fetch_wikidata_claims(self, wikidata_id: str) -> dict[str, str]:
        cache_key = f"wikidata-claims:{wikidata_id}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached  # type: ignore[return-value]

        params = {
            "action": "wbgetentities",
            "format": "json",
            "ids": wikidata_id,
            "props": "claims",
        }
        try:
            response = await self.client.get("https://www.wikidata.org/w/api.php", params=params)
            response.raise_for_status()
        except httpx.HTTPError:
            return {}
        payload = response.json()
        claims = payload.get("entities", {}).get(wikidata_id, {}).get("claims", {})
        extracted: dict[str, str] = {}
        for property_id, key in WIKIDATA_CLAIMS.items():
            value = _extract_claim_value(claims.get(property_id, []))
            if value:
                extracted[key] = value

        self.cache.set(cache_key, extracted)
        return extracted

    async def _extract_social_links_from_website(self, website_url: str) -> dict[str, list[str]]:
        cache_key = f"site-links:{hashlib.sha1(website_url.encode('utf-8')).hexdigest()}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached  # type: ignore[return-value]

        try:
            response = await self.client.get(website_url)
            response.raise_for_status()
        except httpx.HTTPError:
            return {platform: [] for platform in SOCIAL_DOMAINS}

        hrefs = set(re.findall(r'href=["\\\']([^"\\\']+)["\\\']', response.text, flags=re.IGNORECASE))
        links = {platform: [] for platform in SOCIAL_DOMAINS}
        for href in hrefs:
            absolute_url = urljoin(str(response.url), href)
            host = urlparse(absolute_url).netloc.lower()
            for platform, domains in SOCIAL_DOMAINS.items():
                if any(domain in host for domain in domains):
                    links[platform].append(_normalize_profile_url(absolute_url))
                    break

        self.cache.set(cache_key, links)
        return links

    def _candidate_from_url(
        self,
        platform: str,
        url: str,
        evidence_summary: str,
        entity_name: str,
        account_labels: list[str] | None = None,
    ) -> dict:
        normalized_url = _normalize_profile_url(url)
        handle = _extract_handle_from_url(normalized_url)
        return {
            "platform": platform,
            "url": normalized_url,
            "handle": handle,
            "display_name": entity_name,
            "title": f"{entity_name} {platform}",
            "snippet": evidence_summary,
            "source_domain": urlparse(normalized_url).netloc.lower(),
            "account_labels": account_labels or [],
            "negative_hints": [],
        }

    def _build_profile_url(self, platform: str, username: str) -> str:
        if platform == "Facebook":
            return f"https://www.facebook.com/{username}"
        if platform == "Instagram":
            return f"https://www.instagram.com/{username}"
        if platform == "TikTok":
            return f"https://www.tiktok.com/@{username.lstrip('@')}"
        return f"https://x.com/{username}"


def _extract_claim_value(claims: list[dict]) -> str | None:
    for claim in claims:
        datavalue = claim.get("mainsnak", {}).get("datavalue", {})
        value = datavalue.get("value")
        if isinstance(value, str):
            return value
    return None


def _normalize_profile_url(url: str) -> str:
    parsed = urlparse(url)
    scheme = parsed.scheme or "https"
    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    path = parsed.path.rstrip("/")
    return f"{scheme}://{host}{path}" if path else f"{scheme}://{host}"


def _extract_handle_from_url(url: str) -> str | None:
    segments = [segment for segment in urlparse(url).path.split("/") if segment]
    if not segments:
        return None
    if segments[0] in {"channel", "user", "c", "title", "name", "company"} and len(segments) > 1:
        return segments[1]
    return segments[0]


def _build_imdb_url(imdb_id: str) -> str:
    if imdb_id.startswith("tt"):
        return f"https://www.imdb.com/title/{imdb_id}"
    if imdb_id.startswith("nm"):
        return f"https://www.imdb.com/name/{imdb_id}"
    if imdb_id.startswith("co"):
        return f"https://www.imdb.com/company/{imdb_id}"
    return f"https://www.imdb.com/{imdb_id}"
