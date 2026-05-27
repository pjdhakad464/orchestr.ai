import io

from fastapi.testclient import TestClient

from instagram_comment_news_filter.classifier import classify_comment
from instagram_comment_news_filter.io_utils import parse_uploaded_comments
from instagram_comment_news_filter.main import app
from instagram_comment_news_filter.models import CommentInput


def test_classify_spotify_related_comment():
    result = classify_comment(CommentInput(comment_id="1", text="Spotify premium keeps pausing my music."))
    assert result.category == "spotify_related"
    assert result.is_candidate is False
    assert "spotify" in result.matched_spotify_terms


def test_classify_world_news_comment():
    result = classify_comment(CommentInput(comment_id="2", text="The earthquake news is awful, stay safe everyone."))
    assert result.category == "world_news"
    assert result.is_candidate is True
    assert "earthquake" in result.matched_news_terms


def test_classify_local_news_comment_with_locale_hint():
    result = classify_comment(
        CommentInput(comment_id="3", text="Any update on the Kolkata petrol price hike today?"),
        locale_hint="Kolkata, India",
        local_terms=["kolkata", "india"],
    )
    assert result.category == "local_news"
    assert result.is_candidate is True
    assert "kolkata" in result.matched_local_terms


def test_parse_csv_comments():
    payload = (
        "comment_id,text,username\n"
        "1,Spotify wrapped was fun,alice\n"
        "2,What happened in Delhi today,bob\n"
    ).encode("utf-8")
    comments = parse_uploaded_comments("comments.csv", payload)
    assert len(comments) == 2
    assert comments[1].username == "bob"


def test_classify_file_endpoint_returns_candidates_only():
    client = TestClient(app)
    payload = io.BytesIO(
        (
            "comment_id,text,username\n"
            "1,Spotify wrapped was fun,alice\n"
            "2,What happened in Delhi after the election result today?,bob\n"
        ).encode("utf-8")
    )

    response = client.post(
        "/classify-file",
        data={
            "locale_hint": "Delhi, India",
            "local_terms": "delhi,india",
            "candidates_only": "true",
        },
        files={"comments_file": ("comments.csv", payload.getvalue(), "text/csv")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total_comments"] == 2
    assert body["returned_comments"] == 1
    assert body["comments"][0]["category"] == "local_news"
