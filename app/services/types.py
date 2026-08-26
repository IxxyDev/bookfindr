from dataclasses import dataclass, field
from datetime import date
from typing import Any


@dataclass
class BookRecord:
    source: str
    source_key: str | None
    publisher_id: str
    title: str
    subtitle: str | None = None
    authors: list[str] = field(default_factory=list)
    language: str | None = None
    subjects: list[str] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)
    description: str | None = None
    isbn_10: str | None = None
    isbn_13: str | None = None
    page_count: int | None = None
    print_type: str | None = None
    published_date: date | None = None
    # True when published_date is the day we first saw the book, not a real date
    published_date_is_sighting: bool = False
    cover_url: str | None = None
    info_url: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)
    dedupe_key: str | None = None


# Aggregators rank below connectors; any source not listed here is a connector.
SOURCE_PRIORITY = {
    "google_books": 2,
    "open_library": 1,
}
CONNECTOR_PRIORITY = 3


def source_priority(source: str | None) -> int:
    if not source:
        return 0
    return SOURCE_PRIORITY.get(source, CONNECTOR_PRIORITY)
