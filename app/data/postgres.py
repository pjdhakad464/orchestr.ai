"""PostgreSQL / Supabase repository.

Activated by DATABASE_URL (see app/data/__init__.py). psycopg is imported
lazily so the app has no hard dependency on it until a database is attached.

Design: the full Ticket is stored as a JSONB `snapshot` for reliable
reconstruction, alongside normalized columns and child rows (validation
findings) written for querying/reporting. Every operation opens and closes its
own connection — friendly to serverless (use the Supabase connection pooler,
port 6543, transaction mode).

NOTE: activated by credentials; validated by construction (JSON round-trip),
pending a live smoke test once DATABASE_URL is provided.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from app.tickets.models import Ticket


class PostgresRepository:
    durable = True

    def __init__(self, dsn: str) -> None:
        import psycopg  # lazy: only required when a DB is configured
        self._psycopg = psycopg
        self._dsn = dsn
        # Fail fast if we cannot connect, so get_repository() can fall back.
        with self._connect() as conn:
            conn.execute("select 1")

    def _connect(self):
        return self._psycopg.connect(self._dsn, autocommit=True)

    # ---- tickets ---------------------------------------------------------
    def save_ticket(self, ticket: Ticket) -> None:
        snap = ticket.to_dict()
        with self._connect() as conn:
            conn.execute(
                """
                insert into tickets
                    (id, channel_key, external_ref, ticket_number, client,
                     subject, request_type, request_confidence, priority,
                     status, confidence, raw_text, snapshot, created_at, updated_at)
                values (%(id)s, %(channel)s, %(ext)s, %(num)s, %(client)s,
                        %(subject)s, %(rt)s, %(rc)s, %(priority)s, %(status)s,
                        %(conf)s, %(raw)s, %(snap)s, %(created)s, %(updated)s)
                on conflict (id) do update set
                    status=excluded.status, confidence=excluded.confidence,
                    request_type=excluded.request_type, subject=excluded.subject,
                    snapshot=excluded.snapshot, updated_at=excluded.updated_at
                """,
                {"id": ticket.id, "channel": "manual", "ext": ticket.ticket_id or None,
                 "num": ticket.ticket_id or None, "client": ticket.client,
                 "subject": ticket.subject, "rt": ticket.request_type,
                 "rc": ticket.request_confidence, "priority": ticket.priority,
                 "status": ticket.status.value, "conf": ticket.confidence,
                 "raw": ticket.raw_text, "snap": json.dumps(snap),
                 "created": ticket.created_at, "updated": ticket.updated_at},
            )
            conn.execute("delete from validation_findings where ticket_id=%s", (ticket.id,))
            for f in ticket.findings:
                conn.execute(
                    """insert into validation_findings
                       (ticket_id, check_key, severity, message, detail)
                       values (%s,%s,%s,%s,%s)""",
                    (ticket.id, f.check, f.severity.value, f.message, f.detail),
                )

    def get_ticket(self, ticket_id: str) -> Ticket | None:
        with self._connect() as conn:
            row = conn.execute(
                "select snapshot from tickets where id=%s", (ticket_id,)
            ).fetchone()
        if not row:
            return None
        snap = row[0] if isinstance(row[0], dict) else json.loads(row[0])
        return Ticket.from_dict(snap)

    def list_tickets(self, limit: int = 200) -> list[Ticket]:
        with self._connect() as conn:
            rows = conn.execute(
                "select snapshot from tickets order by created_at desc limit %s",
                (limit,),
            ).fetchall()
        out = []
        for (snap,) in rows:
            out.append(Ticket.from_dict(snap if isinstance(snap, dict) else json.loads(snap)))
        return out

    # ---- activity --------------------------------------------------------
    def log_activity(self, *, kind: str, title: str, actor: str = "system",
                     ticket_id: str | None = None,
                     detail: dict | None = None) -> None:
        with self._connect() as conn:
            conn.execute(
                """insert into activity_log (ticket_id, kind, actor, title, detail, at)
                   values (%s,%s,%s,%s,%s,%s)""",
                (ticket_id, kind, actor, title, json.dumps(detail or {}),
                 datetime.now(timezone.utc)),
            )

    def list_activity(self, limit: int = 50) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """select ticket_id, kind, actor, title, detail, at
                   from activity_log order by at desc limit %s""", (limit,),
            ).fetchall()
        return [{"ticket_id": r[0], "kind": r[1], "actor": r[2], "title": r[3],
                 "detail": r[4] if isinstance(r[4], dict) else json.loads(r[4] or "{}"),
                 "at": r[5]} for r in rows]
