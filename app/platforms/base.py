from __future__ import annotations

from abc import ABC, abstractmethod
from urllib.parse import urlparse

from app.models import EntityCandidate, EntityQuery, SearchResult


NEGATIVE_HINTS = {
    "fan",
    "unofficial",
    "backup",
    "archive",
    "parody",
    "news",
    "updates",
}

POSITIVE_HINTS = {
    "official": "official",
    "verified": "verified",
    "business": "business",
    "creator": "creator",
    "brand channel": "brand channel",
    "official page": "official page",
}


def canonicalize_url(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    elif host.startswith("m."):
        host = host[2:]
    path = parsed.path.rstrip("/")
    return f"{parsed.scheme}://{host}{path}" if path else f"{parsed.scheme}://{host}"


def normalize_tokens(value: str) -> set[str]:
    cleaned = "".join(ch.lower() if ch.isalnum() else " " for ch in value)
    return {token for token in cleaned.split() if token}


class BasePlatformAdapter(ABC):
    platform: str
    allowed_domains: tuple[str, ...]

    def build_queries(self, query: EntityQuery, entity: EntityCandidate) -> list[str]:
        search_name = query.name if len(query.name) >= len(entity.canonical_name) else entity.canonical_name
        qualifiers = []
        if query.entity_type:
            qualifiers.append(query.entity_type.replace("_", " "))
        if query.country:
            qualifiers.append(query.country)
        qualifier_suffix = f" {' '.join(qualifiers)}" if qualifiers else ""
        return [f'"{search_name}" site:{self.allowed_domains[0]}{qualifier_suffix}']

    def extract_candidates(self, results: list[SearchResult]) -> list[dict]:
        candidates: list[dict] = []
        seen_keys: set[str] = set()
        for result in results:
            parsed = urlparse(result.url)
            if not any(parsed.netloc.endswith(domain) for domain in self.allowed_domains):
                continue
            if not self.is_valid_profile_url(result.url):
                continue

            canonical_url = canonicalize_url(result.url)
            dedupe_key = self.candidate_key(canonical_url, result.title)
            if dedupe_key in seen_keys:
                continue
            seen_keys.add(dedupe_key)

            title_blob = f"{result.title} {result.snippet}".lower()
            account_labels = [label for hint, label in POSITIVE_HINTS.items() if hint in title_blob]
            negative_hints = [hint for hint in NEGATIVE_HINTS if hint in title_blob]

            candidates.append(
                {
                    "platform": self.platform,
                    "url": canonical_url,
                    "handle": self.extract_handle(result.url),
                    "display_name": self.extract_display_name(result.title),
                    "title": result.title,
                    "snippet": result.snippet,
                    "source_domain": result.source_domain,
                    "account_labels": account_labels,
                    "negative_hints": negative_hints,
                }
            )
        return candidates

    def candidate_key(self, canonical_url: str, title: str) -> str:
        handle = self.extract_handle(canonical_url)
        if handle:
            return handle.lower()
        return canonical_url.lower()

    def extract_display_name(self, title: str) -> str:
        for separator in [" | ", " - "]:
            if separator in title:
                first = title.split(separator, 1)[0].strip()
                if first:
                    return first
        return title.strip()

    @abstractmethod
    def extract_handle(self, url: str) -> str | None:
        raise NotImplementedError

    @abstractmethod
    def is_valid_profile_url(self, url: str) -> bool:
        raise NotImplementedError
