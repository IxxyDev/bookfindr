from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class GoogleBooksConfig(BaseModel):
    inpublishers: List[str] = Field(default_factory=list)
    subjects: List[str] = Field(default_factory=list)


class OpenLibraryConfig(BaseModel):
    publishers: List[str] = Field(default_factory=list)
    languages: List[str] = Field(default_factory=list)


class PublisherConfig(BaseModel):
    id: str
    name: str
    languages: List[str] = Field(default_factory=list)
    subjects: List[str] = Field(default_factory=list)
    google_books: Optional[GoogleBooksConfig] = None
    open_library: Optional[OpenLibraryConfig] = None
    connectors: List[str] = Field(default_factory=list)
    aliases: List[str] = Field(default_factory=list)

    @field_validator("id")
    @classmethod
    def normalize_id(cls, v: str) -> str:
        return v.strip().lower()


class PublishersFile(BaseModel):
    publishers: List[PublisherConfig]
    window_days: int = 90


class Settings(BaseSettings):
    app_env: str = "dev"
    database_url: str = "sqlite+aiosqlite:///./bookfindr.db"
    google_books_api_key: Optional[str] = None
    sync_api_key: Optional[str] = None
    window_days: int = 90
    request_timeout: float = 15.0
    max_results_per_source: int = 200
    user_agent: str = "bookfindr/0.1"
    publishers_file: str = "publishers.yml"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache()
def get_settings() -> Settings:
    return Settings()


def load_publishers(config_path: Optional[str] = None) -> PublishersFile:
    path = Path(config_path or get_settings().publishers_file)
    if not path.exists():
        raise FileNotFoundError(f"Publishers config not found at {path}")
    raw: Dict[str, Any] = yaml.safe_load(path.read_text()) or {}
    return PublishersFile(**raw)
