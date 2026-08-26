import re
from datetime import date, timedelta

from selectolax.lexbor import LexborHTMLParser

from app.clients.connectors._http import Collector, source_client
from app.core.config import PublisherConfig, get_settings
from app.services.types import BookRecord
from app.utils.dates import parse_date
from app.utils.http import request_with_retries

MANNING_CATALOG_URL = "https://www.manning.com/search/getCatalogData"
# the catalog filter id this connector has always sent; Manning does not document it
MANNING_COMPUTING_CATEGORY_ID = 1
MANNING_WIDE_COVER_URL = "https://images.manning.com/264/149/resize/"
MANNING_COVER_URL = "https://images.manning.com/320/400/resize/"

WHITESPACE_RE = re.compile(r"\s+")


def _manning_cover_url(obj: dict) -> str | None:
    image = obj.get("imageUrl")
    if not image:
        return None
    base = MANNING_WIDE_COVER_URL if obj.get("wideCover") else MANNING_COVER_URL
    return base + image


def _manning_authors(authorship: str | None) -> list[str]:
    if not authorship:
        return []
    clean = LexborHTMLParser(authorship).text(separator=" ")
    clean = WHITESPACE_RE.sub(" ", clean).strip()
    if not clean:
        return []
    parts = re.split(r",| and | with ", clean, flags=re.IGNORECASE)
    return [p.strip(" ,") for p in parts if p.strip()]


def _manning_date(value: str | None) -> date | None:
    if not value:
        return None
    date_part = value.split("T")[0]
    try:
        return date.fromisoformat(date_part)
    except ValueError:
        return parse_date(date_part)


async def fetch_manning_catalog(publisher: PublisherConfig, window_days: int) -> list[BookRecord]:
    settings = get_settings()
    cutoff = date.today() - timedelta(days=window_days)
    payload = {
        "accessType": [],
        "keywords": [],
        "level": [],
        "meapFilter": "",
        "productType": [],
        "programmingLanguages": [],
        "selectedCategoryIds": [MANNING_COMPUTING_CATEGORY_ID],
        "sort": "newest",
        "includePrices": True,
    }

    page = 1
    collector = Collector(settings.max_results_per_source)
    headers = {"Content-Type": "application/json"}
    async with source_client(settings, headers=headers) as client:
        while True:
            payload["page"] = page
            resp = await request_with_retries(client, "POST", MANNING_CATALOG_URL, json=payload)
            data = resp.json()
            products = data.get("products") or []
            page_dates: list[date] = []
            for prod in products:
                published = _manning_date(prod.get("date"))
                if published:
                    page_dates.append(published)
                product_key = prod.get("id") or prod.get("slug") or prod.get("link")
                if not product_key:
                    continue  # nothing to dedupe on; str() turned it into the key "None"
                authors = _manning_authors(prod.get("authorshipDisplay"))
                record = BookRecord(
                    source="manning_catalog",
                    source_key=str(product_key),
                    publisher_id=publisher.id,
                    title=prod.get("title") or "Untitled",
                    subtitle=prod.get("subtitle") or None,
                    authors=authors,
                    language="en",
                    subjects=["computers"],
                    description=None,
                    isbn_13=None,
                    published_date=published,
                    cover_url=_manning_cover_url(prod),
                    info_url=prod.get("link"),
                    raw=prod,
                )
                if collector.add(record):
                    return collector.records
            pagination = data.get("pagination") or {}
            current_page = pagination.get("page") or 0
            total_pages = pagination.get("pages") or 0
            has_next = bool(pagination.get("hasNextPage") and current_page < total_pages)
            if page_dates and min(page_dates) < cutoff:
                break
            if not has_next:
                break
            page += 1
    return collector.records
