import logging
from collections.abc import Callable
from datetime import date, timedelta

import httpx

from app.core.config import PublisherConfig, Settings, get_settings
from app.services.types import BookRecord
from app.utils.dates import is_year_only, parse_published_date
from app.utils.filters import is_computing as _is_computing_check
from app.utils.http import get_with_retries
from app.utils.isbn import normalize_isbn10, normalize_isbn13
from app.utils.lang import normalize_language

logger = logging.getLogger(__name__)

OPEN_LIBRARY_SEARCH = "https://openlibrary.org/search.json"
MAX_PAGES = 50
# search.json stopped returning publish_date unless asked for it by name
SEARCH_FIELDS = ",".join(
    [
        "key",
        "title",
        "subtitle",
        "author_name",
        "publish_date",
        "first_publish_year",
        "language",
        "subject",
        "subject_facet",
        "isbn",
        "cover_i",
        "number_of_pages_median",
        "publisher",
    ]
)


async def fetch_open_library(
    publisher: PublisherConfig,
    settings: Settings | None = None,
    window_days: int | None = None,
) -> list[BookRecord]:
    cfg = settings or get_settings()
    if not publisher.open_library:
        return []

    timeout = httpx.Timeout(cfg.request_timeout, connect=cfg.request_timeout)
    headers = {"User-Agent": cfg.user_agent}
    today = date.today()
    cutoff = today - timedelta(days=window_days or cfg.window_days)
    results: list[BookRecord] = []

    publishers = publisher.open_library.publishers or [publisher.name]
    languages = publisher.open_library.languages or publisher.languages or []

    async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
        for pub_name in publishers:
            page = 1
            while True:
                params = {
                    "publisher": pub_name,
                    "sort": "new",
                    "page": page,
                    "fields": SEARCH_FIELDS,
                }
                if languages:
                    params["language"] = languages[0]
                resp = await get_with_retries(client, OPEN_LIBRARY_SEARCH, params=params)
                data = resp.json()
                docs = data.get("docs") or []
                if not docs:
                    break
                added_this_page = 0
                page_too_old = False
                for doc in docs:
                    published, is_sighting = _doc_published(doc, today)
                    if not published:
                        continue
                    if published < cutoff:
                        page_too_old = True
                        continue
                    if not _is_computing(doc):
                        continue
                    logger.debug(
                        "open_library hit publisher=%s title=%s date=%s",
                        publisher.id,
                        doc.get("title"),
                        published,
                    )
                    record = BookRecord(
                        source="open_library",
                        source_key=doc.get("key"),
                        publisher_id=publisher.id,
                        title=doc.get("title") or "Untitled",
                        subtitle=doc.get("subtitle"),
                        authors=doc.get("author_name") or [],
                        language=normalize_language((doc.get("language") or [None])[0]),
                        subjects=doc.get("subject") or [],
                        topics=doc.get("subject_facet") or [],
                        description=None,
                        isbn_10=_first_valid(doc.get("isbn"), normalize_isbn10),
                        isbn_13=_first_valid(doc.get("isbn"), normalize_isbn13),
                        page_count=doc.get("number_of_pages_median"),
                        print_type=None,
                        published_date=published,
                        published_date_is_sighting=is_sighting,
                        cover_url=_cover_url(doc.get("cover_i")),
                        info_url=_info_url(doc.get("key")),
                        raw=doc,
                    )
                    results.append(record)
                    added_this_page += 1
                    if len(results) >= cfg.max_results_per_source:
                        return results
                # sort=new: a page with only out-of-window docs means the rest is older
                if page_too_old and added_this_page == 0:
                    break
                page += 1
                if page > MAX_PAGES:
                    break
    return results


def _doc_published(doc: dict, today: date) -> tuple[date | None, bool]:
    """(latest publish_date, whether it only stands in for a year by first sighting)."""
    dated = _dated_values(doc.get("publish_date") or [], today)
    if not dated and doc.get("first_publish_year"):
        dated = _dated_values([str(doc["first_publish_year"])], today)
    if not dated:
        return None, False
    # on equal dates prefer a real one over a year-only stand-in
    published, year_only = max(dated, key=lambda pair: (pair[0], not pair[1]))
    return published, year_only and published == today


def _dated_values(values: list[str], today: date) -> list[tuple[date, bool]]:
    """(date, value is year-only) for every value that parses."""
    parsed = [(parse_published_date(value, today), is_year_only(value)) for value in values]
    return [(published, year_only) for published, year_only in parsed if published]


def _first_valid(codes: list[str] | None, normalize: Callable[[str], str | None]) -> str | None:
    return next((isbn for isbn in map(normalize, codes or []) if isbn), None)


def _cover_url(cover_id: int | None) -> str | None:
    if not cover_id:
        return None
    return f"https://covers.openlibrary.org/b/id/{cover_id}-L.jpg"


def _info_url(key: str | None) -> str | None:
    if not key:
        return None
    return f"https://openlibrary.org{key}"


def _is_computing(doc: dict) -> bool:
    text_fields = []
    for field in ("subject", "subject_facet", "title", "subtitle"):
        val = doc.get(field)
        if isinstance(val, list):
            text_fields.extend(val)
        elif isinstance(val, str):
            text_fields.append(val)
    return _is_computing_check(text_fields)
