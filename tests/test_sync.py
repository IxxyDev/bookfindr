import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.clients.connectors import ConnectorResult
from app.core.config import PublisherConfig, PublishersFile
from app.core.db import Base, create_fts_objects
from app.models.fetch_run import FetchRun
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


@pytest.fixture()
async def file_session_factory(tmp_path):
    """A file database: unlike the shared in-memory one, a second connection only sees commits."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'sync.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(create_fts_objects)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def test_running_fetch_run_is_committed_before_fetching(file_session_factory, monkeypatch):
    seen_statuses: list[str] = []

    async def observing_fetch(*_args):
        async with file_session_factory() as observer:
            seen_statuses.extend((await observer.scalars(select(FetchRun.status))).all())
        return ConnectorResult()

    monkeypatch.setattr(sync, "fetch_connectors", observing_fetch)
    async with file_session_factory() as session:
        await run_sync(session, _config("pub"))

    assert seen_statuses == ["running"]
