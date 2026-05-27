from __future__ import annotations

import hashlib
from typing import Any

import httpx

from app.cache import TTLCache
from app.config import settings


class TmdbUnavailableError(RuntimeError):
    """Raised when TMDB cannot be used."""


class TmdbClient:
    def __init__(self, timeout_seconds: int, cache: TTLCache) -> None:
        self.timeout_seconds = timeout_seconds
        self.cache = cache
        headers = {"Accept": "application/json"}
        if settings.tmdb_read_access_token:
            headers["Authorization"] = f"Bearer {settings.tmdb_read_access_token}"
        self.client = httpx.AsyncClient(
            timeout=self.timeout_seconds,
            headers=headers,
            limits=httpx.Limits(max_keepalive_connections=20, max_connections=40),
        )

    def is_configured(self) -> bool:
        return bool(settings.tmdb_read_access_token or settings.tmdb_api_key)

    async def search_movie(self, query: str, *, page: int = 1) -> dict[str, Any]:
        return await self._get("/search/movie", {"query": query, "page": page})

    async def search_tv(self, query: str, *, page: int = 1) -> dict[str, Any]:
        return await self._get("/search/tv", {"query": query, "page": page})

    async def search_company(self, query: str, *, page: int = 1) -> dict[str, Any]:
        return await self._get("/search/company", {"query": query, "page": page})

    async def movie_details(self, movie_id: str | int) -> dict[str, Any]:
        return await self._get(f"/movie/{movie_id}")

    async def movie_external_ids(self, movie_id: str | int) -> dict[str, Any]:
        return await self._get(f"/movie/{movie_id}/external_ids")

    async def movie_release_dates(self, movie_id: str | int) -> dict[str, Any]:
        return await self._get(f"/movie/{movie_id}/release_dates")

    async def tv_details(self, tv_id: str | int) -> dict[str, Any]:
        return await self._get(f"/tv/{tv_id}")

    async def tv_external_ids(self, tv_id: str | int) -> dict[str, Any]:
        return await self._get(f"/tv/{tv_id}/external_ids")

    async def company_details(self, company_id: str | int) -> dict[str, Any]:
        return await self._get(f"/company/{company_id}")

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self.is_configured():
            raise TmdbUnavailableError(
                "TMDB is not configured. Add TMDB_API_KEY or TMDB_READ_ACCESS_TOKEN to your .env file."
            )

        merged_params = dict(params or {})
        if settings.tmdb_api_key and "Authorization" not in self.client.headers:
            merged_params["api_key"] = settings.tmdb_api_key

        cache_key = self._cache_key(path, merged_params)
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached  # type: ignore[return-value]

        url = f"https://api.themoviedb.org/3{path}"
        try:
            response = await self.client.get(url, params=merged_params)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            if status_code in {401, 403}:
                raise TmdbUnavailableError(
                    f"TMDB request failed with HTTP {status_code}. Check your TMDB API credentials."
                ) from exc
            raise TmdbUnavailableError(f"TMDB request failed with HTTP {status_code}.") from exc
        except httpx.ConnectError as exc:
            raise TmdbUnavailableError("TMDB request failed: could not connect.") from exc
        except httpx.TimeoutException as exc:
            raise TmdbUnavailableError("TMDB request timed out.") from exc
        except httpx.HTTPError as exc:
            raise TmdbUnavailableError(f"TMDB request failed: {exc.__class__.__name__}.") from exc

        payload = response.json()
        self.cache.set(cache_key, payload)
        return payload

    def _cache_key(self, path: str, params: dict[str, Any]) -> str:
        digest = hashlib.sha1(f"{path}:{sorted(params.items())}".encode("utf-8")).hexdigest()
        return f"tmdb:{digest}"
