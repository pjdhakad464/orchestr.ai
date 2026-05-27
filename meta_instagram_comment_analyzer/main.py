from __future__ import annotations

import csv
import io
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from .analysis import analyze_comments
from .config import settings
from .dataset_parser import parse_uploaded_comments
from .meta_client import MetaGraphClient, MetaOAuthError
from .store import auth_store, export_store


app = FastAPI(
    title="Instagram Comment Dataset Analyzer",
    version="0.1.0",
    description=(
        "Standalone app for analyzing uploaded Instagram comment datasets, with an optional "
        "owner-authorized Meta API path for accounts you manage."
    ),
)

templates = Jinja2Templates(directory=str(Path(__file__).with_name("templates")))


@app.get("/", response_class=HTMLResponse)
async def index(request: Request, session_id: str | None = None, error: str | None = None) -> HTMLResponse:
    accounts = []
    if session_id:
        session = auth_store.get_session(session_id)
        if session:
            client = MetaGraphClient(access_token=session.access_token, graph_version=session.graph_version)
            try:
                accounts = await client.get_instagram_accounts()
            except Exception as exc:  # pragma: no cover - protects live API flow
                error = f"Could not load Instagram accounts: {exc}"
        else:
            error = "The authorization session is missing or expired. Connect again."
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "settings": settings,
            "session_id": session_id,
            "accounts": accounts,
            "error": error,
            "connected": bool(accounts),
        },
    )


@app.post("/analyze-upload", response_class=HTMLResponse)
async def analyze_upload(
    request: Request,
    comments_file: UploadFile = File(...),
    extra_spotify_terms: str = Form(default=""),
    locale_terms: str = Form(default=""),
    only_offtopic: bool = Form(default=True),
) -> HTMLResponse:
    try:
        payload = await comments_file.read()
        comments = parse_uploaded_comments(comments_file.filename or "comments.csv", payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    results = analyze_comments(
        comments,
        extra_spotify_terms=_split_terms(extra_spotify_terms),
        locale_terms=_split_terms(locale_terms),
        only_offtopic=only_offtopic,
    )
    export_id = export_store.create_export(
        results=results,
        source_name=_safe_source_name(comments_file.filename or "uploaded_comments"),
    )
    return _render_results(
        request=request,
        source_label=comments_file.filename or "Uploaded dataset",
        comments_scanned=len(comments),
        results=results,
        media_limit=None,
        comments_per_media=None,
        only_offtopic=only_offtopic,
        extra_spotify_terms=extra_spotify_terms,
        locale_terms=locale_terms,
        export_url=f"/exports/{export_id}.csv",
    )


@app.get("/connect")
async def connect() -> RedirectResponse:
    if not settings.meta_app_id or not settings.meta_app_secret:
        raise HTTPException(status_code=400, detail="Set META_APP_ID and META_APP_SECRET before connecting.")
    state = auth_store.create_state()
    authorize_url = MetaGraphClient().build_authorize_url(state=state)
    return RedirectResponse(authorize_url, status_code=302)


@app.get("/auth/callback")
async def auth_callback(code: str | None = None, state: str | None = None, error: str | None = None) -> RedirectResponse:
    if error:
        params = urlencode({"error": f"Meta returned an authorization error: {error}"})
        return RedirectResponse(f"/?{params}", status_code=302)
    if not code or not state or not auth_store.consume_state(state):
        params = urlencode({"error": "Invalid or expired OAuth callback state."})
        return RedirectResponse(f"/?{params}", status_code=302)

    client = MetaGraphClient()
    try:
        token_payload = await client.exchange_code(code)
    except MetaOAuthError as exc:
        params = urlencode({"error": f"Access token exchange failed: {exc}"})
        return RedirectResponse(f"/?{params}", status_code=302)

    access_token = token_payload.get("access_token")
    if not access_token:
        params = urlencode({"error": "Meta response did not include an access token."})
        return RedirectResponse(f"/?{params}", status_code=302)

    session = auth_store.create_session(access_token=access_token, graph_version=settings.meta_graph_version)
    params = urlencode({"session_id": session.session_id})
    return RedirectResponse(f"/?{params}", status_code=302)


@app.post("/analyze", response_class=HTMLResponse)
async def analyze(
    request: Request,
    session_id: str = Form(...),
    instagram_user_id: str = Form(...),
    media_limit: int = Form(default=settings.default_media_limit),
    comments_per_media: int = Form(default=settings.default_comments_per_media),
    extra_spotify_terms: str = Form(default=""),
    locale_terms: str = Form(default=""),
    only_offtopic: bool = Form(default=True),
) -> HTMLResponse:
    session = auth_store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=400, detail="Authorization session expired. Connect again.")

    comments, results = await _run_meta_analysis(
        session_id=session_id,
        instagram_user_id=instagram_user_id,
        media_limit=media_limit,
        comments_per_media=comments_per_media,
        extra_spotify_terms=extra_spotify_terms,
        locale_terms=locale_terms,
        only_offtopic=only_offtopic,
    )
    export_id = export_store.create_export(results=results, source_name=instagram_user_id)
    return _render_results(
        request=request,
        source_label=f"Meta account {instagram_user_id}",
        comments_scanned=len(comments),
        results=results,
        media_limit=media_limit,
        comments_per_media=comments_per_media,
        only_offtopic=only_offtopic,
        extra_spotify_terms=extra_spotify_terms,
        locale_terms=locale_terms,
        export_url=f"/exports/{export_id}.csv",
    )


