from datetime import datetime

from meta_instagram_comment_analyzer.analysis import analyze_comments
from meta_instagram_comment_analyzer.models import MediaComment


def _comment(text: str) -> MediaComment:
    return MediaComment(
        media_id="m1",
        media_caption=None,
        media_permalink="https://instagram.com/p/test",
        media_timestamp=datetime.fromisoformat("2026-03-27T10:00:00+00:00"),
        comment_id="c1",
        text=text,
        username="demo",
        timestamp=datetime.fromisoformat("2026-03-27T10:01:00+00:00"),
        raw={},
    )


def test_filters_spotify_related_comment_when_only_offtopic_enabled():
    results = analyze_comments([_comment("Spotify premium keeps crashing after every song.")], only_offtopic=True)
    assert results == []


def test_keeps_offtopic_comment_and_marks_negative_sentiment():
    results = analyze_comments(
        [_comment("The flood disaster news is heartbreaking and horrible.")],
        locale_terms=["india"],
        only_offtopic=True,
    )
    assert len(results) == 1
    assert results[0].relevance == "offtopic"
    assert results[0].sentiment == "negative"
    assert "flood" in results[0].matched_offtopic_terms


def test_marks_unclear_when_no_signals_exist():
    results = analyze_comments([_comment("Nice post")], only_offtopic=False)
    assert len(results) == 1
    assert results[0].relevance == "unclear"
    assert results[0].sentiment == "neutral"

