from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


class MetacriticCalendarItem(BaseModel):
    section: Literal["games", "movies", "tv"]
    section_label: str
    source_title: str
    source_url: str
    group_label: str
    release_date: str = ""
    title: str
    url: str = ""
    provider: str = ""
    availability: str = ""
    details: str = ""
    metascore: int | None = None
    imdb_id: str = ""


class MetacriticCalendarSnapshot(BaseModel):
    calendar_type: str
    generated_at: datetime
    export_id: str | None = None
    items: list[MetacriticCalendarItem] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class MetacriticTvClassificationItem(BaseModel):
    release_date: str = ""
    title: str
    imdb_ttcode: str = ""
    metacritic_url: str = ""
    network: str = ""
    daypart: str = ""
    program_type: str = ""
    language_type: str = ""
    genre_1: str = ""
    genre_2: str = ""
    genre_3: str = ""


class MetacriticTvClassificationSnapshot(BaseModel):
    generated_at: datetime
    source_url: str
    window_start: date | None = None
    window_end: date | None = None
    export_id: str | None = None
    items: list[MetacriticTvClassificationItem] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class BoxOfficeMojoReleaseItem(BaseModel):
    release_date: str
    title: str
    url: str = ""
    release_notes: str = ""
    genres: str = ""
    cast: str = ""
    runtime: str = ""
    distributor: str = ""
    scale: str = ""
    imdb_id: str = ""


class BoxOfficeMojoReleaseWindowSnapshot(BaseModel):
    report_key: str
    report_label: str
    generated_at: datetime
    window_start: date
    window_end: date
    source_url: str
    export_id: str | None = None
    items: list[BoxOfficeMojoReleaseItem] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


ImdbMatchStatus = Literal["found", "uncertain", "not_found", "error"]


class TvImdbEpisodeCountItem(BaseModel):
    release_date: str = ""
    title: str
    metacritic_url: str = ""
    network_distributor: str = ""
    provider: str = ""
    availability: str = ""
    details: str = ""
    imdb_id: str = ""
    imdb_url: str = ""
    imdb_title: str = ""
    imdb_start_year: str = ""
    imdb_title_type: str = ""
    imdb_match_status: ImdbMatchStatus = "not_found"
    imdb_match_score: float | None = None
    season_count: int | None = None
    latest_season_number: int | None = None
    latest_season_episode_count: int | None = None
    latest_season_start_date: str = ""
    latest_season_end_date: str = ""
    latest_season_date_source: str = ""
    episode_count: int | None = None
    notes: list[str] = Field(default_factory=list)


class TvImdbEpisodeCountSnapshot(BaseModel):
    generated_at: datetime
    source_url: str
    date_window_key: str = "year"
    date_window_label: str = "Upcoming Year"
    window_start: date | None = None
    window_end: date | None = None
    export_id: str | None = None
    items: list[TvImdbEpisodeCountItem] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
