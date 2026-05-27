from __future__ import annotations

import csv
import io
import re
import uuid
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from openpyxl import Workbook
from pydantic import ValidationError

from title_url_lookup_app.cache import TTLCache
from title_url_lookup_app.config import settings
from title_url_lookup_app.models import (
    BulkTitleLookupRequest,
    BulkTitleLookupResponse,
    DownloadArtifact,
    TitleLookupQuery,
    TitleLookupResponse,
    TitleType,
    TitleUrlExportRow,
)
from title_url_lookup_app.services.title_lookup import TitleUrlLookupService


BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
router = APIRouter()
lookup_service = TitleUrlLookupService()
cache = TTLCache(settings.title_lookup_export_ttl_seconds)

TITLE_TYPE_OPTIONS: list[tuple[TitleType, str]] = [
    ("any", "Auto detect"),
    ("movie", "Movie"),
    ("tv", "TV show / series"),
]


def _metacritic_redirect_url(request: Request, target_path: str) -> str:
    query_string = request.url.query
    base_url = settings.metacritic_calendar_base_url.rstrip("/")
    url = f"{base_url}{target_path}"
    if query_string:
        return f"{url}?{query_string}"
    return url


@router.get("/calendar", include_in_schema=False)
async def redirect_metacritic_calendar_home(request: Request) -> RedirectResponse:
    return RedirectResponse(_metacritic_redirect_url(request, "/"), status_code=307)


@router.get("/calendar/search", include_in_schema=False)
async def redirect_metacritic_calendar_search_page(request: Request) -> RedirectResponse:
    return RedirectResponse(_metacritic_redirect_url(request, "/"), status_code=307)


@router.post("/calendar/search", include_in_schema=False)
async def redirect_metacritic_calendar_search_submit(request: Request) -> RedirectResponse:
    return RedirectResponse(_metacritic_redirect_url(request, "/calendar/search"), status_code=307)


@router.get("/api/calendar", include_in_schema=False)
async def redirect_metacritic_calendar_api(request: Request) -> RedirectResponse:
    return RedirectResponse(_metacritic_redirect_url(request, "/api/calendar"), status_code=307)


@router.post("/box-office-mojo/search", include_in_schema=False)
async def redirect_box_office_mojo_last_7_days(request: Request) -> RedirectResponse:
    return RedirectResponse(_metacritic_redirect_url(request, "/box-office-mojo/search"), status_code=307)


@router.post("/box-office-mojo/upcoming-12-months/search", include_in_schema=False)
async def redirect_box_office_mojo_upcoming_12_months(request: Request) -> RedirectResponse:
    return RedirectResponse(_metacritic_redirect_url(request, "/box-office-mojo/upcoming-12-months/search"), status_code=307)


@router.get("/api/box-office-mojo/last-7-days", include_in_schema=False)
async def redirect_box_office_mojo_last_7_days_api(request: Request) -> RedirectResponse:
    return RedirectResponse(_metacritic_redirect_url(request, "/api/box-office-mojo/last-7-days"), status_code=307)


@router.get("/api/box-office-mojo/upcoming-12-months", include_in_schema=False)
async def redirect_box_office_mojo_upcoming_12_months_api(request: Request) -> RedirectResponse:
    return RedirectResponse(_metacritic_redirect_url(request, "/api/box-office-mojo/upcoming-12-months"), status_code=307)


@router.get("/export/{export_id}/csv", include_in_schema=False)
async def redirect_metacritic_calendar_export(request: Request, export_id: str) -> RedirectResponse:
    return RedirectResponse(_metacritic_redirect_url(request, f"/export/{export_id}/csv"), status_code=307)


@router.get("/box-office-mojo/export/{export_id}/{fmt}", include_in_schema=False)
async def redirect_box_office_mojo_export(request: Request, export_id: str, fmt: str) -> RedirectResponse:
    return RedirectResponse(_metacritic_redirect_url(request, f"/box-office-mojo/export/{export_id}/{fmt}"), status_code=307)


