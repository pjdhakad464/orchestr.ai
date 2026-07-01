from __future__ import annotations

import pytest
import openpyxl
from pathlib import Path
import tempfile
import json
from datetime import datetime, timezone
from fastapi.testclient import TestClient

from app.main import app
from app.services.imdb_enricher import IMDbEnricher, TitleQuery
from app.services.duplicate_detector import DuplicateDetector
from app.services.excel_comparator import ExcelComparator
from app.services.health_scorer import MetadataHealthScorer
from app.services.anomaly_detector import AnomalyDetector
from app.engine.pipeline import PipelineEngine, Pipeline, PipelineStep
from app.engine.state import get_pipeline_state

client = TestClient(app)

# 1. Test Duplicate Detector
def test_duplicate_detector():
    detector = DuplicateDetector()
    rows = [
        {"title": "The Dark Knight", "year": "2008", "imdb_id": "tt0468569"},
        {"title": "The Dark Knight", "year": "2008", "imdb_id": "tt0468569"}, # exact duplicate
        {"title": "Dark Knight, The", "year": "2008", "imdb_id": "tt0468569"}, # fuzzy duplicate
        {"title": "Inception", "year": "2010", "imdb_id": "tt1375666"},
    ]
    
    # Exact
    exact_res = detector.detect_exact_duplicates(rows, ["title", "year"])
    assert exact_res.total_duplicates == 2
    assert exact_res.groups[0].match_type == "exact"

    # Fuzzy
    fuzzy_res = detector.detect_fuzzy_duplicates(rows, "title", threshold=0.8)
    assert len(fuzzy_res.groups) >= 1

# 2. Test Excel Comparator
def test_excel_comparator():
    comparator = ExcelComparator()
    
    # Create mock excel files
    with tempfile.TemporaryDirectory() as tmpdir:
        path_a = Path(tmpdir) / "file_a.xlsx"
        path_b = Path(tmpdir) / "file_b.xlsx"
        
        # File A
        wb_a = openpyxl.Workbook()
        ws_a = wb_a.active
        ws_a.title = "Titles"
        ws_a.append(["imdb_id", "title", "year"])
        ws_a.append(["tt1", "Movie One", "2020"])
        ws_a.append(["tt2", "Movie Two", "2021"])
        wb_a.save(path_a)
        
        # File B
        wb_b = openpyxl.Workbook()
        ws_b = wb_b.active
        ws_b.title = "Titles"
        ws_b.append(["imdb_id", "title", "year"])
        ws_b.append(["tt1", "Movie One", "2020"])
        ws_b.append(["tt2", "Movie Two (Modified)", "2021"]) # Modified
        ws_b.append(["tt3", "Movie Three", "2022"]) # Added
        wb_b.save(path_b)
        
        report = comparator.compare(path_a, path_b, key_columns=["imdb_id"])
        
        assert report.total_rows_a == 2
        assert report.total_rows_b == 3
        assert report.added_rows == 1
        assert report.modified_rows == 1
        
        # Test export
        out_report = Path(tmpdir) / "diff.xlsx"
        comparator.export_to_xlsx(report, out_report)
        assert out_report.exists()

# 3. Test Health Scorer
def test_health_scorer():
    scorer = MetadataHealthScorer()
    
    row_perfect = {
        "title": "Inception",
        "released_on": "2010-07-16",
        "imdb_id": "tt1375666",
        "wikipedia_url": "https://en.wikipedia.org/wiki/Inception",
        "year": "2010"
    }
    
    score_p = scorer.score_row(row_perfect)
    assert score_p.overall_score == 100.0
    assert score_p.grade == "A"
    
    row_bad = {
        "title": "",
        "released_on": "invalid-date",
        "imdb_id": "bad-id",
        "wikipedia_url": "not-a-url"
    }
    
    score_b = scorer.score_row(row_bad)
    assert score_b.overall_score < 70.0
    assert score_b.grade in {"D", "F"}

    # Test Movie release date sequencing consistency rules
    row_date_anomaly = {
        "title": "Inception",
        "released_on": "2010-07-16",
        "digital_release_date": "2010-06-01",  # Digital before theatrical
        "trailer_release_date": "2010-08-01",  # Trailer after theatrical
        "imdb_id": "tt1375666",
        "year": "2010"
    }
    score_date = scorer.score_row(row_date_anomaly)
    # Checks fail, so overall score should decline and issues list should capture both mismatches
    assert any("Theatrical date" in issue for issue in score_date.issues)
    assert any("Trailer date" in issue for issue in score_date.issues)

# 4. Test Anomaly Detector
def test_anomaly_detector():
    detector = AnomalyDetector()
    rows = [
        {"title": "A", "released_on": "2020"},
        {"title": "B", "released_on": "2021"},
        {"title": "C", "released_on": "2022"},
        {"title": "D", "released_on": "1920"}, # Outlier year
        {"title": "E", "released_on": "2021"},
        {"title": "F", "released_on": "2022"},
    ]
    
    report = detector.detect_all(rows)
    assert len(report.anomalies) >= 1
    assert report.anomalies[0].anomaly_type == "date_outlier"

# 5. Test Pipeline Engine
@pytest.mark.asyncio
async def test_pipeline_engine():
    engine = PipelineEngine()
    
    # Simple pipeline: score health
    pipeline = Pipeline(
        name="Test Score Pipeline",
        steps=[
            PipelineStep(
                name="Score Rows",
                handler_name="score_health",
                inputs={"rows": []}
            )
        ]
    )
    
    initial_inputs = {
        "rows": [
            {"title": "Inception", "released_on": "2010", "imdb_id": "tt1375666"}
        ]
    }
    
    state = await engine.execute_run(pipeline, initial_inputs, run_by="test_suite")
    assert state.status == "completed"
    assert state.progress_pct == 100.0
    assert "report" in state.step_results["Score Rows"].output

# 6. Test API Endpoints
def test_api_health_status():
    resp = client.get("/api/v1/status")
    assert resp.status_code == 200
    assert resp.json()["status"] == "success"

def test_api_list_pipelines():
    resp = client.get("/api/v1/pipelines")
    assert resp.status_code == 200
    assert len(resp.json()["data"]) >= 2
