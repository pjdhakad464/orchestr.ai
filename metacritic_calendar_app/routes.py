from __future__ import annotations

import io
import uuid
from datetime import date
from pathlib import Path
from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool

from metacritic_calendar_app.cache import TTLCache
from metacritic_calendar_app.config import settings
from metacritic_calendar_app.models import (
    BoxOfficeMojoReleaseWindowSnapshot,
    MetacriticCalendarSnapshot,
    MetacriticTvClassificationSnapshot,
    TvImdbEpisodeCountSnapshot,
)
from metacritic_calendar_app.services.billboard import BillboardService, BillboardArtistSnapshot
from metacritic_calendar_app.services.calendar import MetacriticCalendarError, MetacriticCalendarService
from metacritic_calendar_app.services.box_office_mojo import BoxOfficeMojoCalendarError, BoxOfficeMojoCalendarService
from metacritic_calendar_app.services.imdb_episode_counts import (
    DEFAULT_TV_IMDB_DATE_WINDOW_KEY,
    TV_IMDB_OUTPUT_COLUMNS,
    TvImdbEpisodeCountService,
    tv_imdb_date_window_options,
)
from metacritic_calendar_app.services.tv_classification import MetacriticTvClassificationReportService


BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
router = APIRouter()
cache = TTLCache(settings.metacritic_calendar_export_ttl_seconds)
calendar_service = MetacriticCalendarService(settings.request_timeout_seconds)
box_office_mojo_service = BoxOfficeMojoCalendarService(settings.request_timeout_seconds)
tv_imdb_episode_count_service = TvImdbEpisodeCountService(calendar_service=calendar_service)
tv_classification_report_service = MetacriticTvClassificationReportService(calendar_service=calendar_service)
billboard_service = BillboardService(settings.request_timeout_seconds)

CALENDAR_OPTIONS = [
    ("all", "All sections"),
    ("games", "Games"),
    ("movies", "Movies"),
    ("tv", "TV Shows"),
]
CALENDAR_MULTISELECT_OPTIONS = [
    ("games", "Games"),
    ("movies", "Movies"),
    ("tv", "TV Shows"),
]
DEFAULT_CALENDAR_TYPES = [value for value, _label in CALENDAR_MULTISELECT_OPTIONS]


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
    snapshot: MetacriticCalendarSnapshot | None = None,
    box_office_snapshot: BoxOfficeMojoReleaseWindowSnapshot | None = None,
    tv_imdb_snapshot: TvImdbEpisodeCountSnapshot | None = None,
    tv_classification_snapshot: MetacriticTvClassificationSnapshot | None = None,
    billboard_snapshot: BillboardArtistSnapshot | None = None,
    error_message: str = "",
    box_office_error_message: str = "",
    tv_imdb_error_message: str = "",
    tv_classification_error_message: str = "",
    billboard_error_message: str = "",
    selected_day: str = "monday",
    selected_task: str = "",
    selected_calendar_types: list[str] | None = None,
    selected_calendar_start_date: str | None = None,
    selected_calendar_end_date: str | None = None,
    selected_tv_imdb_date_window: str | None = None,
    selected_tv_imdb_start_date: str | None = None,
    selected_tv_imdb_end_date: str | None = None,
) -> dict[str, object]:
    selected_types = selected_calendar_types or DEFAULT_CALENDAR_TYPES
    selected_tv_date_window = (
        selected_tv_imdb_date_window
        or (tv_imdb_snapshot.date_window_key if tv_imdb_snapshot is not None else "")
        or DEFAULT_TV_IMDB_DATE_WINDOW_KEY
    )
    selected_tv_start_date = (
        selected_tv_imdb_start_date
        or (
            tv_imdb_snapshot.window_start.isoformat()
            if tv_imdb_snapshot is not None and tv_imdb_snapshot.date_window_key == "custom" and tv_imdb_snapshot.window_start
            else ""
        )
    )
    selected_tv_end_date = (
        selected_tv_imdb_end_date
        or (
            tv_imdb_snapshot.window_end.isoformat()
            if tv_imdb_snapshot is not None and tv_imdb_snapshot.date_window_key == "custom" and tv_imdb_snapshot.window_end
            else ""
        )
    )
    return {
        "request": request,
        "snapshot": snapshot,
        "box_office_snapshot": box_office_snapshot,
        "tv_imdb_snapshot": tv_imdb_snapshot,
        "tv_classification_snapshot": tv_classification_snapshot,
        "billboard_snapshot": billboard_snapshot,
        "error_message": error_message,
        "box_office_error_message": box_office_error_message,
        "tv_imdb_error_message": tv_imdb_error_message,
        "tv_classification_error_message": tv_classification_error_message,
        "billboard_error_message": billboard_error_message,
        "selected_day": selected_day,
        "selected_task": selected_task,
        "selected_calendar_types": selected_types,
        "selected_calendar_type": selected_types[0] if selected_types else "all",
        "selected_calendar_start_date": selected_calendar_start_date or "",
        "selected_calendar_end_date": selected_calendar_end_date or "",
        "calendar_options": CALENDAR_OPTIONS,
        "calendar_multiselect_options": CALENDAR_MULTISELECT_OPTIONS,
        "calendar_api_endpoint": build_calendar_api_endpoint(
            selected_types,
            selected_calendar_start_date or "",
            selected_calendar_end_date or "",
        ),
        "tv_imdb_date_window_options": tv_imdb_date_window_options(),
        "selected_tv_imdb_date_window": selected_tv_date_window,
        "selected_tv_imdb_start_date": selected_tv_start_date,
        "selected_tv_imdb_end_date": selected_tv_end_date,
        "tv_imdb_api_endpoint": build_tv_imdb_api_endpoint(
            selected_tv_date_window,
            selected_tv_start_date,
            selected_tv_end_date,
        ),
        "asset_version": static_asset_version("styles.css"),
    }


