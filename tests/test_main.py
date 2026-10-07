import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app import main
from app.core import db
from app.core.config import PublisherConfig, PublishersFile
from app.models.publisher import Publisher
from app.services import sync


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


async def test_daily_job_runs_after_a_missed_start(startup):
    _, scheduler = startup
    async with main.lifespan(main.app):
        pass

    [job] = scheduler.jobs
    assert (job["trigger"], job["hour"], job["minute"]) == ("cron", 3, 0)
    assert job["misfire_grace_time"] is None
    assert job["coalesce"] is True


async def test_scheduled_job_runs_a_sync_and_releases_the_lock(startup, monkeypatch):
    calls: list[dict] = []

    async def fake_run_sync(_session, config, **kwargs):
        calls.append({"publishers": [p.id for p in config.publishers], **kwargs})
        return []

    monkeypatch.setattr(sync, "run_sync", fake_run_sync)
    monkeypatch.setattr(sync, "load_publishers", main.load_publishers)

    await main.scheduled_sync_job()

    assert calls == [
        {"publishers": ["fresh"], "publisher_id": None, "sources": None, "dry_run": False}
    ]
    assert not sync.sync_lock.locked()


async def test_scheduled_job_skips_while_a_sync_runs(startup, monkeypatch):
    async def fail_run_sync(*_args, **_kwargs):
        raise AssertionError("must not run")

    monkeypatch.setattr(sync, "run_sync", fail_run_sync)
    async with sync.sync_lock:
        await main.scheduled_sync_job()
