import re
import html
import time
import sqlite3
import asyncio
from pathlib import Path
from urllib.parse import quote
import httpx
from pydantic import BaseModel, Field
from datetime import datetime

# Database path (synchronized via sync_db.py)
DB_PATH = Path("data/wikipedia_cache/wikipedia_cache.sqlite3")

class BillboardArtistItem(BaseModel):
    rank: int
    name: str
    slug: str
    gender: str = ""
    profession: str = ""
    imdb_id: str = ""
    wikipedia_url: str = ""

class BillboardArtistSnapshot(BaseModel):
    generated_at: datetime
    export_id: str | None = None
    items: list[BillboardArtistItem] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

def ensure_cache_table():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS billboard_artist_cache (
                name TEXT PRIMARY KEY,
                slug TEXT,
                gender TEXT,
                profession TEXT,
                imdb_id TEXT,
                wikipedia_url TEXT,
                resolved_at INTEGER
            )
        """)
        conn.commit()

def get_cached_artist(name: str) -> dict | None:
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM billboard_artist_cache WHERE LOWER(name) = ?", (name.lower(),)).fetchone()
            return dict(row) if row else None
    except Exception:
        return None

def cache_artist(name: str, slug: str, gender: str, profession: str, imdb_id: str, wikipedia_url: str):
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO billboard_artist_cache (name, slug, gender, profession, imdb_id, wikipedia_url, resolved_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (name, slug, gender, profession, imdb_id, wikipedia_url, int(time.time())))
            conn.commit()
    except Exception as e:
        print(f"Failed to cache artist {name}: {e}")

class BillboardService:
    CHART_URL = "https://www.billboard.com/charts/artist-100/"
    WIKIDATA_API = "https://www.wikidata.org/w/api.php"
    
    def __init__(self, request_timeout_seconds: int = 15):
        self.timeout = request_timeout_seconds
        self.headers = {
            "User-Agent": "OfficialProfileFinder/0.1 (test@example.com) Python/httpx"
        }
        ensure_cache_table()

    async def fetch_billboard_artists(self) -> list[tuple[str, str]]:
        """Scrapes the Billboard Artist 100 page and returns a list of (name, slug) tuples."""
        async with httpx.AsyncClient(headers=self.headers, timeout=self.timeout, follow_redirects=True) as client:
            r = await client.get(self.CHART_URL)
            if r.status_code != 200:
                raise RuntimeError(f"Billboard returned status code {r.status_code}")
            
            html_content = r.text
            # Regex to match: href="https://www.billboard.com/artist/taylor-swift/" or similar
            pattern = re.compile(
                r'href="https://www\.billboard\.com/artist/(?P<slug>[^/"]+)/?"[^>]*>\s*(?P<name>[^\n\r\t<>]+)\s*</a>', 
                re.IGNORECASE
            )
            matches = pattern.findall(html_content)
            
            seen = set()
            artists = []
            for slug, name in matches:
                unescaped_name = html.unescape(name).strip()
                if unescaped_name and unescaped_name.lower() not in seen:
                    seen.add(unescaped_name.lower())
                    artists.append((unescaped_name, slug))
            return artists

    async def resolve_artist_details(self, name: str, slug: str) -> dict:
        """Resolves gender, profession, IMDb ID and Wikipedia URL for an artist name, using cache when available."""
        cached = get_cached_artist(name)
        if cached:
            return cached

        # Resolve from Wikidata
        result = {
            "name": name,
            "slug": slug,
            "gender": "Unknown",
            "profession": "Unknown",
            "imdb_id": "",
            "wikipedia_url": ""
        }

        try:
            async with httpx.AsyncClient(headers=self.headers, timeout=self.timeout) as client:
                # 1. Search Wikidata
                search_params = {
                    "action": "wbsearchentities",
                    "format": "json",
                    "language": "en",
                    "type": "item",
                    "limit": 3,
                    "search": name
                }
                r_search = await client.get(self.WIKIDATA_API, params=search_params)
                if r_search.status_code != 200:
                    return result
                
                search_data = r_search.json()
                search_hits = search_data.get("search", [])
                if not search_hits:
                    cache_artist(name, slug, result["gender"], result["profession"], result["imdb_id"], result["wikipedia_url"])
                    return result
                
                # Take top result
                qid = search_hits[0].get("id")
                
                # 2. Get claims and sitelinks
                entity_params = {
                    "action": "wbgetentities",
                    "format": "json",
                    "ids": qid,
                    "props": "claims|sitelinks",
                    "languages": "en"
                }
                r_entity = await client.get(self.WIKIDATA_API, params=entity_params)
                if r_entity.status_code != 200:
                    return result
                
                entity_data = r_entity.json()
                entity = entity_data.get("entities", {}).get(qid, {})
                
                # Sitelinks
                enwiki_title = entity.get("sitelinks", {}).get("enwiki", {}).get("title")
                if enwiki_title:
                    result["wikipedia_url"] = f"https://en.wikipedia.org/wiki/{quote(enwiki_title.replace(' ', '_'))}"
                
                claims = entity.get("claims", {})
                
                # IMDb ID (P345)
                imdb_claims = claims.get("P345", [])
                if imdb_claims:
                    result["imdb_id"] = imdb_claims[0].get("mainsnak", {}).get("datavalue", {}).get("value", "")
                
                # Gender QID (P21)
                gender_claims = claims.get("P21", [])
                gender_qid = ""
                if gender_claims:
                    gender_qid = gender_claims[0].get("mainsnak", {}).get("datavalue", {}).get("value", {}).get("id", "")
                
                # Profession QIDs (P106)
                profession_claims = claims.get("P106", [])
                prof_qids = []
                for claim in profession_claims[:3]:
                    pqid = claim.get("mainsnak", {}).get("datavalue", {}).get("value", {}).get("id", "")
                    if pqid:
                        prof_qids.append(pqid)
                
                # Resolve labels
                qids_to_resolve = [qid for qid in ([gender_qid] + prof_qids) if qid]
                if qids_to_resolve:
                    resolve_params = {
                        "action": "wbgetentities",
                        "format": "json",
                        "ids": "|".join(qids_to_resolve),
                        "props": "labels",
                        "languages": "en"
                    }
                    r_resolve = await client.get(self.WIKIDATA_API, params=resolve_params)
                    if r_resolve.status_code == 200:
                        resolved_entities = r_resolve.json().get("entities", {})
                        
                        if gender_qid:
                            result["gender"] = resolved_entities.get(gender_qid, {}).get("labels", {}).get("en", {}).get("value", "Unknown")
                        
                        prof_labels = []
                        for pqid in prof_qids:
                            pl = resolved_entities.get(pqid, {}).get("labels", {}).get("en", {}).get("value", "")
                            if pl:
                                prof_labels.append(pl)
                        if prof_labels:
                            result["profession"] = ", ".join(prof_labels)
            
            # Cache the result
            cache_artist(name, slug, result["gender"], result["profession"], result["imdb_id"], result["wikipedia_url"])
        except Exception as e:
            print(f"Error resolving details for {name}: {e}")
            
        return result

    async def get_top_artists_snapshot(self) -> BillboardArtistSnapshot:
        """Fetch Billboard Artist 100 and resolve detail profiles for all artists in parallel."""
        raw_artists = await self.fetch_billboard_artists()
        
        # Limit concurrency using semaphore to avoid overwhelming Wikidata
        semaphore = asyncio.Semaphore(10)
        
        async def resolve_with_sem(name, slug):
            async with semaphore:
                return await self.resolve_artist_details(name, slug)
        
        tasks = [resolve_with_sem(name, slug) for name, slug in raw_artists]
        resolved_results = await asyncio.gather(*tasks)
        
        items = []
        for idx, res in enumerate(resolved_results, start=1):
            items.append(
                BillboardArtistItem(
                    rank=idx,
                    name=res["name"],
                    slug=res["slug"],
                    gender=res["gender"],
                    profession=res["profession"],
                    imdb_id=res["imdb_id"],
                    wikipedia_url=res["wikipedia_url"]
                )
            )
        
        return BillboardArtistSnapshot(
            generated_at=datetime.now().astimezone(),
            items=items,
            notes=[
                "Source: Billboard Artist 100 Chart.",
                "Artist gender, professions, IMDb ID, and Wikipedia URLs resolved dynamically via Wikidata API."
            ]
        )
