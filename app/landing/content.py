"""Landing page content — the single place to edit marketing copy.

Every section of the landing renders from this dict, so changing a headline,
feature, tool, or testimonial means editing only this file. Structure mirrors
the section partials in app/templates/landing/sections/.
"""

from __future__ import annotations

HUB_URL = "https://media-tools-hub.onrender.com/"

LANDING: dict = {
    "nav": {
        "links": [
            {"label": "Platform", "href": "#platform"},
            {"label": "Media Tools Hub", "href": "#hub"},
            {"label": "Automation", "href": "#automation"},
            {"label": "Integrations", "href": "#integrations"},
        ],
    },
    "hero": {
        "badge_new": "NEW",
        "badge_text": "Media Tools Hub is now integrated",
        "title_lead": "Run data operations",
        "title_accent": "on autopilot.",
        "subtitle": "OrchestrAI coordinates workflows, metadata, and automation "
                    "in one workspace — validate, enrich, and ship brand data "
                    "with AI doing the heavy lifting.",
        "cta_primary": {"label": "Open the platform", "href": "/excel-validator"},
        "cta_secondary": {"label": "Explore tools", "href": "/tools"},
    },
    "preview": {
        "sidebar": ["Site Overview", "Validator", "BDR Builder", "Taxonomy",
                    "Enrichment", "Media Tools Hub", "Automation"],
        "stats": [
            {"k": "Records validated", "v": "35.6K", "delta": "+5.6%", "down": False},
            {"k": "Auto-classified", "v": "10.1K", "delta": "+12%", "down": False},
        ],
        "keywords": ["official social profiles", "IMDb / TMDB enrichment",
                     "taxonomy category + sub-category", "brand-set membership",
                     "duplicate detection", "metadata QA"],
    },
    "logos": {
        "caption": "Trusted across the ListenFirst data operation",
        "entries": ["ListenFirst", "Data Ops", "Radaac", "Zendesk",
                  "Asana", "Google Drive", "Slack", "Metacritic"],
    },
    "platform": {
        "eyebrow": "Platform",
        "title": "One workspace for every data-ops motion",
        "lead": "The tools your team used to juggle across tabs, unified and "
                "wired into one another.",
        "features": [
            {"icon": "shield", "title": "Workbook Validator",
             "desc": "Rule-based QA that highlights failed cells and adds a "
                     "validation summary sheet."},
            {"icon": "construction", "title": "BDR Ingest Builder",
             "desc": "Turn requests into ingest-ready, colour-coded workbooks "
                     "in the canonical template."},
            {"icon": "sell", "title": "Taxonomy Classifier",
             "desc": "Map entities to the approved title category and "
                     "sub-category — never guessed."},
            {"icon": "movie", "title": "IMDb / TMDB Enrichment",
             "desc": "Season and episode counts, ttcodes, and title URLs "
                     "resolved automatically."},
            {"icon": "person_search", "title": "Official Profile Finder",
             "desc": "Verified Facebook, Instagram, YouTube, X, TikTok and "
                     "Wikipedia links."},
            {"icon": "difference", "title": "Apply Report QA",
             "desc": "Diff an apply report against the source and surface "
                     "exactly what changed."},
        ],
    },
    "hub": {
        "eyebrow": "Media Tools Hub",
        "title": "Every media data tool, one click away",
        "lead": "Billboard charts, YouTube release verification, box-office "
                "and premiere calendars — launch them from the hub.",
        "cta": {"label": "Open Media Tools Hub", "href": HUB_URL},
        "tools": ["Billboard New Entries", "YouTube Release Verifier",
                  "TV Premiere Calendar", "Movie & Game Calendars",
                  "Box Office Mojo", "Weekly Openings", "Release Changes"],
    },
    "automation": {
        "eyebrow": "Automation Engine",
        "title": "Tickets in, finished BDRs out",
        "lead": "The moment a Zendesk ticket lands, OrchestrAI parses it, "
                "researches every entity, builds the BDR, validates it, and "
                "files it — before anyone opens the tab.",
        "steps": [
            {"n": "01", "title": "Detect", "desc": "New ticket in the ops channel."},
            {"n": "02", "title": "Research", "desc": "Handles + Wikidata + taxonomy."},
            {"n": "03", "title": "Validate", "desc": "Run the BDR QA rules."},
            {"n": "04", "title": "Deliver", "desc": "Drive folder + instant Slack ping."},
        ],
    },
    "agents": {
        "eyebrow": "AI Agents",
        "title": "Specialists, not a single black box",
        "lead": "Each agent owns one job and defers to a human when it isn't "
                "certain — accuracy over autonomy.",
        "entries": [
            {"icon": "verified", "title": "Verifier", "desc": "Confirms identity from official handles before trusting a match."},
            {"icon": "category", "title": "Classifier", "desc": "Assigns approved taxonomy, flags anything ambiguous."},
            {"icon": "hub", "title": "Enricher", "desc": "Pulls IMDb/TMDB and social metadata per entity."},
            {"icon": "rule", "title": "QA Reviewer", "desc": "Applies validation rules and marks NEEDS REVIEW."},
        ],
    },
    "analytics": {
        "eyebrow": "Analytics",
        "title": "See the operation at a glance",
        "lead": "Throughput, review load, and data quality — surfaced so you "
                "act on what needs attention.",
        "metrics": [
            {"k": "Tickets automated / week", "v": "120+"},
            {"k": "Avg. turnaround", "v": "< 5 min"},
            {"k": "Fields auto-filled", "v": "82%"},
            {"k": "Manual QA saved", "v": "30 hrs/wk"},
        ],
    },
    "integrations": {
        "eyebrow": "Integrations",
        "title": "Plugged into the tools you already run",
        "lead": "OrchestrAI reads and writes where your team already works.",
        "entries": [
            {"icon": "task_alt", "name": "Asana"},
            {"icon": "support_agent", "name": "Zendesk"},
            {"icon": "folder", "name": "Google Drive"},
            {"icon": "forum", "name": "Slack"},
            {"icon": "movie", "name": "IMDb / TMDB"},
            {"icon": "public", "name": "Wikidata"},
        ],
    },
    "benefits": {
        "eyebrow": "Why OrchestrAI",
        "title": "Built for accuracy, reliability, and scale",
        "entries": [
            {"icon": "target", "title": "Never guesses", "desc": "Unconfirmed values are flagged NEEDS REVIEW, never invented."},
            {"icon": "bolt", "title": "Minutes, not mornings", "desc": "Work that took a human operator hours completes in minutes."},
            {"icon": "lock", "title": "Human-approved ingest", "desc": "Automation prepares; a person approves before anything ships."},
            {"icon": "extension", "title": "Modular by design", "desc": "Each capability is isolated, so changes stay contained."},
        ],
    },
    "testimonials": {
        "eyebrow": "From the team",
        "title": "What the operators say",
        "entries": [
            {"quote": "It files the BDR before I've finished reading the ticket. "
                      "I just review and approve.", "name": "Data Ops Analyst", "role": "ListenFirst"},
            {"quote": "The taxonomy classifier is careful — when it isn't sure it "
                      "says so, which is exactly what I want.", "name": "QA Reviewer", "role": "Data Operations"},
            {"quote": "Everything lives in one place now. No more ten open tabs "
                      "every morning.", "name": "Team Lead", "role": "ListenFirst India"},
        ],
    },
    "cta": {
        "title": "Ready to put your mornings on autopilot?",
        "lead": "Open the platform and let OrchestrAI handle the busywork.",
        "cta_primary": {"label": "Open the platform", "href": "/excel-validator"},
        "cta_secondary": {"label": "Browse all tools", "href": "/tools"},
    },
    "footer": {
        "columns": [
            {"title": "Platform", "links": [
                {"label": "Validator", "href": "/excel-validator"},
                {"label": "All Tools", "href": "/tools"},
                {"label": "Automation Tasks", "href": "/calendar/"},
                {"label": "Title URL Finder", "href": "/title-lookup/"}]},
            {"title": "Media Tools Hub", "links": [
                {"label": "Open Hub", "href": HUB_URL},
                {"label": "Billboard", "href": HUB_URL},
                {"label": "YouTube Verifier", "href": HUB_URL}]},
            {"title": "Resources", "links": [
                {"label": "Validator Guide", "href": "/excel-validator/guide"},
                {"label": "IMDb Lookup", "href": "/imdb/"}]},
        ],
        "note": "OrchestrAI · Data Ops Intelligence for ListenFirst.",
    },
}
