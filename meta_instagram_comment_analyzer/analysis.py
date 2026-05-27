from __future__ import annotations

import re

from .models import AnalyzedComment, MediaComment


TOKEN_RE = re.compile(r"[a-z0-9']+")

SPOTIFY_TERMS = {
    "spotify",
    "wrapped",
    "playlist",
    "playlists",
    "premium",
    "ads",
    "shuffle",
    "lyrics",
    "discover",
    "song",
    "songs",
    "music",
    "album",
    "albums",
    "artist",
    "artists",
    "listen",
    "listening",
    "podcast",
    "podcasts",
    "track",
    "tracks",
    "stream",
    "streaming",
    "dj",
}

OFFTOPIC_HINT_TERMS = {
    "election",
    "elections",
    "president",
    "prime",
    "minister",
    "government",
    "parliament",
    "policy",
    "budget",
    "inflation",
    "market",
    "markets",
    "war",
    "ceasefire",
    "attack",
    "earthquake",
    "flood",
    "cyclone",
    "storm",
    "wildfire",
    "crash",
    "strike",
    "protest",
    "court",
    "verdict",
    "local",
    "news",
    "breaking",
    "headline",
    "headlines",
    "city",
    "state",
    "country",
    "visa",
    "border",
    "petrol",
    "diesel",
    "price",
    "prices",
}

POSITIVE_TERMS = {
    "good",
    "great",
    "love",
    "excellent",
    "happy",
    "hope",
    "safe",
    "beautiful",
    "impressive",
    "strong",
    "support",
    "amazing",
    "best",
}

NEGATIVE_TERMS = {
    "bad",
    "awful",
    "terrible",
    "angry",
    "sad",
    "hate",
    "worse",
    "worst",
    "corrupt",
    "disaster",
    "heartbreaking",
    "scared",
    "fear",
    "danger",
    "broken",
    "crisis",
    "horrible",
}


def analyze_comments(
    comments: list[MediaComment],
    *,
    extra_spotify_terms: list[str] | None = None,
    locale_terms: list[str] | None = None,
    only_offtopic: bool = True,
) -> list[AnalyzedComment]:
    results = []
    spotify_terms = SPOTIFY_TERMS | set(_expand_terms(extra_spotify_terms or []))
    topical_terms = OFFTOPIC_HINT_TERMS | set(_expand_terms(locale_terms or []))

    for comment in comments:
        analyzed = analyze_comment(comment, spotify_terms=spotify_terms, offtopic_terms=topical_terms)
        if only_offtopic and analyzed.relevance != "offtopic":
            continue
        results.append(analyzed)
    return results


def analyze_comment(
    comment: MediaComment,
    *,
    spotify_terms: set[str],
    offtopic_terms: set[str],
) -> AnalyzedComment:
    normalized = comment.text.casefold()
    tokens = TOKEN_RE.findall(normalized)

    matched_spotify = sorted({token for token in tokens if token in spotify_terms})
    matched_offtopic = sorted({token for token in tokens if token in offtopic_terms})

    spotify_score = float(len(matched_spotify))
    offtopic_score = float(len(matched_offtopic))
    reasons: list[str] = []

    if "spotify" in matched_spotify:
        spotify_score += 2.0
        reasons.append("Explicit Spotify mention detected.")
    if any(term in matched_offtopic for term in {"election", "war", "earthquake", "flood", "budget", "protest"}):
        offtopic_score += 1.5
        reasons.append("Comment contains strong public-affairs or breaking-news language.")
    if any(phrase in normalized for phrase in ("what happened in", "any update on", "breaking news", "price hike")):
        offtopic_score += 1.0
        reasons.append("Comment phrasing looks like off-topic news discussion.")

    relevance = "spotify_related" if spotify_score >= offtopic_score and spotify_score > 0 else "offtopic"
    if relevance == "offtopic" and offtopic_score == 0 and spotify_score == 0:
        relevance = "unclear"
        reasons.append("No strong Spotify or off-topic indicators were detected.")
    elif relevance == "offtopic":
        reasons.append("Off-topic indicators outweighed Spotify-related language.")
    else:
        reasons.append("Spotify-related indicators outweighed off-topic language.")

    sentiment_score = score_sentiment(tokens)
    sentiment = label_sentiment(sentiment_score)
    confidence = compute_confidence(spotify_score=spotify_score, offtopic_score=offtopic_score, relevance=relevance)

    return AnalyzedComment(
        media_id=comment.media_id,
        media_permalink=comment.media_permalink,
        comment_id=comment.comment_id,
        username=comment.username,
        timestamp=comment.timestamp,
        text=comment.text,
        relevance=relevance,
        sentiment=sentiment,
        sentiment_score=sentiment_score,
        confidence=confidence,
        matched_spotify_terms=matched_spotify,
        matched_offtopic_terms=matched_offtopic,
        reasons=reasons,
    )


def score_sentiment(tokens: list[str]) -> float:
    positive = sum(1 for token in tokens if token in POSITIVE_TERMS)
    negative = sum(1 for token in tokens if token in NEGATIVE_TERMS)
    if positive == 0 and negative == 0:
        return 0.0
    score = (positive - negative) / max(positive + negative, 1)
    return round(score, 2)


def label_sentiment(score: float) -> str:
    if score >= 0.25:
        return "positive"
    if score <= -0.25:
        return "negative"
    return "neutral"


def compute_confidence(*, spotify_score: float, offtopic_score: float, relevance: str) -> float:
    if relevance == "unclear":
        return 0.35
    dominant = max(spotify_score, offtopic_score)
    separation = abs(spotify_score - offtopic_score)
    raw = 0.5 + min(dominant * 0.08, 0.25) + min(separation * 0.07, 0.2)
    return round(min(raw, 0.97), 2)


def _expand_terms(terms: list[str]) -> list[str]:
    expanded: list[str] = []
    for term in terms:
        expanded.extend(TOKEN_RE.findall(term.casefold()))
    return expanded

