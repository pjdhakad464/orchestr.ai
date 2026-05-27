from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BASE_DIR / ".env"


class Settings(BaseSettings):
    request_timeout_seconds: int = 12
    cache_ttl_seconds: int = 900
    validation_history_db: str = ""
    validation_output_dir: str = ""
    validation_history_limit: int = 10
    google_service_account_file: str = ""
    google_drive_folder_id: str = ""
    wikimedia_contact: str = "local-app"
    wikipedia_cache_dir: str = ""
    wikipedia_refresh_hours: int = 24
    tmdb_api_key: str = ""
    tmdb_read_access_token: str = ""
    omdb_api_key: str = ""
    imdb_title_basics_url: str = "https://datasets.imdbws.com/title.basics.tsv.gz"
    imdb_name_basics_url: str = "https://datasets.imdbws.com/name.basics.tsv.gz"
    imdb_dataset_dir: str = ""
    imdb_dataset_refresh_hours: int = 24
    imdb_rebuild_stale_index: bool = False

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
