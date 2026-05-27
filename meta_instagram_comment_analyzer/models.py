from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class AuthSession:
    session_id: str
    access_token: str
    created_at: datetime
    graph_version: str


@dataclass(slots=True)
class InstagramAccount:
    page_id: str
    page_name: str
    instagram_user_id: str
    instagram_username: str | None = None


@dataclass(slots=True)
class MediaComment:
    media_id: str
    media_caption: str | None
    media_permalink: str | None
    media_timestamp: datetime | None
    comment_id: str
    text: str
    username: str | None
    timestamp: datetime | None
    raw: dict = field(default_factory=dict)


@dataclass(slots=True)
class AnalyzedComment:
    media_id: str
    media_permalink: str | None
    comment_id: str
    username: str | None
    timestamp: datetime | None
    text: str
    relevance: str
    sentiment: str
    sentiment_score: float
    confidence: float
    matched_spotify_terms: list[str]
    matched_offtopic_terms: list[str]
    reasons: list[str]