def build_tv_imdb_api_endpoint(date_window: str, start_date: str = "", end_date: str = "") -> str:
    query = {"date_window": date_window}
    if date_window == "custom":
        if start_date:
            query["start_date"] = start_date
        if end_date:
            query["end_date"] = end_date
    return f"/api/tv/imdb-episode-counts?{urlencode(query)}"


def build_calendar_api_endpoint(calendar_types: list[str], start_date: str = "", end_date: str = "") -> str:
    query: list[tuple[str, str]] = [("calendar_type", value) for value in (calendar_types or ["all"])]
    if start_date:
        query.append(("start_date", start_date))
    if end_date:
        query.append(("end_date", end_date))
    return f"/api/calendar?{urlencode(query)}"


def resolve_calendar_date_range(start_date: str | None, end_date: str | None) -> tuple[date | None, date | None]:
    start = _parse_optional_iso_date(start_date, "start_date")
    end = _parse_optional_iso_date(end_date, "end_date")
    if start is not None and end is not None and start > end:
        raise ValueError("Start date must be on or before end date.")
    return start, end


def apply_calendar_date_filter(
    snapshot: MetacriticCalendarSnapshot,
    start_date: date | None,
    end_date: date | None,
) -> MetacriticCalendarSnapshot:
    if start_date is None and end_date is None:
        return snapshot

    filtered_items = []
    skipped_missing_date = 0
    skipped_outside_window = 0
    for item in snapshot.items:
        try:
            item_date = _parse_optional_iso_date(item.release_date, "release_date")
        except ValueError:
            item_date = None
        if item_date is None:
            skipped_missing_date += 1
            continue
        if start_date is not None and item_date < start_date:
            skipped_outside_window += 1
            continue
        if end_date is not None and item_date > end_date:
            skipped_outside_window += 1
            continue
        filtered_items.append(item)

    snapshot.items = filtered_items
    if start_date is not None and end_date is not None:
        snapshot.notes.append(f"Date filter: {start_date.isoformat()} to {end_date.isoformat()}.")
    elif start_date is not None:
        snapshot.notes.append(f"Date filter: from {start_date.isoformat()}.")
    elif end_date is not None:
        snapshot.notes.append(f"Date filter: through {end_date.isoformat()}.")
    if skipped_outside_window:
        snapshot.notes.append(f"{skipped_outside_window} row(s) were outside the selected date range.")
    if skipped_missing_date:
        snapshot.notes.append(f"{skipped_missing_date} row(s) were skipped because the release date was unavailable.")
    return snapshot


