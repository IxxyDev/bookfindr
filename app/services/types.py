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
    cover_url: str | None = None
    info_url: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)
    dedupe_key: str | None = None


SOURCE_PRIORITY = {
    "oreilly_api": 3,
    "dmk_html": 3,
    "piter_json": 3,
    "bhv_store": 3,
    "miroma_price": 3,
    "nit_json": 3,
    "packt_search": 3,
    "manning_catalog": 3,
    "connector": 3,
    "google_books": 2,
    "open_library": 1,
}
