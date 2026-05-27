from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


LookupMode = Literal["auto", "id_to_name", "title_to_id", "person_to_id"]
LookupStatus = Literal["matched", "multiple_matches", "not_found", "invalid"]


class LookupRow(BaseModel):
    input_value: str
    normalized_input: str = ""
    requested_mode: LookupMode = "auto"
    resolved_lookup: str = ""
    status: LookupStatus = "matched"
    match_rank: int = 1
    total_matches: int = 1
    imdb_id: str = ""
    entity_kind: str = ""
    display_name: str = ""
    original_title: str = ""
    title_type: str = ""
    start_year: str = ""
    end_year: str = ""
    birth_year: str = ""
    death_year: str = ""
    primary_profession: str = ""
    known_for_titles: str = ""
    source_url: str = ""
    matched_on: str = ""
    notes: str = ""


class LookupBatchResult(BaseModel):
    rows: list[LookupRow] = Field(default_factory=list)
    summary: list[str] = Field(default_factory=list)
    export_id: str | None = None


class DownloadArtifact(BaseModel):
    export_id: str
    filename_base: str
    csv_bytes: bytes
    xlsx_bytes: bytes
    rows: list[LookupRow] = Field(default_factory=list)
    summary: list[str] = Field(default_factory=list)


class LookupRequest(BaseModel):
    values: list[str] = Field(default_factory=list)
    mode: LookupMode = "auto"
