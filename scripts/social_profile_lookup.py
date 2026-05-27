from __future__ import annotations

import csv
import json
import os
import re
import time
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlparse

import httpx


ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"
TITLE_PATH = ROOT / "data" / "social_lookup_titles_2026_04_30.txt"
OUT_CSV = ROOT / "data" / "social_profile_lookup_2026_04_30.csv"
OUT_JSON = ROOT / "data" / "social_profile_lookup_2026_04_30.json"

PLATFORMS = ("Facebook", "Instagram", "X/Twitter", "TikTok")
PLATFORM_DOMAINS = {
    "Facebook": ("facebook.com", "www.facebook.com", "m.facebook.com"),
    "Instagram": ("instagram.com", "www.instagram.com"),
    "X/Twitter": ("twitter.com", "www.twitter.com", "x.com", "www.x.com"),
    "TikTok": ("tiktok.com", "www.tiktok.com"),
}
EXTERNAL_ID_FIELDS = {
    "Facebook": "facebook_id",
    "Instagram": "instagram_id",
    "X/Twitter": "twitter_id",
}
MANUAL_QUERY_OVERRIDES = {
    "Avatar S2": ("Avatar: The Last Airbender", "tv"),
    "Beef S2": ("BEEF", "tv"),
    "Criminal Minds S19": ("Criminal Minds", "tv"),
    "Daredevil S2": ("Daredevil: Born Again", "tv"),
    "Devil May Cry S2": ("Devil May Cry", "tv"),
    "Euphoria S3": ("Euphoria", "tv"),
    "Industry S4": ("Industry", "tv"),
    "Mayor of Kingstown S4": ("Mayor of Kingstown", "tv"),
    "Only Murders in the Building": ("Only Murders in the Building", "tv"),
    "Queer Eye": ("Queer Eye", "tv"),
    "Rivals S2": ("Rivals", "tv"),
    "School Spirits S3": ("School Spirits", "tv"),
    "Secret Lives of Mormon Wives S4": ("The Secret Lives of Mormon Wives", "tv"),
    "South Park": ("South Park", "tv"),
    "Strange New Worlds S4": ("Star Trek: Strange New Worlds", "tv"),
    "Survivor 50": ("Survivor", "tv"),
    "The Bear": ("The Bear", "tv"),
    "The Comeback S3": ("The Comeback", "tv"),
    "The Four Seasons S2": ("The Four Seasons", "tv"),
    "The Gentlemen": ("The Gentlemen", "tv"),
    "The Gilded Age S4": ("The Gilded Age", "tv"),
    "Welcome to Wrexham": ("Welcome to Wrexham", "tv"),
    "John Wick: Ballerina": ("Ballerina", "movie"),
    "Spongebob Movie: Search for Squarepants": ("The SpongeBob Movie: Search for SquarePants", "movie"),
    "Star Wars: Maul Shadow Lord": ("Star Wars: Maul - Shadow Lord", "tv"),
}
TV_HINTS = {
    "A Knight of the Seven Kingdoms",
    "CIA",
    "Coldwater",
    "Dexter Resurrection",
    "DTF St Louis",
    "Half Man",
    "His & Hers",
    "Lanterns",
    "Lioness",
    "Lupin",
    "Market Fish",
    "Marshals",
    "Mobland",
    "Monster: Lizzie Borden",
    "Paradise",
    "Scrubs",
    "Starfleet Academy",
    "Tell Me Lies",
    "The Hunting Wives",
    "The Madison",
    "The Manipulated",
    "The Pitt",
    "The Testaments",
    "Vision Quest",
    "Wonder Man",
    "Your Friendly Neighborhood Spider-Man",
}
MOVIE_HINTS = {
    "Avengers: Doomsday",
    "Bolero",
    "Enola Holmes 3",
    "Fukushima: A Nuclear Nightmare",
    "Girl Taken",
    "Hoppers",
    "Mel Brooks The 99 Year Old Man!",
    "Mike & Nick & Nick & Alice",
    "Narnia: The Magician's Nephew",
    "Office Romance",
    "Remarkably Bright Creatures",
    "Rooster",
    "Scream 7",
    "Song of the Samurai",
    "Stuart Fails to Save the Universe",
    "The Pink Pill",
    "The Rip",
    "The Running Man",
    "The Smashing Machine",
    "Tron: Ares",
    "Vladimir",
    "War",
    "Zootopia 2",
}


