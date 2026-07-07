"""Ticket processing engine — modular, deterministic, and honest.

Pipeline: parse → classify → validate → QA → draft. Each stage is a small
pure function so new request types or validators are added by extending a
table, not by touching the core. Nothing here calls ListenFirst or ingests
anything; it prepares a ticket for human review.

Design note: research (Phase 5) and live URL reachability need outbound calls
that are unreliable on a serverless host, so they are represented as
integration-ready recommendations rather than fabricated results — the engine
never invents data it did not verify.
"""

from __future__ import annotations

import re

from .models import Finding, QAItem, Severity, Status, Ticket

# --------------------------------------------------------------------------- #
# Phase 1 — parse
# --------------------------------------------------------------------------- #
_TICKET_ID = re.compile(r"(?:ticket\s*#?|#)\s*(\d{3,})", re.I)
_URL = re.compile(r"https?://[^\s<>\"')]+")
_REQUESTER = re.compile(r"(?:requester|from|client)\s*[:\-]\s*([^\n<|]+)", re.I)
_SUBJECT = re.compile(r"(?:subject|re)\s*[:\-]\s*([^\n<|]+)", re.I)
_HANDLE = re.compile(r"@([A-Za-z0-9._]{2,30})")

_PLATFORM_DOMAINS = {
    "instagram.com": "Instagram", "tiktok.com": "TikTok",
    "youtube.com": "YouTube", "youtu.be": "YouTube",
    "facebook.com": "Facebook", "twitter.com": "X", "x.com": "X",
    "open.spotify.com": "Spotify", "spotify.com": "Spotify",
    "podcasts.apple.com": "Apple Podcasts", "wikipedia.org": "Wikipedia",
    "imdb.com": "IMDb",
}


def parse(raw: str) -> Ticket:
    t = Ticket(raw_text=raw)
    m = _TICKET_ID.search(raw)
    if m:
        t.ticket_id = m.group(1)
    rm = _REQUESTER.search(raw)
    if rm:
        t.client = rm.group(1).strip()[:80]
    sm = _SUBJECT.search(raw)
    if sm:
        t.subject = sm.group(1).strip()[:140]
    t.urls = list(dict.fromkeys(u.rstrip(".,);") for u in _URL.findall(raw)))
    platforms = {p for u in t.urls for dom, p in _PLATFORM_DOMAINS.items() if dom in u}
    # platform words mentioned in prose
    for word, p in [("instagram", "Instagram"), ("tiktok", "TikTok"),
                    ("youtube", "YouTube"), ("facebook", "Facebook"),
                    ("spotify", "Spotify"), ("podcast", "Apple Podcasts"),
                    ("twitter", "X")]:
        if re.search(rf"\b{word}\b", raw, re.I):
            platforms.add(p)
    t.platforms = sorted(platforms)
    if re.search(r"\b(urgent|asap|high priority|priority:\s*urgent)\b", raw, re.I):
        t.priority = "High"
    return t


# --------------------------------------------------------------------------- #
# Phase 2 — classify (extensible rules table; first match wins)
# --------------------------------------------------------------------------- #
# (label, regex, keywords). Add a row to support a new request type.
CLASSIFY_RULES: list[tuple[str, str]] = [
    ("Brand Set Upload", r"brand set|brandset|roll-?up|upload.*set"),
    ("Talent Addition", r"\btalent\b|creator|influencer|add.*(person|cast)"),
    ("Handle Update", r"handle|username|update.*(profile|account|url)|correct.*profile"),
    ("YouTube Channel", r"youtube channel|yt channel"),
    ("Spotify", r"spotify"),
    ("Podcast", r"podcast"),
    ("Video Game", r"video game|\bgame\b|twitch"),
    ("Film", r"\bfilm\b|movie|box office|theatrical"),
    ("TV", r"\btv\b|series|episode|season|premiere"),
    ("Social Account Request", r"add.*(account|profile)|new account|social account"),
    ("Metadata Update", r"metadata|category|genre|sub-?category|taxonomy"),
    ("Brand Update", r"update.*brand|edit.*brand|brand.*change"),
    ("Brand Addition", r"add.*brand|new brand|brand addition|add the following"),
    ("Bug Report", r"\bbug\b|error|not working|broken|issue with"),
    ("Question", r"\?|question|how do|can you explain|wondering"),
]


def classify(t: Ticket) -> Ticket:
    hay = f"{t.subject}\n{t.raw_text}".lower()
    for label, pattern in CLASSIFY_RULES:
        if re.search(pattern, hay, re.I):
            t.request_type = label
            t.request_confidence = "high" if label != "Question" else "medium"
            return t
    t.request_type = "Other"
    t.request_confidence = "low"
    return t


