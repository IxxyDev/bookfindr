import re
from datetime import date

import httpx

from app.clients.connectors._html import strip_html
from app.clients.connectors._http import Collector, source_client
from app.core.config import PublisherConfig, get_settings
from app.services.types import BookRecord
from app.utils.filters import is_computing
from app.utils.http import get_with_retries
from app.utils.isbn import normalize_isbn13

BHV_PRODUCTS_URL = "https://bhv.ru/wp-json/wc/store/products"
BHV_PER_PAGE = 50
# newest 150 products: BHV publishes a few dozen books a quarter
BHV_MAX_PAGES = 3
BHV_COMPUTING_CATEGORY = "Компьютеры и программы"
ISBN13_IN_TEXT_RE = re.compile(r"97[89][-\s]?[0-9][-\s]?[0-9]{2,}[-\s]?[0-9]{2,}[-\s]?[0-9]")


async def fetch_bhv_store(publisher: PublisherConfig, window_days: int) -> list[BookRecord]:
    """WooCommerce Store API feed, newest first.

    The Store API exposes no product date, so records are dated by first sighting.
    """
    settings = get_settings()
    collector = Collector(settings.max_results_per_source)

    async with source_client(settings) as client:
        for page in range(1, BHV_MAX_PAGES + 1):
            params = {"per_page": BHV_PER_PAGE, "page": page, "orderby": "date", "order": "desc"}
            try:
                resp = await get_with_retries(client, BHV_PRODUCTS_URL, params=params)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code >= 500:
                    break
                raise
            items = resp.json()
            if not isinstance(items, list) or not items:
                # WooCommerce returns an error object instead of a list on failure
                break
            for item in items:
                if _is_computing_product(item) and collector.add(_bhv_record(item, publisher)):
                    return collector.records
            if len(items) < BHV_PER_PAGE:
                break
    return collector.records


def _is_computing_product(item: dict) -> bool:
    categories = [cat.get("name") or "" for cat in item.get("categories") or []]
    if BHV_COMPUTING_CATEGORY in categories:
        return True
    return is_computing([item.get("name") or "", *categories])


def _bhv_record(item: dict, publisher: PublisherConfig) -> BookRecord:
    desc = item.get("short_description") or item.get("description") or ""
    return BookRecord(
        source="bhv_store",
        source_key=str(item.get("id")),
        publisher_id=publisher.id,
        title=item.get("name") or "Untitled",
        language="ru",
        subjects=["computers"],
        description=strip_html(desc),
        isbn_13=_find_isbn_in_text(desc),
        print_type="book",
        published_date=date.today(),
        published_date_is_sighting=True,
        cover_url=_bhv_cover(item),
        info_url=item.get("permalink"),
        raw=item,
    )


def _bhv_cover(item: dict) -> str | None:
    images = item.get("images") or []
    if isinstance(images, dict):
        # the store API sometimes keys images by id instead of a list
        images = list(images.values())
    if images and isinstance(images[0], dict):
        return images[0].get("src")
    return None


def _find_isbn_in_text(text: str) -> str | None:
    if not text:
        return None
    m = ISBN13_IN_TEXT_RE.search(text)
    return normalize_isbn13(m.group(0)) if m else None
