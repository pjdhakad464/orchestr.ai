"""Ticket storage — now delegates to the datastore-agnostic data layer.

Kept as a thin facade so existing callers (routes) are unchanged. The actual
persistence (in-memory or Postgres/Supabase) is decided in app/data. `durable`
reflects the active backend so the UI can warn when state is ephemeral.
"""

from __future__ import annotations

from app.data import get_repository
from .models import Ticket


class _RepoBackedStore:
    def add(self, ticket: Ticket) -> None:
        repo = get_repository()
        repo.save_ticket(ticket)
        repo.log_activity(kind="ticket_received", title="Ticket queued for review",
                          actor=ticket.client or "system", ticket_id=ticket.id,
                          detail={"request_type": ticket.request_type})

    def get(self, ticket_id: str) -> Ticket | None:
        return get_repository().get_ticket(ticket_id)

    def list(self) -> list[Ticket]:
        return get_repository().list_tickets()

    def update(self, ticket: Ticket) -> None:
        repo = get_repository()
        repo.save_ticket(ticket)
        repo.log_activity(kind=f"ticket_{ticket.status.value}",
                          title=f"Ticket {ticket.status.value.replace('_', ' ')}",
                          actor=ticket.approver or "operator", ticket_id=ticket.id)

    @property
    def durable(self) -> bool:
        return get_repository().durable


_STORE = _RepoBackedStore()


def get_store() -> _RepoBackedStore:
    return _STORE
