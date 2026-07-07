"""Platform core — the extensibility spine.

`status.py` derives operational state from real sources only (config presence
and the validation history DB). Anything without a live data source is
reported honestly as "not connected / integration-ready" — this module never
fabricates metrics.
"""

from .commands import build_commands
from .status import (
    connected_services,
    dashboard_summary,
    integration_ready_panels,
    recent_activity,
)

__all__ = [
    "build_commands",
    "connected_services",
    "dashboard_summary",
    "integration_ready_panels",
    "recent_activity",
]
