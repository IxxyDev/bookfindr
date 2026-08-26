import inspect
import re
import sys

from app.clients.connectors import CONNECTOR_MAP
from app.services.types import source_priority

SOURCE_LITERAL_RE = re.compile(r'source="(\w+)"')


def _connector_sources() -> set[str]:
    """The BookRecord.source names written by the modules behind CONNECTOR_MAP."""
    modules = {sys.modules[fetcher.__module__] for fetcher in CONNECTOR_MAP.values()}
    return {
        source
        for module in modules
        for source in SOURCE_LITERAL_RE.findall(inspect.getsource(module))
    }


def test_every_connector_source_outranks_the_aggregators():
    sources = _connector_sources()
    assert len(sources) == len(CONNECTOR_MAP)  # one source name per connector
    assert {source_priority(source) for source in sources} == {3}


def test_a_source_nobody_listed_counts_as_a_connector():
    assert source_priority("future_connector") == 3


def test_aggregators_rank_google_above_open_library():
    assert source_priority("google_books") == 2
    assert source_priority("open_library") == 1


def test_missing_source_ranks_lowest():
    assert source_priority(None) == 0
    assert source_priority("") == 0
