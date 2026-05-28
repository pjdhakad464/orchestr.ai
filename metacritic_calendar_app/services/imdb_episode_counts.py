from __future__ import annotations

import csv
import gzip
import html
import io
import re
import shutil
import sqlite3
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from threading import Lock

import httpx

from metacritic_calendar_app.models import (
    TvImdbEpisodeCountItem,
    TvImdbEpisodeCountSnapshot,
)
from metacritic_calendar_app.services.calendar import MetacriticCalendarService
from metacritic_calendar_app.services.text import contains_rent_buy
from title_url_lookup_app.config import BASE_DIR, settings as title_lookup_settings
from title_url_lookup_app.models import TitleLookupQuery
from title_url_lookup_app.services.imdb_dataset import ImdbDatasetLookupError, ImdbDatasetLookupService
from openpyxl import Workbook


IMDB_TITLE_EPISODE_FILENAME = "title.episode.tsv.gz"
IMDB_EPISODE_COUNTS_INDEX_FILENAME = "imdb_episode_counts_v2.sqlite3"
IMDB_EPISODE_COUNTS_LOCK = Lock()
IMDB_BASE_URL = "https://www.imdb.com"
EPISODE_DATE_FIELDS_RE = re.compile(
    r'"(?:datePublished|releaseDate|airDate|airdate)"\s*:\s*"(?P<date>\d{4}-\d{2}-\d{2})"',
    re.IGNORECASE,
)
ISO_DATE_RE = re.compile(r"\b(?P<date>\d{4}-\d{2}-\d{2})\b")
US_DATE_RE = re.compile(
    r"\b(?P<month>Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?"
    r"\s+(?P<day>\d{1,2}),\s+(?P<year>\d{4})\b",
    re.IGNORECASE,
)
INTERNATIONAL_DATE_RE = re.compile(
    r"\b(?P<day>\d{1,2})\s+"
    r"(?P<month>Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?"
    r"\s+(?P<year>\d{4})\b",
    re.IGNORECASE,
)
MONTHS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}


class ImdbEpisodeCountError(RuntimeError):
    pass


@dataclass(frozen=True)
class ImdbEpisodeCountLookup:
    imdb_id: str = ""
    imdb_url: str = ""
    imdb_title: str = ""
    imdb_start_year: str = ""
    imdb_title_type: str = ""
    imdb_match_status: str = "not_found"
    imdb_match_score: float | None = None
    season_count: int | None = None
    latest_season_number: int | None = None
    latest_season_episode_count: int | None = None
    latest_season_start_date: str = ""
    latest_season_end_date: str = ""
    latest_season_date_source: str = ""
    episode_count: int | None = None
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class TvImdbDateWindow:
    key: str
    label: str
    start_offset_days: int
    end_offset_days: int


@dataclass(frozen=True)
class ResolvedTvImdbDateWindow:
    key: str
    label: str
    window_start: date
    window_end: date


TV_IMDB_DATE_WINDOWS = (
    TvImdbDateWindow("daily_segment", "Daily (Today, or Sat-Mon on Monday)", 0, 0),
    TvImdbDateWindow("today", "Today (Present Day)", 0, 0),
    TvImdbDateWindow("last_7_days", "Last 7 Days", -6, 0),
    TvImdbDateWindow("week", "Upcoming Week (7 days)", 0, 7),
    TvImdbDateWindow("month", "Upcoming Month (30 days)", 0, 30),
    TvImdbDateWindow("year", "Upcoming Year (365 days)", 0, 365),
)
TV_IMDB_DATE_WINDOW_MAP = {window.key: window for window in TV_IMDB_DATE_WINDOWS}
TV_IMDB_CUSTOM_DATE_WINDOW_KEY = "custom"
TV_IMDB_CUSTOM_DATE_WINDOW_LABEL = "Custom Date Range"
DEFAULT_TV_IMDB_DATE_WINDOW_KEY = "daily_segment"
TV_IMDB_OUTPUT_COLUMNS = [
    "release_date",
    "title",
    "network_distributor",
    "imdb_id",
    "metacritic_url",
    "latest_season_number",
    "latest_season_episode_count",
    "latest_season_start_date",
    "latest_season_end_date",
]



