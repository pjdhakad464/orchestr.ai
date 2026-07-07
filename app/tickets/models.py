"""Ticket lifecycle domain model.

A Ticket moves through: intake → analyzed → pending_review → (approved |
rejected) → completed. Approval and ListenFirst ingestion are always human
actions — the engine never advances a ticket past `pending_review` on its own.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum


class Status(str, Enum):
    INTAKE = "intake"
    ANALYZED = "analyzed"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    COMPLETED = "completed"


class Severity(str, Enum):
    OK = "ok"
    INFO = "info"
    WARNING = "warning"
    BLOCKER = "blocker"


@dataclass
class Finding:
    """A single validation result."""
    check: str
    severity: Severity
    message: str
    detail: str = ""


@dataclass
class QAItem:
    label: str
    done: bool = False
    note: str = ""


@dataclass
class Ticket:
    raw_text: str
    ticket_id: str = ""
    client: str = "unknown"
    subject: str = ""
    request_type: str = "Other"
    request_confidence: str = "low"          # high | medium | low
    priority: str = "Normal"
    brands: list[str] = field(default_factory=list)
    talent: list[str] = field(default_factory=list)
    platforms: list[str] = field(default_factory=list)
    urls: list[str] = field(default_factory=list)
    requested_actions: list[str] = field(default_factory=list)

    findings: list[Finding] = field(default_factory=list)
    qa: list[QAItem] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    recommended_actions: list[str] = field(default_factory=list)
    research_notes: list[str] = field(default_factory=list)

    draft_reply: str = ""
    internal_notes: str = ""

    status: Status = Status.INTAKE
    confidence: str = "low"                  # overall, from validation
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    approver: str = ""
    decision_note: str = ""

    # ---- derived helpers -------------------------------------------------
    @property
    def blockers(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == Severity.BLOCKER]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == Severity.WARNING]

    @property
    def can_approve(self) -> bool:
        """Human can approve only a ticket awaiting review with no blockers."""
        return self.status == Status.PENDING_REVIEW and not self.blockers

    def to_dict(self) -> dict:
        d = asdict(self)
        d["status"] = self.status.value
        for f in d["findings"]:
            f["severity"] = f["severity"].value if hasattr(f["severity"], "value") else f["severity"]
        d["created_at"] = self.created_at.isoformat()
        d["updated_at"] = self.updated_at.isoformat()
        return d
