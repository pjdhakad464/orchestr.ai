from __future__ import annotations

import asyncio
import re
from urllib.parse import quote
import httpx
from app.config import settings
from app.cache import TTLCache

class TaxonomyClassifier:
    def __init__(self, cache: TTLCache) -> None:
        self.cache = cache
        self.contact = settings.wikimedia_contact or "ramesh@listenfirstmedia.com"
        self.headers = {
            "User-Agent": f"OfficialProfileFinderBot/0.1 ({self.contact})",
            "Api-User-Agent": self.contact
        }

    async def classify(self, title: str) -> dict[str, str]:
        title = title.strip()
        if not title:
            return {"category": "UNVERIFIED", "sub_category": "Title name cannot be blank."}

        # Check Cache first
        cache_key = f"classif:{title.lower()}"
        cached = self.cache.get(cache_key)
        if cached:
            return cached

        # Step 1: Search Wikipedia for best page title match
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
                if not search_hits:
                    result = {"category": "UNVERIFIED", "sub_category": "No matching Wikipedia articles found."}
                    self.cache.set(cache_key, result)
                    return result
                
                best_match = search_hits[0]["title"]
            except Exception as e:
                # API error fallback
                best_match = title

            # Step 2: Fetch categories, extracts, and wikibase item (wikidata QID)
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
                if not pages or pages[0].get("missing") is True:
                    result = {"category": "UNVERIFIED", "sub_category": f"Wikipedia page not found for '{best_match}'."}
                    self.cache.set(cache_key, result)
                    return result

                page = pages[0]
                canonical_title = page.get("title", best_match)
                extract = page.get("extract", "").lower()
                categories = [c.get("title", "") for c in page.get("categories", [])]
                wikidata_id = page.get("pageprops", {}).get("wikibase_item")
            except Exception as e:
                canonical_title = best_match
                extract = ""
                categories = []
                wikidata_id = None

            # Step 3: Fetch Wikidata claims if wikidata_id is present
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
            result = self._run_classification_heuristics(canonical_title, extract, categories, claims)
            self.cache.set(cache_key, result)
            return result

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
        claims: dict
    ) -> dict[str, str]:
        # Normalization helpers
        cats_str = " | ".join(categories).lower()
        
        # 1. Determine base category
        category = ""
        sub_category_lines = []

        # Wikidata properties
        p31_qids = self._get_claim_qids(claims, "P31") # instance of
        p106_qids = self._get_claim_qids(claims, "P106") # occupation
        p641_qids = self._get_claim_qids(claims, "P641") # sport
        p452_qids = self._get_claim_qids(claims, "P452") # industry
        p1056_qids = self._get_claim_qids(claims, "P1056") # product or material produced

        # Check human first (Talent)
        is_human = "Q5" in p31_qids or "births" in cats_str or "deaths" in cats_str or "people" in cats_str or "Category:Living people" in categories
        
        if is_human:
            category = "Talent"
            # Extract Gender
            gender = "UNVERIFIED"
            p21_qids = self._get_claim_qids(claims, "P21")
            if "Q6581072" in p21_qids:
                gender = "Woman"
            elif "Q6581097" in p21_qids:
                gender = "Man"
            elif any(qid in p21_qids for qid in ["Q189125", "Q1052281", "Q1090279"]):
                gender = "Non-Binary"
            else:
                # Text check
                if re.search(r"\b(she|her|hers|actress|woman|female)\b", extract):
                    gender = "Woman"
                elif re.search(r"\b(he|him|his|actor|man|male)\b", extract):
                    gender = "Man"
                elif "women" in cats_str or "actresses" in cats_str:
                    gender = "Woman"
                elif "men" in cats_str:
                    gender = "Man"

            sub_category_lines.append(f"Gender - {gender}")

            # Extract Talent Subtype and Talent Type
            subtype = "Internet Personality - Content Creator"
            talent_type = "Internet Personality"

            # Check Athletes
            is_athlete = any(q in p106_qids for q in ["Q3665646", "Q11116515", "Q937857", "Q1165955", "Q10833314", "Q205312", "Q11774882", "Q378622", "Q53725", "Q206653", "Q11571", "Q1747444", "Q13382404"])
            if not is_athlete:
                is_athlete = "player" in extract or "athlete" in cats_str or "footballer" in cats_str or "cricketer" in cats_str or "olympic" in cats_str
            
            if is_athlete:
                talent_type = "Athlete"
                # Determine sport
                sport = "Other"
                if "Q3962" in p641_qids or "basketball" in extract or "basketball" in cats_str or "nba" in extract or "nba" in cats_str:
                    sport = "Basketball"
                elif "Q4113337" in p641_qids or "american football" in extract or "american football" in cats_str or "nfl" in extract or "nfl" in cats_str:
                    sport = "Football"
                elif "Q413" in p641_qids or "soccer" in extract or "soccer" in cats_str or "association football" in extract or "association football" in cats_str or "footballer" in extract or "footballer" in cats_str or "epl" in cats_str or "mls" in cats_str:
                    # Note Football vs Soccer disambiguation
                    sport = "Soccer"
                elif "Q1165955" in p641_qids or "baseball" in extract or "baseball" in cats_str or "mlb" in cats_str:
                    sport = "Baseball"
                elif "Q53725" in p641_qids or "cricket" in extract or "cricket" in cats_str or "ipl" in cats_str:
                    sport = "Cricket"
                elif "Q1914" in p641_qids or "tennis" in extract or "tennis" in cats_str:
                    sport = "Tennis"
                elif "Q205312" in p641_qids or "golf" in extract or "golf" in cats_str:
                    sport = "Golf"
                elif "Q11774882" in p641_qids or "ice hockey" in extract or "ice hockey" in cats_str or "nhl" in cats_str:
                    sport = "Ice Hockey"
                elif "Q378622" in p641_qids or "racing driver" in extract or "racing driver" in cats_str or "formula one" in extract or "formula one" in cats_str or "nascar" in cats_str:
                    sport = "Auto Racing"
                
                # Check Coach
                if "coach" in extract or "coach" in cats_str or "manager" in extract:
                    subtype = "Athlete - Coach"
                else:
                    subtype = f"Athlete - {sport}"
            
            # Musician
            elif any(q in p106_qids for q in ["Q2252262", "Q177220", "Q488205", "Q639669", "Q130857", "Q183944", "Q36834"]) or "musician" in cats_str or "singer" in cats_str or "rapper" in cats_str or "composer" in cats_str:
                talent_type = "Musician"
                if "rapper" in extract or "rapper" in cats_str or "hip hop" in extract:
                    subtype = "Musician - Rapper"
                elif "singer" in extract or "singer" in cats_str or "vocalist" in extract or "vocalist" in cats_str:
                    subtype = "Musician - Singer"
                elif "dj" in extract or "dj" in cats_str or "disc jockey" in extract:
                    subtype = "Musician - DJ"
                else:
                    subtype = "Musician - Instrumentalist"

            # Actor / Actress
            elif any(q in p106_qids for q in ["Q33999", "Q2526255"]) or "actor" in cats_str or "actresses" in cats_str or "actor" in extract or "actress" in extract:
                if gender == "Woman":
                    talent_type = "Actress"
                    subtype = "Actress"
                else:
                    talent_type = "Actor"
                    subtype = "Actor"

            # Internet Personality
            elif any(q in p106_qids for q in ["Q112239616", "Q9062770", "Q11504930"]) or "youtubers" in cats_str or "tiktoker" in cats_str or "streamer" in cats_str or "vlogger" in cats_str or "internet personality" in cats_str or "internet celebrity" in cats_str:
                talent_type = "Internet Personality"
                if "streamer" in extract or "streamer" in cats_str or "twitch" in extract or "twitch" in cats_str:
                    subtype = "Internet Personality - Streamer"
                elif "youtuber" in extract or "youtuber" in cats_str:
                    subtype = "Internet Personality - YouTuber"
                else:
                    subtype = "Internet Personality - Influencer"

            # Journalist & Media Personality
            elif any(q in p106_qids for q in ["Q1930187", "Q482980", "Q214986", "Q16223067"]) or "journalists" in cats_str or "news anchors" in cats_str or "tv host" in extract or "television host" in extract or "journalist" in extract:
                if "journalist" in extract or "journalist" in cats_str or "reporter" in extract:
                    talent_type = "Journalist"
                    subtype = "Media Personality - TV"
                else:
                    talent_type = "Media Personality"
                    subtype = "Media Personality - TV"
                    
            # Writer / Creator / Chef
            elif "chef" in extract or "cook" in extract or "chef" in cats_str:
                talent_type = "Creator"
                subtype = "Creator - Chef"
            elif any(q in p106_qids for q in ["Q36180", "Q49757"]) or "writers" in cats_str or "novelists" in cats_str or "poets" in cats_str:
                talent_type = "Creator"
                subtype = "Writer - Author"
            elif any(q in p106_qids for q in ["Q2526255", "Q3282637", "Q28389", "Q130232"]) or "directors" in cats_str or "filmmaker" in cats_str:
                talent_type = "Creator"
                subtype = "Filmmaker - Director"
            elif "model" in extract or "models" in cats_str:
                talent_type = "Model"
                subtype = "Model"
            elif "politician" in extract or "senator" in extract or "president" in extract or "politicians" in cats_str:
                talent_type = "Public Figure"
                subtype = "Public Figure - Politician"

            sub_category_lines.append(f"Talent Subtype - {subtype}")
            sub_category_lines.append(f"Talent Type - {talent_type}")

        # Non-Human classification
        else:
            # Check Movie
            is_movie = any(q in p31_qids for q in ["Q11424", "Q24869", "Q201658"]) or "films" in cats_str or "movie" in extract or (len(title) > 6 and "film" in title.lower())
            
            # Check TV Show
            is_tv_show = any(q in p31_qids for q in ["Q5398119", "Q15416", "Q15416"]) or "television series" in cats_str or "television programs" in cats_str or "television series" in extract or "television show" in extract
            
            # Check Video Game
            is_game = "Q7889" in p31_qids or "video games" in cats_str or "video game" in extract
            is_game_publisher = any(q in p31_qids for q in ["Q1137107", "Q210167"]) or "video game publishers" in cats_str or "video game developers" in cats_str or "video game developer" in extract or "video game publisher" in extract

            # Check TV Network
            is_tv_network = any(q in p31_qids for q in ["Q229397", "Q2001305"]) or "television networks" in cats_str or "television channels" in cats_str or "television network" in extract or "television channel" in extract or "broadcasting company" in extract

            # Check Sports Franchise
            is_sports_team = any(q in p31_qids for q in ["Q133936", "Q476028", "Q18420188", "Q21531399"]) or "sports teams" in cats_str or "football clubs" in cats_str or "basketball teams" in cats_str or "sports team" in extract or "football club" in extract
            is_sports_league = any(q in p31_qids for q in ["Q15991273", "Q1339744"]) or "sports leagues" in cats_str or "sports governing bodies" in cats_str or "sports league" in extract or "sports association" in extract

            # Check Publishers
            is_publisher = any(q in p31_qids for q in ["Q2085381", "Q1107", "Q41298"]) or "publishing companies" in cats_str or "newspapers" in cats_str or "magazines" in cats_str or "newspaper" in extract or "magazine" in extract or "publisher" in extract

            # Check Restaurants
            is_restaurant = any(q in p31_qids for q in ["Q1142512", "Q11228519", "Q11707"]) or "restaurants" in cats_str or "fast food chains" in cats_str or "coffeehouses" in cats_str or "restaurant" in extract or "fast food" in extract or "coffeehouse" in extract

            # Check Beverages
            is_beverage = "Q11504938" in p31_qids or "beverage companies" in cats_str or "soft drink brands" in cats_str or "breweries" in cats_str or "wineries" in cats_str or "beverage" in extract or "drink" in extract or "brewery" in extract or "soft drink" in extract or "beer" in extract or "wine" in extract

            # Check Fashion
            is_fashion = "fashion" in cats_str or "clothing brands" in cats_str or "apparel" in extract or "clothing brand" in extract or "fashion designer" in extract or "luxury brand" in extract or "fashion brand" in extract

            # Check Health & Beauty
            is_beauty = "cosmetics companies" in cats_str or "beauty brands" in cats_str or "cosmetics" in extract or "makeup brand" in extract or "skincare" in extract or "beauty brand" in extract

            # Check Travel
            is_travel = "airlines" in cats_str or "hotel chains" in cats_str or "cruise lines" in cats_str or "airline" in extract or "hotel chain" in extract or "cruise line" in extract or "resort" in extract or "travel agency" in extract

            # Check Radio
            is_radio = "radio stations" in cats_str or "radio networks" in cats_str or "radio station" in extract or "broadcaster" in extract

            # Check Consumer Electronics
            is_electronics = "consumer electronics" in cats_str or "telecommunications equipment" in cats_str or "consumer electronics" in extract or "smartphone" in extract or "computer hardware" in extract

            # Check Retail
            is_retail = "retailers" in cats_str or "supermarkets" in cats_str or "grocery stores" in cats_str or "retail chain" in extract or "retailer" in extract or "supermarket" in extract or "department store" in extract

            # Resolve Category
            if is_movie:
                category = "Movies"
                # Sub-category helper for Movies
                year_match = re.search(r"\b(19\d\d|20\d\d)\b", extract)
                year = year_match.group(1) if year_match else "UNVERIFIED"
                sub_category_lines.append(f"Release Year - {year}")
                if "warner" in extract or "disney" in extract or "universal" in extract or "paramount" in extract or "sony" in extract:
                    sub_category_lines.append("Studio Type - Major")
                else:
                    sub_category_lines.append("Studio Type - Independent")

            elif is_tv_show:
                category = "TV Shows"
                sub_category_lines.append("Program Type - Series")
                if "animation" in extract or "animated" in cats_str:
                    sub_category_lines.append("Program Genre - Animated")
                elif "reality" in extract or "reality television" in cats_str:
                    sub_category_lines.append("Program Type - Reality TV")

            elif is_game:
                category = "Video Game"
                sub_category_lines.append("Platform - PC")
                sub_category_lines.append("Platform - Console")

            elif is_game_publisher:
                category = "Video Game, Video Game Publishers"
                sub_category_lines.append(f"Publisher - {title}")

            elif is_sports_team:
                category = "Sports Franchise"
                # Guess city/state/sport
                city = "UNVERIFIED"
                state = "UNVERIFIED"
                # Search for typical state abbreviations or city names in title
                sub_category_lines.append("Location: City - UNVERIFIED")
                sub_category_lines.append("Location: State - UNVERIFIED")
                sport = "Soccer"
                if "basketball" in extract or "nba" in extract or "nba" in cats_str:
                    sport = "Basketball"
                elif "football" in extract or "nfl" in extract or "nfl" in cats_str:
                    sport = "Football"
                elif "baseball" in extract or "mlb" in extract or "mlb" in cats_str:
                    sport = "Baseball"
                sub_category_lines.append(f"Sports Type - {sport}")

            elif is_sports_league:
                category = "Sports Franchise, Sports Organizations and Bodies"
                sport = "Soccer"
                if "basketball" in extract or "nba" in extract:
                    sport = "Basketball"
                elif "football" in extract or "nfl" in extract:
                    sport = "Football"
                sub_category_lines.append("League Type - Professional")
                sub_category_lines.append(f"Sports Type - {sport}")

            elif is_tv_network:
                category = "TV Network"
                sub_category_lines.append("Region - North America")
                sub_category_lines.append("Location: Country - United States")

            elif is_publisher:
                category = "Publishers"
                pub_type = "Publisher"
                if "newspaper" in extract or "newspaper" in cats_str:
                    pub_type = "Newspaper"
                elif "magazine" in extract or "magazine" in cats_str:
                    pub_type = "Magazine"
                sub_category_lines.append(f"Publication Type - {pub_type}")

            elif is_restaurant:
                category = "Restaurants"
                rest_cat = "Casual Dining"
                if "fast food" in extract or "quick service" in extract or "mcdonald" in extract.lower():
                    rest_cat = "Fast Food"
                elif "coffee" in extract or "starbucks" in extract:
                    rest_cat = "Coffeehouse"
                sub_category_lines.append(f"Restaurant Category - {rest_cat}")
                sub_category_lines.append("Restaurant Type - Chain")

            elif is_beverage:
                category = "Beverages"
                bev_type = "Soft Drink"
                if "beer" in extract or "brewery" in extract or "beer" in cats_str:
                    bev_type = "Beer"
                elif "wine" in extract or "winery" in extract or "wine" in cats_str:
                    bev_type = "Wine"
                elif "whiskey" in extract or "spirits" in extract or "distillery" in extract:
                    bev_type = "Spirits"
                sub_category_lines.append(f"Beverage Type - {bev_type}")

            elif is_fashion:
                category = "Fashion"
                prod_cat = "Apparel"
                if "shoe" in extract or "footwear" in extract:
                    prod_cat = "Footwear"
                elif "luxury" in extract or "jewelry" in extract:
                    prod_cat = "Luxury Goods"
                sub_category_lines.append(f"Product Category - {prod_cat}")

            elif is_beauty:
                category = "Health & Beauty"
                sub_category_lines.append("Product Category - Cosmetics")

            elif is_travel:
                category = "Travel"
                travel_type = "Hotels"
                if "airline" in extract or "airlines" in cats_str:
                    travel_type = "Airlines"
                elif "cruise" in extract or "cruise lines" in cats_str:
                    travel_type = "Cruise Lines"
                elif "car rental" in extract:
                    travel_type = "Car Rental"
                sub_category_lines.append(f"Travel Type - {travel_type}")

            elif is_radio:
                category = "Radio"
                sub_category_lines.append("Station - UNVERIFIED")

            elif is_electronics:
                category = "Consumer Electronics"
                sub_category_lines.append("Product Type - Smartphones")

            elif is_retail:
                category = "Retail"
                ret_type = "Retailer"
                if "supermarket" in extract or "grocery" in extract:
                    ret_type = "Supermarket"
                sub_category_lines.append(f"Retail Type - {ret_type}")

            else:
                # Default fallback
                category = "CPG"
                sub_category_lines.append("Product Category - Household Products")

        return {
            "category": category,
            "sub_category": "\n".join(sub_category_lines)
        }
