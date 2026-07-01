from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SearchResult(BaseModel):
    title: str
    url: str
    snippet: str = ""
    source_domain: str = ""
    position: int | None = None
    metadata: dict[str, str] = Field(default_factory=dict)


class EntityQuery(BaseModel):
    name: str = Field(min_length=1)
    entity_type: str | None = None
    country: str | None = None
    profession: str | None = None
    date_of_birth: str | None = None

    def search_terms(self) -> list[str]:
        parts = [self.name]
        if self.entity_type:
            parts.append(self.entity_type.replace("_", " "))
        if self.profession:
            parts.append(self.profession)
        if self.date_of_birth:
            parts.append(self.date_of_birth)
        if self.country:
            parts.append(self.country)
        return [part.strip() for part in parts if part and part.strip()]


class EvidenceItem(BaseModel):
    summary: str
    weight: float
    kind: Literal["positive", "negative", "neutral"] = "positive"


class EntityCandidate(BaseModel):
    candidate_id: str
    label: str
    canonical_name: str
    description: str
    source_url: str
    source_domain: str
    wikidata_id: str | None = None
    official_website: str | None = None
    entity_type_hint: str | None = None
    country_hint: str | None = None
    source_metadata: dict[str, str] = Field(default_factory=dict)
    score: float = 0.0
    evidence: list[EvidenceItem] = Field(default_factory=list)


class ProfileCandidate(BaseModel):
    platform: str
    url: str
    handle: str | None = None
    display_name: str | None = None
    status: Literal["found", "uncertain", "not_found"] = "uncertain"
    confidence_score: float = 0.0
    confidence_label: str = "Low"
    evidence: list[EvidenceItem] = Field(default_factory=list)
    account_labels: list[str] = Field(default_factory=list)
    alternate_urls: list[str] = Field(default_factory=list)


class PlatformResult(BaseModel):
    platform: str
    primary: ProfileCandidate | None = None
    alternates: list[ProfileCandidate] = Field(default_factory=list)
    status: Literal["found", "uncertain", "not_found"] = "not_found"


class SearchSession(BaseModel):
    session_id: str
    query: EntityQuery
    candidates: list[EntityCandidate]


class SearchResponse(BaseModel):
    query: EntityQuery
    selected_entity: EntityCandidate | None = None
    session_id: str | None = None
    export_id: str | None = None
    disambiguation_required: bool = False
    entity_candidates: list[EntityCandidate] = Field(default_factory=list)
    platform_results: list[PlatformResult] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class BulkLookupResult(BaseModel):
    query: EntityQuery
    selected_entity: EntityCandidate | None = None
    resolution_status: Literal["resolved", "ambiguous", "not_found"] = "resolved"
    platform_results: list[PlatformResult] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class BulkSearchResponse(BaseModel):
    export_id: str | None = None
    results: list[BulkLookupResult] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class ExportRow(BaseModel):
    entity_query: str
    matched_entity: str = ""
    entity_type: str = ""
    country: str = ""
    metadata_source: str = ""
    official_website: str = ""
    release_type: str = ""
    studio_type: str = ""
    genre: str = ""
    release_date: str = ""
    network: str = ""
    platform: str = ""
    status: str = ""
    display_name: str = ""
    handle: str = ""
    url: str = ""
    confidence_score: float | None = None
    confidence_label: str = ""
    account_labels: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    alternates: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class ExportPayload(BaseModel):
    export_id: str
    title: str
    rows: list[ExportRow] = Field(default_factory=list)
    summary: list[str] = Field(default_factory=list)


