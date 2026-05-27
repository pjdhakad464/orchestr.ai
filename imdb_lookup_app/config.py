from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BASE_DIR / ".env"


class Settings(BaseSettings):
    imdb_lookup_title_basics_url: str = "https://datasets.imdbws.com/title.basics.tsv.gz"
    imdb_lookup_name_basics_url: str = "https://datasets.imdbws.com/name.basics.tsv.gz"
    imdb_lookup_dataset_dir: str = ""
    imdb_lookup_refresh_hours: int = 24
    imdb_lookup_export_ttl_seconds: int = 900

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
