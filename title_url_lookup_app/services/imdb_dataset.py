from __future__ import annotations

import csv
import gzip
import re
import shutil
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

import httpx

from title_url_lookup_app.config import BASE_DIR, settings
from title_url_lookup_app.models import TitleLookupQuery


IMDB_TITLE_BASICS_FILENAME = "title.basics.tsv.gz"
IMDB_NAME_BASICS_FILENAME = "name.basics.tsv.gz"
IMDB_INDEX_FILENAME = "imdb_title_lookup.sqlite3"
IMDB_INDEX_LOCK = Lock()

MOVIE_TYPES = {"movie", "tvMovie"}
TV_TYPES = {"tvSeries", "tvMiniSeries"}
TYPE_WEIGHT = {
    "movie": 35,
    "tvMovie": 25,
    "tvSeries": 35,
    "tvMiniSeries": 30,
    "short": 8,
    "tvShort": 5,
    "video": 3,
    "tvSpecial": 4,
    "tvEpisode": -40,
    "podcastSeries": -55,
    "podcastEpisode": -65,
    "videoGame": -30,
}


class ImdbDatasetLookupError(ValueError):
    pass


@dataclass(frozen=True)
class ImdbTitleMatch:
    imdb_id: str
    url: str
    display_title: str
    original_title: str
    title_type: str
    start_year: str
    end_year: str
    score: float
    matched_on: list[str]


