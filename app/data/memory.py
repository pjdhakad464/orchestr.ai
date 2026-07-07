"""In-memory repository — the safe default when no database is configured.

Process-local and ephemeral (durable=False) so the UI can warn honestly. Same
interface as the Postgres adapter, so swapping is invisible to callers.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # avoid an import cycle (app.tickets imports app.data)
    from app.tickets.models import Ticket


class InMemoryRepository:
    durable = False

    def __init__(self) -> None:
        self._tickets: dict[str, Ticket] = {}
        self._activity: list[dict] = []

    def save_ticket(self, ticket: Ticket) -> None:
        self._tickets[ticket.id] = ticket

    def get_ticket(self, ticket_id: str) -> Ticket | None:
        return self._tickets.get(ticket_id)

    def list_tickets(self, limit: int = 200) -> list[Ticket]:
        return sorted(self._tickets.values(),
                      key=lambda t: t.created_at, reverse=True)[:limit]

    def log_activity(self, *, kind: str, title: str, actor: str = "system",
                     ticket_id: str | None = None,
                     detail: dict | None = None) -> None:
        self._activity.append({
            "kind": kind, "title": title, "actor": actor,
            "ticket_id": ticket_id, "detail": detail or {},
            "at": datetime.now(timezone.utc),
        })

    def list_activity(self, limit: int = 50) -> list[dict]:
        return sorted(self._activity, key=lambda a: a["at"], reverse=True)[:limit]
