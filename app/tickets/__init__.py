"""Ticket lifecycle assistant.

Modules: models (domain) · engine (parse/classify/validate/QA/draft) ·
store (pluggable persistence). The engine prepares a ticket and stops at
PENDING_REVIEW; approval and ListenFirst ingestion are human actions handled
in the routes layer. Add a request type by extending engine.CLASSIFY_RULES;
add a datastore by implementing store.TicketStore.
"""

from .engine import process
from .models import Severity, Status, Ticket
from .store import get_store

__all__ = ["process", "get_store", "Ticket", "Status", "Severity"]
