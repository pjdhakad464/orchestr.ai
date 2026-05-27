from fastapi.testclient import TestClient

from meta_instagram_comment_analyzer import main
from meta_instagram_comment_analyzer.models import InstagramAccount, MediaComment
from meta_instagram_comment_analyzer.store import auth_store


def test_index_renders():
    client = TestClient(main.app)
    response = client.get("/")
    assert response.status_code == 200
    assert "Instagram Comment Dataset Analyzer" in response.text
    assert "Analyze Uploaded Comments" in response.text


def test_api_accounts_returns_mocked_accounts(monkeypatch):
    session = auth_store.create_session("token", "v23.0")

    async def fake_get_instagram_accounts(self):
        return [InstagramAccount(page_id="1", page_name="Spotify Page", instagram_user_id="ig1", instagram_username="spotify")]

    monkeypatch.setattr(main.MetaGraphClient, "get_instagram_accounts", fake_get_instagram_accounts)

    client = TestClient(main.app)
    response = client.get(f"/api/accounts?session_id={session.session_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["accounts"][0]["instagram_username"] == "spotify"


def test_analyze_route_renders_results(monkeypatch):
    session = auth_store.create_session("token", "v23.0")

    async def fake_get_recent_media_comments(self, instagram_user_id, media_limit, comments_per_media):
        return [
            MediaComment(
                media_id="m1",
                media_caption=None,
                media_permalink="https://instagram.com/p/test",
                media_timestamp=None,
                comment_id="c1",
                text="Any update on the election result today?",
                username="reader",
                timestamp=None,
                raw={},
            )
        ]

    monkeypatch.setattr(main.MetaGraphClient, "get_recent_media_comments", fake_get_recent_media_comments)

    client = TestClient(main.app)
    response = client.post(
        "/analyze",
        data={
            "session_id": session.session_id,
            "instagram_user_id": "ig1",
            "media_limit": 5,
            "comments_per_media": 20,
            "extra_spotify_terms": "",
            "locale_terms": "india",
            "only_offtopic": "true",
        },
    )
    assert response.status_code == 200
    assert "Analysis Results" in response.text
    assert "election result" in response.text
    assert "Download CSV" in response.text


def test_analyze_upload_renders_results():
    client = TestClient(main.app)
    response = client.post(
        "/analyze-upload",
        data={
            "extra_spotify_terms": "",
            "locale_terms": "india",
            "only_offtopic": "true",
        },
        files={
            "comments_file": (
                "comments.csv",
                (
                    "comment_id,text,username\n"
                    "1,Spotify premium keeps crashing after every song.,listener\n"
                    "2,Any update on the election result today?,reader\n"
                ).encode("utf-8"),
                "text/csv",
            )
        },
    )
    assert response.status_code == 200
    assert "Analysis Results" in response.text
    assert "comments.csv" in response.text
    assert "Any update on the election result today?" in response.text
    assert "Spotify premium keeps crashing after every song." not in response.text
    assert "Download CSV" in response.text


def test_export_saved_csv_downloads_filtered_results():
    client = TestClient(main.app)
    analyze_response = client.post(
        "/analyze-upload",
        data={
            "extra_spotify_terms": "",
            "locale_terms": "india",
            "only_offtopic": "true",
        },
        files={
            "comments_file": (
                "comments.csv",
                (
                    "comment_id,text,username\n"
                    "1,Spotify premium keeps crashing after every song.,listener\n"
                    "2,Any update on the election result today?,reader\n"
                ).encode("utf-8"),
                "text/csv",
            )
        },
    )
    export_path = _extract_export_path(analyze_response.text)

    response = client.get(export_path)
    assert response.status_code == 200
    assert response.headers["content-disposition"].startswith("attachment; filename=")
    assert "text/csv" in response.headers["content-type"]
    assert "Any update on the election result today?" in response.text
    assert "Spotify premium keeps crashing after every song." not in response.text
    assert "sentiment" in response.text


def _extract_export_path(html: str) -> str:
    marker = '/exports/'
    start = html.index(marker)
    end = html.index('"', start)
    return html[start:end]
