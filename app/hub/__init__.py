"""Media Tools Hub feature module.

The tool catalog lives in `catalog.py` (edit that to add/relabel a tool),
the markup in `app/templates/hub.html`, styles in `app/static/hub/hub.css`,
and client behavior (search / filter / favorites / recently-used) in
`app/static/hub/hub.js`. Favorites and recent history are client-side only
(localStorage) — no API, no server state.
"""

from .catalog import CATEGORIES, TOOLS

__all__ = ["CATEGORIES", "TOOLS"]
