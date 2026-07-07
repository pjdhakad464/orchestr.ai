"""Documentation content — one place to edit the in-app docs.

Each section: id (anchor), title, icon, and `blocks`. A block is either
{"h": heading, "p": paragraph} or {"h": heading, "list": [items]}.
"""

from __future__ import annotations

DOC_SECTIONS: list[dict] = [
    {
        "id": "getting-started", "title": "Getting Started", "icon": "rocket_launch",
        "blocks": [
            {"h": "What OrchestrAI is",
             "p": "OrchestrAI is the DataOps workspace for media-intelligence "
                  "operations: validate workbooks, classify and enrich metadata, "
                  "launch media tools, and track activity — in one place."},
            {"h": "Sign in",
             "p": "Access uses your existing ListenFirst identity. No separate "
                  "account is required; the authentication flow is unchanged."},
            {"h": "First steps",
             "list": ["Open the Operations Dashboard for a live overview.",
                      "Validate a workbook in the Data Ops Validator.",
                      "Browse tools in the Media Tools Hub (⌘K opens the command palette anywhere).",
                      "Review what ran in the Activity Center."]},
        ],
    },
    {
        "id": "architecture", "title": "Architecture", "icon": "account_tree",
        "blocks": [
            {"h": "Platform core + registered tools",
             "p": "The platform core hosts shared services (design system, theme, "
                  "command palette, status). Tools register into a catalog and "
                  "appear automatically in the Hub and the command palette — new "
                  "tools are added without changing the core."},
            {"h": "Modules",
             "list": ["Landing — marketing entry point.",
                      "Media Tools Hub — searchable tool catalog.",
                      "Operations Dashboard & Activity Center — operational visibility.",
                      "Excel Validator, Title/IMDb lookup, Calendars — individual tools.",
                      "API (/api/v1) — validation, taxonomy, enrichment, social."]},
        ],
    },
    {
        "id": "tools", "title": "Tool Guides", "icon": "build",
        "blocks": [
            {"h": "Data Ops Validator",
             "p": "Upload a workbook or paste a Google Sheet URL, apply BDR QA "
                  "rules, and download a reviewed copy with failed cells flagged "
                  "and a validation summary sheet."},
            {"h": "Media Tools Hub",
             "p": "Search and filter every tool by category. Star favorites and "
                  "revisit recently-used tools. External media tools open in a "
                  "new tab; built-in tools open in place."},
            {"h": "Command palette",
             "p": "Press ⌘K (Ctrl+K on Windows) anywhere to jump to a tool or "
                  "run a quick action."},
        ],
    },
    {
        "id": "workflows", "title": "Workflow Guides", "icon": "conveyor_belt",
        "blocks": [
            {"h": "BDR from a ticket",
             "list": ["A request arrives and its entities are researched.",
                      "The BDR is built in the canonical ingest template.",
                      "It is validated against the QA rules.",
                      "Unverified values are flagged NEEDS REVIEW for a human — never guessed."]},
            {"h": "Human-approved ingest",
             "p": "Automation prepares outputs; a person reviews and approves "
                  "before anything is ingested downstream."},
        ],
    },
    {
        "id": "api", "title": "API Overview", "icon": "api",
        "blocks": [
            {"h": "Base path",
             "p": "REST endpoints live under /api/v1 and return a consistent "
                  "{status, message, data} envelope."},
            {"h": "Key endpoints",
             "list": ["POST /api/v1/validate — validate a workbook.",
                      "POST /api/v1/taxonomy/classify — category / sub-category.",
                      "POST /api/v1/social/discover — official profile discovery.",
                      "POST /api/v1/enrich/imdb — IMDb/TMDB enrichment.",
                      "GET  /api/v1/status — service health."]},
        ],
    },
    {
        "id": "faq", "title": "FAQ", "icon": "help",
        "blocks": [
            {"h": "Does it change my data automatically?",
             "p": "No. Tools prepare and suggest; a human approves. Unconfirmed "
                  "values are marked NEEDS REVIEW rather than invented."},
            {"h": "Why is a dashboard panel “Not connected”?",
             "p": "Automation, workflow, and queue feeds come from the automation "
                  "service. Panels are integration-ready and show real data once "
                  "a feed is connected — never placeholder numbers."},
            {"h": "Light or dark mode?",
             "p": "Both. Use the toggle in the top bar; your choice is remembered."},
        ],
    },
    {
        "id": "troubleshooting", "title": "Troubleshooting", "icon": "troubleshoot",
        "blocks": [
            {"h": "A validation didn’t appear in Activity",
             "p": "Activity reflects validations recorded in this environment. "
                  "Re-run the validation; if it still doesn’t show, check the "
                  "service status on the Dashboard."},
            {"h": "A media tool won’t load",
             "p": "External media tools are hosted separately. If one is briefly "
                  "unavailable, try again shortly — the platform surfaces the tool "
                  "but does not host it."},
            {"h": "A service shows “Not configured”",
             "p": "That integration’s credentials aren’t set in this environment. "
                  "It’s optional and safe to leave unset until needed."},
        ],
    },
]
