from app.clients.connectors.insales import fetch_insales_collection
from app.core.config import PublisherConfig
from app.services.types import BookRecord

NIT_SITE = "https://nit.com.ru"
NIT_URL = NIT_SITE + "/collection/komp_lit.json"
# same bound as Piter: a broken "count" must not page forever
NIT_MAX_PAGES = 20


async def fetch_nit_catalog(publisher: PublisherConfig, window_days: int) -> list[BookRecord]:
    return await fetch_insales_collection(
        NIT_URL, publisher, window_days, source="nit_json", site=NIT_SITE, max_pages=NIT_MAX_PAGES
    )
