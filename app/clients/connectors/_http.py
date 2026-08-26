import httpx

from app.core.config import Settings
from app.services.types import BookRecord


def source_client(
    settings: Settings, headers: dict[str, str] | None = None, **kwargs
) -> httpx.AsyncClient:
    """httpx client with the configured timeout and User-Agent."""
    timeout = httpx.Timeout(settings.request_timeout, connect=settings.request_timeout)
    all_headers = {"User-Agent": settings.user_agent, **(headers or {})}
    return httpx.AsyncClient(timeout=timeout, headers=all_headers, **kwargs)


class Collector:
    """Records of one connector run, capped at ``limit`` (max_results_per_source)."""

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.records: list[BookRecord] = []

    @property
    def full(self) -> bool:
        return len(self.records) >= self.limit

    def add(self, record: BookRecord) -> bool:
        """Keep ``record``; True once the cap is reached."""
        self.records.append(record)
        return self.full
