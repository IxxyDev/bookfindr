from app.clients.connectors.insales import fetch_insales_collection
from app.core.config import PublisherConfig
from app.services.types import BookRecord

PITER_SITE = "https://www.piter.com"
PITER_URL = PITER_SITE + "/collection/kompyutery-i-internet.json"
# the whole computing collection is ~11 pages of 100; a bound keeps a broken
# "count" from paging forever
PITER_MAX_PAGES = 20


async def fetch_piter_catalog(publisher: PublisherConfig, window_days: int) -> list[BookRecord]:
    return await fetch_insales_collection(
        PITER_URL,
        publisher,
        window_days,
        source="piter_json",
        site=PITER_SITE,
        max_pages=PITER_MAX_PAGES,
        newest_first=True,
    )
