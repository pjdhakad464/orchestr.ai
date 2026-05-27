from __future__ import annotations

import csv
import io
import json
from typing import Any

from .models import CommentInput


COMMENT_TEXT_COLUMNS = ("text", "comment", "message", "body")
COMMENT_ID_COLUMNS = ("comment_id", "id")
USERNAME_COLUMNS = ("username", "user", "author")
TIMESTAMP_COLUMNS = ("timestamp", "created_at", "time")


def parse_uploaded_comments(filename: str, payload: bytes) -> list[CommentInput]:
    lowered = filename.casefold()
    if lowered.endswith(".json"):
        return _parse_json(payload)
    if lowered.endswith(".csv"):
        return _parse_csv(payload)
    raise ValueError("Only .csv and .json files are supported.")


def _parse_json(payload: bytes) -> list[CommentInput]:
    raw = json.loads(payload.decode("utf-8"))
    if isinstance(raw, dict):
        raw_comments = raw.get("comments", [])
    elif isinstance(raw, list):
        raw_comments = raw
    else:
        raise ValueError("JSON payload must be a list or an object with a comments field.")

    comments = []
    for item in raw_comments:
        comments.append(
            CommentInput(
                comment_id=_pick(item, COMMENT_ID_COLUMNS),
                text=_require_text(item),
                username=_pick(item, USERNAME_COLUMNS),
                timestamp=_pick(item, TIMESTAMP_COLUMNS),
                metadata={k: v for k, v in item.items() if k not in set(COMMENT_ID_COLUMNS + COMMENT_TEXT_COLUMNS + USERNAME_COLUMNS + TIMESTAMP_COLUMNS)},
            )
        )
    return comments


def _parse_csv(payload: bytes) -> list[CommentInput]:
    buffer = io.StringIO(payload.decode("utf-8-sig"))
    reader = csv.DictReader(buffer)
    comments = []
    for row in reader:
        comments.append(
            CommentInput(
                comment_id=_pick(row, COMMENT_ID_COLUMNS),
                text=_require_text(row),
                username=_pick(row, USERNAME_COLUMNS),
                timestamp=_pick(row, TIMESTAMP_COLUMNS),
                metadata={k: v for k, v in row.items() if k and k not in set(COMMENT_ID_COLUMNS + COMMENT_TEXT_COLUMNS + USERNAME_COLUMNS + TIMESTAMP_COLUMNS)},
            )
        )
    return comments


def _require_text(item: dict[str, Any]) -> str:
    text = _pick(item, COMMENT_TEXT_COLUMNS)
    if not text:
        raise ValueError("Each comment requires a text, comment, message, or body field.")
    return str(text)


def _pick(item: dict[str, Any], candidates: tuple[str, ...]) -> Any:
    for candidate in candidates:
        value = item.get(candidate)
        if value not in (None, ""):
            return value
    return None