@dataclass
class SocialHit:
    url: str = ""
    handle: str = ""
    confidence: str = ""
    source: str = ""
    evidence: str = ""


@dataclass
class LookupRow:
    original_title: str
    search_title: str
    media_type: str
    tmdb_match: str = ""
    tmdb_year: str = ""
    tmdb_url: str = ""
    official_website: str = ""
    socials: dict[str, SocialHit] = field(default_factory=lambda: {platform: SocialHit() for platform in PLATFORMS})
    notes: list[str] = field(default_factory=list)


def parse_env() -> dict[str, str]:
    values: dict[str, str] = {}
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def clean_title(title: str) -> tuple[str, str]:
    if title in MANUAL_QUERY_OVERRIDES:
        return MANUAL_QUERY_OVERRIDES[title]
    media_type = "tv" if re.search(r"\bS(?:eason)?\s*\d+\b", title, re.I) or title in TV_HINTS else "movie"
    if title in MOVIE_HINTS:
        media_type = "movie"
    cleaned = re.sub(r"\bSeason\s+\d+\b", "", title, flags=re.I)
    cleaned = re.sub(r"\bS\d+\b", "", cleaned, flags=re.I)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -:")
    return cleaned or title, media_type


def normalized(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.lower()))


def title_score(query: str, candidate: str) -> float:
    q = normalized(query)
    c = normalized(candidate)
    if not q or not c:
        return 0.0
    ratio = SequenceMatcher(None, q, c).ratio()
    q_tokens = set(q.split())
    c_tokens = set(c.split())
    overlap = len(q_tokens & c_tokens) / max(len(q_tokens), 1)
    if q == c:
        return 1.2
    if q in c or c in q:
        return max(ratio, 0.9)
    return ratio * 0.7 + overlap * 0.3


def tmdb_headers(env: dict[str, str]) -> dict[str, str]:
    token = env.get("TMDB_READ_ACCESS_TOKEN", "")
    if token:
        return {"Authorization": f"Bearer {token}"}
    return {}


def tmdb_get(client: httpx.Client, env: dict[str, str], path: str, params: dict[str, str] | None = None) -> dict[str, Any]:
    params = dict(params or {})
    if not env.get("TMDB_READ_ACCESS_TOKEN") and env.get("TMDB_API_KEY"):
        params["api_key"] = env["TMDB_API_KEY"]
    response = client.get(
        f"https://api.themoviedb.org/3{path}",
        params=params,
        headers=tmdb_headers(env),
        timeout=20,
    )
    response.raise_for_status()
    return response.json()


def best_tmdb_candidate(client: httpx.Client, env: dict[str, str], query: str, preferred_type: str) -> tuple[str, dict[str, Any]] | tuple[str, None]:
    candidates: list[tuple[float, str, dict[str, Any]]] = []
    search_types = [preferred_type, "tv" if preferred_type == "movie" else "movie"]
    for media_type in search_types:
        payload = tmdb_get(client, env, f"/search/{media_type}", {"query": query, "include_adult": "false"})
        for item in payload.get("results", [])[:8]:
            title = item.get("name") or item.get("title") or item.get("original_name") or item.get("original_title") or ""
            score = title_score(query, title)
            if media_type == preferred_type:
                score += 0.08
            popularity = float(item.get("popularity") or 0.0)
            score += min(popularity / 1000, 0.03)
            candidates.append((score, media_type, item))
    if not candidates:
        return "", None
    candidates.sort(key=lambda item: item[0], reverse=True)
    score, media_type, item = candidates[0]
    if score < 0.54:
        return "", None
    return media_type, item


