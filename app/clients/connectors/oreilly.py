import logging
from datetime import date, timedelta

import httpx

from app.clients.connectors._html import strip_html
from app.clients.connectors._http import Collector, source_client
from app.core.config import PublisherConfig, get_settings
from app.services.types import BookRecord
from app.utils.dates import parse_date
from app.utils.http import get_with_retries
from app.utils.isbn import normalize_isbn13

logger = logging.getLogger(__name__)

OREILLY_SITE = "https://learning.oreilly.com"
OREILLY_SEARCH_URL = OREILLY_SITE + "/api/v2/search/"


async def fetch_oreilly_api(publisher: PublisherConfig, window_days: int) -> list[BookRecord]:
    """New titles of each ``publisher.oreilly_publishers`` name in the O'Reilly API.

    The API's ``publishers`` parameter alone let other imprints through, so items are
    also checked against the name client-side.
    """
    if not publisher.oreilly_publishers:
        logger.warning("oreilly_api: no oreilly_publishers configured for %s", publisher.id)
        return []
    settings = get_settings()
    collector = Collector(settings.max_results_per_source)
    async with source_client(settings) as client:
        for api_name in publisher.oreilly_publishers:
            await _fetch_oreilly_publisher(client, publisher, api_name, window_days, collector)
            if collector.full:
                break
    return collector.records


async def _fetch_oreilly_publisher(
    client: httpx.AsyncClient,
    publisher: PublisherConfig,
    api_name: str,
    window_days: int,
    collector: Collector,
) -> None:
    cutoff = date.today() - timedelta(days=window_days)
    # sort direction is assumed newest first (the early stop relies on it); unverified
    # since the API began answering 401/403 to anonymous clients
    params = {
        "query": "*",
        "formats": "book",
        "sort": "publication_date",
        "publishers": api_name,
        "page": 1,
    }
    while True:
        resp = await get_with_retries(client, OREILLY_SEARCH_URL, params=params)
        data = resp.json()
        items = data.get("results") or []
        if not items:
            return
        page_too_old = False
        for item in items:
            if api_name not in (item.get("publishers") or []):
                continue
            published = _oreilly_published(item)
            if not published:
                continue
            if published < cutoff:
                page_too_old = True
            if collector.add(_oreilly_record(item, publisher, published)):
                return
        if page_too_old or not data.get("next"):
            return
        params["page"] += 1


def _oreilly_record(item: dict, publisher: PublisherConfig, published: date) -> BookRecord:
    title = item.get("title") or "Untitled"
    info_url = item.get("web_url") or item.get("url")
    if info_url and info_url.startswith("/"):
        info_url = OREILLY_SITE + info_url
    return BookRecord(
        source="oreilly_api",
        source_key=item.get("archive_id") or info_url or title,
        publisher_id=publisher.id,
        title=title,
        authors=_oreilly_authors(item),
        language="en",
        subjects=["computers"],
        description=strip_html(item.get("description")) or None,
        isbn_13=normalize_isbn13(item.get("isbn")),
        page_count=item.get("virtual_pages"),
        print_type="book",
        published_date=published,
        cover_url=item.get("cover_url"),
        info_url=info_url,
        raw=item,
    )


def _oreilly_authors(obj: dict) -> list[str]:
    authors = obj.get("authors") or []
    if isinstance(authors, str):
        return [authors]
    return [a for a in authors if a]


def _oreilly_published(obj: dict) -> date | None:
    for key in ["issued", "date_added", "timestamp"]:
        published = parse_date(obj.get(key))
        if published:
            return published
    return None