def _parse_optional_iso_date(value: str | None, field_name: str) -> date | None:
    cleaned = str(value or "").strip()
    if not cleaned:
        return None
    try:
        return date.fromisoformat(cleaned)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be in YYYY-MM-DD format.") from exc


def store_snapshot(snapshot: MetacriticCalendarSnapshot) -> str:
    export_id = str(uuid.uuid4())
    snapshot.export_id = export_id
    cache.set(f"export:{export_id}", snapshot)
    return export_id


def store_box_office_snapshot(snapshot: BoxOfficeMojoReleaseWindowSnapshot) -> str:
    export_id = str(uuid.uuid4())
    snapshot.export_id = export_id
    cache.set(f"bom:{export_id}", snapshot)
    return export_id


def store_tv_imdb_snapshot(snapshot: TvImdbEpisodeCountSnapshot) -> str:
    export_id = str(uuid.uuid4())
    snapshot.export_id = export_id
    cache.set(f"tv-imdb:{export_id}", snapshot)
    return export_id


def store_tv_classification_snapshot(snapshot: MetacriticTvClassificationSnapshot) -> str:
    export_id = str(uuid.uuid4())
    snapshot.export_id = export_id
    cache.set(f"tv-classification:{export_id}", snapshot)
    return export_id


def tv_imdb_snapshot_to_response_payload(snapshot: TvImdbEpisodeCountSnapshot) -> dict[str, object]:
    payload = snapshot.model_dump(mode="json", exclude={"items"})
    payload["items"] = [
        item.model_dump(mode="json", include=set(TV_IMDB_OUTPUT_COLUMNS))
        for item in snapshot.items
    ]
    return payload


def tv_classification_snapshot_to_response_payload(snapshot: MetacriticTvClassificationSnapshot) -> dict[str, object]:
    payload = snapshot.model_dump(mode="json", exclude={"items"})
    payload["items"] = [
        tv_classification_report_service.item_to_api_payload(item)
        for item in snapshot.items
    ]
    return payload


def store_billboard_snapshot(snapshot: BillboardArtistSnapshot) -> str:
    export_id = str(uuid.uuid4())
    snapshot.export_id = export_id
    cache.set(f"billboard:{export_id}", snapshot)
    return export_id


@router.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "index.html", build_context(request))


