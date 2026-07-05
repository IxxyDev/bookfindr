import logging
from datetime import date, timedelta
from typing import List, Optional

import httpx

from app.core.config import PublisherConfig, Settings, get_settings
from app.services.types import BookRecord
from app.utils.dates import parse_date
from app.utils.filters import is_computing as _is_computing_check
from app.utils.http import get_with_retries

logger = logging.getLogger(__name__)

OPEN_LIBRARY_SEARCH = "https://openlibrary.org/search.json"
MAX_PAGES = 50


async def fetch_open_library(
    publisher: PublisherConfig,
    settings: Settings | None = None,
    window_days: int | None = None,
) -> List[BookRecord]:
    cfg = settings or get_settings()
    if not publisher.open_library:
        return []

    timeout = httpx.Timeout(cfg.request_timeout, connect=cfg.request_timeout)
    headers = {"User-Agent": cfg.user_agent}
    cutoff = date.today() - timedelta(days=window_days or cfg.window_days)
    results: List[BookRecord] = []

    publishers = publisher.open_library.publishers or [publisher.name]
    languages = publisher.open_library.languages or publisher.languages or []
    subjects = publisher.subjects or ["computers"]

    async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
        for pub_name in publishers:
            page = 1
            while True:
                params = {
                    "publisher": pub_name,
                    "sort": "new",
                    "page": page,
                }
                if languages:
                    params["language"] = languages[0]
                if subjects:
                    params["subject"] = ",".join(subjects)
                resp = await get_with_retries(client, OPEN_LIBRARY_SEARCH, params=params)
                data = resp.json()
                docs = data.get("docs") or []
                if not docs:
                    break
                added_this_page = 0
                page_too_old = False
                for doc in docs:
                    published = _parse_publish_date(doc.get("publish_date"))
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
                        language=(doc.get("language") or [None])[0],
                        subjects=doc.get("subject") or [],
                        topics=doc.get("subject_facet") or [],
                        description=None,
                        isbn_10=_find_isbn(doc.get("isbn"), 10),
                        isbn_13=_find_isbn(doc.get("isbn"), 13),
                        page_count=doc.get("number_of_pages_median"),
                        print_type=None,
                        published_date=published,
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


def _parse_publish_date(values: Optional[list]) -> date | None:
    if not values:
        return None
    parsed_dates = []
    for val in values:
        parsed = parse_date(val)
        if parsed:
            parsed_dates.append(parsed)
    return max(parsed_dates) if parsed_dates else None


def _find_isbn(isbn_list, length: int) -> str | None:
    if not isbn_list:
        return None
    for code in isbn_list:
        cleaned = code.replace("-", "")
        if len(cleaned) == length:
            return cleaned
    return None


def _cover_url(cover_id: Optional[int]) -> str | None:
    if not cover_id:
        return None
    return f"https://covers.openlibrary.org/b/id/{cover_id}-L.jpg"


def _info_url(key: Optional[str]) -> str | None:
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
