import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app import main
from app.core import db
from app.core.config import PublisherConfig, PublishersFile
from app.models.publisher import Publisher


class FakeScheduler:
    def __init__(self) -> None:
        self.jobs: list[dict] = []

    def add_job(self, func, trigger, **kwargs) -> None:
        self.jobs.append({"func": func, "trigger": trigger, **kwargs})

    def start(self) -> None:
        pass

    def shutdown(self, wait: bool = True) -> None:
        pass


@pytest.fixture()
def startup(db_engine, monkeypatch) -> tuple[async_sessionmaker, FakeScheduler]:
    async def no_migrations() -> None:
        pass

    session_factory = async_sessionmaker(db_engine, expire_on_commit=False)
    scheduler = FakeScheduler()
    monkeypatch.setattr(db, "_async_session", session_factory)
    monkeypatch.setattr(main, "init_db", no_migrations)
    monkeypatch.setattr(main, "scheduler", scheduler)
    monkeypatch.setattr(
        main,
        "load_publishers",
        lambda: PublishersFile(publishers=[PublisherConfig(id="fresh", name="Fresh")]),
    )
    return session_factory, scheduler


async def test_startup_syncs_publishers_from_config(startup):
    session_factory, _ = startup
    async with main.lifespan(main.app):
        pass

    async with session_factory() as session:
        assert (await session.scalars(select(Publisher.id))).all() == ["fresh"]
