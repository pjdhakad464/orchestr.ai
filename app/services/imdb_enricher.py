from __future__ import annotations

import csv
import gzip
import re
import shutil
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock
from typing import Literal, Any
import httpx
from pydantic import BaseModel, Field

from app.config import BASE_DIR, settings
from app.database import get_connection

IMDB_TITLE_BASICS_FILENAME = "title.basics.tsv.gz"
IMDB_NAME_BASICS_FILENAME = "name.basics.tsv.gz"
IMDB_INDEX_FILENAME = "imdb_title_lookup.sqlite3"
IMDB_INDEX_LOCK = Lock()

class IMDbMatch(BaseModel):
    imdb_id: str
    title: str
    original_title: str = ""
    title_type: str = ""
    year: str = ""
    end_year: str = ""
    genres: str = ""
    source: Literal["local_dataset", "tmdb_api", "omdb_api"]
    confidence: float = 1.0
    source_url: str = ""
    notes: str = ""

class IMDbMetadata(BaseModel):
    imdb_id: str
    title: str
    original_title: str = ""
    title_type: str = ""
    year: str = ""
    end_year: str = ""
    runtime_minutes: str = ""
    genres: list[str] = Field(default_factory=list)
    rating: str = ""
    votes: str = ""
    plot: str = ""
    poster_url: str = ""
    directors: str = ""
    writers: str = ""
    cast: str = ""
    networks: str = ""
    status: str = ""
    source: str = ""
    theatrical_release_date: str = ""
    digital_release_date: str = ""
    trailer_url: str = ""
    trailer_release_date: str = ""

class TitleQuery(BaseModel):
    title: str
    year: int | None = None
    content_type: str | None = None  # movie, tv, any

class EnrichmentResult(BaseModel):
    query: TitleQuery
    matches: list[IMDbMatch] = Field(default_factory=list)
    best_match: IMDbMatch | None = None
    metadata: IMDbMetadata | None = None
    status: Literal["matched", "multiple_matches", "not_found", "invalid"] = "not_found"

class MetadataDiscrepancy(BaseModel):
    field: str
    claimed_value: str
    actual_value: str
    severity: Literal["low", "medium", "high"]
    description: str

class PersonMatch(BaseModel):
    imdb_id: str
    name: str
    birth_year: str = ""
    death_year: str = ""
    professions: str = ""
    known_for: str = ""
    source_url: str = ""

class EpisodeData(BaseModel):
    imdb_id: str
    total_seasons: int = 0
    total_episodes: int = 0
    seasons: dict[int, int] = Field(default_factory=dict)

