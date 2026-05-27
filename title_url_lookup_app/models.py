from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


TitleType = Literal["any", "movie", "tv"]
LookupStatus = Literal["found", "uncertain", "not_found"]


class TitleLookupInput(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    year: str = ""
    title_type: TitleType = "any"

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        return " ".join(value.split())

    @field_validator("year")
    @classmethod
    def normalize_year(cls, value: str) -> str:
        cleaned = value.strip()
        if cleaned and not cleaned.isdigit():
            raise ValueError("Year must contain digits only.")
        if len(cleaned) not in {0, 4}:
            raise ValueError("Year must be empty or four digits.")
        return cleaned


class TitleLookupQuery(TitleLookupInput):
    pass


class TitleUrlCandidate(BaseModel):
    url: str
    canonical_url: str
    result_title: str = ""
    snippet: str = ""
    score: float = 0.0
    matched_on: list[str] = Field(default_factory=list)


class SiteLookupResult(BaseModel):
    site_key: str
    site_label: str
    status: LookupStatus = "not_found"
    primary: TitleUrlCandidate | None = None
    alternates: list[TitleUrlCandidate] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class TitleLookupResponse(BaseModel):
    query: TitleLookupQuery
    results: list[SiteLookupResult] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class BulkTitleLookupRequest(BaseModel):
    entries: list[TitleLookupQuery] = Field(default_factory=list)

    @field_validator("entries")
    @classmethod
    def validate_entries(cls, value: list[TitleLookupQuery]) -> list[TitleLookupQuery]:
        if not value:
            raise ValueError("At least one title entry is required.")
        if len(value) > 100:
            raise ValueError("Bulk lookup is limited to 100 titles per run.")
        return value


class BulkTitleLookupResponse(BaseModel):
    entries: list[TitleLookupResponse] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    export_id: str | None = None


class TitleUrlExportRow(BaseModel):
    input_title: str
    input_year: str = ""
    input_type: str = ""
    site: str
    status: str
    url: str = ""
    matched_title: str = ""
    score: float | None = None
    alternates: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class DownloadArtifact(BaseModel):
    export_id: str
    filename_base: str
    csv_bytes: bytes
    xlsx_bytes: bytes
    rows: list[TitleUrlExportRow] = Field(default_factory=list)
    summary: list[str] = Field(default_factory=list)
