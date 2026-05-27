from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from .models import ClassifiedComment, CommentInput


SPOTIFY_TERMS = {
    "spotify",
    "playlist",
    "playlists",
    "premium",
    "wrapped",
    "stream",
    "streaming",
    "track",
    "tracks",
    "album",
    "albums",
    "song",
    "songs",
    "artist",
    "artists",
    "podcast",
    "podcasts",
    "shuffle",
    "lyrics",
    "listen",
    "listening",
    "music",
}

NEWS_TERMS = {
    "news",
    "breaking",
    "headline",
    "headlines",
    "election",
    "elections",
    "vote",
    "voting",
    "government",
    "minister",
    "president",
    "prime",
    "parliament",
    "policy",
    "budget",
    "economy",
    "inflation",
    "market",
    "markets",
    "stocks",
    "war",
    "ceasefire",
    "attack",
    "protest",
    "strike",
    "earthquake",
    "flood",
    "cyclone",
    "storm",
    "wildfire",
    "crash",
    "outbreak",
    "court",
    "verdict",
    "arrest",
    "scandal",
    "world",
    "global",
    "local",
    "city",
    "state",
    "country",
    "visa",
    "border",
    "conflict",
    "summit",
    "tax",
    "rupee",
    "dollar",
    "petrol",
    "diesel",
    "price",
    "prices",
}

QUESTION_LED_NEWS_PATTERNS = (
    "what happened in",
    "any update on",
    "is it true that",
    "did you see the news",
    "why is everyone talking about",
)

TOKEN_RE = re.compile(r"[a-z0-9']+")


@dataclass(slots=True)
class ScoreBreakdown:
    spotify_terms: list[str]
    news_terms: list[str]
    local_terms: list[str]
    spotify_score: float
    news_score: float
    local_score: float


def classify_comments(
    comments: Iterable[CommentInput],
    *,
    locale_hint: str | None = None,
    local_terms: list[str] | None = None,
    candidates_only: bool = False,
) -> list[ClassifiedComment]:
    results = [
        classify_comment(comment, locale_hint=locale_hint, local_terms=local_terms or [])
        for comment in comments
    ]
    if candidates_only:
        return [item for item in results if item.is_candidate]
    return results


def classify_comment(
    comment: CommentInput,
    *,
    locale_hint: str | None = None,
    local_terms: list[str] | None = None,
) -> ClassifiedComment:
    breakdown = score_comment(comment.text, locale_hint=locale_hint, local_terms=local_terms or [])
    category = "other_offtopic"
    reason = "No strong Spotify or news indicators were detected."
    is_candidate = False

    if breakdown.spotify_score >= 2 and breakdown.spotify_score >= breakdown.news_score:
        category = "spotify_related"
        reason = "Matched Spotify or music-platform discussion terms."
    elif breakdown.news_score >= 2:
        is_candidate = True
        if breakdown.local_score >= 1:
            category = "local_news"
            reason = "Matched news terms plus locale-specific hints."
        else:
            category = "world_news"
            reason = "Matched news terms without a strong local anchor."
    elif breakdown.spotify_score > 0:
        category = "spotify_related"
        reason = "Weak Spotify relevance was detected, but not enough news context."

    confidence = _calculate_confidence(breakdown, category)
    return ClassifiedComment(
        comment_id=comment.comment_id,
        text=comment.text,
        username=comment.username,
        timestamp=comment.timestamp,
        category=category,
        is_candidate=is_candidate,
        confidence=confidence,
        reason=reason,
        matched_spotify_terms=breakdown.spotify_terms,
        matched_news_terms=breakdown.news_terms,
        matched_local_terms=breakdown.local_terms,
        metadata=dict(comment.metadata),
    )


def score_comment(text: str, *, locale_hint: str | None, local_terms: list[str]) -> ScoreBreakdown:
    normalized = text.casefold()
    tokens = TOKEN_RE.findall(normalized)

    spotify_terms = _matched_terms(tokens, SPOTIFY_TERMS)
    news_terms = _matched_terms(tokens, NEWS_TERMS)

    extra_local_terms = []
    if locale_hint:
        extra_local_terms.extend(TOKEN_RE.findall(locale_hint.casefold()))
    for term in local_terms:
        extra_local_terms.extend(TOKEN_RE.findall(term.casefold()))

    local_terms_found = _matched_terms(tokens, set(extra_local_terms))

    spotify_score = float(len(spotify_terms))
    news_score = float(len(news_terms))
    local_score = float(len(local_terms_found))

    if "spotify" in spotify_terms:
        spotify_score += 2.0
    if any(phrase in normalized for phrase in QUESTION_LED_NEWS_PATTERNS):
        news_score += 1.5
    if locale_hint and locale_hint.casefold() in normalized:
        local_score += 1.5
    if any(term in {"election", "war", "earthquake", "flood", "budget", "protest"} for term in news_terms):
        news_score += 1.0

    return ScoreBreakdown(
        spotify_terms=spotify_terms,
        news_terms=news_terms,
        local_terms=local_terms_found,
        spotify_score=spotify_score,
        news_score=news_score,
        local_score=local_score,
    )


def _matched_terms(tokens: list[str], terms: set[str]) -> list[str]:
    matched = sorted({token for token in tokens if token in terms})
    return matched


def _calculate_confidence(breakdown: ScoreBreakdown, category: str) -> float:
    if category == "spotify_related":
        raw = 0.45 + min(breakdown.spotify_score * 0.12, 0.45)
    elif category in {"local_news", "world_news"}:
        raw = 0.5 + min(breakdown.news_score * 0.1, 0.35) + min(breakdown.local_score * 0.08, 0.12)
    else:
        raw = 0.4
    return round(min(raw, 0.98), 2)

