from __future__ import annotations

import csv
import io
import uuid
from datetime import datetime, timezone

from app.config import settings
from app.models import BulkLookupResult, BulkSearchResponse, ExportPayload, ExportRow, SearchResponse


TABLE_COLUMNS = [
    "Entity Query",
    "Matched Entity",
    "Entity Type",
    "Country",
    "Metadata Source",
    "Official Website",
    "Release Type",
    "Studio Type",
    "Genre",
    "Release Date",
    "Network / Studio",
    "Platform",
    "Status",
    "Display Name",
    "Handle",
    "URL",
    "Confidence Score",
    "Confidence Label",
    "Account Labels",
    "Evidence",
    "Alternates",
    "Notes",
]
PLATFORM_COLUMNS = ["Facebook", "Instagram", "YouTube", "X/Twitter", "TikTok", "Wikipedia", "IMDb"]


def build_export_payload_from_search(response: SearchResponse) -> ExportPayload:
    rows: list[ExportRow] = []
    matched_entity = response.selected_entity.label if response.selected_entity else ""
    media_metadata = _media_metadata(response)
    for platform_result in response.platform_results:
        primary = platform_result.primary
        rows.append(
            ExportRow(
                entity_query=response.query.name,
                matched_entity=matched_entity,
                entity_type=response.query.entity_type or "",
                country=response.query.country or "",
                metadata_source=media_metadata["metadata_source"],
                official_website=media_metadata["official_website"],
                release_type=media_metadata["release_type"],
                studio_type=media_metadata["studio_type"],
                genre=media_metadata["genre"],
                release_date=media_metadata["release_date"],
                network=media_metadata["network"],
                platform=platform_result.platform,
                status=platform_result.status,
                display_name=primary.display_name if primary else "",
                handle=primary.handle if primary and primary.handle else "",
                url=primary.url if primary else "",
                confidence_score=primary.confidence_score if primary else None,
                confidence_label=primary.confidence_label if primary else "",
                account_labels=primary.account_labels if primary else [],
                evidence=[item.summary for item in primary.evidence] if primary else [],
                alternates=[
                    alternate.url for alternate in platform_result.alternates if alternate.confidence_score >= 60
                ],
                notes=response.notes,
            )
        )

    return ExportPayload(
        export_id=str(uuid.uuid4()),
        title=f"{response.query.name} profile results",
        rows=rows,
        summary=response.notes,
    )


def build_export_payload_from_bulk(response: BulkSearchResponse) -> ExportPayload:
    rows: list[ExportRow] = []
    for result in response.results:
        matched_entity = result.selected_entity.label if result.selected_entity else ""
        media_metadata = _media_metadata(result)
        if not result.platform_results:
            rows.append(
                ExportRow(
                    entity_query=result.query.name,
                    matched_entity=matched_entity,
                    entity_type=result.query.entity_type or "",
                    country=result.query.country or "",
                    metadata_source=media_metadata["metadata_source"],
                    official_website=media_metadata["official_website"],
                    release_type=media_metadata["release_type"],
                    studio_type=media_metadata["studio_type"],
                    genre=media_metadata["genre"],
                    release_date=media_metadata["release_date"],
                    network=media_metadata["network"],
                    status=result.resolution_status,
                    notes=result.notes,
                )
            )
            continue

        for platform_result in result.platform_results:
            primary = platform_result.primary
            rows.append(
                ExportRow(
                    entity_query=result.query.name,
                    matched_entity=matched_entity,
                    entity_type=result.query.entity_type or "",
                    country=result.query.country or "",
                    metadata_source=media_metadata["metadata_source"],
                    official_website=media_metadata["official_website"],
                    release_type=media_metadata["release_type"],
                    studio_type=media_metadata["studio_type"],
                    genre=media_metadata["genre"],
                    release_date=media_metadata["release_date"],
                    network=media_metadata["network"],
                    platform=platform_result.platform,
                    status=platform_result.status,
                    display_name=primary.display_name if primary else "",
                    handle=primary.handle if primary and primary.handle else "",
                    url=primary.url if primary else "",
                    confidence_score=primary.confidence_score if primary else None,
                    confidence_label=primary.confidence_label if primary else "",
                    account_labels=primary.account_labels if primary else [],
                    evidence=[item.summary for item in primary.evidence] if primary else [],
                    alternates=[
                        alternate.url for alternate in platform_result.alternates if alternate.confidence_score >= 60
                    ],
                    notes=result.notes,
                )
            )

    return ExportPayload(
        export_id=str(uuid.uuid4()),
        title=f"Bulk profile results {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        rows=rows,
        summary=response.notes,
    )


def rows_to_csv_bytes(payload: ExportPayload) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(TABLE_COLUMNS)
    for row in payload.rows:
        writer.writerow(_row_values(row))
    return buffer.getvalue().encode("utf-8-sig")


