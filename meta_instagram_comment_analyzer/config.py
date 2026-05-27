from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(slots=True)
class Settings:
    meta_app_id: str = os.getenv("META_APP_ID", "")
    meta_app_secret: str = os.getenv("META_APP_SECRET", "")
    meta_redirect_uri: str = os.getenv("META_REDIRECT_URI", "http://127.0.0.1:8010/auth/callback")
    meta_graph_version: str = os.getenv("META_GRAPH_VERSION", "v23.0")
    meta_oauth_scopes: str = os.getenv(
        "META_OAUTH_SCOPES",
        "instagram_basic,instagram_manage_comments,pages_show_list,pages_read_engagement,business_management",
    )
    app_base_url: str = os.getenv("APP_BASE_URL", "http://127.0.0.1:8010")
    request_timeout_seconds: float = float(os.getenv("REQUEST_TIMEOUT_SECONDS", "20"))
    default_media_limit: int = int(os.getenv("DEFAULT_MEDIA_LIMIT", "10"))
    default_comments_per_media: int = int(os.getenv("DEFAULT_COMMENTS_PER_MEDIA", "50"))


settings = Settings()

