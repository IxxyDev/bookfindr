from app.core.config import PublisherConfig, PublishersFile
from app.services import sync
from app.services.sync import redact_url_query, run_sync

LEAKY_ERROR = (
    "Client error '403 Forbidden' for url "
    "'https://www.googleapis.com/books/v1/volumes?q=subject%3Acomputers&key=SECRET'"
)


def _config(*publisher_ids: str) -> PublishersFile:
    return PublishersFile(
        publishers=[PublisherConfig(id=pid, name=pid.upper()) for pid in publisher_ids]
    )


def test_redact_url_query_drops_query_strings():
    assert redact_url_query(LEAKY_ERROR) == (
        "Client error '403 Forbidden' for url "
        "'https://www.googleapis.com/books/v1/volumes?<redacted>'"
    )
    assert redact_url_query("no url here") == "no url here"


async def test_run_sync_stores_redacted_error(db_session, monkeypatch):
    async def failing_fetch(*_args):
        raise RuntimeError(LEAKY_ERROR)

    monkeypatch.setattr(sync, "fetch_connectors", failing_fetch)
    runs = await run_sync(db_session, _config("pub"))

    assert runs[0].status == "error"
    assert "SECRET" not in runs[0].error
    assert "volumes?<redacted>" in runs[0].error
