from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field

class APIResponse(BaseModel):
    status: Literal["success", "error"]
    message: str
    data: Any = None

class ValidateRequest(BaseModel):
    file_path: str
    rules_file: str | None = None
    run_by: str = "REST API"

class IMDbEnrichRequest(BaseModel):
    title: str
    year: int | None = None
    content_type: str | None = None

class IMDbBulkEnrichRequest(BaseModel):
    queries: list[IMDbEnrichRequest] = Field(default_factory=list)

class SocialDiscoverRequest(BaseModel):
    name: str
    entity_type: str | None = None
    profession: str | None = None
    country: str | None = None

class SocialBulkDiscoverRequest(BaseModel):
    queries: list[SocialDiscoverRequest] = Field(default_factory=list)

class CompareRequest(BaseModel):
    file_a: str
    file_b: str
    key_columns: list[str] | None = None
    output_path: str | None = None

class PipelineRunRequest(BaseModel):
    template_name: str
    inputs: dict[str, Any] = Field(default_factory=dict)
    run_by: str = "REST API"
