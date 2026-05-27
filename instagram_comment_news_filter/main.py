from __future__ import annotations

from fastapi import FastAPI, File, Form, HTTPException, UploadFile

from .classifier import classify_comments
from .instagram_api import InstagramConfigError, fetch_owned_media_comments
from .io_utils import parse_uploaded_comments
from .models import ClassificationRequest, ClassificationResponse


app = FastAPI(
    title="Instagram Comment News Filter",
    version="0.1.0",
    description=(
        "Standalone prototype for identifying off-topic Instagram comments that look like "
        "world news or locale news. Public third-party scraping is intentionally not included."
    ),
)


@app.get("/health")
async def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/")
async def root() -> dict[str, object]:
    return {
        "app": "Instagram Comment News Filter",
        "supported_inputs": [
            "POST /classify with JSON comments",
            "POST /classify-file with CSV or JSON upload",
            "POST /instagram/media/{media_id}/comments/classify for owner-authorized collection",
        ],
        "note": (
            "Use the Instagram endpoint only for media you are authorized to manage via Meta's official API."
        ),
    }


@app.post("/classify", response_model=ClassificationResponse)
async def classify_payload(request: ClassificationRequest) -> ClassificationResponse:
    results = classify_comments(
        request.comments,
        locale_hint=request.locale_hint,
        local_terms=request.local_terms,
        candidates_only=request.candidates_only,
    )
    return _build_response(results, total_comments=len(request.comments), locale_hint=request.locale_hint)


@app.post("/classify-file", response_model=ClassificationResponse)
async def classify_file(
    comments_file: UploadFile = File(...),
    locale_hint: str | None = Form(default=None),
    local_terms: str | None = Form(default=None),
    candidates_only: bool = Form(default=False),
) -> ClassificationResponse:
    try:
        payload = await comments_file.read()
        comments = parse_uploaded_comments(comments_file.filename or "comments.csv", payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    parsed_local_terms = [term.strip() for term in (local_terms or "").split(",") if term.strip()]
    results = classify_comments(
        comments,
        locale_hint=locale_hint,
        local_terms=parsed_local_terms,
        candidates_only=candidates_only,
    )
    return _build_response(results, total_comments=len(comments), locale_hint=locale_hint)


@app.post("/instagram/media/{media_id}/comments/classify", response_model=ClassificationResponse)
async def classify_owned_instagram_media(
    media_id: str,
    locale_hint: str | None = Form(default=None),
    local_terms: str | None = Form(default=None),
    limit: int = Form(default=100),
    candidates_only: bool = Form(default=True),
) -> ClassificationResponse:
    parsed_local_terms = [term.strip() for term in (local_terms or "").split(",") if term.strip()]
    try:
        comments = await fetch_owned_media_comments(media_id, limit=limit)
    except InstagramConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover - protects against live API errors
        raise HTTPException(status_code=502, detail=f"Instagram API request failed: {exc}") from exc

    results = classify_comments(
        comments,
        locale_hint=locale_hint,
        local_terms=parsed_local_terms,
        candidates_only=candidates_only,
    )
    return _build_response(results, total_comments=len(comments), locale_hint=locale_hint)


def _build_response(results, *, total_comments: int, locale_hint: str | None) -> ClassificationResponse:
    candidates_found = sum(1 for item in results if item.is_candidate)
    return ClassificationResponse(
        total_comments=total_comments,
        returned_comments=len(results),
        candidates_found=candidates_found,
        locale_hint=locale_hint,
        comments=results,
    )

