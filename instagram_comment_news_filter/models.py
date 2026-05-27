from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class CommentInput(BaseModel):
    comment_id: str | None = None
    text: str = Field(min_length=1)
    username: str | None = None
    timestamp: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ClassificationRequest(BaseModel):
    comments: list[CommentInput]
    locale_hint: str | None = None
    local_terms: list[str] = Field(default_factory=list)
    candidates_only: bool = False


class ClassifiedComment(BaseModel):
    comment_id: str | None = None
    text: str
    username: str | None = None
    timestamp: datetime | None = None
    category: str
    is_candidate: bool
    confidence: float
    reason: str
    matched_spotify_terms: list[str] = Field(default_factory=list)
    matched_news_terms: list[str] = Field(default_factory=list)
    matched_local_terms: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ClassificationResponse(BaseModel):
    total_comments: int
    returned_comments: int
    candidates_found: int
    locale_hint: str | None = None
    comments: list[ClassifiedComment]

