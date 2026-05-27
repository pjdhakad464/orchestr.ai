from __future__ import annotations

from datetime import datetime, timedelta, timezone
from secrets import token_urlsafe

from .models import AnalyzedComment, AuthSession


class InMemoryAuthStore:
    def __init__(self) -> None:
        self._states: dict[str, datetime] = {}
        self._sessions: dict[str, AuthSession] = {}
        self._ttl = timedelta(hours=2)

    def create_state(self) -> str:
        self._prune()
        state = token_urlsafe(24)
        self._states[state] = datetime.now(timezone.utc)
        return state

    def consume_state(self, state: str) -> bool:
        self._prune()
        return self._states.pop(state, None) is not None

    def create_session(self, access_token: str, graph_version: str) -> AuthSession:
        self._prune()
        session = AuthSession(
            session_id=token_urlsafe(24),
            access_token=access_token,
            created_at=datetime.now(timezone.utc),
            graph_version=graph_version,
        )
        self._sessions[session.session_id] = session
        return session

    def get_session(self, session_id: str) -> AuthSession | None:
        self._prune()
        return self._sessions.get(session_id)

    def _prune(self) -> None:
        cutoff = datetime.now(timezone.utc) - self._ttl
        self._states = {k: v for k, v in self._states.items() if v >= cutoff}
        self._sessions = {k: v for k, v in self._sessions.items() if v.created_at >= cutoff}


auth_store = InMemoryAuthStore()


class InMemoryExportStore:
    def __init__(self) -> None:
        self._exports: dict[str, tuple[datetime, dict]] = {}
        self._ttl = timedelta(hours=2)

    def create_export(self, *, results: list[AnalyzedComment], source_name: str) -> str:
        self._prune()
        export_id = token_urlsafe(18)
        self._exports[export_id] = (
            datetime.now(timezone.utc),
            {
                "results": results,
                "source_name": source_name,
            },
        )
        return export_id

    def get_export(self, export_id: str) -> dict | None:
        self._prune()
        record = self._exports.get(export_id)
        if not record:
            return None
        return record[1]

    def _prune(self) -> None:
        cutoff = datetime.now(timezone.utc) - self._ttl
        self._exports = {k: v for k, v in self._exports.items() if v[0] >= cutoff}


export_store = InMemoryExportStore()