# --------------------------------------------------------------------------- #
# Phase 3 — validate (returns findings; never guesses)
# --------------------------------------------------------------------------- #
def validate(t: Ticket) -> Ticket:
    f = t.findings

    if not t.ticket_id:
        f.append(Finding("ticket_id", Severity.WARNING,
                         "No ticket number detected in the request text."))
    if t.request_type == "Other":
        f.append(Finding("classification", Severity.WARNING,
                         "Request type could not be classified confidently.",
                         "Review manually and, if it is a new recurring type, "
                         "add a rule to the classifier."))

    # URL format + platform sanity (format only — reachability is not asserted)
    bad = [u for u in t.urls if not re.match(r"https?://[^\s]+\.[^\s]+", u)]
    for u in bad:
        f.append(Finding("url_format", Severity.BLOCKER,
                         "Malformed URL — cannot be used as provided.", u))
    if t.urls:
        f.append(Finding("url_reachability", Severity.INFO,
                         f"{len(t.urls)} URL(s) parsed. Live reachability check "
                         f"is an integration-ready step (not yet verified)."))

    # Request-type-specific required inputs
    needs_profile = t.request_type in {
        "Talent Addition", "Handle Update", "Social Account Request",
        "YouTube Channel", "Spotify", "Podcast"}
    if needs_profile and not t.urls and "@" not in t.raw_text:
        t.missing.append("At least one profile URL or @handle for the account(s).")
        f.append(Finding("required_input", Severity.BLOCKER,
                         "No profile URL or handle provided for an account request."))
    if t.request_type == "Brand Set Upload" and "attach" not in t.raw_text.lower() \
            and not any("docs.google.com" in u for u in t.urls):
        t.missing.append("The brand-set datasheet (attachment or Google Sheet link).")
        f.append(Finding("required_input", Severity.WARNING,
                         "Brand set requested but no datasheet/sheet link detected."))

    if not any(f_.severity == Severity.BLOCKER for f_ in f) and not t.missing:
        f.append(Finding("inputs", Severity.OK, "Required inputs appear present."))

    # Overall confidence
    if t.blockers:
        t.confidence = "low"
    elif t.warnings or t.missing:
        t.confidence = "medium"
    else:
        t.confidence = "high"
    return t


# --------------------------------------------------------------------------- #
# Phase 5/6 — research recommendations + QA (honest, no fabrication)
# --------------------------------------------------------------------------- #
_RESEARCH_BY_TYPE = {
    "Talent Addition": ["Verify identity via official handles + Wikidata",
                        "Confirm each platform account is the official one"],
    "Handle Update": ["Confirm the new handle resolves to the correct entity"],
    "Film": ["Cross-check IMDb ttcode and release date",
             "Check Box Office Mojo for the theatrical run"],
    "TV": ["Confirm IMDb season/episode data", "Check Metacritic premiere date"],
    "Spotify": ["Confirm the Spotify artist/show URI is official"],
    "Podcast": ["Confirm Apple Podcasts + Spotify show pages match"],
    "Brand Set Upload": ["Validate the datasheet against the ingest template",
                         "Run duplicate detection against existing brand sets"],
}


def build_qa(t: Ticket) -> Ticket:
    t.research_notes = _RESEARCH_BY_TYPE.get(t.request_type, [
        "Verify all provided information against approved sources before ingest."])

    t.qa = [
        QAItem("Request type classified", t.request_type != "Other"),
        QAItem("Ticket number captured", bool(t.ticket_id)),
        QAItem("Required inputs present", not t.missing and not t.blockers),
        QAItem("URLs parsed", bool(t.urls) or "no URLs in request" == ""),
        QAItem("No blocking validation errors", not t.blockers),
        QAItem("Research verified (manual)", False,
               "Confirm against approved sources before approval."),
        QAItem("Drive folder prepared", False,
               "Integration-ready — connect Drive to auto-create TicketID/ tree."),
    ]

    t.recommended_actions = []
    if t.missing:
        t.recommended_actions.append(
            "Request the missing information from the client before proceeding.")
    if t.blockers:
        t.recommended_actions.append(
            "Resolve blocking validation errors before this can be approved.")
    t.recommended_actions.append(
        f"Verify the {t.request_type.lower()} details against approved sources.")
    t.recommended_actions.append(
        "Review the draft reply, then approve to authorize ListenFirst ingestion.")
    return t


# --------------------------------------------------------------------------- #
# Phase 7 — draft response (never sent automatically)
# --------------------------------------------------------------------------- #
def draft_response(t: Ticket) -> Ticket:
    who = t.client if t.client and t.client != "unknown" else "there"
    if t.missing:
        needed = "\n".join(f"  • {m}" for m in t.missing)
        t.draft_reply = (
            f"Hi {who},\n\nThanks for the request. Before we proceed we need a "
            f"little more information:\n{needed}\n\nOnce we have that we'll get "
            f"this into the platform right away.\n\nBest,\nData Operations")
    else:
        t.draft_reply = (
            f"Hi {who},\n\nThanks for the request — we've reviewed the details "
            f"and everything needed is here. We'll complete this and confirm "
            f"once it's live in the platform.\n\nBest,\nData Operations")
    t.internal_notes = (
        f"Type: {t.request_type} ({t.request_confidence} confidence). "
        f"Confidence: {t.confidence}. "
        f"{len(t.blockers)} blocker(s), {len(t.warnings)} warning(s). "
        f"Prepared by OrchestrAI — awaiting human approval before ingestion.")
    return t


def process(raw: str) -> Ticket:
    """Full intake→review pipeline. Ends at PENDING_REVIEW — never further."""
    t = parse(raw)
    classify(t)
    validate(t)
    build_qa(t)
    draft_response(t)
    t.status = Status.PENDING_REVIEW
    return t
