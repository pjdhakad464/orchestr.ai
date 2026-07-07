import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.tickets.engine import process, classify, parse
from app.tickets.models import Ticket, Status, Severity


TALENT = """Ticket #34481 — PV Talent Spreadsheet Tracking
Requester: Phil Cutler
Please add the official social profiles for the talent/cast. Instagram and TikTok.
https://www.instagram.com/alanritchson"""

BRANDSET = """Ticket #34473 Subject: Brand Set Upload 7/1
Requester: Elliott
Could we please get the attached brand set uploaded?"""

VAGUE = """Requester: Someone
hey can you help with a thing"""


def test_parse_extracts_core_fields():
    t = parse(TALENT)
    assert t.ticket_id == "34481"
    assert "Phil Cutler" in t.client
    assert "Instagram" in t.platforms and "TikTok" in t.platforms
    assert any("instagram.com/alanritchson" in u for u in t.urls)


def test_classify_talent_and_brandset():
    assert classify(parse(TALENT)).request_type in {"Talent Addition", "Handle Update", "Social Account Request"}
    assert classify(parse(BRANDSET)).request_type == "Brand Set Upload"


def test_pipeline_stops_at_pending_review():
    t = process(TALENT)
    assert t.status == Status.PENDING_REVIEW  # never auto-advances
    assert t.draft_reply and t.qa and t.recommended_actions


def test_missing_inputs_flagged_not_assumed():
    # An account request with no URL/handle must flag a blocker, not proceed
    t = process("Ticket #1 Requester: X\nPlease add a new social account for our brand")
    assert t.missing or t.blockers
    assert not t.can_approve  # cannot approve with blockers


def test_clean_ticket_can_be_approved():
    t = process(TALENT)
    # talent ticket has a URL + handle, so no required-input blocker
    assert not t.blockers
    assert t.can_approve


def test_unclassifiable_is_other_low_confidence():
    t = process(VAGUE)
    assert t.request_type == "Other"
    assert t.confidence in {"low", "medium"}


def test_no_fabricated_research():
    # research notes are instructions to verify, never asserted facts
    t = process(TALENT)
    assert all("verify" in n.lower() or "confirm" in n.lower() or "check" in n.lower()
               or "validate" in n.lower() for n in t.research_notes)