@router.post("/run-task", response_class=HTMLResponse)
async def run_task(
    request: Request,
    task: Annotated[str, Form()] = "",
    date_window: Annotated[str, Form()] = DEFAULT_TV_IMDB_DATE_WINDOW_KEY,
    custom_start_date: Annotated[str, Form()] = "",
    custom_end_date: Annotated[str, Form()] = "",
) -> HTMLResponse:
    snapshot = None
    box_office_snapshot = None
    tv_imdb_snapshot = None
    tv_classification_snapshot = None
    billboard_snapshot = None

    error_message = ""
    box_office_error_message = ""
    tv_imdb_error_message = ""
    tv_classification_error_message = ""
    billboard_error_message = ""

    try:
        if task == "billboard":
            billboard_snapshot = await billboard_service.get_top_artists_snapshot()
            store_billboard_snapshot(billboard_snapshot)
        elif task == "review_release":
            box_office_snapshot = await run_in_threadpool(box_office_mojo_service.fetch_upcoming_12_months_snapshot)
            store_box_office_snapshot(box_office_snapshot)
        elif task == "box_office":
            box_office_snapshot = await run_in_threadpool(box_office_mojo_service.fetch_last_7_days_snapshot)
            store_box_office_snapshot(box_office_snapshot)
        elif task == "tv_metadata":
            tv_imdb_snapshot = await run_in_threadpool(
                tv_imdb_episode_count_service.fetch_snapshot,
                date_window,
                custom_start_date or None,
                custom_end_date or None,
            )
            store_tv_imdb_snapshot(tv_imdb_snapshot)
        elif task == "film_adding":
            snapshot = await run_in_threadpool(calendar_service.fetch_snapshot, ["movies"])
            if custom_start_date or custom_end_date:
                start_date_parsed, end_date_parsed = resolve_calendar_date_range(custom_start_date, custom_end_date)
                apply_calendar_date_filter(snapshot, start_date_parsed, end_date_parsed)
            store_snapshot(snapshot)
        elif task == "calendar_scrape":
            snapshot = await run_in_threadpool(calendar_service.fetch_snapshot, ["tv"])
            if custom_start_date or custom_end_date:
                start_date_parsed, end_date_parsed = resolve_calendar_date_range(custom_start_date, custom_end_date)
                apply_calendar_date_filter(snapshot, start_date_parsed, end_date_parsed)
            store_snapshot(snapshot)
        elif task == "tv_adding":
            tv_classification_snapshot = await run_in_threadpool(tv_classification_report_service.fetch_snapshot)
            store_tv_classification_snapshot(tv_classification_snapshot)
        elif task == "brand_review":
            snapshot = await run_in_threadpool(calendar_service.fetch_snapshot, ["games"])
            if custom_start_date or custom_end_date:
                start_date_parsed, end_date_parsed = resolve_calendar_date_range(custom_start_date, custom_end_date)
                apply_calendar_date_filter(snapshot, start_date_parsed, end_date_parsed)
            store_snapshot(snapshot)
        else:
            error_message = f"Unknown automation task: {task}"
    except Exception as exc:
        import traceback
        traceback.print_exc()
        if task == "billboard":
            billboard_error_message = str(exc)
        elif task in ("review_release", "box_office"):
            box_office_error_message = str(exc)
        elif task == "tv_metadata":
            tv_imdb_error_message = str(exc)
        elif task == "tv_adding":
            tv_classification_error_message = str(exc)
        else:
            error_message = str(exc)

    return templates.TemplateResponse(
        request,
        "index.html",
        build_context(
            request,
            snapshot=snapshot,
            box_office_snapshot=box_office_snapshot,
            tv_imdb_snapshot=tv_imdb_snapshot,
            tv_classification_snapshot=tv_classification_snapshot,
            billboard_snapshot=billboard_snapshot,
            error_message=error_message,
            box_office_error_message=box_office_error_message,
            tv_imdb_error_message=tv_imdb_error_message,
            tv_classification_error_message=tv_classification_error_message,
            billboard_error_message=billboard_error_message,
            selected_task=task,
            selected_tv_imdb_date_window=date_window,
            selected_tv_imdb_start_date=custom_start_date,
            selected_tv_imdb_end_date=custom_end_date,
        ),
    )