def tmdb_social_url(platform: str, value: str) -> str:
    cleaned = value.strip().strip("/")
    if not cleaned:
        return ""
    if platform == "Facebook":
        return f"https://www.facebook.com/{cleaned}"
    if platform == "Instagram":
        return f"https://www.instagram.com/{cleaned}"
    if platform == "X/Twitter":
        return f"https://x.com/{cleaned}"
    return ""


def handle_from_url(platform: str, url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path.strip("/")
    if not path:
        return ""
    first = path.split("/")[0]
    if platform == "TikTok" and first.startswith("@"):
        return first
    if platform in {"Instagram", "X/Twitter"}:
        return f"@{first.lstrip('@')}"
    return first


def unwrap_google_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.netloc.endswith("google.com") and parsed.path == "/url":
        target = parse_qs(parsed.query).get("q", [""])[0]
        if target:
            return target
    return url


def canonical_social_url(platform: str, raw_url: str) -> str:
    raw_url = unwrap_google_url(raw_url)
    parsed = urlparse(raw_url)
    host = parsed.netloc.lower().removeprefix("m.")
    path = unquote(parsed.path).strip("/")
    if not any(host == domain or host.endswith(f".{domain}") for domain in PLATFORM_DOMAINS[platform]):
        return ""
    if platform == "TikTok":
        match = re.search(r"@[^/?#]+", path)
        if not match:
            return ""
        return f"https://www.tiktok.com/{match.group(0)}"
    if platform == "Instagram":
        first = path.split("/")[0] if path else ""
        if first.lower() in {"p", "reel", "reels", "explore", "stories", "tags", "accounts"} or not first:
            return ""
        return f"https://www.instagram.com/{first}"
    if platform == "X/Twitter":
        first = path.split("/")[0] if path else ""
        if first.lower() in {"i", "intent", "share", "search", "hashtag", "home", "status"} or not first:
            return ""
        return f"https://x.com/{first}"
    if platform == "Facebook":
        parts = path.split("/") if path else []
        if not parts:
            return ""
        if parts[0].lower() in {"share", "sharer", "groups", "events", "watch", "hashtag", "photo", "permalink.php"}:
            return ""
        if parts[0].lower() == "pages" and len(parts) >= 2:
            return f"https://www.facebook.com/pages/{parts[1]}"
        return f"https://www.facebook.com/{parts[0]}"
    return raw_url


def serpapi_search(client: httpx.Client, env: dict[str, str], query: str, num: int = 10) -> dict[str, Any]:
    api_key = env.get("SERPAPI_API_KEY", "")
    if not api_key:
        return {}
    response = client.get(
        "https://serpapi.com/search.json",
        params={
            "engine": env.get("SERPAPI_ENGINE", "google"),
            "q": query,
            "api_key": api_key,
            "num": str(num),
            "hl": "en",
            "gl": "us",
        },
        timeout=14,
    )
    response.raise_for_status()
    return response.json()


def iter_serp_candidates(payload: dict[str, Any]) -> list[dict[str, str]]:
    candidates: list[dict[str, str]] = []
    knowledge_graph = payload.get("knowledge_graph") or {}
    for key in ("profiles", "social_profiles"):
        for item in knowledge_graph.get(key) or []:
            candidates.append(
                {
                    "title": str(item.get("name") or item.get("title") or ""),
                    "link": str(item.get("link") or ""),
                    "snippet": "Google knowledge graph social profile",
                    "source": "Google knowledge graph",
                }
            )
    for result in payload.get("organic_results") or []:
        candidates.append(
            {
                "title": str(result.get("title") or ""),
                "link": str(result.get("link") or ""),
                "snippet": str(result.get("snippet") or ""),
                "source": "Google organic result",
            }
        )
        for sitelink in (result.get("sitelinks") or {}).get("inline") or []:
            candidates.append(
                {
                    "title": str(sitelink.get("title") or result.get("title") or ""),
                    "link": str(sitelink.get("link") or ""),
                    "snippet": str(result.get("snippet") or ""),
                    "source": "Google sitelink",
                }
            )
    return candidates


NEGATIVE_TERMS = (
    "fan",
    "fans",
    "parody",
    "trailer",
    "wiki",
    "wikipedia",
    "fandom",
    "news",
    "cast",
    "review",
    "reddit",
    "podcast",
)


def candidate_score(platform: str, query_title: str, candidate: dict[str, str]) -> float:
    url = canonical_social_url(platform, candidate["link"])
    if not url:
        return 0.0
    haystack = normalized(" ".join([candidate.get("title", ""), candidate.get("snippet", ""), url]))
    q_tokens = set(normalized(query_title).split())
    if not q_tokens:
        return 0.0
    score = 0.25
    overlap = len(q_tokens & set(haystack.split())) / len(q_tokens)
    score += overlap * 0.35
    if "official" in haystack or "verified" in haystack:
        score += 0.25
    if "movie" in haystack or "series" in haystack or "show" in haystack or "tv" in haystack:
        score += 0.05
    if candidate.get("source") == "Google knowledge graph":
        score += 0.35
    if any(term in haystack for term in NEGATIVE_TERMS):
        score -= 0.4
    handle = handle_from_url(platform, url).lstrip("@")
    if handle and any(token in normalized(handle).split() or token in normalized(handle) for token in q_tokens):
        score += 0.15
    return score


def maybe_set_search_hit(row: LookupRow, platform: str, query_title: str, candidate: dict[str, str]) -> None:
    url = canonical_social_url(platform, candidate["link"])
    if not url:
        return
    score = candidate_score(platform, query_title, candidate)
    existing = row.socials[platform]
    existing_weight = {"High": 1.0, "Medium": 0.72, "Low": 0.45, "": 0.0}.get(existing.confidence, 0.0)
    if score <= existing_weight:
        return
    if score >= 0.82:
        confidence = "High"
    elif score >= 0.58:
        confidence = "Medium"
    elif score >= 0.44:
        confidence = "Low"
    else:
        return
    row.socials[platform] = SocialHit(
        url=url,
        handle=handle_from_url(platform, url),
        confidence=confidence,
        source=candidate.get("source", "Search"),
        evidence=(candidate.get("title", "") + " - " + candidate.get("snippet", "")).strip(" -")[:240],
    )


def apply_serp_payload(row: LookupRow, payload: dict[str, Any], query_title: str) -> None:
    for candidate in iter_serp_candidates(payload):
        for platform in PLATFORMS:
            maybe_set_search_hit(row, platform, query_title, candidate)


def lookup_one(client: httpx.Client, env: dict[str, str], original_title: str) -> LookupRow:
    search_title, preferred_type = clean_title(original_title)
    row = LookupRow(original_title=original_title, search_title=search_title, media_type=preferred_type)

    try:
        media_type, candidate = best_tmdb_candidate(client, env, search_title, preferred_type)
    except Exception as exc:
        row.notes.append(f"TMDB lookup failed: {exc.__class__.__name__}")
        media_type, candidate = "", None

    if candidate:
        row.media_type = media_type
        tmdb_id = str(candidate.get("id") or "")
        title = candidate.get("name") or candidate.get("title") or ""
        date_value = candidate.get("first_air_date") if media_type == "tv" else candidate.get("release_date")
        row.tmdb_match = title
        row.tmdb_year = (date_value or "")[:4]
        row.tmdb_url = f"https://www.themoviedb.org/{'tv' if media_type == 'tv' else 'movie'}/{tmdb_id}"
        try:
            details = tmdb_get(client, env, f"/{media_type}/{tmdb_id}")
            row.official_website = details.get("homepage") or ""
        except Exception:
            pass
        try:
            external_ids = tmdb_get(client, env, f"/{media_type}/{tmdb_id}/external_ids")
            for platform, field_name in EXTERNAL_ID_FIELDS.items():
                value = str(external_ids.get(field_name) or "").strip()
                if not value:
                    continue
                url = tmdb_social_url(platform, value)
                row.socials[platform] = SocialHit(
                    url=url,
                    handle=handle_from_url(platform, url),
                    confidence="High",
                    source="TMDB external IDs",
                    evidence=f"{field_name} published on TMDB for {title}",
                )
        except Exception as exc:
            row.notes.append(f"TMDB external IDs failed: {exc.__class__.__name__}")
    else:
        row.notes.append("No confident TMDB match.")

    media_words = "TV series" if row.media_type == "tv" else "movie"
    queries = [
        f'"{search_title}" official {media_words} social media',
        f'"{search_title}" official Instagram Facebook Twitter TikTok',
    ]
    for query in queries:
        try:
            payload = serpapi_search(client, env, query, num=10)
            apply_serp_payload(row, payload, search_title)
            time.sleep(0.15)
        except Exception as exc:
            row.notes.append(f"Search failed: {exc.__class__.__name__}")
            break

    if os.environ.get("DEEP_SOCIAL_LOOKUP") == "1":
        missing = [platform for platform in PLATFORMS if not row.socials[platform].url]
        for platform in missing:
            platform_query = "Twitter OR X" if platform == "X/Twitter" else platform
            try:
                payload = serpapi_search(client, env, f'"{search_title}" official {platform_query}', num=8)
                apply_serp_payload(row, payload, search_title)
                time.sleep(0.15)
            except Exception as exc:
                row.notes.append(f"{platform} search failed: {exc.__class__.__name__}")
                break

    if not any(hit.url for hit in row.socials.values()):
        row.notes.append("No official social pages found in TMDB or search results.")
    return row


def row_to_dict(row: LookupRow) -> dict[str, str]:
    data = {
        "Original Title": row.original_title,
        "Search Title": row.search_title,
        "Media Type": row.media_type,
        "TMDB Match": row.tmdb_match,
        "TMDB Year": row.tmdb_year,
        "TMDB URL": row.tmdb_url,
        "Official Website": row.official_website,
        "Notes": " | ".join(dict.fromkeys(row.notes)),
    }
    for platform in PLATFORMS:
        hit = row.socials[platform]
        data[f"{platform} URL"] = hit.url
        data[f"{platform} Handle"] = hit.handle
        data[f"{platform} Confidence"] = hit.confidence
        data[f"{platform} Source"] = hit.source
        data[f"{platform} Evidence"] = hit.evidence
    return data


def write_outputs(dict_rows: list[dict[str, str]]) -> None:
    OUT_JSON.write_text(json.dumps(dict_rows, indent=2), encoding="utf-8")
    with OUT_CSV.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(dict_rows[0].keys()))
        writer.writeheader()
        writer.writerows(dict_rows)


def main() -> None:
    env = parse_env()
    titles = [line.strip() for line in TITLE_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
    dict_rows: list[dict[str, str]] = []
    completed: set[str] = set()
    if OUT_JSON.exists():
        try:
            dict_rows = json.loads(OUT_JSON.read_text(encoding="utf-8"))
            completed = {row["Original Title"] for row in dict_rows}
        except Exception:
            dict_rows = []
            completed = set()
    with httpx.Client(follow_redirects=True) as client:
        for index, title in enumerate(titles, start=1):
            if title in completed:
                print(f"[{index}/{len(titles)}] {title} (cached)", flush=True)
                continue
            print(f"[{index}/{len(titles)}] {title}", flush=True)
            dict_rows.append(row_to_dict(lookup_one(client, env, title)))
            write_outputs(dict_rows)
    print(f"Wrote {OUT_CSV}")
    print(f"Wrote {OUT_JSON}")


if __name__ == "__main__":
    main()
