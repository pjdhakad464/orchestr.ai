from __future__ import annotations

from datetime import datetime
from typing import Any
from urllib.parse import urlencode

import httpx

from .config import settings
from .models import InstagramAccount, MediaComment


class MetaOAuthError(RuntimeError):
    """Raised when the Meta OAuth exchange fails."""


class MetaGraphClient:
    def __init__(self, access_token: str | None = None, graph_version: str | None = None) -> None:
        self.access_token = access_token
        self.graph_version = graph_version or settings.meta_graph_version
        self.base_graph_url = f"https://graph.facebook.com/{self.graph_version}"
        self.base_auth_url = f"https://www.facebook.com/{self.graph_version}"

    def build_authorize_url(self, state: str) -> str:
        query = urlencode(
            {
                "client_id": settings.meta_app_id,
                "redirect_uri": settings.meta_redirect_uri,
                "scope": settings.meta_oauth_scopes,
                "response_type": "code",
                "state": state,
            }
        )
        return f"{self.base_auth_url}/dialog/oauth?{query}"

    async def exchange_code(self, code: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
            response = await client.get(
                f"{self.base_graph_url}/oauth/access_token",
                params={
                    "client_id": settings.meta_app_id,
                    "client_secret": settings.meta_app_secret,
                    "redirect_uri": settings.meta_redirect_uri,
                    "code": code,
                },
            )
        if response.status_code >= 400:
            raise MetaOAuthError(response.text)
        return response.json()

    async def get_instagram_accounts(self) -> list[InstagramAccount]:
        pages = await self._get_paginated(
            "/me/accounts",
            params={
                "fields": "id,name,instagram_business_account,connected_instagram_account",
                "limit": 50,
            },
        )
        accounts: list[InstagramAccount] = []
        for page in pages:
            instagram_reference = page.get("instagram_business_account") or page.get("connected_instagram_account")
            if not instagram_reference:
                continue
            instagram_id = instagram_reference.get("id")
            instagram_username = await self._get_instagram_username(instagram_id)
            accounts.append(
                InstagramAccount(
                    page_id=page["id"],
                    page_name=page.get("name", "Unknown Page"),
                    instagram_user_id=instagram_id,
                    instagram_username=instagram_username,
                )
            )
        return accounts

    async def get_recent_media_comments(
        self,
        instagram_user_id: str,
        *,
        media_limit: int,
        comments_per_media: int,
    ) -> list[MediaComment]:
        media_items = await self._get_paginated(
            f"/{instagram_user_id}/media",
            params={
                "fields": "id,caption,permalink,timestamp",
                "limit": media_limit,
            },
            max_items=media_limit,
        )

        comments: list[MediaComment] = []
        async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
            for media in media_items:
                media_id = media["id"]
                next_url = (
                    f"{self.base_graph_url}/{media_id}/comments"
                    f"?fields=id,text,username,timestamp&limit={comments_per_media}&access_token={self.access_token}"
                )
                collected = 0
                while next_url and collected < comments_per_media:
                    response = await client.get(next_url)
                    response.raise_for_status()
                    payload = response.json()
                    for item in payload.get("data", []):
                        comments.append(
                            MediaComment(
                                media_id=media_id,
                                media_caption=media.get("caption"),
                                media_permalink=media.get("permalink"),
                                media_timestamp=_parse_dt(media.get("timestamp")),
                                comment_id=item["id"],
                                text=item.get("text", ""),
                                username=item.get("username"),
                                timestamp=_parse_dt(item.get("timestamp")),
                                raw=item,
                            )
                        )
                        collected += 1
                        if collected >= comments_per_media:
                            break
                    next_url = payload.get("paging", {}).get("next")
        return comments

    async def _get_instagram_username(self, instagram_user_id: str | None) -> str | None:
        if not instagram_user_id:
            return None
        async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
            response = await client.get(
                f"{self.base_graph_url}/{instagram_user_id}",
                params={
                    "fields": "username",
                    "access_token": self.access_token,
                },
            )
        response.raise_for_status()
        return response.json().get("username")

    async def _get_paginated(
        self,
        path: str,
        *,
        params: dict[str, Any],
        max_items: int | None = None,
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
            next_url = f"{self.base_graph_url}{path}"
            next_params = {**params, "access_token": self.access_token}
            while next_url:
                response = await client.get(next_url, params=next_params)
                response.raise_for_status()
                payload = response.json()
                items.extend(payload.get("data", []))
                if max_items is not None and len(items) >= max_items:
                    return items[:max_items]
                next_url = payload.get("paging", {}).get("next")
                next_params = None
        return items


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
