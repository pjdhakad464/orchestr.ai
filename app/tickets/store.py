"""Ticket storage — pluggable interface.

`TicketStore` is the seam a durable backend drops into (Postgres, Redis, a
managed KV, etc.) without touching the engine or the UI. The shipped default
is `InMemoryTicketStore`, which is EPHEMERAL: on a serverless host it does not
persist across requests. The UI surfaces this honestly ("ephemeral store")
rather than pretending queued tickets are durable.

To make the queue production-durable, implement this interface against a real
datastore and return it from `get_store()` when a connection string is set.
"""

from __future__ import annotations

from typing import Protocol

from .models import Ticket


class TicketStore(Protocol):
    def add(self, ticket: Ticket) -> None: ...
    def get(self, ticket_id: str) -> Ticket | None: ...
    def list(self) -> list[Ticket]: ...
    def update(self, ticket: Ticket) -> None: ...
    @property
    def durable(self) -> bool: ...


class InMemoryTicketStore:
    """Process-local store. Durable=False so the UI can warn the operator."""

    def __init__(self) -> None:
        self._items: dict[str, Ticket] = {}

    durable = False

    def add(self, ticket: Ticket) -> None:
        self._items[ticket.id] = ticket

    def get(self, ticket_id: str) -> Ticket | None:
        return self._items.get(ticket_id)

    def list(self) -> list[Ticket]:
        return sorted(self._items.values(), key=lambda t: t.created_at, reverse=True)

    def update(self, ticket: Ticket) -> None:
        self._items[ticket.id] = ticket


_STORE: TicketStore | None = None


def get_store() -> TicketStore:
    """Return the active store. Swap in a durable implementation here once a
    datastore is provisioned (e.g. read a connection string from settings)."""
    global _STORE
    if _STORE is None:
        _STORE = InMemoryTicketStore()
    return _STORE