def static_asset_version(*relative_paths: str) -> str:
    versions: list[int] = []
    for relative_path in relative_paths:
        asset_path = BASE_DIR / "static" / relative_path
        try:
            versions.append(asset_path.stat().st_mtime_ns)
        except FileNotFoundError:
            continue
    if not versions:
        return "1"
    return str(max(versions))


def build_context(
    request: Request,
    *,
    result: TitleLookupResponse | None = None,
    bulk_result: BulkTitleLookupResponse | None = None,
    error_message: str = "",
    title: str = "",
    year: str = "",
    selected_title_type: TitleType = "any",
    bulk_entries: str = "",
) -> dict[str, object]:
    return {
        "request": request,
        "result": result,
        "bulk_result": bulk_result,
        "error_message": error_message,
        "title": title,
        "year": year,
        "selected_title_type": selected_title_type,
        "bulk_entries": bulk_entries,
        "title_type_options": TITLE_TYPE_OPTIONS,
        "asset_version": static_asset_version("styles.css"),
    }


def parse_bulk_entries(raw_text: str, default_title_type: TitleType = "any") -> list[TitleLookupQuery]:
    entries: list[TitleLookupQuery] = []
    for line in raw_text.splitlines():
        cleaned = line.strip()
        if not cleaned:
            continue
        parts = [part.strip() for part in cleaned.split("|")]
        title = parts[0]
        year = parts[1] if len(parts) > 1 else ""
        title_type = parts[2] if len(parts) > 2 and parts[2] else default_title_type
        entries.append(TitleLookupQuery(title=title, year=year, title_type=title_type))  # type: ignore[arg-type]
    if not entries:
        raise ValueError("Add at least one title line for bulk lookup.")
    return entries


def build_export_rows(entries: list[TitleLookupResponse]) -> list[TitleUrlExportRow]:
    rows: list[TitleUrlExportRow] = []
    for entry in entries:
        for site in entry.results:
            primary = site.primary
            rows.append(
                TitleUrlExportRow(
                    input_title=entry.query.title,
                    input_year=entry.query.year,
                    input_type=entry.query.title_type,
                    site=site.site_label,
                    status=site.status,
                    url=primary.url if primary else "",
                    matched_title=primary.result_title if primary else "",
                    score=primary.score if primary else None,
                    alternates=[item.url for item in site.alternates],
                    notes=[*entry.notes, *site.notes],
                )
            )
    return rows


def rows_to_csv_bytes(rows: list[TitleUrlExportRow]) -> bytes:
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer,
        fieldnames=[
            "input_title",
            "input_year",
            "input_type",
            "site",
            "status",
            "url",
            "matched_title",
            "score",
            "alternates",
            "notes",
        ],
    )
    writer.writeheader()
    for row in rows:
        payload = row.model_dump()
        payload["alternates"] = " | ".join(row.alternates)
        payload["notes"] = " | ".join(row.notes)
        writer.writerow(payload)
    return buffer.getvalue().encode("utf-8-sig")


def rows_to_xlsx_bytes(rows: list[TitleUrlExportRow], summary: list[str]) -> bytes:
    workbook = Workbook()
    summary_sheet = workbook.active
    summary_sheet.title = "Summary"
    summary_sheet.append(["Item", "Value"])
    for index, item in enumerate(summary, start=1):
        summary_sheet.append([f"Summary {index}", item])

    results_sheet = workbook.create_sheet("Results")
    headers = [
        "Input Title",
        "Input Year",
        "Input Type",
        "Site",
        "Status",
        "URL",
        "Matched Title",
        "Score",
        "Alternates",
        "Notes",
    ]
    results_sheet.append(headers)
    for row in rows:
        results_sheet.append(
            [
                row.input_title,
                row.input_year,
                row.input_type,
                row.site,
                row.status,
                row.url,
                row.matched_title,
                row.score if row.score is not None else "",
                " | ".join(row.alternates),
                " | ".join(row.notes),
            ]
        )

    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()


