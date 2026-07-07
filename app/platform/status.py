"""Operational status derived from REAL sources only.

Sources:
  * `settings` — presence of a configured key/file tells us honestly whether
    a capability is connected.
  * `validation_history` — the one first-party activity log this app owns.

Anything the platform cannot observe yet (automation runs, workflow queue —
these live in the separate automation service) is returned by
`integration_ready_panels()` as an explicit "not connected" panel, so the UI
can show an integration-ready placeholder instead of a fabricated number.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.config import settings

try:  # validation history is optional / may be empty on ephemeral hosts
    from app.services.validation_history import list_validation_runs
except Exception:  # pragma: no cover - defensive
    list_validation_runs = None  # type: ignore


def connected_services() -> list[dict]:
    """Honest connection status from configured credentials. 'Available'
    means no key is required (public API); 'Connected' means a key/file is
    present; 'Not configured' means the integration is ready but unset."""
    def state(present: bool) -> str:
        return "Connected" if present else "Not configured"

    return [
        {"name": "IMDb / TMDB Enrichment", "icon": "movie",
         "status": state(bool(settings.tmdb_api_key
                              or settings.tmdb_read_access_token
                              or settings.omdb_api_key))},
        {"name": "Web Search", "icon": "travel_explore",
         "status": state(bool(settings.serpapi_api_key))},
        {"name": "Google Drive", "icon": "folder",
         "status": state(bool(settings.google_service_account_file
                              or settings.google_drive_folder_id))},
        {"name": "IMDb Dataset Index", "icon": "database",
         "status": state(bool(settings.imdb_dataset_dir))},
        {"name": "Wikidata", "icon": "public", "status": "Available"},
    ]


def _runs(limit: int | None = None) -> list:
    if list_validation_runs is None:
        return []
    try:
        return list_validation_runs(limit=limit)
    except Exception:
        return []


def dashboard_summary() -> dict:
    """Counts from real validation history. Zeroes and an `has_data` flag let
    the template show an honest empty state — no invented figures."""
    runs = _runs(limit=500)
    today = datetime.now(timezone.utc).date()
    todays = [r for r in runs if r.created_at.astimezone(timezone.utc).date() == today]
    clean = [r for r in runs if r.issue_count == 0]
    return {
        "has_data": bool(runs),
        "total_validations": len(runs),
        "validations_today": len(todays),
        "clean_runs": len(clean),
        "flagged_runs": len(runs) - len(clean),
        "total_issues": sum(r.issue_count for r in runs),
    }


def recent_activity(limit: int = 12) -> list[dict]:
    """Unified activity timeline from real validation runs (the first-party
    source this app owns). Returns [] when there is nothing to show."""
    items = []
    for r in _runs(limit=limit):
        clean = r.issue_count == 0
        items.append({
            "kind": "validation",
            "icon": "shield",
            "tone": "success" if clean else "warning",
            "title": "Validation completed"
                     + ("" if clean else f" · {r.issue_count} issue"
                        + ("s" if r.issue_count != 1 else "")),
            "subject": r.original_filename,
            "actor": r.run_by or "—",
            "at": r.created_at.astimezone(timezone.utc),
            "href": f"/api/v1/validate/{r.validation_id}",
        })
    return items


def integration_ready_panels() -> list[dict]:
    """Operational surfaces that require the automation service (separate
    deployment). Shown as integration-ready placeholders — never fabricated.
    Wire a real feed by giving each panel a `source` later."""
    return [
        {"key": "automation", "title": "Automation status", "icon": "bolt",
         "note": "Connect the automation service to show today's scheduled runs."},
        {"key": "workflows", "title": "Active workflows", "icon": "account_tree",
         "note": "Live workflow runs appear here once a feed is connected."},
        {"key": "queue", "title": "Queue status", "icon": "queue",
         "note": "Pending and in-flight jobs will surface here."},
        {"key": "reports", "title": "Recent reports", "icon": "description",
         "note": "Generated reports will be listed here when reporting is enabled."},
    ]