@router.get("/billboard/export/{export_id}/csv")
async def export_billboard_csv(export_id: str):
    import csv as csv_module
    snapshot = cache.get(f"billboard:{export_id}")
    if not isinstance(snapshot, BillboardArtistSnapshot):
        return HTMLResponse("Export expired. Run the Billboard search again.", status_code=404)

    output = io.StringIO()
    writer = csv_module.DictWriter(
        output,
        fieldnames=["rank", "name", "slug", "gender", "profession", "imdb_id", "wikipedia_url"]
    )
    writer.writeheader()
    for item in snapshot.items:
        writer.writerow({
            "rank": item.rank,
            "name": item.name,
            "slug": item.slug,
            "gender": item.gender,
            "profession": item.profession,
            "imdb_id": item.imdb_id,
            "wikipedia_url": item.wikipedia_url
        })
    data = output.getvalue().encode("utf-8-sig")
    filename = f"billboard_artists_{snapshot.generated_at.strftime('%Y%m%d')}.csv"
    return StreamingResponse(
        io.BytesIO(data),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/calendar/search", response_class=HTMLResponse)
async def calendar_search_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "index.html", build_context(request))


@router.post("/calendar/search", response_class=HTMLResponse)
async def search_calendar(
    request: Request,
    calendar_type: Annotated[list[str] | None, Form()] = None,
    custom_start_date: Annotated[str, Form()] = "",
    custom_end_date: Annotated[str, Form()] = "",
) -> HTMLResponse:
    selected_calendar_types = calendar_type or DEFAULT_CALENDAR_TYPES
    task_map = {
        "movies": "film_adding",
        "tv": "calendar_scrape",
        "games": "brand_review",
    }
    primary_type = selected_calendar_types[0] if selected_calendar_types else "tv"
    task = task_map.get(primary_type, "calendar_scrape")
    try:
        start_date, end_date = resolve_calendar_date_range(custom_start_date, custom_end_date)
        snapshot = await run_in_threadpool(calendar_service.fetch_snapshot, selected_calendar_types)
        apply_calendar_date_filter(snapshot, start_date, end_date)
    except (MetacriticCalendarError, ValueError) as exc:
        return templates.TemplateResponse(
            request,
            "index.html",
            build_context(
                request,
                error_message=str(exc),
                selected_task=task,
                selected_calendar_types=selected_calendar_types,
                selected_calendar_start_date=custom_start_date,
                selected_calendar_end_date=custom_end_date,
            ),
        )

    store_snapshot(snapshot)
    return templates.TemplateResponse(
        request,
        "index.html",
        build_context(
            request,
            snapshot=snapshot,
            selected_task=task,
            selected_calendar_types=selected_calendar_types,
            selected_calendar_start_date=custom_start_date,
            selected_calendar_end_date=custom_end_date,
        ),
    )


@router.post("/box-office-mojo/search", response_class=HTMLResponse)
async def search_box_office_mojo_last_7_days(request: Request) -> HTMLResponse:
    try:
        snapshot = await run_in_threadpool(box_office_mojo_service.fetch_last_7_days_snapshot)
    except BoxOfficeMojoCalendarError as exc:
        return templates.TemplateResponse(
            request,
            "index.html",
            build_context(request, box_office_error_message=str(exc), selected_task="box_office"),
        )

    store_box_office_snapshot(snapshot)
    return templates.TemplateResponse(
        request,
        "index.html",
        build_context(request, box_office_snapshot=snapshot, selected_task="box_office"),
    )


@router.post("/box-office-mojo/upcoming-12-months/search", response_class=HTMLResponse)
async def search_box_office_mojo_upcoming_12_months(request: Request) -> HTMLResponse:
    try:
        snapshot = await run_in_threadpool(box_office_mojo_service.fetch_upcoming_12_months_snapshot)
    except BoxOfficeMojoCalendarError as exc:
        return templates.TemplateResponse(
            request,
            "index.html",
            build_context(request, box_office_error_message=str(exc), selected_task="review_release"),
        )

    store_box_office_snapshot(snapshot)
    return templates.TemplateResponse(
        request,
        "index.html",
        build_context(request, box_office_snapshot=snapshot, selected_task="review_release"),
    )


@router.get("/tv/imdb-episode-counts", response_class=HTMLResponse)
async def tv_imdb_episode_counts_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "index.html", build_context(request))


@router.get("/tv/classification-report", response_class=HTMLResponse)
async def tv_classification_report_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "index.html", build_context(request))


