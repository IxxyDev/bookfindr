"""Per-publisher connectors: one module per source site."""

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from app.clients.connectors.bhv import fetch_bhv_store
from app.clients.connectors.dmk import fetch_dmk_catalog
from app.clients.connectors.manning import fetch_manning_catalog
from app.clients.connectors.miroma import fetch_miroma_price
from app.clients.connectors.nit import fetch_nit_catalog
from app.clients.connectors.oreilly import fetch_oreilly_api
from app.clients.connectors.piter import fetch_piter_catalog
from app.core.config import PublisherConfig
from app.services.types import BookRecord

logger = logging.getLogger(__name__)

# Naive HTML scrapers for dialektika/williams/eksmo/fizmatlit/gelios/ast/knorus/
# eunivers/apress/nostarch/informit/binom were removed: they collected every <a>
# on the page as a "book" with published_date=today. Re-add per-site connectors
# here once proper selectors are written and tested against saved fixtures.
# a connector takes (publisher, window_days)
CONNECTOR_MAP: dict[str, Callable[[PublisherConfig, int], Awaitable[list[BookRecord]]]] = {
    "oreilly_api": fetch_oreilly_api,
    "dmk_catalog": fetch_dmk_catalog,
    "piter_catalog": fetch_piter_catalog,
    "bhv_store": fetch_bhv_store,
    "miroma_price": fetch_miroma_price,
    "nit_catalog": fetch_nit_catalog,
    "manning_catalog": fetch_manning_catalog,
}


@dataclass
class ConnectorResult:
    records: list[BookRecord] = field(default_factory=list)
    # one line per failed source: "<name>: <ExcType>: <message>"
    errors: list[str] = field(default_factory=list)


def failure_line(source: str, exc: Exception) -> str:
    return f"{source}: {type(exc).__name__}: {exc}"


async def fetch_connectors(publisher: PublisherConfig, window_days: int) -> ConnectorResult:
    """Run the publisher's connectors.

    ``window_days`` only tells a connector where to stop paging; the sync applies
    the window filter to every source alike.
    """
    result = ConnectorResult()
    for name in publisher.connectors or []:
        fetcher = CONNECTOR_MAP.get(name)
        if not fetcher:
            logger.warning("Unknown connector %s for %s", name, publisher.id)
            continue
        try:
            result.records.extend(await fetcher(publisher, window_days))
        except Exception as exc:
            logger.exception("Connector %s failed for %s", name, publisher.id)
            result.errors.append(failure_line(name, exc))
    return result


__all__ = ["CONNECTOR_MAP", "ConnectorResult", "failure_line", "fetch_connectors"]