@app.get("/exports/{export_id}.csv")
async def export_saved_csv(export_id: str) -> Response:
    export_record = export_store.get_export(export_id)
    if not export_record:
        raise HTTPException(status_code=404, detail="Export expired or was not found.")
    results = export_record["results"]
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer,
        fieldnames=[
            "media_id",
            "media_permalink",
            "comment_id",
            "username",
            "timestamp",
            "text",
            "relevance",
            "sentiment",
            "sentiment_score",
            "confidence",
            "matched_spotify_terms",
            "matched_offtopic_terms",
            "reasons",
        ],
    )
    writer.writeheader()
    for item in results:
        writer.writerow(
            {
                "media_id": item.media_id,
                "media_permalink": item.media_permalink or "",
                "comment_id": item.comment_id,
                "username": item.username or "",
                "timestamp": item.timestamp.isoformat() if item.timestamp else "",
                "text": item.text,
                "relevance": item.relevance,
                "sentiment": item.sentiment,
                "sentiment_score": item.sentiment_score,
                "confidence": item.confidence,
                "matched_spotify_terms": ", ".join(item.matched_spotify_terms),
                "matched_offtopic_terms": ", ".join(item.matched_offtopic_terms),
                "reasons": " | ".join(item.reasons),
            }
        )

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"instagram_comment_analysis_{export_record['source_name']}_{timestamp}.csv"
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


async def _run_meta_analysis(
    *,
    session_id: str,
    instagram_user_id: str,
    media_limit: int,
    comments_per_media: int,
    extra_spotify_terms: str,
    locale_terms: str,
    only_offtopic: bool,
):
    session = auth_store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=400, detail="Authorization session expired. Connect again.")

    client = MetaGraphClient(access_token=session.access_token, graph_version=session.graph_version)
    try:
        comments = await client.get_recent_media_comments(
            instagram_user_id,
            media_limit=media_limit,
            comments_per_media=comments_per_media,
        )
    except Exception as exc:  # pragma: no cover - protects live API flow
        raise HTTPException(status_code=502, detail=f"Meta Graph API request failed: {exc}") from exc

    results = analyze_comments(
        comments,
        extra_spotify_terms=_split_terms(extra_spotify_terms),
        locale_terms=_split_terms(locale_terms),
        only_offtopic=only_offtopic,
    )
    return comments, results


@app.get("/api/accounts")
async def api_accounts(session_id: str):
    session = auth_store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=400, detail="Authorization session expired. Connect again.")
    client = MetaGraphClient(access_token=session.access_token, graph_version=session.graph_version)
    accounts = await client.get_instagram_accounts()
    return {"accounts": [asdict(account) for account in accounts]}


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


def _render_results(
    *,
    request: Request,
    source_label: str,
    comments_scanned: int,
    results,
    media_limit: int | None,
    comments_per_media: int | None,
    only_offtopic: bool,
    extra_spotify_terms: str,
    locale_terms: str,
    export_url: str,
) -> HTMLResponse:
    summary = {
        "total_comments_scanned": comments_scanned,
        "returned_comments": len(results),
        "relevance_counts": Counter(item.relevance for item in results),
        "sentiment_counts": Counter(item.sentiment for item in results),
    }
    return templates.TemplateResponse(
        request,
        "results.html",
        {
            "source_label": source_label,
            "summary": summary,
            "results": results,
            "media_limit": media_limit,
            "comments_per_media": comments_per_media,
            "only_offtopic": only_offtopic,
            "extra_spotify_terms": extra_spotify_terms,
            "locale_terms": locale_terms,
            "export_url": export_url,
        },
    )


def _split_terms(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _safe_source_name(value: str) -> str:
    stem = Path(value).stem
    cleaned = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in stem)
    return cleaned or "uploaded_comments"