class IMDbEnricher:
    def __init__(self) -> None:
        pass

    def ensure_dataset_index(self) -> Path:
        """Ensures the IMDb local dataset index is built (offline-first)."""
        dataset_dir = self._imdb_dataset_dir()
        db_path = dataset_dir / IMDB_INDEX_FILENAME

        import os
        if os.environ.get("VERCEL") == "1":
            if db_path.exists():
                return db_path
            # On Vercel, local dataset may not exist. Return path but allow API fallback.
            return db_path

        if db_path.exists() and db_path.stat().st_size > 10 * 1024 * 1024:
            return db_path

        dataset_dir.mkdir(parents=True, exist_ok=True)

        # Use app/config settings
        title_url = settings.imdb_title_basics_url or "https://datasets.imdbws.com/title.basics.tsv.gz"
        name_url = settings.imdb_name_basics_url or "https://datasets.imdbws.com/name.basics.tsv.gz"

        title_path = self._ensure_dataset_file(title_url, dataset_dir / IMDB_TITLE_BASICS_FILENAME)
        name_path = self._ensure_dataset_file(name_url, dataset_dir / IMDB_NAME_BASICS_FILENAME)

        with IMDB_INDEX_LOCK:
            if self._index_is_current(db_path, [title_path, name_path]):
                return db_path
            if db_path.exists() and db_path.stat().st_size > 10 * 1024 * 1024:
                return db_path
            self._build_index(db_path, title_path, name_path)
            return db_path

    def _imdb_dataset_dir(self) -> Path:
        configured = _clean_dataset_value(settings.imdb_dataset_dir)
        if configured:
            return Path(configured)
        return BASE_DIR / "data" / "imdb_datasets"

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
            
            # Load TSVs
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

    def _ensure_dataset_file(self, source: str, destination: Path) -> Path:
        cleaned_source = _clean_dataset_value(source)
        if not cleaned_source:
            raise ValueError("IMDb dataset source is not configured.")

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
            raise ValueError(f"IMDb dataset file was not found: {source_path}")
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

    # Core Lookups
    async def match_title(self, title: str, year: int | None = None, content_type: str | None = None) -> list[IMDbMatch]:
        """Matches a title against IMDb local dataset, TMDB, or OMDb."""
        imdb_id = _extract_imdb_identifier(title)
        if imdb_id:
            m = await self.match_by_id(imdb_id)
            return [m] if m else []

        matches: list[IMDbMatch] = []
        
        # 1. Local Lookup
        try:
            db_path = self.ensure_dataset_index()
            if db_path.exists() and db_path.stat().st_size > 10 * 1024 * 1024:
                normalized = _normalize_lookup_text(title)
                with sqlite3.connect(db_path) as conn:
                    conn.row_factory = sqlite3.Row
                    local_rows = conn.execute(
                        """
                        SELECT tconst, primary_title, original_title, title_type, start_year, end_year
                        FROM title_basics
                        WHERE primary_title_norm = ? OR original_title_norm = ?
                        LIMIT 10
                        """,
                        (normalized, normalized)
                    ).fetchall()
                    for r in local_rows:
                        matches.append(IMDbMatch(
                            imdb_id=r["tconst"],
                            title=_clean_dataset_value(r["primary_title"]),
                            original_title=_clean_dataset_value(r["original_title"]),
                            title_type=_normalize_title_type(r["title_type"]),
                            year=_clean_dataset_value(r["start_year"]),
                            end_year=_clean_dataset_value(r["end_year"]),
                            source="local_dataset",
                            source_url=f"https://www.imdb.com/title/{r['tconst']}/"
                        ))
        except Exception:
            pass

        if matches:
            return matches

        # 2. TMDB API Lookup
        async with httpx.AsyncClient(timeout=20.0) as client:
            matches = await self._lookup_tmdb(client, title, year, content_type)
            if matches:
                return matches

            # 3. OMDb API Lookup
            matches = await self._lookup_omdb(client, title, year)
            
        return matches

    async def match_by_id(self, imdb_id: str) -> IMDbMatch | None:
        """Lookup direct match by tconst (IMDb ID) or nconst."""
        try:
            db_path = self.ensure_dataset_index()
            if db_path.exists() and db_path.stat().st_size > 10 * 1024 * 1024:
                with sqlite3.connect(db_path) as conn:
                    conn.row_factory = sqlite3.Row
                    if imdb_id.startswith("tt"):
                        r = conn.execute(
                            "SELECT tconst, primary_title, original_title, title_type, start_year, end_year FROM title_basics WHERE tconst = ?",
                            (imdb_id,)
                        ).fetchone()
                        if r:
                            return IMDbMatch(
                                imdb_id=r["tconst"],
                                title=_clean_dataset_value(r["primary_title"]),
                                original_title=_clean_dataset_value(r["original_title"]),
                                title_type=_normalize_title_type(r["title_type"]),
                                year=_clean_dataset_value(r["start_year"]),
                                end_year=_clean_dataset_value(r["end_year"]),
                                source="local_dataset",
                                source_url=f"https://www.imdb.com/title/{r['tconst']}/"
                            )
        except Exception:
            pass

        # Fallback to API lookup for direct ID
        async with httpx.AsyncClient(timeout=20.0) as client:
            # 1. TMDB Find
            if settings.tmdb_api_key:
                try:
                    url = f"https://api.themoviedb.org/3/find/{imdb_id}"
                    params = {"external_source": "imdb_id", "api_key": settings.tmdb_api_key}
                    resp = await client.get(url, params=params)
                    if resp.status_code == 200:
                        data = resp.json()
                        movies = data.get("movie_results") or []
                        tvs = data.get("tv_results") or []
                        if movies:
                            m = movies[0]
                            return IMDbMatch(
                                imdb_id=imdb_id,
                                title=m.get("title") or m.get("original_title") or "",
                                original_title=m.get("original_title") or "",
                                title_type="movie",
                                year=(m.get("release_date") or "")[:4],
                                source="tmdb_api",
                                source_url=f"https://www.imdb.com/title/{imdb_id}/"
                            )
                        elif tvs:
                            t = tvs[0]
                            return IMDbMatch(
                                imdb_id=imdb_id,
                                title=t.get("name") or t.get("original_name") or "",
                                original_title=t.get("original_name") or "",
                                title_type="tvSeries",
                                year=(t.get("first_air_date") or "")[:4],
                                source="tmdb_api",
                                source_url=f"https://www.imdb.com/title/{imdb_id}/"
                            )
                except Exception:
                    pass

            # 2. OMDb direct lookup
            if settings.omdb_api_key:
                try:
                    url = "https://www.omdbapi.com/"
                    params = {"apikey": settings.omdb_api_key, "i": imdb_id}
                    resp = await client.get(url, params=params)
                    if resp.status_code == 200 and resp.json().get("Response") != "False":
                        data = resp.json()
                        year = data.get("Year") or ""
                        start_year = year.split("–")[0].strip() if "–" in year else year.strip()
                        return IMDbMatch(
                            imdb_id=imdb_id,
                            title=data.get("Title") or "",
                            original_title=data.get("Title") or "",
                            title_type=_normalize_title_type(data.get("Type")),
                            year=start_year,
                            source="omdb_api",
                            source_url=f"https://www.imdb.com/title/{imdb_id}/"
                        )
                except Exception:
                    pass

        return None

    async def search_person(self, name: str) -> list[PersonMatch]:
        """Search a person name against local name basics or TMDB API."""
        matches: list[PersonMatch] = []
        try:
            db_path = self.ensure_dataset_index()
            if db_path.exists() and db_path.stat().st_size > 10 * 1024 * 1024:
                normalized = _normalize_lookup_text(name)
                with sqlite3.connect(db_path) as conn:
                    conn.row_factory = sqlite3.Row
                    rows = conn.execute(
                        "SELECT nconst, primary_name, birth_year, death_year, primary_profession, known_for_titles FROM name_basics WHERE primary_name_norm = ? LIMIT 10",
                        (normalized,)
                    ).fetchall()
                    for r in rows:
                        matches.append(PersonMatch(
                            imdb_id=r["nconst"],
                            name=_clean_dataset_value(r["primary_name"]),
                            birth_year=_clean_dataset_value(r["birth_year"]),
                            death_year=_clean_dataset_value(r["death_year"]),
                            professions=_clean_dataset_value(r["primary_profession"]),
                            known_for=_clean_dataset_value(r["known_for_titles"]),
                            source_url=f"https://www.imdb.com/name/{r['nconst']}/"
                        ))
        except Exception:
            pass

        if matches:
            return matches

        # TMDB Person Search
        if settings.tmdb_api_key:
            async with httpx.AsyncClient(timeout=20.0) as client:
                try:
                    url = "https://api.themoviedb.org/3/search/person"
                    params = {"api_key": settings.tmdb_api_key, "query": name}
                    resp = await client.get(url, params=params)
                    if resp.status_code == 200:
                        for p in (resp.json().get("results") or []):
                            # Try to get IMDb external ID
                            tmdb_id = p.get("id")
                            imdb_id = ""
                            try:
                                ext_resp = await client.get(
                                    f"https://api.themoviedb.org/3/person/{tmdb_id}/external_ids",
                                    params={"api_key": settings.tmdb_api_key}
                                )
                                if ext_resp.status_code == 200:
                                    imdb_id = ext_resp.json().get("imdb_id") or ""
                            except Exception:
                                pass
                            matches.append(PersonMatch(
                                imdb_id=imdb_id,
                                name=p.get("name") or "",
                                professions=p.get("known_for_department") or "",
                                known_for=", ".join([w.get("title") or w.get("name") or "" for w in p.get("known_for") or [] if w.get("title") or w.get("name")]),
                                source_url=f"https://www.imdb.com/name/{imdb_id}/" if imdb_id else ""
                            ))
                except Exception:
                    pass

        return matches

    # Enrichment
    async def enrich_by_id(self, imdb_id: str) -> IMDbMetadata | None:
        """Enriches metadata for an IMDb ID by querying TMDB, OMDb, and caching the result."""
        # Check general cache first
        cache_key = f"imdb_enrich:{imdb_id}"
        cached = self._get_cached_value(cache_key)
        if cached:
            return IMDbMetadata.model_validate_json(cached)

        # 1. Fetch TMDB details
        tmdb_data = await self._fetch_tmdb_details(imdb_id)
        
        # 2. Fetch OMDb details if OMDb key is available
        omdb_data = {}
        if settings.omdb_api_key:
            async with httpx.AsyncClient(timeout=20.0) as client:
                try:
                    resp = await client.get(
                        "https://www.omdbapi.com/",
                        params={"apikey": settings.omdb_api_key, "i": imdb_id, "plot": "full"}
                    )
                    if resp.status_code == 200:
                        omdb_data = resp.json()
                except Exception:
                    pass

        if not tmdb_data and not omdb_data:
            return None

        # Build unified metadata
        genres = []
        if tmdb_data.get("genres"):
            genres = [g["name"] for g in tmdb_data["genres"]]
        elif omdb_data.get("Genre"):
            genres = [g.strip() for g in omdb_data["Genre"].split(",") if g.strip()]

        title = tmdb_data.get("title") or tmdb_data.get("name") or omdb_data.get("Title") or ""
        original_title = tmdb_data.get("original_title") or tmdb_data.get("original_name") or omdb_data.get("Title") or ""
        title_type = "movie" if tmdb_data.get("media_type") == "movie" or omdb_data.get("Type") == "movie" else "tvSeries"
        
        year = ""
        date_val = tmdb_data.get("release_date") or tmdb_data.get("first_air_date") or omdb_data.get("Year")
        if date_val:
            year = date_val[:4]

        runtime = str(tmdb_data.get("runtime") or "")
        if not runtime and tmdb_data.get("episode_run_time"):
            runtime = str(tmdb_data["episode_run_time"][0])
        if not runtime:
            runtime = omdb_data.get("Runtime") or ""

        rating = str(tmdb_data.get("vote_average") or "")
        if not rating:
            rating = omdb_data.get("imdbRating") or ""

        votes = str(tmdb_data.get("vote_count") or "")
        if not votes:
            votes = omdb_data.get("imdbVotes") or ""

        plot = tmdb_data.get("overview") or omdb_data.get("Plot") or ""
        
        poster_path = tmdb_data.get("poster_path")
        poster_url = f"https://image.tmdb.org/t/p/w500{poster_path}" if poster_path else (omdb_data.get("Poster") or "")

        networks = ""
        if tmdb_data.get("networks"):
            networks = ", ".join([n["name"] for n in tmdb_data["networks"]])

        status = tmdb_data.get("status") or ""

        # Parse Theatrical and Digital Release dates
        theatrical_date = tmdb_data.get("release_date") or ""
        digital_date = ""
        
        release_results = tmdb_data.get("release_dates", {}).get("results", [])
        for country_data in release_results:
            country_code = country_data.get("iso_3166_1", "").upper()
            # Focus on US release windows
            if country_code == "US":
                for rd in country_data.get("release_dates", []):
                    rd_type = rd.get("type")
                    rd_val = (rd.get("release_date") or "")[:10]
                    if rd_type == 3: # Theatrical
                        theatrical_date = rd_val
                    elif rd_type == 4: # Digital
                        digital_date = rd_val

        # Parse Trailer details
        trailer_url = ""
        trailer_date = ""
        video_results = tmdb_data.get("videos", {}).get("results", [])
        # Find official YouTube trailer
        for vid in video_results:
            vid_type = vid.get("type")
            vid_site = vid.get("site")
            if vid_type == "Trailer" and vid_site == "YouTube":
                trailer_url = f"https://www.youtube.com/watch?v={vid.get('key')}"
                trailer_date = (vid.get("published_at") or "")[:10]
                if vid.get("official"):
                    break # Prefer official trailer

        meta = IMDbMetadata(
            imdb_id=imdb_id,
            title=title,
            original_title=original_title,
            title_type=title_type,
            year=year,
            end_year=tmdb_data.get("last_air_date", "")[:4] if tmdb_data.get("last_air_date") else "",
            runtime_minutes=runtime,
            genres=genres,
            rating=rating,
            votes=votes,
            plot=plot,
            poster_url=poster_url,
            directors=omdb_data.get("Director") or "",
            writers=omdb_data.get("Writer") or "",
            cast=omdb_data.get("Actors") or "",
            networks=networks,
            status=status,
            source="TMDB/OMDb API Integration",
            theatrical_release_date=theatrical_date,
            digital_release_date=digital_date,
            trailer_url=trailer_url,
            trailer_release_date=trailer_date
        )

        self._set_cached_value(cache_key, meta.model_dump_json(), expires_in_sec=86400 * 7) # Cache for 7 days
        return meta

    async def bulk_enrich(self, queries: list[TitleQuery], progress_cb=None) -> list[EnrichmentResult]:
        """Perform bulk enrichment on a list of TitleQuery objects."""
        results = []
        total = len(queries)
        for idx, q in enumerate(queries):
            matches = await self.match_title(q.title, q.year, q.content_type)
            best_match = matches[0] if matches else None
            metadata = None
            status = "not_found"
            
            if best_match:
                status = "matched" if len(matches) == 1 else "multiple_matches"
                metadata = await self.enrich_by_id(best_match.imdb_id)
                
            results.append(EnrichmentResult(
                query=q,
                matches=matches,
                best_match=best_match,
                metadata=metadata,
                status=status
            ))
            
            if progress_cb:
                progress_cb(idx + 1, total)
                
        return results

    async def verify_metadata(self, imdb_id: str, claimed: dict) -> list[MetadataDiscrepancy]:
        """Verifies claimed metadata against official IMDb/TMDB records and identifies discrepancies."""
        actual = await self.enrich_by_id(imdb_id)
        if not actual:
            return [MetadataDiscrepancy(
                field="imdb_id",
                claimed_value=imdb_id,
                actual_value="Not Found",
                severity="high",
                description="IMDb ID could not be found or enrichment failed."
            )]

        discrepancies = []
        
        # Verify Title
        claimed_title = claimed.get("title") or claimed.get("TV Show/Movie") or ""
        if claimed_title:
            norm_claimed = _normalize_lookup_text(claimed_title)
            norm_actual = _normalize_lookup_text(actual.title)
            norm_actual_orig = _normalize_lookup_text(actual.original_title)
            if norm_claimed != norm_actual and norm_claimed != norm_actual_orig:
                discrepancies.append(MetadataDiscrepancy(
                    field="title",
                    claimed_value=str(claimed_title),
                    actual_value=actual.title,
                    severity="high",
                    description=f"Claimed title '{claimed_title}' does not match official title '{actual.title}'."
                ))

        # Verify Release Year
        claimed_year = claimed.get("year") or claimed.get("released_on") or ""
        if claimed_year:
            # Extract 4 digit year
            claimed_year_str = str(claimed_year)[:4]
            if claimed_year_str.isdigit() and actual.year and claimed_year_str != actual.year:
                discrepancies.append(MetadataDiscrepancy(
                    field="year",
                    claimed_value=str(claimed_year),
                    actual_value=actual.year,
                    severity="medium",
                    description=f"Claimed release year '{claimed_year_str}' differs from official year '{actual.year}'."
                ))

        # Verify Network/Platform
        claimed_network = claimed.get("network") or claimed.get("platform") or claimed.get("distributor") or ""
        if claimed_network and actual.networks:
            claimed_net_norm = _normalize_lookup_text(claimed_network)
            actual_net_norm = _normalize_lookup_text(actual.networks)
            if claimed_net_norm not in actual_net_norm and actual_net_norm not in claimed_net_norm:
                discrepancies.append(MetadataDiscrepancy(
                    field="network",
                    claimed_value=str(claimed_network),
                    actual_value=actual.networks,
                    severity="medium",
                    description=f"Claimed network/platform '{claimed_network}' differs from official networks '{actual.networks}'."
                ))

        # Verify Genres
        claimed_genre = claimed.get("primary_genre") or claimed.get("genre") or ""
        if claimed_genre and actual.genres:
            claimed_genres = [g.strip().casefold() for g in str(claimed_genre).replace("/", ",").split(",") if g.strip()]
            actual_genres = [g.casefold() for g in actual.genres]
            mismatches = [g for g in claimed_genres if g not in actual_genres]
            if len(mismatches) == len(claimed_genres):
                discrepancies.append(MetadataDiscrepancy(
                    field="genres",
                    claimed_value=str(claimed_genre),
                    actual_value=", ".join(actual.genres),
                    severity="low",
                    description=f"None of the claimed genres match the official genres: {', '.join(actual.genres)}."
                ))

        return discrepancies

    async def get_episode_counts(self, imdb_id: str) -> EpisodeData:
        """Fetches total season/episode count information from TMDB."""
        # Try metadata cache
        cache_key = f"imdb_episodes:{imdb_id}"
        cached = self._get_cached_value(cache_key)
        if cached:
            return EpisodeData.model_validate_json(cached)

        ep_data = EpisodeData(imdb_id=imdb_id)
        if not settings.tmdb_api_key:
            return ep_data

        async with httpx.AsyncClient(timeout=20.0) as client:
            try:
                # 1. TMDB Find to get TMDB ID
                url = f"https://api.themoviedb.org/3/find/{imdb_id}"
                params = {"external_source": "imdb_id", "api_key": settings.tmdb_api_key}
                resp = await client.get(url, params=params)
                if resp.status_code == 200:
                    data = resp.json()
                    tv_results = data.get("tv_results") or []
                    if tv_results:
                        tv_id = tv_results[0]["id"]
                        # Fetch full TV details
                        tv_url = f"https://api.themoviedb.org/3/tv/{tv_id}"
                        tv_resp = await client.get(tv_url, params={"api_key": settings.tmdb_api_key})
                        if tv_resp.status_code == 200:
                            tv_details = tv_resp.json()
                            ep_data.total_seasons = tv_details.get("number_of_seasons") or 0
                            ep_data.total_episodes = tv_details.get("number_of_episodes") or 0
                            
                            # Build seasons dictionary
                            seasons_dict = {}
                            for s in tv_details.get("seasons") or []:
                                season_number = s.get("season_number")
                                episode_count = s.get("episode_count")
                                if season_number is not None and episode_count is not None:
                                    # Skip season 0 (specials) usually, but keep if positive
                                    seasons_dict[season_number] = episode_count
                            ep_data.seasons = seasons_dict
            except Exception:
                pass

        self._set_cached_value(cache_key, ep_data.model_dump_json(), expires_in_sec=86400 * 7)
        return ep_data

    # Internal helpers for caches
    def _get_cached_value(self, key: str) -> str | None:
        try:
            with get_connection("metadata_cache.sqlite3") as conn:
                now = datetime.now(timezone.utc).isoformat()
                row = conn.execute(
                    "SELECT cache_value FROM general_cache WHERE cache_key = ? AND expires_at > ?",
                    (key, now)
                ).fetchone()
                if row:
                    return row["cache_value"]
        except Exception:
            pass
        return None

    def _set_cached_value(self, key: str, value: str, expires_in_sec: int) -> None:
        try:
            with get_connection("metadata_cache.sqlite3") as conn:
                expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in_sec)
                conn.execute(
                    "INSERT OR REPLACE INTO general_cache (cache_key, cache_value, expires_at) VALUES (?, ?, ?)",
                    (key, value, expires_at.isoformat())
                )
                conn.commit()
        except Exception:
            pass

    async def _lookup_tmdb(self, client: httpx.AsyncClient, title: str, year: int | None, content_type: str | None) -> list[IMDbMatch]:
        if not settings.tmdb_api_key:
            return []

        matches = []
        try:
            # Query Movies
            if content_type in {None, "movie", "any"}:
                url = "https://api.themoviedb.org/3/search/movie"
                params = {"api_key": settings.tmdb_api_key, "query": title}
                if year:
                    params["primary_release_year"] = str(year)
                resp = await client.get(url, params=params)
                if resp.status_code == 200:
                    for item in (resp.json().get("results") or [])[:5]:
                        tmdb_id = item["id"]
                        imdb_id = await self._fetch_imdb_id_for_tmdb(client, tmdb_id, "movie")
                        if imdb_id:
                            matches.append(IMDbMatch(
                                imdb_id=imdb_id,
                                title=item.get("title") or item.get("original_title") or "",
                                original_title=item.get("original_title") or "",
                                title_type="movie",
                                year=(item.get("release_date") or "")[:4],
                                source="tmdb_api",
                                source_url=f"https://www.imdb.com/title/{imdb_id}/"
                            ))

            # Query TV
            if content_type in {None, "tv", "any"}:
                url = "https://api.themoviedb.org/3/search/tv"
                params = {"api_key": settings.tmdb_api_key, "query": title}
                if year:
                    params["first_air_date_year"] = str(year)
                resp = await client.get(url, params=params)
                if resp.status_code == 200:
                    for item in (resp.json().get("results") or [])[:5]:
                        tmdb_id = item["id"]
                        imdb_id = await self._fetch_imdb_id_for_tmdb(client, tmdb_id, "tv")
                        if imdb_id:
                            matches.append(IMDbMatch(
                                imdb_id=imdb_id,
                                title=item.get("name") or item.get("original_name") or "",
                                original_title=item.get("original_name") or "",
                                title_type="tvSeries",
                                year=(item.get("first_air_date") or "")[:4],
                                source="tmdb_api",
                                source_url=f"https://www.imdb.com/title/{imdb_id}/"
                            ))
        except Exception:
            pass

        return matches

    async def _fetch_imdb_id_for_tmdb(self, client: httpx.AsyncClient, tmdb_id: int, media_type: str) -> str:
        try:
            url = f"https://api.themoviedb.org/3/{media_type}/{tmdb_id}/external_ids"
            resp = await client.get(url, params={"api_key": settings.tmdb_api_key})
            if resp.status_code == 200:
                return resp.json().get("imdb_id") or ""
        except Exception:
            pass
        return ""

    async def _lookup_omdb(self, client: httpx.AsyncClient, title: str, year: int | None) -> list[IMDbMatch]:
        if not settings.omdb_api_key:
            return []

        matches = []
        try:
            url = "https://www.omdbapi.com/"
            params = {"apikey": settings.omdb_api_key, "s": title}
            if year:
                params["y"] = str(year)
            resp = await client.get(url, params=params)
            if resp.status_code == 200 and resp.json().get("Response") != "False":
                for item in (resp.json().get("Search") or [])[:5]:
                    imdb_id = item.get("imdbID") or ""
                    if imdb_id:
                        yr = item.get("Year") or ""
                        start_year = yr.split("–")[0].strip() if "–" in yr else yr.strip()
                        matches.append(IMDbMatch(
                            imdb_id=imdb_id,
                            title=item.get("Title") or "",
                            original_title=item.get("Title") or "",
                            title_type=_normalize_title_type(item.get("Type")),
                            year=start_year,
                            source="omdb_api",
                            source_url=f"https://www.imdb.com/title/{imdb_id}/"
                        ))
        except Exception:
            pass

        return matches

    async def _fetch_tmdb_details(self, imdb_id: str) -> dict:
        if not settings.tmdb_api_key:
            return {}

        async with httpx.AsyncClient(timeout=20.0) as client:
            try:
                # 1. Find by IMDb ID
                url = f"https://api.themoviedb.org/3/find/{imdb_id}"
                params = {"external_source": "imdb_id", "api_key": settings.tmdb_api_key}
                resp = await client.get(url, params=params)
                if resp.status_code == 200:
                    data = resp.json()
                    movies = data.get("movie_results") or []
                    tvs = data.get("tv_results") or []
                    
                    if movies:
                        movie_id = movies[0]["id"]
                        # Fetch full movie details
                        movie_resp = await client.get(
                            f"https://api.themoviedb.org/3/movie/{movie_id}",
                            params={"api_key": settings.tmdb_api_key, "append_to_response": "credits,videos,release_dates"}
                        )
                        if movie_resp.status_code == 200:
                            ret = movie_resp.json()
                            ret["media_type"] = "movie"
                            return ret
                            
                    elif tvs:
                        tv_id = tvs[0]["id"]
                        # Fetch TV details
                        tv_resp = await client.get(
                            f"https://api.themoviedb.org/3/tv/{tv_id}",
                            params={"api_key": settings.tmdb_api_key, "append_to_response": "credits,videos,release_dates"}
                        )
                        if tv_resp.status_code == 200:
                            ret = tv_resp.json()
                            ret["media_type"] = "tv"
                            return ret
            except Exception:
                pass
        return {}

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

def _extract_imdb_identifier(raw_value: str) -> str | None:
    cleaned = raw_value.strip()
    if re.fullmatch(r"(tt|nm)\d{7,}", cleaned, flags=re.IGNORECASE):
        return cleaned.lower()
    return None

def _normalize_title_type(value: object) -> str:
    normalized = _normalize_lookup_text(value).replace(" ", "")
    aliases = {
        "movie": "movie",
        "series": "tvSeries",
        "tvseries": "tvSeries",
        "episode": "tvEpisode",
        "tvepisode": "tvEpisode",
        "tvminiseries": "tvMiniSeries",
        "tvspecial": "tvSpecial",
        "tvmovie": "tvMovie",
    }
    if normalized in aliases:
        return aliases[normalized]
    return _clean_dataset_value(value)