class ValidationRule(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    sheet: str = "*"
    column: str = Field(min_length=1)
    check: Literal[
        "required",
        "not_blank_and_not_in",
        "equals",
        "not_equals",
        "in",
        "regex",
        "min",
        "max",
        "between",
        "unique",
        "date_not_past",
        "date_not_future",
        "contains",
        "contains_any",
        "url_not_contains_if_present",
        "talent_subcategory_format",
        "rottentomatoes_url_match",
        "movie_us_release_date_match",
        "movie_release_type_match",
        "movie_genre_match",
        "reference_lookup_match",
        "social_reference_format",
        "social_reference_reachable",
        "genre_taxonomy_audit",
        "date_cross_check",
        "network_platform_audit",
        "wikipedia_url_audit",
        "imdb_url_audit",
    ]
    platform: Literal["facebook", "twitter", "instagram", "youtube", "tiktok", "wikipedia", "wikidata", "imdb"] | None = None
    value: Any = None
    values: list[Any] = Field(default_factory=list)
    tokens: list[str] = Field(default_factory=list)
    pattern: str | None = None
    min_value: float | None = Field(default=None, alias="min")
    max_value: float | None = Field(default=None, alias="max")
    header_row: int = 1
    ignore_case: bool = True
    when: list["ValidationCondition"] = Field(default_factory=list)
    message: str | None = None

    @model_validator(mode="after")
    def validate_rule_payload(self) -> "ValidationRule":
        if self.check in {"equals", "not_equals", "min", "max", "contains"} and self.value is None:
            raise ValueError(f"Rule '{self.check}' requires a 'value'.")
        if self.check in {"in", "contains_any"} and not self.values:
            raise ValueError(f"Rule '{self.check}' requires a non-empty 'values' list.")
        if self.check == "regex" and not self.pattern:
            raise ValueError("Rule 'regex' requires a 'pattern'.")
        if self.check == "between" and (self.min_value is None or self.max_value is None):
            raise ValueError("Rule 'between' requires both 'min' and 'max'.")
        if self.check in {"not_blank_and_not_in", "url_not_contains_if_present", "talent_subcategory_format"} and not self.tokens:
            raise ValueError(f"Rule '{self.check}' requires a non-empty 'tokens' list.")
        if self.check in {"social_reference_format", "social_reference_reachable", "reference_lookup_match"} and self.platform is None:
            raise ValueError(f"Rule '{self.check}' requires a 'platform'.")
        if self.header_row < 1:
            raise ValueError("'header_row' must be 1 or greater.")
        return self


class ValidationRuleSet(BaseModel):
    rules: list[ValidationRule] = Field(default_factory=list)


class ValidationCondition(BaseModel):
    column: str = Field(min_length=1)
    operator: Literal[
        "equals",
        "not_equals",
        "in",
        "not_in",
        "endswith",
        "not_endswith",
        "contains",
        "not_blank",
        "blank",
    ]
    value: Any = None
    values: list[Any] = Field(default_factory=list)
    ignore_case: bool = True

    @model_validator(mode="after")
    def validate_condition_payload(self) -> "ValidationCondition":
        if self.operator in {"equals", "not_equals", "endswith", "not_endswith", "contains"} and self.value is None:
            raise ValueError(f"Condition '{self.operator}' requires a 'value'.")
        if self.operator in {"in", "not_in"} and not self.values:
            raise ValueError(f"Condition '{self.operator}' requires a non-empty 'values' list.")
        return self


ValidationRule.model_rebuild()


class WorkbookValidationIssue(BaseModel):
    sheet: str
    row: int
    column: str
    cell: str
    rule: str
    message: str
    value: str = ""
    finding_category: str = "Needs Manual Review"
    confidence: str = "High"
    confidence_reason: str = ""


class WorkbookValidationArtifact(BaseModel):
    validation_id: str
    filename: str
    file_bytes: bytes
    issues: list[WorkbookValidationIssue] = Field(default_factory=list)

    @property
    def issue_count(self) -> int:
        return len(self.issues)


class ValidationHistoryEntry(BaseModel):
    validation_id: str
    created_at: datetime
    original_filename: str
    validated_filename: str
    saved_path: str
    saved_dir: str
    issue_count: int = 0
    run_by: str = ""
    client_ip: str = ""

    @property
    def runner_label(self) -> str:
        if self.run_by.strip():
            return self.run_by.strip()
        if self.client_ip.strip():
            return self.client_ip.strip()
        return "Unknown"

    @property
    def created_at_display(self) -> str:
        return self.created_at.astimezone().strftime("%d %b %Y, %I:%M %p %Z")

    @property
    def download_path(self) -> str:
        return f"/validate-excel/download/{self.validation_id}"

# Conveniency imports for consolidated schemas
from app.services.imdb_enricher import IMDbMatch, IMDbMetadata, TitleQuery, EnrichmentResult, MetadataDiscrepancy, PersonMatch, EpisodeData
from app.services.duplicate_detector import DuplicateRow, DuplicateGroup, DuplicateReport
from app.services.excel_comparator import CellDiff, RowDiff, ComparisonReport
from app.services.health_scorer import RowHealthScore, WorkbookHealthReport
from app.services.anomaly_detector import Anomaly, ColumnHealth, AnomalyReport
from app.engine.state import StepResult, PipelineState