class ImdbDatasetLookupService:
    def lookup_title(self, query: TitleLookupQuery) -> list[ImdbTitleMatch]:
        db_path = self._ensure_imdb_dataset_index()
        with sqlite3.connect(db_path) as connection:
            connection.row_factory = sqlite3.Row
            return self._lookup_title_matches(connection, query)

    def _lookup_title_matches(self, connection: sqlite3.Connection, query: TitleLookupQuery) -> list[ImdbTitleMatch]:
        normalized = _normalize_lookup_text(query.title)
        if not normalized:
            return []

        matches = connection.execute(
            """
            SELECT
                tconst,
                primary_title,
                original_title,
                title_type,
                start_year,
                end_year,
                CASE
                    WHEN primary_title_norm = ? THEN 'primary_title'
                    ELSE 'original_title'
                END AS matched_on
            FROM title_basics
            WHERE primary_title_norm = ? OR original_title_norm = ?
            LIMIT 100
            """,
            (normalized, normalized, normalized),
        ).fetchall()

        ranked: list[ImdbTitleMatch] = []
        for row in matches:
            score, matched_on = _score_dataset_match(query, row)
            if score < 0:
                continue
            ranked.append(
                ImdbTitleMatch(
                    imdb_id=row["tconst"],
                    url=f"https://www.imdb.com/title/{row['tconst']}/",
                    display_title=_clean_dataset_value(row["primary_title"]),
                    original_title=_clean_dataset_value(row["original_title"]),
                    title_type=_normalize_title_type(row["title_type"]),
                    start_year=_clean_dataset_value(row["start_year"]),
                    end_year=_clean_dataset_value(row["end_year"]),
                    score=round(score, 2),
                    matched_on=matched_on,
                )
            )

        return sorted(
            ranked,
            key=lambda item: (
                -item.score,
                _sortable_year(item.start_year),
                item.imdb_id,
            ),
        )[:10]

    def _ensure_imdb_dataset_index(self) -> Path:
        dataset_dir = self._imdb_dataset_dir()
        db_path = dataset_dir / IMDB_INDEX_FILENAME

        import os
        if os.environ.get("VERCEL") == "1":
            if db_path.exists() and self._has_required_schema(db_path):
                return db_path
            # Check other possible locations
            candidates = [
                BASE_DIR / "data" / "imdb_lookup_app" / "imdb_lookup.sqlite3",
                BASE_DIR / "data" / "imdb_datasets" / "imdb_basics.sqlite3",
            ]
            for candidate in candidates:
                if candidate.exists() and self._has_required_schema(candidate):
                    return candidate
            raise ImdbDatasetLookupError(
                "IMDb dataset index is not available on Vercel deployment due to bundle size constraints. "
                "Please run this task in a local environment."
            )

        dataset_dir.mkdir(parents=True, exist_ok=True)

        title_path = self._ensure_dataset_file(
            settings.imdb_title_basics_url,
            dataset_dir / IMDB_TITLE_BASICS_FILENAME,
        )
        name_path = self._ensure_dataset_file(
            settings.imdb_name_basics_url,
            dataset_dir / IMDB_NAME_BASICS_FILENAME,
        )
        compatible_index = self._find_compatible_existing_index(title_path, name_path)
        if compatible_index is not None:
            return compatible_index

        with IMDB_INDEX_LOCK:
            if self._index_is_current(db_path, [title_path, name_path]):
                return db_path
            self._build_index(db_path, title_path, name_path)
            return db_path

    def _imdb_dataset_dir(self) -> Path:
        configured = _clean_dataset_value(settings.imdb_dataset_dir)
        if configured:
            return Path(configured)

        local_shared = BASE_DIR / "data" / "imdb_datasets"
        if local_shared.exists():
            return local_shared
        return BASE_DIR / "data" / "title_url_lookup_app"

    def _find_compatible_existing_index(self, title_path: Path, name_path: Path) -> Path | None:
        candidates = [
            self._imdb_dataset_dir() / IMDB_INDEX_FILENAME,
            BASE_DIR / "data" / "imdb_lookup_app" / "imdb_lookup.sqlite3",
            BASE_DIR / "data" / "imdb_datasets" / "imdb_basics.sqlite3",
        ]
        fallback_candidate: Path | None = None
        for candidate in candidates:
            if not candidate.exists():
                continue
            if not self._has_required_schema(candidate):
                continue
            if self._index_is_current(candidate, [title_path, name_path]):
                return candidate
            if fallback_candidate is None:
                fallback_candidate = candidate
        return fallback_candidate

    def _ensure_dataset_file(self, source: str, destination: Path) -> Path:
        cleaned_source = _clean_dataset_value(source)
        if not cleaned_source:
            raise ImdbDatasetLookupError("IMDb dataset source is not configured.")

        if _looks_like_url(cleaned_source):
            if destination.exists():
                refresh_age_hours = max(int(settings.imdb_dataset_refresh_hours or 24), 1)
                age_seconds = time.time() - destination.stat().st_mtime
                if age_seconds < refresh_age_hours * 3600:
                    return destination
            self._download_dataset_file(cleaned_source, destination)
            return destination

        source_path = Path(cleaned_source)
        if not source_path.exists():
            raise ImdbDatasetLookupError(f"IMDb dataset file was not found: {source_path}")
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
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            with client.stream("GET", url) as response:
                response.raise_for_status()
                with temporary_path.open("wb") as file_handle:
                    for chunk in response.iter_bytes():
                        if chunk:
                            file_handle.write(chunk)
        temporary_path.replace(destination)

    def _index_is_current(self, db_path: Path, source_paths: list[Path]) -> bool:
        if not db_path.exists():
            return False
        db_mtime = db_path.stat().st_mtime
        return all(source_path.exists() and source_path.stat().st_mtime <= db_mtime for source_path in source_paths)

    def _has_required_schema(self, db_path: Path) -> bool:
        try:
            with sqlite3.connect(db_path) as connection:
                title_columns = {
                    row[1]
                    for row in connection.execute("PRAGMA table_info(title_basics)").fetchall()
                }
                name_columns = {
                    row[1]
                    for row in connection.execute("PRAGMA table_info(name_basics)").fetchall()
                }
        except sqlite3.DatabaseError:
            return False

        required_title_columns = {
            "tconst",
            "primary_title",
            "original_title",
            "title_type",
            "start_year",
            "end_year",
            "primary_title_norm",
            "original_title_norm",
        }
        required_name_columns = {
            "nconst",
            "primary_name",
            "birth_year",
            "death_year",
            "primary_profession",
            "known_for_titles",
            "primary_name_norm",
        }
        return required_title_columns.issubset(title_columns) and required_name_columns.issubset(name_columns)

    def _build_index(self, db_path: Path, title_path: Path, name_path: Path) -> None:
        temporary_db = db_path.with_suffix(db_path.suffix + ".tmp")
        if temporary_db.exists():
            temporary_db.unlink()

        connection = sqlite3.connect(temporary_db)
        try:
            connection.execute("PRAGMA journal_mode = OFF")
            connection.execute("PRAGMA synchronous = OFF")
            connection.execute("PRAGMA temp_store = MEMORY")
            connection.execute(
                """
                CREATE TABLE title_basics (
                    tconst TEXT PRIMARY KEY,
                    primary_title TEXT NOT NULL,
                    original_title TEXT NOT NULL,
                    title_type TEXT NOT NULL,
                    start_year TEXT NOT NULL,
                    end_year TEXT NOT NULL,
                    primary_title_norm TEXT NOT NULL,
                    original_title_norm TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE name_basics (
                    nconst TEXT PRIMARY KEY,
                    primary_name TEXT NOT NULL,
                    birth_year TEXT NOT NULL,
                    death_year TEXT NOT NULL,
                    primary_profession TEXT NOT NULL,
                    known_for_titles TEXT NOT NULL,
                    primary_name_norm TEXT NOT NULL
                )
                """
            )
            self._load_title_basics(connection, title_path)
            self._load_name_basics(connection, name_path)
            connection.execute("CREATE INDEX idx_title_primary_norm ON title_basics(primary_title_norm)")
            connection.execute("CREATE INDEX idx_title_original_norm ON title_basics(original_title_norm)")
            connection.execute("CREATE INDEX idx_name_primary_norm ON name_basics(primary_name_norm)")
            connection.commit()
        finally:
            connection.close()

        temporary_db.replace(db_path)

    def _load_title_basics(self, connection: sqlite3.Connection, title_path: Path) -> None:
        with gzip.open(title_path, "rt", encoding="utf-8", newline="") as file_handle:
            reader = csv.DictReader(file_handle, delimiter="\t")
            rows: list[tuple[str, str, str, str, str, str, str, str]] = []
            for row in reader:
                primary_title = _clean_dataset_value(row.get("primaryTitle"))
                original_title = _clean_dataset_value(row.get("originalTitle"))
                rows.append(
                    (
                        _clean_dataset_value(row.get("tconst")),
                        primary_title,
                        original_title,
                        _clean_dataset_value(row.get("titleType")),
                        _clean_dataset_value(row.get("startYear")),
                        _clean_dataset_value(row.get("endYear")),
                        _normalize_lookup_text(primary_title),
                        _normalize_lookup_text(original_title),
                    )
                )
                if len(rows) >= 10000:
                    connection.executemany(
                        """
                        INSERT OR REPLACE INTO title_basics (
                            tconst, primary_title, original_title, title_type,
                            start_year, end_year, primary_title_norm, original_title_norm
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        rows,
                    )
                    rows.clear()
            if rows:
                connection.executemany(
                    """
                    INSERT OR REPLACE INTO title_basics (
                        tconst, primary_title, original_title, title_type,
                        start_year, end_year, primary_title_norm, original_title_norm
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    rows,
                )

    def _load_name_basics(self, connection: sqlite3.Connection, name_path: Path) -> None:
        with gzip.open(name_path, "rt", encoding="utf-8", newline="") as file_handle:
            reader = csv.DictReader(file_handle, delimiter="\t")
            rows: list[tuple[str, str, str, str, str, str, str]] = []
            for row in reader:
                primary_name = _clean_dataset_value(row.get("primaryName"))
                rows.append(
                    (
                        _clean_dataset_value(row.get("nconst")),
                        primary_name,
                        _clean_dataset_value(row.get("birthYear")),
                        _clean_dataset_value(row.get("deathYear")),
                        _clean_dataset_value(row.get("primaryProfession")),
                        _clean_dataset_value(row.get("knownForTitles")),
                        _normalize_lookup_text(primary_name),
                    )
                )
                if len(rows) >= 10000:
                    connection.executemany(
                        """
                        INSERT OR REPLACE INTO name_basics (
                            nconst, primary_name, birth_year, death_year,
                            primary_profession, known_for_titles, primary_name_norm
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        rows,
                    )
                    rows.clear()
            if rows:
                connection.executemany(
                    """
                    INSERT OR REPLACE INTO name_basics (
                        nconst, primary_name, birth_year, death_year,
                        primary_profession, known_for_titles, primary_name_norm
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    rows,
                )


def _score_dataset_match(query: TitleLookupQuery, row: sqlite3.Row) -> tuple[float, list[str]]:
    score = 0.0
    matched_on = [_clean_dataset_value(row["matched_on"])]
    title_type = _clean_dataset_value(row["title_type"])
    normalized_type = _normalize_title_type(title_type)

    score += 100 if matched_on[0] == "primary_title" else 92

    type_weight = TYPE_WEIGHT.get(title_type, TYPE_WEIGHT.get(normalized_type, 0))
    score += type_weight
    if query.title_type == "movie":
        if normalized_type in MOVIE_TYPES:
            score += 28
            matched_on.append("movie type matched")
        elif normalized_type in TV_TYPES:
            score -= 25
        elif normalized_type in {"podcastEpisode", "podcastSeries", "tvEpisode"}:
            score -= 60
    elif query.title_type == "tv":
        if normalized_type in TV_TYPES:
            score += 28
            matched_on.append("tv type matched")
        elif normalized_type in MOVIE_TYPES:
            score -= 20
        elif normalized_type in {"podcastEpisode", "podcastSeries"}:
            score -= 60

    start_year = _clean_dataset_value(row["start_year"])
    if query.year:
        if start_year == query.year:
            score += 45
            matched_on.append(f"start year {query.year} matched")
        elif start_year:
            try:
                score -= min(abs(int(start_year) - int(query.year)) * 3, 24)
            except ValueError:
                score -= 8
    elif start_year:
        score += 4

    primary_title = _clean_dataset_value(row["primary_title"])
    if _normalize_lookup_text(primary_title) == _normalize_lookup_text(query.title):
        score += 18
        matched_on.append("normalized title matched")

    return score, matched_on


def _looks_like_url(value: str) -> bool:
    return value.startswith("http://") or value.startswith("https://")


def _clean_dataset_value(value: object) -> str:
    if value is None:
        return ""
    cleaned = str(value).strip()
    return "" if cleaned == r"\N" else cleaned


def _normalize_lookup_text(value: object) -> str:
    cleaned = _clean_dataset_value(value)
    cleaned = cleaned.casefold()
    cleaned = cleaned.replace("&", " and ")
    cleaned = re.sub(r"[^a-z0-9]+", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def _normalize_title_type(value: object) -> str:
    normalized = _normalize_lookup_text(value).replace(" ", "")
    aliases = {
        "tvseries": "tvSeries",
        "tvminiseries": "tvMiniSeries",
        "tvepisode": "tvEpisode",
        "tvspecial": "tvSpecial",
        "tvmovie": "tvMovie",
        "podcastepisode": "podcastEpisode",
        "podcastseries": "podcastSeries",
    }
    if normalized in aliases:
        return aliases[normalized]
    return _clean_dataset_value(value)


def _sortable_year(value: str) -> int:
    try:
        return -int(value)
    except ValueError:
        return 999999
