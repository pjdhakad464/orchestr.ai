"""Media Tools Hub catalog — the single source of truth for hub tiles.

Add a tool by appending a dict to TOOLS. `id` must be stable (favorites and
recently-used are keyed on it in the browser). `category` must be one of
CATEGORIES. `keywords` improves client-side search matching.
"""

from __future__ import annotations

HUB_BASE = "https://media-tools-hub.onrender.com"

# Order defines the filter-chip order; "All" is prepended in the template.
CATEGORIES = ["Validation", "Research", "Calendars", "Charts",
              "Verification", "Box Office"]

TOOLS: list[dict] = [
    {
        "id": "validator", "name": "Data Ops Validator", "url": "/excel-validator",
        "icon": "shield", "category": "Validation", "external": False,
        "desc": "Validate a workbook against BDR QA rules; failed cells are "
                "flagged and a summary sheet is added.",
        "keywords": "excel csv workbook qa rules validate metadata",
    },
    {
        "id": "title-url", "name": "Title URL Finder", "url": "/title-lookup/",
        "icon": "link", "category": "Research", "external": False,
        "desc": "Resolve official title URLs from a name.",
        "keywords": "title url official lookup search",
    },
    {
        "id": "imdb", "name": "IMDb Lookup", "url": "/imdb/",
        "icon": "movie", "category": "Research", "external": False,
        "desc": "Find IMDb ttcodes and nmcodes by title or name.",
        "keywords": "imdb ttcode nmcode movie tv person enrichment",
    },
    {
        "id": "calendars", "name": "Automation Tasks", "url": "/calendar/",
        "icon": "event_note", "category": "Calendars", "external": False,
        "desc": "Metacritic premiere and release calendar automations.",
        "keywords": "metacritic calendar premiere release tv movie game",
    },
    {
        "id": "billboard", "name": "Billboard New Entries",
        "url": f"{HUB_BASE}/billboard-new-entries", "icon": "queue_music",
        "category": "Charts", "external": True,
        "desc": "Artist 100 rows where Last Week = dash, with IMDb + Wikipedia.",
        "keywords": "billboard artist 100 chart music new entries",
    },
    {
        "id": "youtube-verifier", "name": "YouTube Release Verifier",
        "url": f"{HUB_BASE}/youtube-release-verifier", "icon": "smart_display",
        "category": "Verification", "external": True,
        "desc": "Verify official-channel trailers and publish dates via the "
                "YouTube API.",
        "keywords": "youtube trailer official channel verify release",
    },
    {
        "id": "tv-premiere", "name": "TV Premiere Calendar", "url": HUB_BASE,
        "icon": "live_tv", "category": "Calendars", "external": True,
        "desc": "Metacritic TV premieres for a chosen date window.",
        "keywords": "tv premiere metacritic calendar season episode",
    },
    {
        "id": "movie-game", "name": "Movie & Game Calendars", "url": HUB_BASE,
        "icon": "calendar_month", "category": "Calendars", "external": True,
        "desc": "Metacritic movie and game release schedules.",
        "keywords": "movie game release calendar metacritic",
    },
    {
        "id": "box-office", "name": "Box Office Tools", "url": HUB_BASE,
        "icon": "theaters", "category": "Box Office", "external": True,
        "desc": "Box Office Mojo schedule, weekly openings, and date changes.",
        "keywords": "box office mojo opening weekend theatrical revenue",
    },
]
