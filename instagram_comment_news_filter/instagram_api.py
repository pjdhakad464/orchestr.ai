from __future__ import annotations

import os

import httpx

from .models import CommentInput


class InstagramConfigError(RuntimeError):
    """Raised when the owner-authorized Instagram API configuration is incomplete."""


async def fetch_owned_media_comments(media_id: str, *, limit: int = 100) -> list[CommentInput]:
    access_token = os.getenv("INSTAGRAM_ACCESS_TOKEN")
    graph_version = os.getenv("INSTAGRAM_GRAPH_API_VERSION")

    if not access_token or not graph_version:
        raise InstagramConfigError(
            "Set INSTAGRAM_ACCESS_TOKEN and INSTAGRAM_GRAPH_API_VERSION before using the owner-authorized collector."
        )

    comments: list[CommentInput] = []
    next_url = (
        f"https://graph.facebook.com/{graph_version}/{media_id}/comments"
        f"?fields=id,text,timestamp,username&limit={limit}&access_token={access_token}"
    )

    async with httpx.AsyncClient(timeout=20.0) as client:
        while next_url:
            response = await client.get(next_url)
            response.raise_for_status()
            payload = response.json()
            for item in payload.get("data", []):
                comments.append(
                    CommentInput(
                        comment_id=item.get("id"),
                        text=item.get("text", ""),
                        username=item.get("username"),
                        timestamp=item.get("timestamp"),
                        metadata={"source": "instagram_graph_api"},
                    )
                )
            next_url = payload.get("paging", {}).get("next")
            if len(comments) >= limit:
                return comments[:limit]
    return comments

