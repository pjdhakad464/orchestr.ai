from __future__ import annotations

import asyncio
import csv
import re
import sqlite3
from urllib.parse import quote, urlparse
from pathlib import Path
import httpx
from app.config import settings
from app.cache import TTLCache

DB_PATH = Path("data/taxonomy_cache.sqlite3")

def _init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS taxonomy_cache (
            title TEXT,
            instagram TEXT,
            category TEXT,
            sub_category TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (title, instagram)
        )
    """)
    conn.commit()
    conn.close()

def _get_cached_taxonomy(title: str, instagram: str) -> dict[str, str] | None:
    try:
        _init_db()
        conn = sqlite3.connect(str(DB_PATH))
        cursor = conn.cursor()
        cursor.execute(
            "SELECT category, sub_category FROM taxonomy_cache WHERE LOWER(title) = ? AND LOWER(instagram) = ?",
            (title.strip().lower(), instagram.strip().lower())
        )
        row = cursor.fetchone()
        conn.close()
        if row:
            return {"category": row[0], "sub_category": row[1]}
    except Exception:
        pass
    return None

def _save_cached_taxonomy(title: str, instagram: str, category: str, sub_category: str) -> None:
    try:
        _init_db()
        conn = sqlite3.connect(str(DB_PATH))
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO taxonomy_cache (title, instagram, category, sub_category) VALUES (?, ?, ?, ?)",
            (title.strip(), instagram.strip(), category.strip(), sub_category.strip())
        )
        conn.commit()
        conn.close()
    except Exception:
        pass

def _normalize_ig_handle(ig_value: str) -> str:
    if not ig_value:
        return ""
    val = ig_value.strip()
    if "instagram.com" in val:
        parsed = urlparse(val)
        path = parsed.path.strip("/")
        segments = [s for s in path.split("/") if s]
        if segments:
            return segments[0]
    return val.lstrip("@")

def _extract_instagram_metadata(html: str) -> dict[str, str]:
    if not html:
        return {}
    meta = {}
    
    category_match = re.search(r'"category_name"\s*:\s*"([^"]+)"', html, re.IGNORECASE)
    if category_match:
        meta["category_name"] = category_match.group(1)
        
    business_match = re.search(r'"business_category_name"\s*:\s*"([^"]+)"', html, re.IGNORECASE)
    if business_match:
        meta["business_category_name"] = business_match.group(1)
        
    bio_match = re.search(r'"biography"\s*:\s*"([^"]+)"', html, re.IGNORECASE)
    if bio_match:
        try:
            bio = bio_match.group(1).encode('utf-8').decode('unicode-escape')
        except Exception:
            bio = bio_match.group(1)
        meta["biography"] = bio
        
    desc_match = re.search(r'<meta\s+property="og:description"\s+content="([^"]+)"', html, re.IGNORECASE)
    if desc_match:
        meta["description"] = desc_match.group(1)
    else:
        desc_match = re.search(r'<meta\s+name="description"\s+content="([^"]+)"', html, re.IGNORECASE)
        if desc_match:
            meta["description"] = desc_match.group(1)
            
    return meta

def _map_instagram_metadata(handle: str, meta: dict) -> dict[str, str] | None:
    category_name = meta.get("category_name", "").strip()
    business_category = meta.get("business_category_name", "").strip()
    bio = meta.get("biography", "").strip()
    desc = meta.get("description", "").strip()
    
    search_text = f"{category_name} | {business_category} | {bio} | {desc}".lower()
    category = ""
    sub_categories = []
    
    is_talent = False
    talent_type = "Internet Personality"
    talent_subtype = "Internet Personality - Influencer"
    
    if any(k in search_text for k in ["actor", "actress", "model", "musician", "singer", "rapper", "dj", "band", "artist", "athlete", "player", "coach", "chef", "public figure", "blogger", "creator", "comedian", "dancer", "journalist"]):
        is_talent = True
        
    if is_talent:
        category = "Talent"
        gender = "UNVERIFIED"
        if re.search(r"\b(she/her|she|her|hers|woman|female|actress)\b", search_text):
            gender = "Woman"
        elif re.search(r"\b(he/him|he|him|his|man|male|actor)\b", search_text):
            gender = "Man"
        sub_categories.append(f"Gender - {gender}")
        
        if any(k in search_text for k in ["actor", "actress"]):
            talent_type = "Actress" if gender == "Woman" else "Actor"
            talent_subtype = "Actress" if gender == "Woman" else "Actor"
        elif any(k in search_text for k in ["musician", "singer", "rapper", "dj", "band"]):
            talent_type = "Musician"
            if "rapper" in search_text:
                talent_subtype = "Talent Subtype - Musician - Rapper"
            elif "dj" in search_text:
                talent_subtype = "Talent Subtype - Musician - DJ / Producer"
            elif "band" in search_text or "group" in search_text:
                talent_subtype = "Talent Subtype - Musician - Band"
            else:
                talent_subtype = "Talent Subtype - Musician - Singer"
        elif any(k in search_text for k in ["athlete", "player", "coach", "footballer", "soccer", "basketball"]):
            talent_type = "Athlete"
            sport = "Other"
            if "soccer" in search_text or "footballer" in search_text:
                sport = "Soccer"
            elif "basketball" in search_text or "nba" in search_text:
                sport = "Basketball"
            elif "football" in search_text or "nfl" in search_text:
                sport = "Football"
            elif "baseball" in search_text or "mlb" in search_text:
                sport = "Baseball"
            elif "cricket" in search_text or "ipl" in search_text:
                sport = "Cricket"
            
            if "coach" in search_text:
                talent_subtype = "Talent Subtype - Athlete - Coach"
            else:
                talent_subtype = f"Talent Subtype - Athlete - {sport}"
        elif "chef" in search_text or "cook" in search_text:
            talent_type = "Chef"
            talent_subtype = "Talent Subtype - Internet Personality - Content Creator"
        elif "comedian" in search_text or "comedy" in search_text:
            talent_type = "Comedian"
            talent_subtype = "Talent Subtype - Internet Personality - Content Creator"
        elif "journalist" in search_text or "reporter" in search_text:
            talent_type = "Journalist"
            talent_subtype = "Talent Subtype - Media Personality - TV"
        elif "model" in search_text:
            talent_type = "Model"
            talent_subtype = "Talent Subtype - Internet Personality - Content Creator"
        
        if not talent_subtype.startswith("Talent Subtype -"):
            talent_subtype = f"Talent Subtype - {talent_subtype}"
        sub_categories.append(talent_subtype)
        sub_categories.append(f"Talent Type - {talent_type}")
        
        return {"category": category, "sub_category": "\n".join(sub_categories)}

    if any(k in search_text for k in ["restaurant", "cafe", "coffee", "baking", "bakery", "casual dining", "fast food"]):
        category = "Restaurants"
        rest_cat = "Varied Menu"
        rest_type = "Casual Dining"
        if "fast food" in search_text or "quick service" in search_text:
            rest_type = "Quick Service"
        elif "coffee" in search_text or "cafe" in search_text:
            rest_cat = "Coffee"
            rest_type = "Fast Casual"
        sub_categories.append(f"Restaurant Category - {rest_cat}")
        sub_categories.append(f"Restaurant Type - {rest_type}")
        return {"category": category, "sub_category": "\n".join(sub_categories)}

    if any(k in search_text for k in ["clothing", "apparel", "fashion", "jewelry", "bag", "shoe", "watches", "handbag"]):
        category = "Fashion"
        prod_cat = "Women's Apparel"
        if "shoe" in search_text or "footwear" in search_text:
            prod_cat = "Shoes"
        elif "jewelry" in search_text or "accessory" in search_text:
            prod_cat = "Jewelry & Accessories"
        elif "bag" in search_text or "handbag" in search_text:
            prod_cat = "Handbags"
        elif "watch" in search_text:
            prod_cat = "Watches"
        elif "men" in search_text:
            prod_cat = "Men's Apparel"
        sub_categories.append(prod_cat)
        return {"category": category, "sub_category": "\n".join(sub_categories)}

    if any(k in search_text for k in ["beverage", "drink", "brewery", "winery", "beer", "wine", "spirits", "whiskey", "soda", "coke"]):
        if "beer" in search_text or "brewery" in search_text:
            category = "Breweries"
            sub_categories.append("Beverage Type - Beer")
        else:
            category = "Beverages"
            bev_type = "Soft Drinks"
            if "wine" in search_text:
                bev_type = "Wine"
            elif "spirit" in search_text or "whiskey" in search_text:
                bev_type = "Spirits"
            sub_categories.append(f"Beverage Type - {bev_type}")
        return {"category": category, "sub_category": "\n".join(sub_categories)}

    if any(k in search_text for k in ["cosmetics", "beauty", "makeup", "skincare", "hair", "fragrance"]):
        category = "Health & Beauty"
        beauty_type = "Makeup"
        if "skincare" in search_text or "skin" in search_text:
            beauty_type = "Skincare"
        elif "hair" in search_text:
            beauty_type = "Hair"
        elif "fragrance" in search_text or "perfume" in search_text:
            beauty_type = "Fragrance"
        sub_categories.append(f"Beauty Type - {beauty_type}")
        return {"category": category, "sub_category": "\n".join(sub_categories)}

    if "tv show" in search_text or "television series" in search_text or "tv series" in search_text:
        category = "TV Shows"
        sub_categories.append("Program Type - Series")
        return {"category": category, "sub_category": "\n".join(sub_categories)}
    if "movie" in search_text or "film" in search_text:
        category = "Movies"
        sub_categories.append("Studio - Independent")
        return {"category": category, "sub_category": "\n".join(sub_categories)}
    if "tv channel" in search_text or "tv network" in search_text:
        category = "TV Network"
        sub_categories.append("Region - NA")
        sub_categories.append("Location: Country - United States")
        return {"category": category, "sub_category": "\n".join(sub_categories)}

    if any(k in search_text for k in ["magazine", "publisher", "newspaper", "book", "news"]):
        category = "Publishers"
        pub_type = "Publishing Company"
        if "newspaper" in search_text:
            pub_type = "Newspaper"
        elif "magazine" in search_text:
            pub_type = "Magazine"
        sub_categories.append(f"Publication Type - {pub_type}")
        return {"category": category, "sub_category": "\n".join(sub_categories)}

    if "video game" in search_text or "gaming" in search_text:
        if "publisher" in search_text or "studio" in search_text or "developer" in search_text:
            category = "Video Game Publishers"
        else:
            category = "Video Game"
        return {"category": category, "sub_category": ""}

    if "sports team" in search_text or "sports club" in search_text or "football club" in search_text or "soccer club" in search_text:
        category = "Sports Franchise"
        sub_categories.append("Sports Type - Soccer")
        return {"category": category, "sub_category": "\n".join(sub_categories)}

    if any(k in search_text for k in ["hotel", "resort", "airline", "travel", "cruise"]):
        category = "Travel"
        travel_type = "Hotels"
        if "airline" in search_text:
            travel_type = "Airlines"
        elif "cruise" in search_text:
            travel_type = "Cruise Lines"
        sub_categories.append(f"Travel Type - {travel_type}")
        return {"category": category, "sub_category": "\n".join(sub_categories)}

    if "electronics" in search_text or "smartphone" in search_text or "gadget" in search_text:
        category = "Consumer Electronics"
        return {"category": category, "sub_category": ""}

    if "retail" in search_text or "store" in search_text or "shop" in search_text:
        category = "Retail"
        sub_categories.append("Retail Type - Retailer")
        return {"category": category, "sub_category": "\n".join(sub_categories)}

    return None


class TaxonomyClassifier:
    def __init__(self, cache: TTLCache) -> None:
        self.cache = cache
        self.contact = settings.wikimedia_contact or "ramesh@listenfirstmedia.com"
        self.headers = {
            "User-Agent": f"OfficialProfileFinderBot/0.1 ({self.contact})",
            "Api-User-Agent": self.contact
        }
        self.reference_map = self._load_reference_taxonomy()

    def _load_reference_taxonomy(self) -> dict[str, list[str]]:
        ref_path = Path("data/title_taxonomy_reference.csv")
        mapping = {}
        if ref_path.exists():
            try:
                with ref_path.open("r", encoding="utf-8-sig") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        cat = row.get("title_category", "").strip()
                        sub = row.get("title_sub_category", "").strip()
                        if cat and sub:
                            mapping.setdefault(cat, []).append(sub)
            except Exception as e:
                print(f"Failed to load title_taxonomy_reference.csv: {e}")
        return mapping

    def align_to_taxonomy(self, category: str, sub_categories: list[str]) -> tuple[str, str]:
        if not self.reference_map:
            return category, "\n".join(sub_categories)
            
        matched_cat = "Other"
        for ref_cat in self.reference_map:
            if ref_cat.lower() == category.lower():
                matched_cat = ref_cat
                break
        
        if matched_cat == "Other":
            for ref_cat in self.reference_map:
                if category.lower() in ref_cat.lower() or ref_cat.lower() in category.lower():
                    matched_cat = ref_cat
                    break
        
        allowed_subs = self.reference_map.get(matched_cat, [])
        if not allowed_subs:
            return matched_cat, "\n".join(sub_categories)
            
        aligned_subs = []
        for sub in sub_categories:
            sub = sub.strip()
            if not sub:
                continue
            found = False
            for allowed in allowed_subs:
                if allowed.lower() == sub.lower():
                    aligned_subs.append(allowed)
                    found = True
                    break
            if not found:
                for allowed in allowed_subs:
                    if sub.lower() in allowed.lower() or allowed.lower() in sub.lower():
                        aligned_subs.append(allowed)
                        found = True
                        break
                        
        seen = set()
        deduped_subs = []
        for s in aligned_subs:
            if s not in seen:
                seen.add(s)
                deduped_subs.append(s)
                
        return matched_cat, "\n".join(deduped_subs)

    async def classify(self, title: str, instagram: str | None = None) -> dict[str, str]:
        title = title.strip()
        instagram_val = (instagram or "").strip()
        if not title:
            return {"category": "UNVERIFIED", "sub_category": "Title name cannot be blank."}

        # Check in-memory Cache first
        cache_key = f"classif:{title.lower()}:{instagram_val.lower()}"
        cached = self.cache.get(cache_key)
        if cached:
            return cached

        # Check persistent SQLite cache next
        persistent_cached = _get_cached_taxonomy(title, instagram_val)
        if persistent_cached:
            self.cache.set(cache_key, persistent_cached)
            return persistent_cached

        # Step 1: Query Instagram if handle is provided
        ig_handle = _normalize_ig_handle(instagram_val)
        instagram_meta = None
        if ig_handle:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept-Language": "en-US,en;q=0.9",
            }
            async with httpx.AsyncClient(timeout=8.0, follow_redirects=True, headers=headers) as client:
                try:
                    res = await client.get(f"https://www.instagram.com/{ig_handle}/")
                    if res.status_code == 200:
                        instagram_meta = _extract_instagram_metadata(res.text)
                except Exception:
                    pass

        # Step 2: Try to resolve using Instagram metadata directly if we got strong category indicators
        if instagram_meta:
            ig_result = _map_instagram_metadata(ig_handle, instagram_meta)
            if ig_result and ig_result["category"]:
                aligned_cat, aligned_sub = self.align_to_taxonomy(ig_result["category"], ig_result["sub_category"].split("\n"))
                final_result = {"category": aligned_cat, "sub_category": aligned_sub}
                _save_cached_taxonomy(title, instagram_val, aligned_cat, aligned_sub)
                self.cache.set(cache_key, final_result)
                return final_result

        # Step 3: Fall back or verify using Wikipedia/Wikidata
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True, headers=self.headers) as client:
            try:
                search_res = await client.get(
                    "https://en.wikipedia.org/w/api.php",
                    params={
                        "action": "query",
                        "list": "search",
                        "srsearch": title,
                        "format": "json",
                        "formatversion": "2"
                    }
                )
                search_res.raise_for_status()
                search_data = search_res.json()
                search_hits = search_data.get("query", {}).get("search", [])
                best_match = search_hits[0]["title"] if search_hits else title
            except Exception:
                best_match = title

            try:
                page_res = await client.get(
                    "https://en.wikipedia.org/w/api.php",
                    params={
                        "action": "query",
                        "titles": best_match,
                        "redirects": "1",
                        "prop": "categories|extracts|pageprops",
                        "exintro": "1",
                        "explaintext": "1",
                        "cllimit": 50,
                        "format": "json",
                        "formatversion": "2"
                    }
                )
                page_res.raise_for_status()
                page_data = page_res.json()
                pages = page_data.get("query", {}).get("pages", [])
                
                if pages and pages[0].get("missing") is not True:
                    page = pages[0]
                    canonical_title = page.get("title", best_match)
                    extract = page.get("extract", "").lower()
                    categories = [c.get("title", "") for c in page.get("categories", [])]
                    wikidata_id = page.get("pageprops", {}).get("wikibase_item")
                else:
                    canonical_title = best_match
                    extract = ""
                    categories = []
                    wikidata_id = None
            except Exception:
                canonical_title = best_match
                extract = ""
                categories = []
                wikidata_id = None

            claims = {}
            if wikidata_id:
                try:
                    wd_res = await client.get(
                        "https://www.wikidata.org/w/api.php",
                        params={
                            "action": "wbgetentities",
                            "ids": wikidata_id,
                            "props": "claims",
                            "format": "json",
                            "formatversion": "2"
                        }
                    )
                    wd_res.raise_for_status()
                    wd_data = wd_res.json()
                    entity = wd_data.get("entities", {}).get(wikidata_id, {})
                    claims = entity.get("claims", {})
                except Exception:
                    claims = {}

            # Step 4: Run Heuristics to Classify
            result = self._run_classification_heuristics(canonical_title, extract, categories, claims, instagram_meta)
            
            # Align to taxonomy reference map
            aligned_cat, aligned_sub = self.align_to_taxonomy(result["category"], result["sub_category"].split("\n"))
            final_result = {"category": aligned_cat, "sub_category": aligned_sub}
            
            _save_cached_taxonomy(title, instagram_val, aligned_cat, aligned_sub)
            self.cache.set(cache_key, final_result)
            return final_result

    def _get_claim_qids(self, claims: dict, prop: str) -> list[str]:
        qids = []
        prop_claims = claims.get(prop, [])
        for claim in prop_claims:
            mainsnak = claim.get("mainsnak", {})
            datavalue = mainsnak.get("datavalue", {})
            value = datavalue.get("value", {})
            if isinstance(value, dict) and value.get("entity-type") == "item":
                qids.append(value.get("id"))
        return qids

    def _run_classification_heuristics(
        self,
        title: str,
        extract: str,
        categories: list[str],
        claims: dict,
        instagram_meta: dict | None = None
    ) -> dict[str, str]:
        cats_str = " | ".join(categories).lower()
        category = ""
        sub_category_lines = []

        p31_qids = self._get_claim_qids(claims, "P31")
        p106_qids = self._get_claim_qids(claims, "P106")
        p641_qids = self._get_claim_qids(claims, "P641")

        is_human = "Q5" in p31_qids or "births" in cats_str or "deaths" in cats_str or "people" in cats_str or "Category:Living people" in categories
        
        if is_human:
            category = "Talent"
            gender = "UNVERIFIED"
            p21_qids = self._get_claim_qids(claims, "P21")
            if "Q6581072" in p21_qids:
                gender = "Woman"
            elif "Q6581097" in p21_qids:
                gender = "Man"
            elif any(qid in p21_qids for qid in ["Q189125", "Q1052281", "Q1090279"]):
                gender = "Non-Binary"
            else:
                if re.search(r"\b(she|her|hers|actress|woman|female)\b", extract):
                    gender = "Woman"
                elif re.search(r"\b(he|him|his|actor|man|male)\b", extract):
                    gender = "Man"
                elif "women" in cats_str or "actresses" in cats_str:
                    gender = "Woman"
                elif "men" in cats_str:
                    gender = "Man"

            sub_category_lines.append(f"Gender - {gender}")
            subtype = "Internet Personality - Content Creator"
            talent_type = "Internet Personality"

            is_athlete = any(q in p106_qids for q in ["Q3665646", "Q11116515", "Q937857", "Q1165955", "Q10833314", "Q205312", "Q11774882", "Q378622", "Q53725", "Q206653", "Q11571", "Q1747444", "Q13382404"])
            if not is_athlete:
                is_athlete = "player" in extract or "athlete" in cats_str or "footballer" in cats_str or "cricketer" in cats_str or "olympic" in cats_str
            
            if is_athlete:
                talent_type = "Athlete"
                sport = "Other"
                if "Q3962" in p641_qids or "basketball" in extract or "basketball" in cats_str or "nba" in extract or "nba" in cats_str:
                    sport = "Basketball"
                elif "Q4113337" in p641_qids or "american football" in extract or "american football" in cats_str or "nfl" in extract or "nfl" in cats_str:
                    sport = "Football"
                elif "Q413" in p641_qids or "soccer" in extract or "soccer" in cats_str or "association football" in extract or "association football" in cats_str or "footballer" in extract or "footballer" in cats_str:
                    sport = "Soccer"
                elif "Q1165955" in p641_qids or "baseball" in extract or "baseball" in cats_str:
                    sport = "Baseball"
                elif "Q53725" in p641_qids or "cricket" in extract or "cricket" in cats_str:
                    sport = "Cricket"
                elif "Q1914" in p641_qids or "tennis" in extract or "tennis" in cats_str:
                    sport = "Tennis"
                elif "Q205312" in p641_qids or "golf" in extract or "golf" in cats_str:
                    sport = "Golf"
                
                if "coach" in extract or "coach" in cats_str or "manager" in extract:
                    subtype = "Athlete - Coach"
                else:
                    subtype = f"Athlete - {sport}"
            elif any(q in p106_qids for q in ["Q2252262", "Q177220", "Q488205", "Q639669", "Q130857", "Q183944", "Q36834"]) or "musician" in cats_str or "singer" in cats_str or "rapper" in cats_str or "composer" in cats_str:
                talent_type = "Musician"
                if "rapper" in extract or "rapper" in cats_str:
                    subtype = "Musician - Rapper"
                elif "singer" in extract or "singer" in cats_str or "vocalist" in extract:
                    subtype = "Musician - Singer"
                elif "dj" in extract or "dj" in cats_str:
                    subtype = "Musician - DJ / Producer"
                else:
                    subtype = "Musician - Singer"
            elif any(q in p106_qids for q in ["Q33999", "Q2526255"]) or "actor" in cats_str or "actresses" in cats_str or "actor" in extract or "actress" in extract:
                if gender == "Woman":
                    talent_type = "Actress"
                    subtype = "Actress"
                else:
                    talent_type = "Actor"
                    subtype = "Actor"
            elif any(q in p106_qids for q in ["Q112239616", "Q9062770", "Q11504930"]) or "youtubers" in cats_str or "tiktoker" in cats_str or "streamer" in cats_str:
                talent_type = "Internet Personality"
                if "streamer" in extract or "streamer" in cats_str:
                    subtype = "Internet Personality - Streamer"
                elif "youtuber" in extract or "youtuber" in cats_str:
                    subtype = "Internet Personality - Content Creator"
                else:
                    subtype = "Internet Personality - Influencer"
            elif any(q in p106_qids for q in ["Q1930187", "Q482980", "Q214986", "Q16223067"]) or "journalists" in cats_str or "news anchors" in cats_str:
                talent_type = "Journalist"
                subtype = "Media Personality - TV"

            sub_category_lines.append(f"Talent Subtype - {subtype}")
            sub_category_lines.append(f"Talent Type - {talent_type}")

        else:
            is_movie = any(q in p31_qids for q in ["Q11424", "Q24869", "Q201658"]) or "films" in cats_str or "movie" in extract or (len(title) > 6 and "film" in title.lower())
            is_tv_show = any(q in p31_qids for q in ["Q5398119", "Q15416"]) or "television series" in cats_str or "television programs" in cats_str or "television series" in extract or "television show" in extract
            is_game = "Q7889" in p31_qids or "video games" in cats_str or "video game" in extract
            is_game_publisher = any(q in p31_qids for q in ["Q1137107", "Q210167"]) or "video game publishers" in cats_str or "video game developers" in cats_str
            is_tv_network = any(q in p31_qids for q in ["Q229397", "Q2001305"]) or "television networks" in cats_str or "television channels" in cats_str or "television network" in extract
            is_sports_team = any(q in p31_qids for q in ["Q133936", "Q476028", "Q18420188"]) or "sports teams" in cats_str or "football clubs" in cats_str or "sports team" in extract
            is_sports_league = any(q in p31_qids for q in ["Q15991273", "Q1339744"]) or "sports leagues" in cats_str
            is_publisher = any(q in p31_qids for q in ["Q2085381", "Q1107", "Q41298"]) or "publishing companies" in cats_str or "newspapers" in cats_str or "magazines" in cats_str
            is_restaurant = any(q in p31_qids for q in ["Q1142512", "Q11228519", "Q11707"]) or "restaurants" in cats_str or "fast food chains" in cats_str
            is_beverage = "Q11504938" in p31_qids or "beverage companies" in cats_str or "soft drink brands" in cats_str or "breweries" in cats_str
            is_fashion = "fashion" in cats_str or "clothing brands" in cats_str or "apparel" in extract
            is_beauty = "cosmetics companies" in cats_str or "beauty brands" in cats_str or "cosmetics" in extract
            is_travel = "airlines" in cats_str or "hotel chains" in cats_str or "airline" in extract
            is_radio = "radio stations" in cats_str or "radio networks" in cats_str
            is_electronics = "consumer electronics" in cats_str or "consumer electronics" in extract
            is_retail = "retailers" in cats_str or "supermarkets" in cats_str

            if is_movie:
                category = "Movies"
                year_match = re.search(r"\b(19\d\d|20\d\d)\b", extract)
                year = year_match.group(1) if year_match else "UNVERIFIED"
                sub_category_lines.append(f"Release Year - {year}")
                if "warner" in extract or "disney" in extract or "universal" in extract or "paramount" in extract or "sony" in extract:
                    sub_category_lines.append("Studio - Major")
                else:
                    sub_category_lines.append("Studio - Independent")
            elif is_tv_show:
                category = "TV Shows"
                sub_category_lines.append("Program Type - Series")
                if "reality" in extract:
                    sub_category_lines.append("Program Type - Reality TV")
            elif is_game:
                category = "Video Game"
                sub_category_lines.append("PC")
            elif is_game_publisher:
                category = "Video Game Publishers"
            elif is_sports_team:
                category = "Sports Franchise"
                sport = "Soccer"
                if "basketball" in extract:
                    sport = "Basketball"
                elif "football" in extract:
                    sport = "Football"
                sub_category_lines.append(f"Sports Type - {sport}")
            elif is_sports_league:
                category = "Sports Franchise, Sports Organizations and Bodies"
            elif is_tv_network:
                category = "TV Network"
                sub_category_lines.append("Region - NA")
                sub_category_lines.append("Location: Country - United States")
            elif is_publisher:
                category = "Publishers"
                pub_type = "Publishing Company"
                if "newspaper" in extract:
                    pub_type = "Newspaper"
                elif "magazine" in extract:
                    pub_type = "Magazine"
                sub_category_lines.append(f"Publication Type - {pub_type}")
            elif is_restaurant:
                category = "Restaurants"
                rest_cat = "Varied Menu"
                rest_type = "Casual Dining"
                if "fast food" in extract:
                    rest_type = "Quick Service"
                sub_category_lines.append(f"Restaurant Category - {rest_cat}")
                sub_category_lines.append(f"Restaurant Type - {rest_type}")
            elif is_beverage:
                category = "Beverages"
                bev_type = "Soft Drinks"
                if "beer" in extract:
                    category = "Breweries"
                    bev_type = "Beer"
                sub_category_lines.append(f"Beverage Type - {bev_type}")
            elif is_fashion:
                category = "Fashion"
                sub_category_lines.append("Women's Apparel")
            elif is_beauty:
                category = "Health & Beauty"
                sub_category_lines.append("Beauty Type - Makeup")
            elif is_travel:
                category = "Travel"
                sub_category_lines.append("Travel Type - Hotels")
            elif is_radio:
                category = "Radio"
            elif is_electronics:
                category = "Consumer Electronics"
            elif is_retail:
                category = "Retail"
                sub_category_lines.append("Retail Type - Retailer")
            else:
                category = "CPG"

        return {
            "category": category,
            "sub_category": "\n".join(sub_category_lines)
        }
