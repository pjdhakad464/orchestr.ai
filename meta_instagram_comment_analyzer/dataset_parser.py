from __future__ import annotations

import csv
import io
import json
from datetime import datetime
from typing import Any

from .models import MediaComment


COMMENT_TEXT_COLUMNS = ("text", "comment", "message", "body")
COMMENT_ID_COLUMNS = ("comment_id", "id")
USERNAME_COLUMNS = ("username", "user", "author")
TIMESTAMP_COLUMNS = ("timestamp", "created_at", "time")
MEDIA_ID_COLUMNS = ("media_id", "post_id", "parent_id")
MEDIA_PERMALINK_COLUMNS = ("media_permalink", "permalink", "post_url")
MEDIA_CAPTION_COLUMNS = ("media_caption", "caption", "post_caption")
MEDIA_TIMESTAMP_COLUMNS = ("media_timestamp", "post_timestamp")


def parse_uploaded_comments(filename: str, payload: bytes) -> list[MediaComment]:
    lowered = filename.casefold()
    if lowered.endswith(".json"):
        return _parse_json(payload)
    if lowered.endswith(".csv"):
        return _parse_csv(payload)
    raise ValueError("Only .csv and .json files are supported.")


def _parse_json(payload: bytes) -> list[MediaComment]:
    raw = json.loads(payload.decode("utf-8"))
    if isinstance(raw, dict):
        raw_comments = raw.get("comments", [])
    elif isinstance(raw, list):
        raw_comments = raw
    else:
        raise ValueError("JSON payload must be a list or an object with a comments field.")

    return [_build_comment(item, index) for index, item in enumerate(raw_comments, start=1)]


def _parse_csv(payload: bytes) -> list[MediaComment]:
    buffer = io.StringIO(payload.decode("utf-8-sig"))
    reader = csv.DictReader(buffer)
    return [_build_comment(row, index) for index, row in enumerate(reader, start=1)]


def _build_comment(item: dict[str, Any], index: int) -> MediaComment:
    text = _pick(item, COMMENT_TEXT_COLUMNS)
    if not text:
        raise ValueError("Each comment requires a text, comment, message, or body field.")

    media_id = str(_pick(item, MEDIA_ID_COLUMNS) or f"uploaded-media-{index}")
    comment_id = str(_pick(item, COMMENT_ID_COLUMNS) or f"uploaded-comment-{index}")
    timestamp = _parse_dt(_pick(item, TIMESTAMP_COLUMNS))
    media_timestamp = _parse_dt(_pick(item, MEDIA_TIMESTAMP_COLUMNS))

    return MediaComment(
        media_id=media_id,
        media_caption=_as_str(_pick(item, MEDIA_CAPTION_COLUMNS)),
        media_permalink=_as_str(_pick(item, MEDIA_PERMALINK_COLUMNS)),
        media_timestamp=media_timestamp,
        comment_id=comment_id,
        text=str(text),
        username=_as_str(_pick(item, USERNAME_COLUMNS)),
        timestamp=timestamp,
        raw=dict(item),
    )


def _pick(item: dict[str, Any], candidates: tuple[str, ...]) -> Any:
    for candidate in candidates:
        value = item.get(candidate)
        if value not in (None, ""):
            return value
    return None


def _as_str(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _parse_dt(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    text = str(value)
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
