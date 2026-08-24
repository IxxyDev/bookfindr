import logging
from datetime import date, timedelta

import httpx

from app.core.config import PublisherConfig, Settings, get_settings
from app.services.types import BookRecord
from app.utils.dates import is_year_only, parse_published_date
from app.utils.filters import is_computing as _is_computing_check
from app.utils.http import get_with_retries
from app.utils.isbn import normalize_isbn10, normalize_isbn13

logger = logging.getLogger(__name__)

GOOGLE_BOOKS_ENDPOINT = "https://www.googleapis.com/books/v1/volumes"
# Google Books rejects startIndex beyond ~1000 anyway
MAX_START_INDEX = 1000


async def fetch_google_books(
    publisher: PublisherConfig,
    settings: Settings | None = None,
    window_days: int | None = None,
) -> list[BookRecord]:
    cfg = settings or get_settings()
    if not publisher.google_books:
        return []

    timeout = httpx.Timeout(cfg.request_timeout, connect=cfg.request_timeout)
    headers = {"User-Agent": cfg.user_agent}
    if cfg.google_books_api_key:
        # a header keeps the key out of URLs, which end up in logs and fetch_runs.error
        headers["X-Goog-Api-Key"] = cfg.google_books_api_key
    today = date.today()
    cutoff = today - timedelta(days=window_days or cfg.window_days)
    results: list[BookRecord] = []

    inpublishers = publisher.google_books.inpublishers or [publisher.name]
    subjects = publisher.google_books.subjects or publisher.subjects or ["computers"]

    async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
        for inpub in inpublishers:
            for subj in subjects:
                query = f'subject:{subj} inpublisher:"{inpub}"'
                start_index = 0
                while True:
                    params = {
                        "q": query,
                        "orderBy": "newest",
                        "printType": "books",
                        "maxResults": 40,
                        "startIndex": start_index,
                    }
                    resp = await get_with_retries(client, GOOGLE_BOOKS_ENDPOINT, params=params)
                    data = resp.json()
                    items = data.get("items") or []
                    if not items:
                        break
                    in_window_this_page = 0
                    page_too_old = False
                    for item in items:
                        volume = item.get("volumeInfo", {})
                        raw_date = volume.get("publishedDate")
                        published = parse_published_date(raw_date, today)
                        is_sighting = is_year_only(raw_date) and published == today
                        if not published:
                            continue
                        if published < cutoff:
                            page_too_old = True
                            continue
                        in_window_this_page += 1
                        if not _is_computing(volume):
                            continue
                        logger.debug(
                            "google_books hit publisher=%s title=%s date=%s",
                            publisher.id,
                            volume.get("title"),
                            published,
                        )
                        record = BookRecord(
                            source="google_books",
                            source_key=item.get("id"),
                            publisher_id=publisher.id,
                            title=volume.get("title") or "Untitled",
                            subtitle=volume.get("subtitle"),
                            authors=volume.get("authors") or [],
                            language=volume.get("language"),
                            subjects=volume.get("categories") or [],
                            topics=[],
                            description=volume.get("description"),
                            isbn_10=normalize_isbn10(
                                _find_isbn(volume.get("industryIdentifiers"), "ISBN_10")
                            ),
                            isbn_13=normalize_isbn13(
                                _find_isbn(volume.get("industryIdentifiers"), "ISBN_13")
                            ),
                            page_count=volume.get("pageCount"),
                            print_type=volume.get("printType"),
                            published_date=published,
                            published_date_is_sighting=is_sighting,
                            cover_url=_get_cover(volume),
                            info_url=volume.get("infoLink"),
                            raw=item,
                        )
                        results.append(record)
                        if len(results) >= cfg.max_results_per_source:
                            return results
                    # orderBy=newest: once a page holds only out-of-window items,
                    # everything further is older still (off-topic items still count
                    # as in-window: they say nothing about the dates further on)
                    if page_too_old and in_window_this_page == 0:
                        break
                    start_index += 40
                    if start_index >= MAX_START_INDEX:
                        break
    return results


def _find_isbn(identifiers, kind: str) -> str | None:
    if not identifiers:
        return None
    for ident in identifiers:
        if ident.get("type") == kind and ident.get("identifier"):
            return ident["identifier"]
    return None


def _get_cover(volume: dict) -> str | None:
    images = volume.get("imageLinks") or {}
    for key in ("thumbnail", "smallThumbnail"):
        if images.get(key):
            return images[key]
    return None


def _is_computing(volume: dict) -> bool:
    text_fields = []
    for field in ("title", "subtitle", "description"):
        val = volume.get(field)
        if isinstance(val, str):
            text_fields.append(val)
    cats = volume.get("categories") or []
    if isinstance(cats, list):
        text_fields.extend(cats)
    return _is_computing_check(text_fields)
