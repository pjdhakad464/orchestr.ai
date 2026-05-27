from __future__ import annotations

import io
import uuid
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool

from app.cache import TTLCache
from app.config import settings
from app.models import EntityQuery, ExportPayload, SearchSession, ValidationHistoryEntry, WorkbookValidationArtifact
from app.services.entity_resolver import EntityResolver
from app.services.exporter import (
    build_ui_matrix_rows,
    build_export_payload_from_bulk,
    build_export_payload_from_search,
    export_to_google_sheets,
    rows_to_csv_bytes,
    rows_to_xlsx_bytes,
)
from app.services.factory import build_entity_resolver, build_media_resolver
from app.services.media_resolver import MediaResolver
from app.services.search_provider import SearchProviderUnavailableError
from app.services.tmdb_client import TmdbUnavailableError
from app.services.validation_history import list_validation_runs, load_saved_validation_file, record_validation_run
from app.services.workbook_validator import (
    WorkbookValidationConfigError,
    build_sample_rules_json,
    load_google_sheet_workbook,
    parse_validation_rules,
    validate_loaded_workbook,
    validate_workbook,
)
from app.services.taxonomy_classifier import TaxonomyClassifier


BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
router = APIRouter()
cache = TTLCache(settings.cache_ttl_seconds)
resolver = build_entity_resolver(cache)
media_resolver = build_media_resolver(cache)
taxonomy_classifier = TaxonomyClassifier(cache)


def render_partial(request: Request, template_name: str, **context) -> HTMLResponse:
    return templates.TemplateResponse(request, template_name, context)


def store_export_payload(payload: ExportPayload) -> str:
    cache.set(f"export:{payload.export_id}", payload)
    return payload.export_id


def store_validation_artifact(artifact: WorkbookValidationArtifact) -> str:
    cache.set(f"validation:{artifact.validation_id}", artifact)
    return artifact.validation_id


def parse_bulk_queries(raw_text: str, default_entity_type: str | None, default_country: str | None) -> list[EntityQuery]:
    queries: list[EntityQuery] = []
    for line in raw_text.splitlines():
        cleaned = line.strip()
        if not cleaned:
            continue
        parts = [part.strip() for part in cleaned.split("|")]
        name = parts[0]
        entity_type = parts[1] if len(parts) > 1 and parts[1] else default_entity_type
        country = parts[2] if len(parts) > 2 and parts[2] else default_country
        queries.append(EntityQuery(name=name, entity_type=entity_type or None, country=country or None))
    return queries


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


def build_template_context(request: Request) -> dict[str, object]:
    return {
        "request": request,
        "company_entity_types": EntityResolver.COMPANY_ENTITY_TYPES,
        "media_types": MediaResolver.MEDIA_TYPES,
        "talent_types": EntityResolver.TALENT_TYPES,
        "talent_professions": EntityResolver.TALENT_PROFESSIONS,
        "platforms": EntityResolver.SUPPORTED_PLATFORMS,
        "validator_rules_example": build_sample_rules_json(),
        "validation_history": list_validation_runs(settings.validation_history_limit),
        "asset_version": static_asset_version("styles.css", "ai-tech-bg.svg", "htmx-fallback.js"),
    }


def build_validation_history_context(latest_history: ValidationHistoryEntry | None = None) -> dict[str, object]:
    history_runs = list_validation_runs(settings.validation_history_limit)
    return {
        "history_runs": history_runs,
        "latest_history": latest_history or (history_runs[0] if history_runs else None),
    }


@router.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "index.html", build_template_context(request))


@router.get("/excel-validator", response_class=HTMLResponse)
async def excel_validator(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "validator.html", build_template_context(request))


@router.get("/excel-validator/guide", response_class=HTMLResponse)
async def excel_validator_guide(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "validator_guide.html", build_template_context(request))


@router.post("/search", response_class=HTMLResponse)
async def search(
    request: Request,
    name: Annotated[str, Form()],
    entity_type: Annotated[str | None, Form()] = None,
    country: Annotated[str | None, Form()] = None,
) -> HTMLResponse:
    cleaned_name = name.strip()
    if not cleaned_name:
        return render_partial(request, "_error.html", message="Enter a name to search.")
    if entity_type in {"movie", "tv_show", "tv_network", "celebrity", "influencer"}:
        return render_partial(
            request,
            "_error.html",
            message="Use Media Finder for movies/TV and Talents for influencers or celebrities.",
        )

    query = EntityQuery(name=cleaned_name, entity_type=entity_type or None, country=country or None)
    try:
        response = await resolver.search(query)
    except SearchProviderUnavailableError as exc:
        return render_partial(request, "_error.html", message=str(exc))

    if response.disambiguation_required:
        return render_partial(request, "_disambiguation.html", response=response, resolve_path="/resolve-entity")

    payload = build_export_payload_from_search(response)
    response.export_id = store_export_payload(payload)
    return render_partial(request, "_results.html", response=response, table_rows=build_ui_matrix_rows(payload.rows))


