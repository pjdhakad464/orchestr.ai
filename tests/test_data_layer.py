import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.data.memory import InMemoryRepository
from app.tickets.engine import process
from app.tickets.models import Ticket, Status


def test_ticket_snapshot_roundtrip():
    t = process("Ticket #34481 Requester: Phil\nAdd talent Instagram https://instagram.com/x")
    restored = Ticket.from_dict(t.to_dict())
    assert restored.id == t.id
    assert restored.ticket_id == t.ticket_id
    assert restored.request_type == t.request_type
    assert restored.status == t.status
    assert [f.severity for f in restored.findings] == [f.severity for f in t.findings]
    assert [q.label for q in restored.qa] == [q.label for q in t.qa]
    assert restored.created_at == t.created_at


def test_inmemory_repository_crud():
    repo = InMemoryRepository()
    assert repo.durable is False
    t = process("Ticket #1 Requester: X\nAdd brand set (attached)")
    repo.save_ticket(t)
    assert repo.get_ticket(t.id).id == t.id
    assert len(repo.list_tickets()) == 1
    repo.log_activity(kind="ticket_received", title="queued", ticket_id=t.id)
    acts = repo.list_activity()
    assert acts and acts[0]["kind"] == "ticket_received"


def test_store_facade_uses_repository():
    from app.tickets.store import get_store
    store = get_store()
    t = process("Ticket #2 Requester: Y\nquestion about a brand?")
    store.add(t)
    assert store.get(t.id).id == t.id
    assert any(x.id == t.id for x in store.list())
    assert store.durable is False  # no DATABASE_URL in tests
