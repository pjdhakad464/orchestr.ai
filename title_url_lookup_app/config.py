from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BASE_DIR / ".env"


class Settings(BaseSettings):
    request_timeout_seconds: int = 12
    cache_ttl_seconds: int = 900
    title_lookup_export_ttl_seconds: int = 900
    metacritic_calendar_base_url: str = "http://127.0.0.1:8002"
    wikimedia_contact: str = "local-app"
    imdb_title_basics_url: str = "https://datasets.imdbws.com/title.basics.tsv.gz"
    imdb_name_basics_url: str = "https://datasets.imdbws.com/name.basics.tsv.gz"
    imdb_title_episode_url: str = "https://datasets.imdbws.com/title.episode.tsv.gz"
    imdb_dataset_dir: str = ""
    imdb_dataset_refresh_hours: int = 24

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
