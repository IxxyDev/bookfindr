"""Collection JSON of InSales shops (Piter, NiT)."""

from datetime import date, datetime, timedelta

from app.clients.connectors._http import Collector, source_client
from app.core.config import PublisherConfig, get_settings
from app.services.types import BookRecord
from app.utils.dates import date_from_year
from app.utils.http import get_with_retries
from app.utils.isbn import normalize_isbn13

INSALES_PER_PAGE = 100  # the largest page InSales serves
# characteristic names (lowercased) differ between shops
INSALES_AUTHOR_KEYS = ["автор(ы)", "автор"]
INSALES_YEAR_KEYS = ["год", "год издания", "год тиража"]
INSALES_PAGES_KEYS = ["страниц", "количество страниц"]


async def fetch_insales_collection(
    url: str,
    publisher: PublisherConfig,
    window_days: int,
    source: str,
    site: str,
    max_pages: int,
    newest_first: bool = False,
) -> list[BookRecord]:
    settings = get_settings()
    cutoff = date.today() - timedelta(days=window_days)
    collector = Collector(settings.max_results_per_source)

    async with source_client(settings) as client:
        for page in range(1, max_pages + 1):
            page_params = {"page": page, "per": INSALES_PER_PAGE}
            if newest_first:
                page_params["sort"] = "created_at_desc"
            resp = await get_with_retries(client, url, params=page_params)
            data = resp.json()
            products = data.get("products") or []
            if not products:
                break
            records = [_insales_record(prod, publisher, source, site) for prod in products]
            for record in records:
                if collector.add(record):
                    return collector.records
            total = data.get("count") or 0
            if len(products) < INSALES_PER_PAGE or (total and page * INSALES_PER_PAGE >= total):
                break
            # only a newest-first listing lets a page dated before the window end it
            if newest_first and all(
                r.published_date and r.published_date < cutoff for r in records
            ):
                break
    return collector.records


def _insales_record(prod: dict, publisher: PublisherConfig, source: str, site: str) -> BookRecord:
    values = _insales_char_values(prod)
    published = _insales_published_date(prod, values)
    today = date.today()
    # dated today though the feed did not say so: date_from_year fell back to first sighting
    is_sighting = published == today and _insales_updated_at(prod) != today
    return BookRecord(
        source=source,
        source_key=str(prod.get("id")),
        publisher_id=publisher.id,
        title=prod.get("title") or "Untitled",
        authors=_insales_authors(values),
        language="ru",
        subjects=["computers"],
        description=prod.get("short_description"),
        isbn_13=_insales_isbn(values),
        page_count=_insales_pages(values),
        print_type="book",
        published_date=published,
        published_date_is_sighting=is_sighting,
        cover_url=_insales_cover(prod),
        # the feed sends "url": null for some products
        info_url=site + prod["url"] if prod.get("url") else None,
        raw=prod,
    )


def _insales_char_values(prod: dict) -> dict[str, list[str]]:
    """Characteristic values keyed by lowercased property title."""
    property_titles = {p["id"]: p.get("title") for p in prod.get("properties", [])}
    values: dict[str, list[str]] = {}
    for ch in prod.get("characteristics") or []:
        name = property_titles.get(ch.get("property_id"))
        if not name:
            continue
        values.setdefault(name.lower(), []).append(ch.get("title") or "")
    return values


def _first_values(values: dict[str, list[str]], keys: list[str]) -> list[str]:
    return next((values[key] for key in keys if values.get(key)), [])


def _insales_updated_at(prod: dict) -> date | None:
    updated_at = prod.get("updated_at")
    if not updated_at:
        return None
    try:
        return datetime.fromisoformat(updated_at.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _insales_published_date(prod: dict, values: dict[str, list[str]]) -> date | None:
    updated = _insales_updated_at(prod)
    # most Piter products carry only "год тиража" (print-run year), not "год"
    year_text = (_first_values(values, INSALES_YEAR_KEYS) or [""])[0][:4]
    if year_text.isdigit():
        return date_from_year(int(year_text), date.today(), fallback=updated)
    return updated


def _insales_authors(values: dict[str, list[str]]) -> list[str]:
    authors = _first_values(values, INSALES_AUTHOR_KEYS)
    return [a.strip() for val in authors for a in val.split(",") if a.strip()]


def _insales_isbn(values: dict[str, list[str]]) -> str | None:
    return next((i for i in map(normalize_isbn13, values.get("isbn") or []) if i), None)


def _insales_pages(values: dict[str, list[str]]) -> int | None:
    pages = _first_values(values, INSALES_PAGES_KEYS)
    return next((int(val) for val in pages if val.isdigit()), None)


def _insales_cover(prod: dict) -> str | None:
    img = prod.get("first_image") or {}
    return img.get("large_url") or img.get("original_url") or img.get("url")
