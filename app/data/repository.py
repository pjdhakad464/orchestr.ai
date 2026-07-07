"""Repository interface — the single seam every datastore implements.

Kept intentionally small and storage-agnostic: the domain (app/tickets) and
UI speak only this protocol. Ticket objects are the currency; activity events
are dicts (kind/title/actor/at/detail) so any source can log to one timeline.
"""

from __future__ import annotations

from typing import Protocol, TYPE_CHECKING

if TYPE_CHECKING:  # avoid an import cycle (app.tickets imports app.data)
    from app.tickets.models import Ticket


class Repository(Protocol):
    durable: bool

    # ---- tickets ---------------------------------------------------------
    def save_ticket(self, ticket: Ticket) -> None: ...
    def get_ticket(self, ticket_id: str) -> Ticket | None: ...
    def list_tickets(self, limit: int = 200) -> list[Ticket]: ...

    # ---- activity log ----------------------------------------------------
    def log_activity(self, *, kind: str, title: str, actor: str = "system",
                     ticket_id: str | None = None,
                     detail: dict | None = None) -> None: ...
    def list_activity(self, limit: int = 50) -> list[dict]: ...
