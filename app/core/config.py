from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class GoogleBooksConfig(BaseModel):
    inpublishers: list[str] = Field(default_factory=list)
    subjects: list[str] = Field(default_factory=list)


class OpenLibraryConfig(BaseModel):
    publishers: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)


class PublisherConfig(BaseModel):
    id: str
    name: str
    languages: list[str] = Field(default_factory=list)
    subjects: list[str] = Field(default_factory=list)
    google_books: GoogleBooksConfig | None = None
    open_library: OpenLibraryConfig | None = None
    connectors: list[str] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)
    # publisher names as the O'Reilly learning API spells them (oreilly_api connector)
    oreilly_publishers: list[str] = Field(default_factory=list)

    @field_validator("id")
    @classmethod
    def normalize_id(cls, v: str) -> str:
        return v.strip().lower()


class PublishersFile(BaseModel):
    publishers: list[PublisherConfig]
    # YAML wins; otherwise WINDOW_DAYS / Settings. Everything reads the window from here.
    window_days: int = Field(default_factory=lambda: get_settings().window_days)


class Settings(BaseSettings):
    app_env: str = "dev"
    database_url: str = "sqlite+aiosqlite:///./bookfindr.db"
    google_books_api_key: str | None = None
    sync_api_key: str | None = None
    window_days: int = 90
    request_timeout: float = 15.0
    max_results_per_source: int = 200
    user_agent: str = "bookfindr/0.1"
    publishers_file: str = "publishers.yml"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Relative paths mean "in the project", not "in whatever directory the app started from"
    @field_validator("database_url")
    @classmethod
    def resolve_sqlite_path(cls, v: str) -> str:
        url = make_url(v)
        database = url.database
        if not url.drivername.startswith("sqlite") or not database or database == ":memory:":
            return v
        if Path(database).is_absolute():
            return v
        return url.set(database=str(PROJECT_ROOT / database)).render_as_string(hide_password=False)

    @field_validator("publishers_file")
    @classmethod
    def resolve_publishers_file(cls, v: str) -> str:
        return v if Path(v).is_absolute() else str(PROJECT_ROOT / v)


@lru_cache
def get_settings() -> Settings:
    return Settings()


def load_publishers(config_path: str | None = None) -> PublishersFile:
    path = Path(config_path or get_settings().publishers_file)
    if not path.exists():
        raise FileNotFoundError(f"Publishers config not found at {path}")
    raw: dict[str, Any] = yaml.safe_load(path.read_text()) or {}
    return PublishersFile(**raw)


def get_publishers_config() -> PublishersFile:
    """FastAPI dependency: the publishers file as loaded now."""
    return load_publishers()
