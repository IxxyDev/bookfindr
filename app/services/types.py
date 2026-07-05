from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional


@dataclass
class BookRecord:
    source: str
    source_key: Optional[str]
    publisher_id: str
    title: str
    subtitle: Optional[str] = None
    authors: List[str] = field(default_factory=list)
    language: Optional[str] = None
    subjects: List[str] = field(default_factory=list)
    topics: List[str] = field(default_factory=list)
    description: Optional[str] = None
    isbn_10: Optional[str] = None
    isbn_13: Optional[str] = None
    page_count: Optional[int] = None
    print_type: Optional[str] = None
    published_date: Optional[date] = None
    cover_url: Optional[str] = None
    info_url: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict)
    dedupe_key: Optional[str] = None


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