@router.post("/tv/classification-report/search", response_class=HTMLResponse)
async def search_tv_classification_report(request: Request) -> HTMLResponse:
    try:
        snapshot = await run_in_threadpool(tv_classification_report_service.fetch_snapshot)
    except (MetacriticCalendarError, RuntimeError) as exc:
        return templates.TemplateResponse(
            request,
            "index.html",
            build_context(request, tv_classification_error_message=str(exc), selected_task="tv_adding"),
        )

    store_tv_classification_snapshot(snapshot)
    return templates.TemplateResponse(
        request,
        "index.html",
        build_context(request, tv_classification_snapshot=snapshot, selected_task="tv_adding"),
    )


@router.post("/tv/imdb-episode-counts/search", response_class=HTMLResponse)
async def search_tv_imdb_episode_counts(
    request: Request,
    date_window: Annotated[str, Form()] = DEFAULT_TV_IMDB_DATE_WINDOW_KEY,
    custom_start_date: Annotated[str, Form()] = "",
    custom_end_date: Annotated[str, Form()] = "",
) -> HTMLResponse:
    try:
        snapshot = await run_in_threadpool(
            tv_imdb_episode_count_service.fetch_snapshot,
            date_window,
            custom_start_date or None,
            custom_end_date or None,
        )
    except (MetacriticCalendarError, RuntimeError, ValueError) as exc:
        return templates.TemplateResponse(
            request,
            "index.html",
            build_context(
                request,
                tv_imdb_error_message=str(exc),
                selected_tv_imdb_date_window=date_window,
                selected_tv_imdb_start_date=custom_start_date,
                selected_tv_imdb_end_date=custom_end_date,
                selected_task="tv_metadata",
            ),
        )

    store_tv_imdb_snapshot(snapshot)
    return templates.TemplateResponse(
        request,
        "index.html",
        build_context(request, tv_imdb_snapshot=snapshot, selected_task="tv_metadata"),
    )


@router.get("/api/calendar")
async def calendar_api(
    calendar_type: Annotated[list[str] | None, Query()] = None,
    start_date: Annotated[str | None, Query()] = None,
    end_date: Annotated[str | None, Query()] = None,
) -> JSONResponse:
    selected_calendar_types = calendar_type or ["all"]
    try:
        resolved_start_date, resolved_end_date = resolve_calendar_date_range(start_date, end_date)
        snapshot = await run_in_threadpool(calendar_service.fetch_snapshot, selected_calendar_types)
        apply_calendar_date_filter(snapshot, resolved_start_date, resolved_end_date)
    except (MetacriticCalendarError, ValueError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)

    store_snapshot(snapshot)
    return JSONResponse(snapshot.model_dump(mode="json"))


@router.get("/api/box-office-mojo/last-7-days")
async def box_office_mojo_last_7_days_api() -> JSONResponse:
    try:
        snapshot = await run_in_threadpool(box_office_mojo_service.fetch_last_7_days_snapshot)
    except BoxOfficeMojoCalendarError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)

    store_box_office_snapshot(snapshot)
    return JSONResponse(snapshot.model_dump(mode="json"))


@router.get("/api/box-office-mojo/upcoming-12-months")
async def box_office_mojo_upcoming_12_months_api() -> JSONResponse:
    try:
        snapshot = await run_in_threadpool(box_office_mojo_service.fetch_upcoming_12_months_snapshot)
    except BoxOfficeMojoCalendarError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)

    store_box_office_snapshot(snapshot)
    return JSONResponse(snapshot.model_dump(mode="json"))


