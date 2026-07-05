import logging
import os
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.api.routes_books import router as books_router
from app.api.routes_health import router as health_router
from app.api.routes_publishers import router as publishers_router
from app.api.routes_stats import router as stats_router
from app.api.routes_sync import router as sync_router
from app.core.config import get_settings, load_publishers
from app.core.db import get_async_session, init_db
from app.services.sync import run_sync, sync_lock

loglevel = os.getenv("LOGLEVEL", "INFO").upper()
logging.basicConfig(level=getattr(logging, loglevel, logging.INFO))
logger = logging.getLogger(__name__)

templates = Jinja2Templates(directory="app/templates")
scheduler = AsyncIOScheduler()


async def scheduled_sync_job() -> None:
    if sync_lock.locked():
        logger.info("Skipping scheduled sync: another sync is already running")
        return
    async with sync_lock:
        config = load_publishers()
        async with get_async_session()() as session:
            await run_sync(session, config)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    scheduler.add_job(
        scheduled_sync_job,
        "cron",
        hour=3,
        minute=0,
        id="daily_sync",
        replace_existing=True,
    )
    scheduler.start()
    yield
    scheduler.shutdown(wait=False)


app = FastAPI(title="Bookfindr", version="0.1.0", lifespan=lifespan)

app.include_router(health_router)
app.include_router(publishers_router)
app.include_router(books_router)
app.include_router(sync_router)
app.include_router(stats_router)

app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    settings = get_settings()
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "window_days": settings.window_days,
        },
    )