@router.post("/search/media", response_class=HTMLResponse)
async def search_media(
    request: Request,
    name: Annotated[str, Form()],
    media_type: Annotated[str, Form()] = "movie",
    country: Annotated[str | None, Form()] = None,
) -> HTMLResponse:
    cleaned_name = name.strip()
    if not cleaned_name:
        return render_partial(request, "_error.html", message="Enter a movie, TV show, or network name to search.")

    query = EntityQuery(name=cleaned_name, entity_type=media_type or "movie", country=(country or "").strip() or None)
    try:
        response = await media_resolver.search(query)
    except TmdbUnavailableError as exc:
        return render_partial(request, "_error.html", message=str(exc))

    if response.disambiguation_required:
        session_id = response.session_id or str(uuid.uuid4())
        cache.set(
            f"media-session:{session_id}",
            SearchSession(session_id=session_id, query=query, candidates=response.entity_candidates),
        )
        response.session_id = session_id
        return render_partial(request, "_disambiguation.html", response=response, resolve_path="/resolve-media")

    payload = build_export_payload_from_search(response)
    response.export_id = store_export_payload(payload)
    return render_partial(request, "_results.html", response=response, table_rows=build_ui_matrix_rows(payload.rows))


@router.post("/search/talent", response_class=HTMLResponse)
async def search_talent(
    request: Request,
    name: Annotated[str, Form()],
    talent_type: Annotated[str, Form()] = "celebrity",
    profession: Annotated[str | None, Form()] = None,
    date_of_birth: Annotated[str | None, Form()] = None,
    country: Annotated[str | None, Form()] = None,
) -> HTMLResponse:
    cleaned_name = name.strip()
    if not cleaned_name:
        return render_partial(request, "_error.html", message="Enter a talent name to search.")

    query = EntityQuery(
        name=cleaned_name,
        entity_type=talent_type or "celebrity",
        profession=(profession or "").strip() or None,
        date_of_birth=(date_of_birth or "").strip() or None,
        country=(country or "").strip() or None,
    )
    try:
        response = await resolver.search(query)
    except SearchProviderUnavailableError as exc:
        return render_partial(request, "_error.html", message=str(exc))

    if response.disambiguation_required:
        return render_partial(request, "_disambiguation.html", response=response, resolve_path="/resolve-entity")

    payload = build_export_payload_from_search(response)
    response.export_id = store_export_payload(payload)
    return render_partial(request, "_results.html", response=response, table_rows=build_ui_matrix_rows(payload.rows))


@router.post("/resolve-entity", response_class=HTMLResponse)
async def resolve_entity(
    request: Request,
    session_id: Annotated[str, Form()],
    candidate_id: Annotated[str, Form()],
) -> HTMLResponse:
    try:
        response = await resolver.resolve_from_session(session_id=session_id, candidate_id=candidate_id)
    except SearchProviderUnavailableError as exc:
        return render_partial(request, "_error.html", message=str(exc))

    payload = build_export_payload_from_search(response)
    response.export_id = store_export_payload(payload)
    return render_partial(request, "_results.html", response=response, table_rows=build_ui_matrix_rows(payload.rows))


@router.post("/resolve-media", response_class=HTMLResponse)
async def resolve_media(
    request: Request,
    session_id: Annotated[str, Form()],
    candidate_id: Annotated[str, Form()],
) -> HTMLResponse:
    session = cache.get(f"media-session:{session_id}")
    if not isinstance(session, SearchSession):
        return render_partial(request, "_error.html", message="This media search session expired. Please search again.")

    selected = next((item for item in session.candidates if item.candidate_id == candidate_id), None)
    if selected is None:
        return render_partial(request, "_error.html", message="The selected media candidate was not found.")

    try:
        response = await media_resolver.resolve_candidate(session.query, selected)
    except TmdbUnavailableError as exc:
        return render_partial(request, "_error.html", message=str(exc))

    payload = build_export_payload_from_search(response)
    response.export_id = store_export_payload(payload)
    return render_partial(request, "_results.html", response=response, table_rows=build_ui_matrix_rows(payload.rows))


@router.post("/bulk-search", response_class=HTMLResponse)
async def bulk_search(
    request: Request,
    names: Annotated[str, Form()],
    entity_type: Annotated[str | None, Form()] = None,
    country: Annotated[str | None, Form()] = None,
) -> HTMLResponse:
    if entity_type in {"movie", "tv_show", "tv_network", "celebrity", "influencer"}:
        return render_partial(
            request,
            "_error.html",
            message="Bulk Lookup currently supports the company flow only. Use Media Finder for movies/TV.",
        )
    queries = parse_bulk_queries(names, entity_type or None, country or None)
    if not queries:
        return render_partial(request, "_error.html", message="Enter at least one line for bulk search.")
    if len(queries) > 500:
        return render_partial(request, "_error.html", message="Bulk search is limited to 500 lines at a time.")

    try:
        bulk_response = await resolver.bulk_search(queries)
    except SearchProviderUnavailableError as exc:
        return render_partial(request, "_error.html", message=str(exc))

    payload = build_export_payload_from_bulk(bulk_response)
    bulk_response.export_id = store_export_payload(payload)
    return render_partial(
        request,
        "_bulk_results.html",
        response=bulk_response,
        table_rows=build_ui_matrix_rows(payload.rows),
    )