@router.get("/api/tv/imdb-episode-counts")
async def tv_imdb_episode_counts_api(
    date_window: Annotated[str, Query()] = DEFAULT_TV_IMDB_DATE_WINDOW_KEY,
    start_date: Annotated[str | None, Query()] = None,
    end_date: Annotated[str | None, Query()] = None,
) -> JSONResponse:
    try:
        snapshot = await run_in_threadpool(
            tv_imdb_episode_count_service.fetch_snapshot,
            date_window,
            start_date,
            end_date,
        )
    except (MetacriticCalendarError, RuntimeError, ValueError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)

    store_tv_imdb_snapshot(snapshot)
    return JSONResponse(tv_imdb_snapshot_to_response_payload(snapshot))


@router.get("/api/tv/classification-report")
async def tv_classification_report_api() -> JSONResponse:
    try:
        snapshot = await run_in_threadpool(tv_classification_report_service.fetch_snapshot)
    except (MetacriticCalendarError, RuntimeError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)

    store_tv_classification_snapshot(snapshot)
    return JSONResponse(tv_classification_snapshot_to_response_payload(snapshot))


@router.get("/export/{export_id}/csv")
async def export_calendar_csv(export_id: str):
    snapshot = cache.get(f"export:{export_id}")
    if not isinstance(snapshot, MetacriticCalendarSnapshot):
        return HTMLResponse("Export expired. Run the calendar search again.", status_code=404)

    data = calendar_service.snapshot_to_csv_bytes(snapshot)
    filename = f"metacritic_{snapshot.calendar_type}_calendar.csv"
    return StreamingResponse(
        io.BytesIO(data),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/tv/classification-report/export/{export_id}/{fmt}")
async def export_tv_classification_report(export_id: str, fmt: str):
    snapshot = cache.get(f"tv-classification:{export_id}")
    if not isinstance(snapshot, MetacriticTvClassificationSnapshot):
        return HTMLResponse("Export expired. Run the TV classification report again.", status_code=404)

    filename_base = "metacritic_tv_classification_report"
    if fmt == "csv":
        return StreamingResponse(
            io.BytesIO(tv_classification_report_service.snapshot_to_csv_bytes(snapshot)),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename_base}.csv"'},
        )
    if fmt == "xlsx":
        return StreamingResponse(
            io.BytesIO(tv_classification_report_service.snapshot_to_xlsx_bytes(snapshot)),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{filename_base}.xlsx"'},
        )
    return HTMLResponse("Unsupported export format.", status_code=400)


@router.get("/tv/imdb-episode-counts/export/{export_id}/csv")
async def export_tv_imdb_episode_counts_csv(export_id: str):
    snapshot = cache.get(f"tv-imdb:{export_id}")
    if not isinstance(snapshot, TvImdbEpisodeCountSnapshot):
        return HTMLResponse("Export expired. Run the TV IMDb episode count fetch again.", status_code=404)

    data = tv_imdb_episode_count_service.snapshot_to_csv_bytes(snapshot)
    filename = f"tv_imdb_episode_counts_{snapshot.date_window_key}.csv"
    return StreamingResponse(
        io.BytesIO(data),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/box-office-mojo/export/{export_id}/{fmt}")
async def export_box_office_mojo_data(export_id: str, fmt: str):
    snapshot = cache.get(f"bom:{export_id}")
    if not isinstance(snapshot, BoxOfficeMojoReleaseWindowSnapshot):
        return HTMLResponse("Export expired. Run the Box Office Mojo fetch again.", status_code=404)

    filename_base = (
        f"box_office_mojo_{snapshot.report_key}_{snapshot.window_start.isoformat()}_{snapshot.window_end.isoformat()}"
    )
    if fmt == "csv":
        return StreamingResponse(
            io.BytesIO(box_office_mojo_service.snapshot_to_csv_bytes(snapshot)),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename_base}.csv"'},
        )
    if fmt == "xlsx":
        return StreamingResponse(
            io.BytesIO(box_office_mojo_service.snapshot_to_xlsx_bytes(snapshot)),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{filename_base}.xlsx"'},
        )
    return HTMLResponse("Unsupported export format.", status_code=400)