def format_date_dd_mm_yyyy(date_str: str) -> str:
    if not date_str or date_str == "-":
        return ""
    try:
        # Check if already in DD-MM-YYYY format
        if re.match(r"^\d{2}-\d{2}-\d{4}$", date_str):
            return date_str
        dt = date.fromisoformat(date_str)
        return dt.strftime("%d-%m-%Y")
    except ValueError:
        return date_str


class ImdbEpisodeCountService:
    def __init__(
        self,
        timeout_seconds: int = 12,
        imdb_dataset_lookup: ImdbDatasetLookupService | None = None,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.imdb_dataset_lookup = imdb_dataset_lookup or ImdbDatasetLookupService()
        self._imdb_episode_date_fetch_blocked = False

    def lookup_show(self, title: str) -> ImdbEpisodeCountLookup:
        normalized_title = " ".join(title.split())
        if not normalized_title:
            return ImdbEpisodeCountLookup(notes=("No title was provided.",))

        try:
            matches = self.imdb_dataset_lookup.lookup_title(
                TitleLookupQuery(title=normalized_title, title_type="tv")
            )
        except (ImdbDatasetLookupError, ValueError) as exc:
            return ImdbEpisodeCountLookup(
                imdb_match_status="error",
                notes=(f"IMDb title lookup failed: {exc}",),
            )

        if not matches:
            return ImdbEpisodeCountLookup(notes=("No matching IMDb TV title was found.",))

        top_match = matches[0]
        status = self._match_status(matches)
        if status == "not_found":
            return ImdbEpisodeCountLookup(notes=("No strong IMDb TV title match was found.",))

        notes: list[str] = []
        if status == "uncertain":
            notes.append("Closest IMDb title match was not definitive; review the IMDb URL.")

        try:
            season_count, latest_season_number, latest_season_episode_count, episode_count = self._lookup_counts(
                top_match.imdb_id
            )
        except ImdbEpisodeCountError as exc:
            return ImdbEpisodeCountLookup(
                imdb_id=top_match.imdb_id,
                imdb_url=top_match.url,
                imdb_title=top_match.display_title,
                imdb_start_year=top_match.start_year,
                imdb_title_type=top_match.title_type,
                imdb_match_status="error",
                imdb_match_score=top_match.score,
                notes=(f"IMDb episode count lookup failed: {exc}",),
            )

        if episode_count == 0:
            notes.append("IMDb title matched, but no episode rows were available.")

        latest_season_start_date = ""
        latest_season_end_date = ""
        latest_season_date_source = ""
        if latest_season_number is not None and latest_season_episode_count:
            try:
                (
                    latest_season_start_date,
                    latest_season_end_date,
                    latest_season_date_source,
                    date_notes,
                ) = self._lookup_latest_season_window(
                    top_match.imdb_id,
                    latest_season_number,
                    latest_season_episode_count,
                )
                notes.extend(date_notes)
            except ImdbEpisodeCountError as exc:
                notes.append(f"IMDb latest-season date lookup failed: {exc}")

        return ImdbEpisodeCountLookup(
            imdb_id=top_match.imdb_id,
            imdb_url=top_match.url,
            imdb_title=top_match.display_title,
            imdb_start_year=top_match.start_year,
            imdb_title_type=top_match.title_type,
            imdb_match_status=status,
            imdb_match_score=top_match.score,
            season_count=season_count,
            latest_season_number=latest_season_number,
            latest_season_episode_count=latest_season_episode_count,
            latest_season_start_date=latest_season_start_date,
            latest_season_end_date=latest_season_end_date,
            latest_season_date_source=latest_season_date_source,
            episode_count=episode_count,
            notes=tuple(notes),
        )

    def _lookup_counts(self, imdb_id: str) -> tuple[int, int | None, int, int]:
        db_path = self._ensure_episode_counts_index()
        try:
            with sqlite3.connect(db_path) as connection:
                row = connection.execute(
                    """
                    SELECT season_count, latest_season_number, latest_season_episode_count, episode_count
                    FROM episode_counts
                    WHERE parent_tconst = ?
                    """,
                    (imdb_id,),
                ).fetchone()
        except sqlite3.DatabaseError as exc:
            raise ImdbEpisodeCountError(f"could not read episode count index: {exc}") from exc

        if row is None:
            return 0, None, 0, 0
        latest_season_number = int(row[1]) if row[1] is not None else None
        return int(row[0] or 0), latest_season_number, int(row[2] or 0), int(row[3] or 0)

    def _lookup_latest_season_window(
        self,
        imdb_id: str,
        season_number: int,
        latest_season_episode_count: int,
    ) -> tuple[str, str, str, list[str]]:
        if self._imdb_episode_date_fetch_blocked:
            return "", "", "", []

        response = self._fetch_latest_season_episode_page(imdb_id, season_number)
        if response.status_code == 202 and response.headers.get("x-amzn-waf-action", "").casefold() == "challenge":
            self._imdb_episode_date_fetch_blocked = True
            return "", "", "", ["IMDb episode dates were unavailable due to an IMDb challenge response."]
        if response.status_code >= 400:
            return "", "", "", [f"IMDb episode dates were unavailable: HTTP {response.status_code}."]

        episode_dates = parse_imdb_episode_dates(response.text)
        if not episode_dates:
            return "", "", "", ["IMDb episode dates were unavailable for the latest season."]

        return _date_window_from_episode_dates(episode_dates, latest_season_episode_count) + ("imdb", [])

    def _fetch_latest_season_episode_page(self, imdb_id: str, season_number: int) -> httpx.Response:
        url = f"{IMDB_BASE_URL}/title/{imdb_id}/episodes/"
        timeout = httpx.Timeout(connect=5.0, read=min(max(float(self.timeout_seconds), 5.0), 12.0), write=5.0, pool=5.0)
        try:
            with httpx.Client(timeout=timeout, follow_redirects=True, headers=self._build_imdb_headers()) as client:
                return client.get(url, params={"season": str(season_number)})
        except httpx.HTTPError as exc:
            raise ImdbEpisodeCountError(f"could not fetch IMDb episode page: {exc.__class__.__name__}") from exc

    def _build_imdb_headers(self) -> dict[str, str]:
        return {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/133.0.0.0 Safari/537.36"
            ),
            "Referer": IMDB_BASE_URL,
        }

    def _ensure_episode_counts_index(self) -> Path:
        dataset_dir = self._imdb_dataset_dir()
        db_path = dataset_dir / IMDB_EPISODE_COUNTS_INDEX_FILENAME

        import os
        if os.environ.get("VERCEL") == "1":
            if db_path.exists():
                return db_path
            raise ImdbEpisodeCountError(
                "IMDb episode counts dataset is not available on Vercel deployment due to bundle size constraints. "
                "Please run this task in a local environment."
            )

        dataset_dir.mkdir(parents=True, exist_ok=True)
        episode_path = self._ensure_dataset_file(
            self._episode_dataset_source(),
            dataset_dir / IMDB_TITLE_EPISODE_FILENAME,
        )

        with IMDB_EPISODE_COUNTS_LOCK:
            if self._index_is_current(db_path, episode_path):
                return db_path
            self._build_counts_index(db_path, episode_path)
            return db_path

    def _build_counts_index(self, db_path: Path, episode_path: Path) -> None:
        total_counts: dict[str, int] = {}
        season_counts: dict[str, dict[int, int]] = {}
        try:
            with gzip.open(episode_path, "rt", encoding="utf-8", newline="") as file_handle:
                reader = csv.DictReader(file_handle, delimiter="\t")
                for row in reader:
                    parent_tconst = _clean_dataset_value(row.get("parentTconst"))
                    if not parent_tconst:
                        continue
                    total_counts[parent_tconst] = total_counts.get(parent_tconst, 0) + 1
                    season_number = _clean_dataset_value(row.get("seasonNumber"))
                    parsed_season_number = _parse_positive_int(season_number)
                    if parsed_season_number is not None:
                        parent_season_counts = season_counts.setdefault(parent_tconst, {})
                        parent_season_counts[parsed_season_number] = (
                            parent_season_counts.get(parsed_season_number, 0) + 1
                        )
        except (OSError, csv.Error) as exc:
            raise ImdbEpisodeCountError(f"could not parse IMDb episode dataset: {exc}") from exc

        temporary_db = db_path.with_suffix(db_path.suffix + ".tmp")
        if temporary_db.exists():
            temporary_db.unlink()

        connection = sqlite3.connect(temporary_db)
        try:
            connection.execute("PRAGMA journal_mode = OFF")
            connection.execute("PRAGMA synchronous = OFF")
            connection.execute(
                """
                CREATE TABLE episode_counts (
                    parent_tconst TEXT PRIMARY KEY,
                    season_count INTEGER NOT NULL,
                    latest_season_number INTEGER,
                    latest_season_episode_count INTEGER NOT NULL,
                    episode_count INTEGER NOT NULL
                )
                """
            )
            rows = []
            for parent_tconst, episode_count in total_counts.items():
                parent_season_counts = season_counts.get(parent_tconst, {})
                latest_season_number = max(parent_season_counts) if parent_season_counts else None
                latest_season_episode_count = (
                    parent_season_counts[latest_season_number] if latest_season_number is not None else 0
                )
                rows.append(
                    (
                        parent_tconst,
                        len(parent_season_counts),
                        latest_season_number,
                        latest_season_episode_count,
                        episode_count,
                    )
                )
            connection.executemany(
                """
                INSERT INTO episode_counts (
                    parent_tconst, season_count, latest_season_number,
                    latest_season_episode_count, episode_count
                ) VALUES (?, ?, ?, ?, ?)
                """,
                rows,
            )
            connection.commit()
        except sqlite3.DatabaseError as exc:
            raise ImdbEpisodeCountError(f"could not build episode count index: {exc}") from exc
        finally:
            connection.close()

        temporary_db.replace(db_path)

    def _ensure_dataset_file(self, source: str, destination: Path) -> Path:
        cleaned_source = _clean_dataset_value(source)
        if not cleaned_source:
            raise ImdbEpisodeCountError("IMDb title.episode dataset source is not configured.")

        if _looks_like_url(cleaned_source):
            if destination.exists():
                refresh_age_hours = max(int(title_lookup_settings.imdb_dataset_refresh_hours or 24), 1)
                age_seconds = time.time() - destination.stat().st_mtime
                if age_seconds < refresh_age_hours * 3600:
                    return destination
            self._download_dataset_file(cleaned_source, destination)
            return destination

        source_path = Path(cleaned_source)
        if not source_path.exists():
            raise ImdbEpisodeCountError(f"IMDb episode dataset file was not found: {source_path}")
        if (
            not destination.exists()
            or source_path.stat().st_mtime > destination.stat().st_mtime
            or source_path.stat().st_size != destination.stat().st_size
        ):
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, destination)
        return destination

    def _download_dataset_file(self, url: str, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = destination.with_suffix(destination.suffix + ".tmp")
        timeout = httpx.Timeout(connect=10.0, read=90.0, write=90.0, pool=10.0)
        try:
            with httpx.Client(timeout=timeout, follow_redirects=True) as client:
                with client.stream("GET", url) as response:
                    response.raise_for_status()
                    with temporary_path.open("wb") as file_handle:
                        for chunk in response.iter_bytes():
                            if chunk:
                                file_handle.write(chunk)
        except httpx.HTTPError as exc:
            raise ImdbEpisodeCountError(f"could not download IMDb episode dataset: {exc}") from exc
        temporary_path.replace(destination)

    def _index_is_current(self, db_path: Path, episode_path: Path) -> bool:
        return db_path.exists() and episode_path.exists() and episode_path.stat().st_mtime <= db_path.stat().st_mtime

    def _imdb_dataset_dir(self) -> Path:
        configured = _clean_dataset_value(title_lookup_settings.imdb_dataset_dir)
        if configured:
            return Path(configured)

        shared_dir = BASE_DIR / "data" / "imdb_datasets"
        if shared_dir.exists():
            return shared_dir
        return BASE_DIR / "data" / "metacritic_calendar_app"

    def _episode_dataset_source(self) -> str:
        return title_lookup_settings.imdb_title_episode_url

    def _match_status(self, matches: list[object]) -> str:
        top = matches[0]
        top_score = float(getattr(top, "score", 0) or 0)
        runner_up = matches[1] if len(matches) > 1 else None
        runner_score = float(getattr(runner_up, "score", 0) or 0) if runner_up is not None else 0
        if top_score >= 150 and (runner_up is None or top_score - runner_score >= 8):
            return "found"
        if top_score >= 110:
            return "uncertain"
        return "not_found"


class TvImdbEpisodeCountService:
    def __init__(
        self,
        calendar_service: MetacriticCalendarService | None = None,
        imdb_episode_count_service: ImdbEpisodeCountService | None = None,
    ) -> None:
        self.calendar_service = calendar_service or MetacriticCalendarService()
        self.imdb_episode_count_service = imdb_episode_count_service or ImdbEpisodeCountService()

    def fetch_snapshot(
        self,
        date_window: str = DEFAULT_TV_IMDB_DATE_WINDOW_KEY,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
        today: date | None = None,
    ) -> TvImdbEpisodeCountSnapshot:
        resolved_window = resolve_tv_imdb_date_window(date_window, today, start_date, end_date)
        tv_snapshot = self.calendar_service.fetch_snapshot("tv")
        generated_at = datetime.now().astimezone()
        items: list[TvImdbEpisodeCountItem] = []
        lookup_cache: dict[str, ImdbEpisodeCountLookup] = {}
        skipped_outside_window = 0
        skipped_missing_date = 0
        skipped_rent_buy = 0
        skipped_movies = 0

        for tv_item in tv_snapshot.items:
            release_date = _parse_iso_date(tv_item.release_date)
            if release_date is None:
                skipped_missing_date += 1
                continue
            if not resolved_window.window_start <= release_date <= resolved_window.window_end:
                skipped_outside_window += 1
                continue
            if contains_rent_buy(tv_item.availability):
                skipped_rent_buy += 1
                continue
            if _is_movie_calendar_item(tv_item):
                skipped_movies += 1
                continue

            cache_key = _normalize_lookup_text(tv_item.title)
            lookup = lookup_cache.get(cache_key)
            if lookup is None:
                lookup = self.imdb_episode_count_service.lookup_show(tv_item.title)
                lookup_cache[cache_key] = lookup
            items.append(self._build_item(tv_item, lookup))

        notes = list(tv_snapshot.notes)
        notes.append(
            "Date window: "
            f"{resolved_window.label} "
            f"({resolved_window.window_start.isoformat()} to {resolved_window.window_end.isoformat()})."
        )
        if skipped_outside_window:
            notes.append(_format_tv_row_note(skipped_outside_window, "outside the selected date window."))
        if skipped_missing_date:
            notes.append(_format_tv_row_note(skipped_missing_date, "skipped because the release date was unavailable."))
        if skipped_rent_buy:
            notes.append(_format_tv_row_note(skipped_rent_buy, "skipped because the availability is Rent/Buy."))
        if skipped_movies:
            notes.append(_format_tv_row_note(skipped_movies, "skipped because the title is tagged as a movie."))
        if not items:
            notes.append("No TV rows were found in the selected date window.")
        error_count = sum(1 for item in items if item.imdb_match_status == "error")
        uncertain_count = sum(1 for item in items if item.imdb_match_status == "uncertain")
        not_found_count = sum(1 for item in items if item.imdb_match_status == "not_found")
        if uncertain_count:
            notes.append(f"{uncertain_count} IMDb matches need review.")
        if not_found_count:
            notes.append(f"{not_found_count} TV shows did not receive a strong IMDb match.")
        if error_count:
            notes.append(f"{error_count} IMDb episode count lookups failed.")

        return TvImdbEpisodeCountSnapshot(
            generated_at=generated_at,
            source_url=MetacriticCalendarService.TARGETS["tv"].source_url,
            date_window_key=resolved_window.key,
            date_window_label=resolved_window.label,
            window_start=resolved_window.window_start,
            window_end=resolved_window.window_end,
            items=items,
            notes=notes,
        )

    def snapshot_to_csv_bytes(self, snapshot: TvImdbEpisodeCountSnapshot) -> bytes:
        output = io.StringIO()
        writer = csv.DictWriter(
            output,
            fieldnames=TV_IMDB_OUTPUT_COLUMNS,
        )
        writer.writeheader()
        for item in snapshot.items:
            writer.writerow(
                {
                    "release_date": format_date_dd_mm_yyyy(item.release_date),
                    "title": item.title,
                    "network_distributor": item.network_distributor,
                    "imdb_id": item.imdb_id,
                    "metacritic_url": item.metacritic_url,
                    "latest_season_number": (
                        item.latest_season_number if item.latest_season_number is not None else ""
                    ),
                    "latest_season_episode_count": (
                        item.latest_season_episode_count if item.latest_season_episode_count is not None else ""
                    ),
                    "latest_season_start_date": format_date_dd_mm_yyyy(item.latest_season_start_date),
                    "latest_season_end_date": format_date_dd_mm_yyyy(item.latest_season_end_date),
                }
            )
        return output.getvalue().encode("utf-8-sig")

    def snapshot_to_xlsx_bytes(self, snapshot: TvImdbEpisodeCountSnapshot) -> bytes:
        workbook = Workbook()
        releases_sheet = workbook.active
        releases_sheet.title = "Export"
        releases_sheet.append(TV_IMDB_OUTPUT_COLUMNS)
        for item in snapshot.items:
            releases_sheet.append(
                [
                    format_date_dd_mm_yyyy(item.release_date),
                    item.title,
                    item.network_distributor,
                    item.imdb_id,
                    item.metacritic_url,
                    item.latest_season_number if item.latest_season_number is not None else "",
                    item.latest_season_episode_count if item.latest_season_episode_count is not None else "",
                    format_date_dd_mm_yyyy(item.latest_season_start_date),
                    format_date_dd_mm_yyyy(item.latest_season_end_date),
                ]
            )

        output = io.BytesIO()
        workbook.save(output)
        return output.getvalue()

    def _build_item(self, tv_item, lookup: ImdbEpisodeCountLookup) -> TvImdbEpisodeCountItem:
        return TvImdbEpisodeCountItem(
            release_date=tv_item.release_date,
            title=tv_item.title,
            metacritic_url=tv_item.url,
            network_distributor=tv_item.availability,
            provider=tv_item.provider,
            availability=tv_item.availability,
            details=tv_item.details,
            imdb_id=lookup.imdb_id,
            imdb_url=lookup.imdb_url,
            imdb_title=lookup.imdb_title,
            imdb_start_year=lookup.imdb_start_year,
            imdb_title_type=lookup.imdb_title_type,
            imdb_match_status=lookup.imdb_match_status,
            imdb_match_score=lookup.imdb_match_score,
            season_count=lookup.season_count,
            latest_season_number=lookup.latest_season_number,
            latest_season_episode_count=lookup.latest_season_episode_count,
            latest_season_start_date=self._resolve_latest_season_start_date(tv_item.release_date, lookup),
            latest_season_end_date=self._resolve_latest_season_end_date(tv_item.release_date, lookup),
            latest_season_date_source=lookup.latest_season_date_source
            or ("metacritic_fallback" if lookup.latest_season_episode_count and tv_item.release_date else ""),
            episode_count=lookup.episode_count,
            notes=self._build_item_notes(tv_item.release_date, lookup),
        )

    def _resolve_latest_season_start_date(self, release_date: str, lookup: ImdbEpisodeCountLookup) -> str:
        if lookup.latest_season_start_date:
            return lookup.latest_season_start_date
        if not lookup.latest_season_episode_count:
            return ""
        return release_date if _parse_iso_date(release_date) is not None else ""

    def _resolve_latest_season_end_date(self, release_date: str, lookup: ImdbEpisodeCountLookup) -> str:
        if lookup.latest_season_end_date:
            return lookup.latest_season_end_date
        if not lookup.latest_season_episode_count:
            return ""

        parsed_release_date = _parse_iso_date(release_date)
        if parsed_release_date is None:
            return ""
        return (parsed_release_date + timedelta(days=30)).isoformat()

    def _build_item_notes(self, release_date: str, lookup: ImdbEpisodeCountLookup) -> list[str]:
        notes = list(lookup.notes)
        if not lookup.latest_season_start_date and lookup.latest_season_episode_count and release_date:
            notes.append("Latest-season dates use the Metacritic release date fallback.")
        return notes


def _clean_dataset_value(value: object) -> str:
    if value is None:
        return ""
    cleaned = str(value).strip()
    return "" if cleaned == r"\N" else cleaned


def _looks_like_url(value: str) -> bool:
    return value.startswith("http://") or value.startswith("https://")


def _normalize_lookup_text(value: str) -> str:
    return " ".join(value.casefold().split())


def _is_movie_calendar_item(item: object) -> bool:
    section = str(getattr(item, "section", "") or "").casefold()
    if section == "movies":
        return True
    url = str(getattr(item, "url", "") or "").casefold()
    return "/movie/" in url


def _format_tv_row_note(count: int, message: str) -> str:
    row_word = "row" if count == 1 else "rows"
    verb = "was" if count == 1 else "were"
    return f"{count} TV {row_word} {verb} {message}"


def tv_imdb_date_window_options() -> list[tuple[str, str]]:
    return [(window.key, window.label) for window in TV_IMDB_DATE_WINDOWS] + [
        (TV_IMDB_CUSTOM_DATE_WINDOW_KEY, TV_IMDB_CUSTOM_DATE_WINDOW_LABEL)
    ]


def resolve_tv_imdb_date_window(
    date_window: str,
    today: date | None = None,
    start_date: date | str | None = None,
    end_date: date | str | None = None,
) -> ResolvedTvImdbDateWindow:
    key = _clean_dataset_value(date_window).casefold() or DEFAULT_TV_IMDB_DATE_WINDOW_KEY
    if key == TV_IMDB_CUSTOM_DATE_WINDOW_KEY:
        window_start = _parse_required_iso_date(start_date, "custom start date")
        window_end = _parse_required_iso_date(end_date, "custom end date")
        if window_start > window_end:
            raise ValueError("Custom start date must be on or before custom end date.")
        return ResolvedTvImdbDateWindow(
            key=TV_IMDB_CUSTOM_DATE_WINDOW_KEY,
            label=TV_IMDB_CUSTOM_DATE_WINDOW_LABEL,
            window_start=window_start,
            window_end=window_end,
        )

    anchor_date = today or datetime.now().astimezone().date()
    if key == "daily_segment":
        # Monday is 0
        if anchor_date.weekday() == 0:
            window_start = anchor_date - timedelta(days=2)
            window_end = anchor_date
            label = "Saturday, Sunday, Monday (Weekend + Monday)"
        else:
            window_start = anchor_date
            window_end = anchor_date
            label = f"Daily - {anchor_date.strftime('%A')}"
        return ResolvedTvImdbDateWindow(
            key="daily_segment",
            label=label,
            window_start=window_start,
            window_end=window_end,
        )

    window = TV_IMDB_DATE_WINDOW_MAP.get(key)
    if window is None:
        valid_keys = ", ".join([item.key for item in TV_IMDB_DATE_WINDOWS] + [TV_IMDB_CUSTOM_DATE_WINDOW_KEY])
        raise ValueError(f"Choose a valid TV IMDb date window: {valid_keys}.")

    return ResolvedTvImdbDateWindow(
        key=window.key,
        label=window.label,
        window_start=anchor_date + timedelta(days=window.start_offset_days),
        window_end=anchor_date + timedelta(days=window.end_offset_days),
    )


def _parse_positive_int(value: object) -> int | None:
    cleaned = _clean_dataset_value(value)
    if not cleaned:
        return None
    try:
        parsed = int(cleaned)
    except ValueError:
        return None
    return parsed if parsed > 0 else None


def parse_imdb_episode_dates(payload: str) -> list[date]:
    parsed_dates: set[date] = set()
    for match in EPISODE_DATE_FIELDS_RE.finditer(payload):
        parsed_date = _parse_iso_date(match.group("date"))
        if parsed_date is not None:
            parsed_dates.add(parsed_date)

    if not parsed_dates:
        visible_text = _html_to_text(payload)
        for match in ISO_DATE_RE.finditer(visible_text):
            parsed_date = _parse_iso_date(match.group("date"))
            if parsed_date is not None:
                parsed_dates.add(parsed_date)
        for match in US_DATE_RE.finditer(visible_text):
            parsed_date = _parse_named_month_date(
                match.group("year"),
                match.group("month"),
                match.group("day"),
            )
            if parsed_date is not None:
                parsed_dates.add(parsed_date)
        for match in INTERNATIONAL_DATE_RE.finditer(visible_text):
            parsed_date = _parse_named_month_date(
                match.group("year"),
                match.group("month"),
                match.group("day"),
            )
            if parsed_date is not None:
                parsed_dates.add(parsed_date)

    return sorted(parsed_dates)


def _date_window_from_episode_dates(episode_dates: list[date], latest_season_episode_count: int) -> tuple[str, str]:
    start_date = min(episode_dates)
    end_date = max(episode_dates)
    if latest_season_episode_count <= 1 or start_date == end_date:
        end_date = start_date + timedelta(days=30)
    return start_date.isoformat(), end_date.isoformat()


def _parse_iso_date(value: object) -> date | None:
    cleaned = _clean_dataset_value(value)
    if not cleaned:
        return None
    try:
        return date.fromisoformat(cleaned)
    except ValueError:
        return None


def _parse_required_iso_date(value: object, field_label: str) -> date:
    parsed = _parse_iso_date(value)
    if parsed is None:
        raise ValueError(f"Enter a valid {field_label} in YYYY-MM-DD format.")
    return parsed


def _parse_named_month_date(year: str, month: str, day: str) -> date | None:
    month_number = MONTHS.get(month.rstrip(".").casefold())
    if month_number is None:
        return None
    try:
        return date(int(year), month_number, int(day))
    except ValueError:
        return None


def _html_to_text(payload: str) -> str:
    text = re.sub(r"<script\b[^>]*>.*?</script>", " ", payload, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<style\b[^>]*>.*?</style>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    return html.unescape(re.sub(r"\s+", " ", text))