def store_download_artifact(rows: list[TitleUrlExportRow], summary: list[str], filename_hint: str) -> str:
    export_id = str(uuid.uuid4())
    filename_base = _slugify_filename(filename_hint)
    artifact = DownloadArtifact(
        export_id=export_id,
        filename_base=filename_base,
        csv_bytes=rows_to_csv_bytes(rows),
        xlsx_bytes=rows_to_xlsx_bytes(rows, summary),
        rows=rows,
        summary=summary,
    )
    cache.set(f"export:{export_id}", artifact)
    return export_id


def _slugify_filename(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "_", value.strip()).strip("_")
    return cleaned or "title_url_lookup_results"


@router.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "index.html", build_context(request))


@router.post("/lookup", response_class=HTMLResponse)
async def lookup_title(
    request: Request,
    title: Annotated[str, Form()],
    year: Annotated[str, Form()] = "",
    title_type: Annotated[TitleType, Form()] = "any",
) -> HTMLResponse:
    try:
        query = TitleLookupQuery(title=title, year=year, title_type=title_type)
        result = await lookup_service.lookup_title(query)
    except (ValueError, ValidationError) as exc:
        return templates.TemplateResponse(
            request,
            "index.html",
            build_context(
                request,
                error_message=str(exc),
                title=title,
                year=year,
                selected_title_type=title_type,
            ),
        )

    return templates.TemplateResponse(
        request,
        "index.html",
        build_context(
            request,
            result=result,
            title=query.title,
            year=query.year,
            selected_title_type=query.title_type,
        ),
    )


@router.post("/bulk-lookup", response_class=HTMLResponse)
async def bulk_lookup(
    request: Request,
    entries: Annotated[str, Form()],
    title_type: Annotated[TitleType, Form()] = "any",
) -> HTMLResponse:
    try:
        queries = parse_bulk_entries(entries, title_type)
        payload = BulkTitleLookupRequest(entries=queries)
        bulk_result = await lookup_service.lookup_titles(payload.entries)
        export_rows = build_export_rows(bulk_result.entries)
        summary = [f"{len(payload.entries)} input titles processed", f"{len(export_rows)} site rows generated", *bulk_result.notes]
        bulk_result.export_id = store_download_artifact(export_rows, summary, "title_url_bulk_lookup")
    except (ValueError, ValidationError) as exc:
        return templates.TemplateResponse(
            request,
            "index.html",
            build_context(
                request,
                error_message=str(exc),
                bulk_entries=entries,
                selected_title_type=title_type,
            ),
        )

    return templates.TemplateResponse(
        request,
        "index.html",
        build_context(
            request,
            bulk_result=bulk_result,
            bulk_entries=entries,
            selected_title_type=title_type,
        ),
    )


@router.post("/api/lookup")
async def api_lookup(payload: TitleLookupQuery) -> JSONResponse:
    result = await lookup_service.lookup_title(payload)
    return JSONResponse(TitleLookupResponse.model_validate(result).model_dump(mode="json"))


@router.post("/api/bulk-lookup")
async def api_bulk_lookup(payload: BulkTitleLookupRequest) -> JSONResponse:
    result = await lookup_service.lookup_titles(payload.entries)
    return JSONResponse(BulkTitleLookupResponse.model_validate(result).model_dump(mode="json"))


@router.get("/download/{export_id}/{fmt}")
async def download_export(export_id: str, fmt: str):
    artifact = cache.get(f"export:{export_id}")
    if not isinstance(artifact, DownloadArtifact):
        return HTMLResponse("Export expired. Run the bulk lookup again.", status_code=404)

    if fmt == "csv":
        return StreamingResponse(
            io.BytesIO(artifact.csv_bytes),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{artifact.filename_base}.csv"'},
        )
    if fmt == "xlsx":
        return StreamingResponse(
            io.BytesIO(artifact.xlsx_bytes),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{artifact.filename_base}.xlsx"'},
        )
    return HTMLResponse("Unsupported export format.", status_code=400)