@router.post("/validate-excel", response_class=HTMLResponse)
async def validate_excel(
    request: Request,
    workbook: UploadFile | None = File(None),
    rules_json: Annotated[str | None, Form()] = None,
    rules_file: UploadFile | None = File(None),
    google_sheet_url: Annotated[str | None, Form()] = None,
    run_by: Annotated[str | None, Form()] = None,
) -> HTMLResponse:
    run_by_name = (run_by or "").strip()
    if not run_by_name:
        return render_partial(request, "_error.html", message="Enter a name in the Run by field before validating.")

    if rules_file and rules_file.filename:
        rules_source = (await rules_file.read()).decode("utf-8")
    else:
        rules_source = (rules_json or "").strip()

    google_sheet_reference = (google_sheet_url or "").strip()
    uploaded_filename = Path(workbook.filename or "").name if workbook else ""
    workbook_name = uploaded_filename or "workbook.xlsx"
    if not uploaded_filename and not google_sheet_reference:
        return render_partial(
            request,
            "_error.html",
            message="Upload an Excel workbook (.xlsx), a CSV file (.csv), or paste a Google Sheets URL.",
        )

    try:
        rules = parse_validation_rules(rules_source)
        if uploaded_filename:
            suffix = Path(uploaded_filename).suffix.lower()
            if suffix not in {".xlsx", ".csv"}:
                return render_partial(
                    request,
                    "_error.html",
                    message="Upload an Excel workbook (.xlsx), a CSV file (.csv), or use a Google Sheets URL.",
                )
            artifact = await run_in_threadpool(validate_workbook, await workbook.read(), uploaded_filename, rules)
            workbook_name = uploaded_filename
        else:
            google_workbook, source_name = await run_in_threadpool(load_google_sheet_workbook, google_sheet_reference)
            artifact = await run_in_threadpool(validate_loaded_workbook, google_workbook, source_name, rules)
            workbook_name = source_name
    except WorkbookValidationConfigError as exc:
        return render_partial(request, "_error.html", message=str(exc))
    except UnicodeDecodeError:
        return render_partial(request, "_error.html", message="Rules file must be a UTF-8 JSON file.")
    except Exception as exc:
        return render_partial(request, "_error.html", message=f"Workbook validation failed: {exc}")

    validation_id = store_validation_artifact(artifact)
    latest_history = await run_in_threadpool(
        record_validation_run,
        artifact,
        original_filename=workbook_name,
        run_by=run_by_name,
        client_ip=request.client.host if request.client else "",
    )
    return render_partial(
        request,
        "_validation_results.html",
        artifact=artifact,
        validation_id=validation_id,
        **build_validation_history_context(latest_history),
    )


@router.get("/validate-excel/download/{validation_id}")
async def download_validated_workbook(validation_id: str):
    artifact = cache.get(f"validation:{validation_id}")
    if isinstance(artifact, WorkbookValidationArtifact):
        file_bytes = artifact.file_bytes
        filename = artifact.filename
    else:
        saved_file = load_saved_validation_file(validation_id)
        if saved_file is None:
            return HTMLResponse("Validated workbook expired. Upload the file again.", status_code=404)
        file_bytes, filename = saved_file

    return StreamingResponse(
        io.BytesIO(file_bytes),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/export/{export_id}/{fmt}")
async def export_results(export_id: str, fmt: str):
    payload = cache.get(f"export:{export_id}")
    if not isinstance(payload, ExportPayload):
        return HTMLResponse("Export expired. Run the search again.", status_code=404)

    safe_name = payload.title.replace(" ", "_").replace("/", "_")
    if fmt == "csv":
        return StreamingResponse(
            io.BytesIO(rows_to_csv_bytes(payload)),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{safe_name}.csv"'},
        )
    if fmt == "xlsx":
        try:
            data = rows_to_xlsx_bytes(payload)
        except RuntimeError as exc:
            return HTMLResponse(str(exc), status_code=500)
        return StreamingResponse(
            io.BytesIO(data),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{safe_name}.xlsx"'},
        )
    if fmt == "google-sheets":
        try:
            sheet_url = export_to_google_sheets(payload)
        except RuntimeError as exc:
            return HTMLResponse(str(exc), status_code=500)
        return RedirectResponse(sheet_url)

    return HTMLResponse("Unsupported export format.", status_code=400)


@router.post("/classify-title", response_class=HTMLResponse)
async def classify_title(
    request: Request,
    title_name: Annotated[str, Form()],
) -> HTMLResponse:
    cleaned_name = title_name.strip()
    if not cleaned_name:
        return render_partial(request, "_error.html", message="Enter a title name to classify.")

    try:
        result = await taxonomy_classifier.classify(cleaned_name)
    except Exception as exc:
        return render_partial(request, "_error.html", message=f"Taxonomy classification failed: {exc}")

    return render_partial(
        request,
        "_classification_results.html",
        title=cleaned_name,
        category=result["category"],
        sub_category=result["sub_category"],
    )
