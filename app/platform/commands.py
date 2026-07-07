"""Command palette catalog (⌘K) — the AI-assistant foundation.

Every command is a structured intent: a label, an icon, keywords for
matching, and — for now — an `href` it routes to. This is deliberately
LLM-ready: a future assistant can map a free-text query to one of these
intents (or a new one) and dispatch it, without the UI changing. Nothing
here fabricates AI output; commands simply navigate today.

Built from the hub catalog so new tools appear in the palette automatically.
"""

from __future__ import annotations

from app.hub.catalog import TOOLS


def build_commands() -> list[dict]:
    commands: list[dict] = [
        # Go to — core platform destinations
        {"group": "Go to", "label": "Operations Dashboard", "icon": "dashboard",
         "href": "/dashboard", "keywords": "home overview kpis status command center"},
        {"group": "Go to", "label": "Approval Queue", "icon": "inbox",
         "href": "/approvals", "keywords": "approvals review tickets queue pending approve"},
        {"group": "Go to", "label": "New ticket intake", "icon": "add_circle",
         "href": "/approvals/new", "keywords": "new ticket intake paste zendesk analyze"},
        {"group": "Go to", "label": "Activity Center", "icon": "timeline",
         "href": "/activity", "keywords": "timeline history events recent log"},
        {"group": "Go to", "label": "Media Tools Hub", "icon": "hub",
         "href": "/tools", "keywords": "tools workspace catalog search"},
        {"group": "Go to", "label": "Data Ops Validator", "icon": "shield",
         "href": "/excel-validator", "keywords": "validate workbook qa rules excel"},
        {"group": "Go to", "label": "Documentation", "icon": "menu_book",
         "href": "/guide", "keywords": "docs help guide api faq troubleshooting getting started"},
    ]

    for t in TOOLS:  # Tools — every registered tool becomes a command
        commands.append({
            "group": "Open tool", "label": t["name"], "icon": t["icon"],
            "href": t["url"], "external": t.get("external", False),
            "keywords": t.get("keywords", "") + " " + t.get("category", ""),
        })

    # Ask OrchestrAI — example intents. They route to the best destination
    # today; an LLM can later resolve free text to the same intent shape.
    commands += [
        {"group": "Ask OrchestrAI", "label": "Validate today's BDR", "icon": "auto_awesome",
         "href": "/excel-validator", "keywords": "ai validate bdr today workbook", "ai": True},
        {"group": "Ask OrchestrAI", "label": "Show recent activity", "icon": "auto_awesome",
         "href": "/activity", "keywords": "ai failed workflows recent activity events", "ai": True},
        {"group": "Ask OrchestrAI", "label": "Open Media Tools", "icon": "auto_awesome",
         "href": "/tools", "keywords": "ai open media tools hub", "ai": True},
        {"group": "Ask OrchestrAI", "label": "Check system status", "icon": "auto_awesome",
         "href": "/dashboard", "keywords": "ai system health connected services status", "ai": True},
    ]
    return commands
