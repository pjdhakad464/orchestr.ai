from __future__ import annotations

from pydantic import BaseModel, Field


class SearchResult(BaseModel):
    title: str
    url: str
    snippet: str = ""
    source_domain: str = ""
    position: int | None = None
    metadata: dict[str, str] = Field(default_factory=dict)
