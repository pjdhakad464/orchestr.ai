from __future__ import annotations

import csv
import gzip
import re
import shutil
import sqlite3
import time
from pathlib import Path
from threading import Lock

import httpx

from imdb_lookup_app.config import BASE_DIR, settings
from imdb_lookup_app.models import LookupBatchResult, LookupMode, LookupRow, LookupStatus


IMDB_TITLE_BASICS_FILENAME = "title.basics.tsv.gz"
IMDB_NAME_BASICS_FILENAME = "name.basics.tsv.gz"
IMDB_INDEX_FILENAME = "imdb_title_lookup.sqlite3"
IMDB_INDEX_LOCK = Lock()


class ImdbLookupServiceError(ValueError):
    pass


class ImdbLookupService:
    def lookup_values(self, values: list[str], mode: LookupMode) -> LookupBatchResult:
        cleaned_values = [value.strip() for value in values if value and value.strip()]
        if not cleaned_values:
            return LookupBatchResult(summary=["No values were provided."])

        db_path = self._ensure_imdb_dataset_index()
        rows: list[LookupRow] = []
        status_counts: dict[LookupStatus, int] = {
            "matched": 0,
            "multiple_matches": 0,
            "not_found": 0,
            "invalid": 0,
        }

        with sqlite3.connect(db_path) as connection:
            connection.row_factory = sqlite3.Row
            for value in cleaned_values:
                matched_rows, status = self._lookup_single_value(connection, value, mode)
                rows.extend(matched_rows)
                status_counts[status] += 1

        summary = [f"{len(cleaned_values)} inputs processed"]
        if status_counts["matched"]:
            summary.append(f"{status_counts['matched']} inputs matched exactly")
        if status_counts["multiple_matches"]:
            summary.append(f"{status_counts['multiple_matches']} inputs returned multiple matches")
        if status_counts["not_found"]:
            summary.append(f"{status_counts['not_found']} inputs were not found")
        if status_counts["invalid"]:
            summary.append(f"{status_counts['invalid']} inputs were invalid for the selected mode")
        summary.append(f"{len(rows)} output rows generated")
        return LookupBatchResult(rows=rows, summary=summary)

    def _lookup_single_value(
        self,
        connection: sqlite3.Connection,
        raw_value: str,
        mode: LookupMode,
    ) -> tuple[list[LookupRow], LookupStatus]:
        imdb_id = _extract_imdb_identifier(raw_value)

        if mode == "id_to_name":
            if not imdb_id:
                return [self._build_invalid_row(raw_value, mode, "Expected an IMDb id like tt1234567 or nm1234567.")], "invalid"
            result = self._lookup_by_identifier(connection, raw_value, imdb_id, mode)
            return [result], result.status

        if mode == "title_to_id":
            rows = self._lookup_title_matches(connection, raw_value, mode)
            return rows, _rows_status(rows)

        if mode == "person_to_id":
            rows = self._lookup_person_matches(connection, raw_value, mode)
            return rows, _rows_status(rows)

        if imdb_id:
            result = self._lookup_by_identifier(connection, raw_value, imdb_id, mode)
            return [result], result.status

        title_rows = self._lookup_title_matches(connection, raw_value, mode)
        person_rows = self._lookup_person_matches(connection, raw_value, mode)
        rows = title_rows + person_rows
        if rows:
            return _rebalance_auto_rows(rows), _rows_status(rows)
        return [self._build_not_found_row(raw_value, mode, "No exact title or person match was found.")], "not_found"

    def _lookup_by_identifier(
        self,
        connection: sqlite3.Connection,
        raw_value: str,
        imdb_id: str,
        mode: LookupMode,
    ) -> LookupRow:
        if imdb_id.startswith("tt"):
            row = connection.execute(
                """
                SELECT tconst, primary_title, original_title, title_type, start_year, end_year
                FROM title_basics
                WHERE tconst = ?
                """,
                (imdb_id,),
            ).fetchone()
            if row is None:
                return self._build_not_found_row(raw_value, mode, "The IMDb title id was not found in the local dataset.")
            return LookupRow(
                input_value=raw_value,
                normalized_input=imdb_id,
                requested_mode=mode,
                resolved_lookup="id_to_title",
                status="matched",
                imdb_id=row["tconst"],
                entity_kind="title",
                display_name=_clean_dataset_value(row["primary_title"]),
                original_title=_clean_dataset_value(row["original_title"]),
                title_type=_normalize_title_type(row["title_type"]),
                start_year=_clean_dataset_value(row["start_year"]),
                end_year=_clean_dataset_value(row["end_year"]),
                source_url=f"https://www.imdb.com/title/{row['tconst']}/",
                matched_on="tconst",
                notes="",
            )

        row = connection.execute(
            """
            SELECT nconst, primary_name, birth_year, death_year, primary_profession, known_for_titles
            FROM name_basics
            WHERE nconst = ?
            """,
            (imdb_id,),
        ).fetchone()
        if row is None:
            return self._build_not_found_row(raw_value, mode, "The IMDb name id was not found in the local dataset.")

        known_for_titles = self._resolve_known_for_titles(connection, _clean_dataset_value(row["known_for_titles"]))
        return LookupRow(
            input_value=raw_value,
            normalized_input=imdb_id,
            requested_mode=mode,
            resolved_lookup="id_to_person",
            status="matched",
            imdb_id=row["nconst"],
            entity_kind="person",
            display_name=_clean_dataset_value(row["primary_name"]),
            birth_year=_clean_dataset_value(row["birth_year"]),
            death_year=_clean_dataset_value(row["death_year"]),
            primary_profession=_clean_dataset_value(row["primary_profession"]),
            known_for_titles=known_for_titles,
            source_url=f"https://www.imdb.com/name/{row['nconst']}/",
            matched_on="nconst",
            notes="",
        )

    def _lookup_title_matches(
        self,
        connection: sqlite3.Connection,
        raw_value: str,
        mode: LookupMode,
    ) -> list[LookupRow]:
        normalized = _normalize_lookup_text(raw_value)
        if not normalized:
            return [self._build_invalid_row(raw_value, mode, "The title value is blank after normalization.")]

        matches = connection.execute(
            """
            SELECT tconst, primary_title, original_title, title_type, start_year, end_year,
                   CASE
                       WHEN primary_title_norm = ? THEN 'primary_title'
                       ELSE 'original_title'
                   END AS matched_on
            FROM title_basics
            WHERE primary_title_norm = ? OR original_title_norm = ?
            ORDER BY
                CASE WHEN primary_title_norm = ? THEN 0 ELSE 1 END,
                CASE
                    WHEN start_year GLOB '[0-9][0-9][0-9][0-9]' THEN CAST(start_year AS INTEGER)
                    ELSE 0
                END DESC,
                tconst
            LIMIT 25
            """,
            (normalized, normalized, normalized, normalized),
        ).fetchall()
        if not matches:
            return [self._build_not_found_row(raw_value, mode, "No exact normalized title match was found.")]

        total_matches = len(matches)
        status: LookupStatus = "multiple_matches" if total_matches > 1 else "matched"
        rows: list[LookupRow] = []
        for index, row in enumerate(matches, start=1):
            rows.append(
                LookupRow(
                    input_value=raw_value,
                    normalized_input=normalized,
                    requested_mode=mode,
                    resolved_lookup="title_to_id",
                    status=status,
                    match_rank=index,
                    total_matches=total_matches,
                    imdb_id=row["tconst"],
                    entity_kind="title",
                    display_name=_clean_dataset_value(row["primary_title"]),
                    original_title=_clean_dataset_value(row["original_title"]),
                    title_type=_normalize_title_type(row["title_type"]),
                    start_year=_clean_dataset_value(row["start_year"]),
                    end_year=_clean_dataset_value(row["end_year"]),
                    source_url=f"https://www.imdb.com/title/{row['tconst']}/",
                    matched_on=_clean_dataset_value(row["matched_on"]),
                    notes="",
                )
            )
        return rows

    def _lookup_person_matches(
        self,
        connection: sqlite3.Connection,
        raw_value: str,
        mode: LookupMode,
    ) -> list[LookupRow]:
        normalized = _normalize_lookup_text(raw_value)
        if not normalized:
            return [self._build_invalid_row(raw_value, mode, "The person name is blank after normalization.")]

        matches = connection.execute(
            """
            SELECT nconst, primary_name, birth_year, death_year, primary_profession, known_for_titles
            FROM name_basics
            WHERE primary_name_norm = ?
            ORDER BY
                CASE
                    WHEN birth_year GLOB '[0-9][0-9][0-9][0-9]' THEN CAST(birth_year AS INTEGER)
                    ELSE 0
                END ASC,
                nconst
            LIMIT 25
            """,
            (normalized,),
        ).fetchall()
        if not matches:
            return [self._build_not_found_row(raw_value, mode, "No exact normalized person-name match was found.")]

        total_matches = len(matches)
        status: LookupStatus = "multiple_matches" if total_matches > 1 else "matched"
        rows: list[LookupRow] = []
        for index, row in enumerate(matches, start=1):
            rows.append(
                LookupRow(
                    input_value=raw_value,
                    normalized_input=normalized,
                    requested_mode=mode,
                    resolved_lookup="person_to_id",
                    status=status,
                    match_rank=index,
                    total_matches=total_matches,
                    imdb_id=row["nconst"],
                    entity_kind="person",
                    display_name=_clean_dataset_value(row["primary_name"]),
                    birth_year=_clean_dataset_value(row["birth_year"]),
                    death_year=_clean_dataset_value(row["death_year"]),
                    primary_profession=_clean_dataset_value(row["primary_profession"]),
                    known_for_titles=self._resolve_known_for_titles(connection, _clean_dataset_value(row["known_for_titles"])),
                    source_url=f"https://www.imdb.com/name/{row['nconst']}/",
                    matched_on="primary_name",
                    notes="",
                )
            )
        return rows

    def _resolve_known_for_titles(self, connection: sqlite3.Connection, known_for_titles: str) -> str:
        identifiers = [token.strip() for token in known_for_titles.split(",") if token.strip()]
        if not identifiers:
            return ""

        placeholders = ",".join("?" for _ in identifiers)
        rows = connection.execute(
            f"""
            SELECT tconst, primary_title
            FROM title_basics
            WHERE tconst IN ({placeholders})
            """,
            identifiers,
        ).fetchall()
        title_by_id = {row["tconst"]: _clean_dataset_value(row["primary_title"]) for row in rows}
        titles = [title_by_id.get(identifier, identifier) for identifier in identifiers]
        return ", ".join([title for title in titles if title])

    def _build_invalid_row(self, raw_value: str, mode: LookupMode, note: str) -> LookupRow:
        normalized = _normalize_lookup_text(raw_value) or raw_value.strip()
        return LookupRow(
            input_value=raw_value,
            normalized_input=normalized,
            requested_mode=mode,
            resolved_lookup=mode,
            status="invalid",
            notes=note,
        )

    def _build_not_found_row(self, raw_value: str, mode: LookupMode, note: str) -> LookupRow:
        normalized = _normalize_lookup_text(raw_value) or raw_value.strip()
        return LookupRow(
            input_value=raw_value,
            normalized_input=normalized,
            requested_mode=mode,
            resolved_lookup=mode,
            status="not_found",
            notes=note,
        )

    def _ensure_imdb_dataset_index(self) -> Path:
        dataset_dir = self._imdb_dataset_dir()
        db_path = dataset_dir / IMDB_INDEX_FILENAME

        import os
        if os.environ.get("VERCEL") == "1":
            if db_path.exists():
                return db_path
            raise ImdbLookupServiceError(
                "IMDb dataset index is not available on Vercel deployment due to bundle size constraints. "
                "Please run this task in a local environment."
            )

        # Bypass rebuilds and file checks if database exists and has substantial size
        if db_path.exists() and db_path.stat().st_size > 10 * 1024 * 1024:
            return db_path

        dataset_dir.mkdir(parents=True, exist_ok=True)

        title_path = self._ensure_dataset_file(
            settings.imdb_lookup_title_basics_url,
            dataset_dir / IMDB_TITLE_BASICS_FILENAME,
        )
        name_path = self._ensure_dataset_file(
            settings.imdb_lookup_name_basics_url,
            dataset_dir / IMDB_NAME_BASICS_FILENAME,
        )

        with IMDB_INDEX_LOCK:
            if self._index_is_current(db_path, [title_path, name_path]):
                return db_path
            # Reusing existing database of substantial size to prevent slow builds during requests
            if db_path.exists() and db_path.stat().st_size > 10 * 1024 * 1024:
                return db_path
            self._build_index(db_path, title_path, name_path)
            return db_path

    def _imdb_dataset_dir(self) -> Path:
        configured = _clean_dataset_value(settings.imdb_lookup_dataset_dir)
        if configured:
            return Path(configured)
        return BASE_DIR / "data" / "imdb_datasets"

    def _ensure_dataset_file(self, source: str, destination: Path) -> Path:
        cleaned_source = _clean_dataset_value(source)
        if not cleaned_source:
            raise ImdbLookupServiceError("IMDb dataset source is not configured.")

        if _looks_like_url(cleaned_source):
            if destination.exists():
                refresh_age_hours = max(int(settings.imdb_lookup_refresh_hours or 24), 1)
                age_seconds = time.time() - destination.stat().st_mtime
                if age_seconds < refresh_age_hours * 3600:
                    return destination
            self._download_dataset_file(cleaned_source, destination)
            return destination

        source_path = Path(cleaned_source)
        if not source_path.exists():
            raise ImdbLookupServiceError(f"IMDb dataset file was not found: {source_path}")
        if not destination.exists() or source_path.stat().st_mtime > destination.stat().st_mtime or source_path.stat().st_size != destination.stat().st_size:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, destination)
        return destination

    def _download_dataset_file(self, url: str, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = destination.with_suffix(destination.suffix + ".tmp")
        timeout = httpx.Timeout(connect=10.0, read=60.0, write=60.0, pool=10.0)
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


def _rows_status(rows: list[LookupRow]) -> LookupStatus:
    statuses = {row.status for row in rows}
    if "invalid" in statuses:
        return "invalid"
    if "multiple_matches" in statuses:
        return "multiple_matches"
    if "matched" in statuses:
        return "matched"
    return "not_found"


def _rebalance_auto_rows(rows: list[LookupRow]) -> list[LookupRow]:
    successful_rows = [row for row in rows if row.status in {"matched", "multiple_matches"}]
    if not successful_rows:
        return rows

    total_matches = len(successful_rows)
    status: LookupStatus = "multiple_matches" if total_matches > 1 else "matched"
    rebalanced: list[LookupRow] = []
    for index, row in enumerate(successful_rows, start=1):
        rebalanced.append(
            row.model_copy(
                update={
                    "status": status,
                    "match_rank": index,
                    "total_matches": total_matches,
                    "resolved_lookup": row.resolved_lookup if total_matches == 1 else f"auto:{row.resolved_lookup}",
                    "notes": row.notes or ("Auto mode found both title and person candidates." if total_matches > 1 else ""),
                }
            )
        )
    return rebalanced


def _extract_imdb_identifier(raw_value: str) -> str | None:
    cleaned = raw_value.strip()
    if re.fullmatch(r"(tt|nm)\d{7,}", cleaned, flags=re.IGNORECASE):
        return cleaned.lower()
    return None


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
    }
    if normalized in aliases:
        return aliases[normalized]
    return _clean_dataset_value(value)