def rows_to_xlsx_bytes(payload: ExportPayload) -> bytes:
    try:
        from openpyxl import Workbook
    except ImportError as exc:
        raise RuntimeError("openpyxl is not installed. Run: python -m pip install -e .[dev]") from exc

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Results"
    sheet.append(TABLE_COLUMNS)
    for row in payload.rows:
        sheet.append(_row_values(row))
    for column in sheet.columns:
        max_length = max(len(str(cell.value or "")) for cell in column)
        sheet.column_dimensions[column[0].column_letter].width = min(max(max_length + 2, 14), 60)

    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()


def export_to_google_sheets(payload: ExportPayload) -> str:
    if not settings.google_service_account_file:
        raise RuntimeError(
            "GOOGLE_SERVICE_ACCOUNT_FILE is not configured. Add it to .env before exporting to Google Sheets."
        )

    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise RuntimeError(
            "Google API packages are not installed. Run: python -m pip install -e .[dev]"
        ) from exc

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    credentials = service_account.Credentials.from_service_account_file(
        settings.google_service_account_file,
        scopes=scopes,
    )
    sheets_service = build("sheets", "v4", credentials=credentials)
    drive_service = build("drive", "v3", credentials=credentials)

    spreadsheet = sheets_service.spreadsheets().create(
        body={"properties": {"title": payload.title}},
        fields="spreadsheetId,spreadsheetUrl",
    ).execute()

    values = [TABLE_COLUMNS, *[_row_values(row) for row in payload.rows]]
    sheets_service.spreadsheets().values().update(
        spreadsheetId=spreadsheet["spreadsheetId"],
        range="A1",
        valueInputOption="RAW",
        body={"values": values},
    ).execute()

    if settings.google_drive_folder_id:
        drive_service.files().update(
            fileId=spreadsheet["spreadsheetId"],
            addParents=settings.google_drive_folder_id,
            fields="id, parents",
        ).execute()

    return spreadsheet["spreadsheetUrl"]


def _row_values(row: ExportRow) -> list[str]:
    return [
        row.entity_query,
        row.matched_entity,
        row.entity_type,
        row.country,
        row.metadata_source,
        row.official_website,
        row.release_type,
        row.studio_type,
        row.genre,
        row.release_date,
        row.network,
        row.platform,
        row.status,
        row.display_name,
        row.handle,
        row.url,
        "" if row.confidence_score is None else str(row.confidence_score),
        row.confidence_label,
        ", ".join(row.account_labels),
        " | ".join(row.evidence),
        " | ".join(row.alternates),
        " | ".join(row.notes),
    ]


def build_ui_matrix_rows(rows: list[ExportRow]) -> list[dict]:
    grouped: dict[str, dict] = {}
    for row in rows:
        key = "||".join(
            [
                row.entity_query,
                row.matched_entity,
                row.entity_type,
                row.country,
                row.metadata_source,
                row.official_website,
                row.release_type,
                row.studio_type,
                row.genre,
                row.release_date,
                row.network,
            ]
        )
        current = grouped.setdefault(
            key,
            {
                "entity_query": row.entity_query,
                "matched_entity": row.matched_entity or "-",
                "entity_type": row.entity_type or "-",
                "country": row.country or "-",
                "metadata_source": row.metadata_source or "-",
                "official_website": row.official_website or "-",
                "release_type": row.release_type or "-",
                "studio_type": row.studio_type or "-",
                "genre": row.genre or "-",
                "release_date": row.release_date or "-",
                "network": row.network or "-",
                "status": row.status or "-",
                "notes": " | ".join(row.notes) if row.notes else "-",
                "platforms": {platform: "-" for platform in PLATFORM_COLUMNS},
            },
        )

        current["status"] = _combine_status(current["status"], row.status)
        if row.notes:
            current["notes"] = " | ".join(row.notes)

        if row.platform in PLATFORM_COLUMNS and row.confidence_score is not None and row.confidence_score >= 60:
            parts = []
            if row.display_name:
                parts.append(row.display_name)
            if row.handle:
                parts.append(row.handle if row.handle.startswith("@") else f"@{row.handle}")
            parts.append(f"{row.confidence_score}/{row.confidence_label}")
            if row.url:
                parts.append(row.url)
            current["platforms"][row.platform] = " | ".join(parts)

    return list(grouped.values())


def _combine_status(existing: str, new_status: str) -> str:
    priority = {
        "found": 4,
        "resolved": 4,
        "uncertain": 3,
        "ambiguous": 2,
        "not_found": 1,
        "-": 0,
        "": 0,
    }
    return existing if priority.get(existing, 0) >= priority.get(new_status, 0) else new_status


def _media_metadata(result: SearchResponse | BulkLookupResult | object) -> dict[str, str]:
    selected_entity = getattr(result, "selected_entity", None)
    source_metadata = getattr(selected_entity, "source_metadata", {}) if selected_entity else {}
    return {
        "metadata_source": source_metadata.get("metadata_source", ""),
        "official_website": getattr(selected_entity, "official_website", "") or source_metadata.get("official_website", ""),
        "release_type": source_metadata.get("release_type", ""),
        "studio_type": source_metadata.get("studio_type", ""),
        "genre": source_metadata.get("genre", ""),
        "release_date": source_metadata.get("release_date", ""),
        "network": source_metadata.get("network", ""),
    }
