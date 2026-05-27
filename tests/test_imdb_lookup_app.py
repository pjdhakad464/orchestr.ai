import csv
import gzip
import io
from pathlib import Path

from fastapi.testclient import TestClient
from openpyxl import Workbook, load_workbook

from imdb_lookup_app.config import settings
from imdb_lookup_app.main import app
from imdb_lookup_app.routes import cache


def test_index_page_renders():
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200
    assert "IMDb Bulk Lookup" in response.text
    assert "Quick Bulk Lookup" in response.text
    assert "CSV Or Excel Input" in response.text


def test_api_lookup_resolves_ids_and_reverse_matches(monkeypatch, tmp_path):
    _configure_lookup_datasets(monkeypatch, tmp_path)
    client = TestClient(app)

    response = client.post(
        "/api/lookup",
        json={
            "mode": "auto",
            "values": ["tt0000001", "Jane Example", "Shared Name"],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    rows = payload["rows"]
    assert any(row["imdb_id"] == "tt0000001" and row["display_name"] == "First Title" for row in rows)
    assert any(row["imdb_id"] == "nm0000001" and row["display_name"] == "Jane Example" for row in rows)

    shared_rows = [row for row in rows if row["input_value"] == "Shared Name"]
    assert len(shared_rows) == 3
    assert all(row["status"] == "multiple_matches" for row in shared_rows)
    assert any(row["entity_kind"] == "title" for row in shared_rows)
    assert any(row["entity_kind"] == "person" for row in shared_rows)


def test_file_upload_returns_downloadable_csv_and_xlsx(monkeypatch, tmp_path):
    _configure_lookup_datasets(monkeypatch, tmp_path)
    client = TestClient(app)

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Input"
    sheet.append(["input"])
    sheet.append(["tt0000001"])
    sheet.append(["Jane Example"])
    buffer = io.BytesIO()
    workbook.save(buffer)

    response = client.post(
        "/lookup/file",
        data={"mode": "auto", "sheet_name": "Input", "input_column": "input"},
        files={
            "dataset_file": (
                "lookup.xlsx",
                buffer.getvalue(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )

    assert response.status_code == 200
    assert "Download CSV" in response.text
    assert "Download Excel" in response.text
    export_id = _extract_export_id(response.text, "csv")

    csv_response = client.get(f"/download/{export_id}/csv")
    assert csv_response.status_code == 200
    csv_rows = list(csv.DictReader(io.StringIO(csv_response.content.decode("utf-8-sig"))))
    assert any(row["imdb_id"] == "tt0000001" for row in csv_rows)
    assert any(row["display_name"] == "Jane Example" for row in csv_rows)

    xlsx_response = client.get(f"/download/{export_id}/xlsx")
    assert xlsx_response.status_code == 200
    workbook_result = load_workbook(io.BytesIO(xlsx_response.content))
    assert "Summary" in workbook_result.sheetnames
    assert "Results" in workbook_result.sheetnames
    result_sheet = workbook_result["Results"]
    assert result_sheet["H2"].value == "tt0000001"

    cache._items.clear()


def _extract_export_id(html: str, fmt: str) -> str:
    marker = "/download/"
    start = html.index(marker) + len(marker)
    end = html.index(f"/{fmt}", start)
    return html[start:end]


def _configure_lookup_datasets(monkeypatch, tmp_path: Path) -> None:
    title_dataset = tmp_path / "title.basics.tsv.gz"
    name_dataset = tmp_path / "name.basics.tsv.gz"
    cache_dir = tmp_path / "cache"

    _write_gzipped_tsv(
        title_dataset,
        ["tconst", "titleType", "primaryTitle", "originalTitle", "isAdult", "startYear", "endYear", "runtimeMinutes", "genres"],
        [
            ["tt0000001", "movie", "First Title", "Original First", "0", "1999", r"\N", "136", "Action"],
            ["tt0000002", "tvSeries", "Shared Name", "Shared Name", "0", "2010", "2014", "45", "Drama"],
            ["tt0000003", "movie", "Shared Name", "Shared Name", "0", "2024", r"\N", "110", "Drama"],
        ],
    )
    _write_gzipped_tsv(
        name_dataset,
        ["nconst", "primaryName", "birthYear", "deathYear", "primaryProfession", "knownForTitles"],
        [
            ["nm0000001", "Jane Example", "1980", r"\N", "actor,producer", "tt0000001,tt0000002"],
            ["nm0000002", "Shared Name", "1975", r"\N", "actor", "tt0000003"],
        ],
    )

    monkeypatch.setattr(settings, "imdb_lookup_title_basics_url", str(title_dataset))
    monkeypatch.setattr(settings, "imdb_lookup_name_basics_url", str(name_dataset))
    monkeypatch.setattr(settings, "imdb_lookup_dataset_dir", str(cache_dir))
    monkeypatch.setattr(settings, "imdb_lookup_refresh_hours", 24)
    monkeypatch.setattr(settings, "imdb_lookup_export_ttl_seconds", 900)
    cache._items.clear()


def _write_gzipped_tsv(path: Path, headers: list[str], rows: list[list[str]]) -> None:
    with gzip.open(path, "wt", encoding="utf-8", newline="") as file_handle:
        writer = csv.writer(file_handle, delimiter="\t")
        writer.writerow(headers)
        writer.writerows(rows)
