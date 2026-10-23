# Bookfindr — daily computer-book watcher

Single-user service that once a day (or on demand) pulls new computer/IT books for the last `window_days` (90 by default) from per-publisher connectors and, on request, the Google Books and Open Library aggregators, stores them in SQLite, and serves a small UI/API with filters by publisher, language, topic, and publication date.

## Stack and principles
- Python 3.14, FastAPI, SQLite (with FTS5 for search), APScheduler.
- HTTP clients: httpx with timeouts and exponential-backoff retries (Retry-After honoured on 429/5xx). No per-source rate limiting beyond that.
- Schema/ORM: SQLAlchemy 2.x; schema versioned with Alembic (`migrations/`), applied automatically on startup.
- Config-first: publishers described in a YAML file; no auth/roles needed.
- Idempotent upserts; store raw payloads for debugging; deduplicate across sources.

## Publisher configuration (YAML example)
```yaml
publishers:
  - id: oreilly
    name: O'Reilly Media
    languages: [en]
    subjects: [computers]
    google_books:
      inpublishers: ["O'Reilly Media"]
      subjects: ["computers"]
    open_library:
      publishers: ["O'Reilly Media"]
    oreilly_publishers: ["O'Reilly Media, Inc."]  # names as the O'Reilly API spells them
    connectors: ["oreilly_api"]  # optional per-publisher connector
  - id: packt
    name: Packt
    languages: [en]
    subjects: [computers]
    google_books:
      inpublishers: ["Packt Publishing"]
      subjects: ["computers"]
    open_library:
      publishers: ["Packt Publishing"]
    connectors: []
  - id: dmk
    name: DMK Press
    languages: [ru]
    subjects: [computers]
    google_books:
      inpublishers: ["DMK-Press"]
      subjects: ["computers"]
    open_library:
      publishers: ["DMK-Press"]
    connectors: ["dmk_catalog"]
window_days: 90
```
Notes:
- Each source is optional per publisher; add aliases or alternative spellings as arrays.
- `window_days` in the YAML wins; without it the `WINDOW_DAYS` env var (default 90) applies. Sync, the `/books` default `date_from` and the UI label all read this one value.

## Data model (SQLite)
- publishers(id TEXT PK, name TEXT, aliases JSON, languages JSON, created_at, updated_at).
- books(
  id TEXT PK (UUID),
  title TEXT NOT NULL,
  subtitle TEXT,
  authors JSON,
  publisher_id TEXT FK,
  language TEXT,            -- two-letter code (eng/rus from sources are normalized to en/ru)
  subjects JSON,
  topics JSON,
  description TEXT,
  isbn_10 TEXT UNIQUE,
  isbn_13 TEXT UNIQUE,
  dedupe_key TEXT,          -- sha1(normalized title | publisher_id | first author's surname)
  page_count INTEGER,
  print_type TEXT,
  published_date DATE,
  published_date_is_sighting BOOLEAN,  -- the date is when a connector first saw the book
  cover_url TEXT,
  info_url TEXT,
  source_primary TEXT,      -- source of the highest-priority record merged into the book
  source_keys JSON,         -- {source: source_key}
  created_at, updated_at
).
- book_sources(id TEXT PK, book_id FK, source TEXT, source_key TEXT, raw JSON, fetched_at); unique (book_id, source, source_key): a re-fetch refreshes raw/fetched_at in place.
- fetch_runs(id TEXT PK, source TEXT, publisher_id TEXT, started_at, finished_at, status, error TEXT, new_count INT, updated_count INT). status: running, success, partial (some connectors failed, one line each in error), error. URL query strings are redacted from error. Rows older than 30 days are deleted.
- book_fts: FTS5 index over title, description, authors, kept in sync by triggers.
Indexes: publisher_id, published_date, language, dedupe_key, isbn_13, isbn_10.

Source names: `google_books`, `open_library`, and one per connector (`oreilly_api`, `dmk_html`, `piter_json`, `bhv_store`, `miroma_price`, `nit_json`, `manning_catalog`). Merge priority: connectors 3 > Google Books 2 > Open Library 1.

Dedup rules:
1) Look up by isbn_13, then isbn_10.
2) Only a record without any ISBN is matched by dedupe_key (a record with its own ISBN that matches by title is another edition).
3) When merging, a higher-priority source overwrites fields; a lower one only fills missing ones. Empty strings and lists count as missing. A "first seen" date (connectors without a publication date) only fills a missing published_date; a real date from any source replaces a stored "first seen" one. The dedupe_key is recomputed from the merged book.

## Fetch pipeline (daily APScheduler + manual trigger)
1. For each publisher and requested source (default: connectors only):
   - Google Books: `q=subject:{subject} inpublisher:"{name}"&orderBy=newest&printType=books&maxResults=40` with pagination; collect within window_days.
   - Open Library: `/search.json?q=publisher:"{name}"&sort=new&language={lang}`; filter by publish_date locally.
   - Connector(s) listed under `connectors` in the YAML (`CONNECTOR_MAP` in `app/clients/connectors`).
2. Normalize each item into a canonical `BookRecord`; keep records dated within `[today - window_days, today]`.
3. Deduplicate using the rules above; upsert `books` and `book_sources`; log one `fetch_runs` row per publisher (committed as `running` before fetching, so `/sync/status` shows it). A database error in one publisher is recorded and the rest continue.
4. After all publishers: delete books dated before the window or in the future (with their book_sources) and fetch_runs older than 30 days.
5. `dry_run` performs the upsert inside a savepoint and rolls it back: counts are real, nothing is stored or purged.

## API (FastAPI)
- GET /health
- POST /sync/run (body: publisher_id? sources? dry_run?) — запускает синк в фоне, отвечает 202 сразу; 409 если синк уже идёт; 404 для publisher_id не из конфига; sources — только `google_books`, `open_library`, `connectors` (иначе 422). Default sources: `["connectors"]`. With `SYNC_API_KEY` set, the `X-Api-Key` header is required (403 otherwise).
- GET /sync/status — `{running, last_runs}` по журналу fetch_runs.
- GET /publishers — publishers present in the YAML, in YAML order (rows of publishers removed from the YAML stay in the DB but are hidden).
- GET /books — filters: publisher_id, language (normalized, `eng` = `en`), subject, date_from (default: today - window_days), date_to, q (FTS, the last word matches as a prefix), limit/offset; sorted by published_date desc; total в заголовке X-Total-Count. Timestamps are UTC with an offset.
- GET /books/{book_id} — detail plus per-source payloads.
- GET /stats — counts per publisher/source, последние fetch_runs.

## UI (vanilla JS, `app/static/app.js`)
- Filters: publisher, language, subject, date range, search box (the latest query wins, older requests are aborted).
- Cards with title, authors, publisher, date, language, cover and source link; "load more" follows X-Total-Count.
- Detail modal with description, ISBNs, subjects and per-source records.
- Only http(s) URLs are rendered as links or images; source data is inserted as text, never as HTML.
- "Обновить каталоги" calls /sync/run and polls /sync/status; with `SYNC_API_KEY` set it reports that the sync has to be started through the API.

## Error handling & observability
- Per-source timeouts + retry with backoff; 429/5xx retried with Retry-After.
- Log fetch_runs with status and error; keep raw payloads for debugging.
- Validation layer to drop obviously bad rows (empty title, no date, etc.).

## Local dev bootstrap
- Use uv or Poetry with Python 3.14.
- Tasks: `make install`, `make dev` (uvicorn with reload), `make lint`, `make fmt`, `make test`, `make serve`, `make sync`, `make migrate`, `make revision m="..."`.
- Env: `.env` with API keys (Google Books) and optional proxy; SQLite path configurable.

## Delivery plan (incremental)
1) Init repo: pyproject (uv), FastAPI skeleton, config loader, SQLite migrations (Alembic).  
2) Models + FTS + publisher config loader + sample data.  
3) Google Books/Open Library clients with normalization, dedup, upsert.  
4) APScheduler daily job + POST /sync/run.  
5) UI filters + list/detail.  
6) Add first special connector (O'Reilly), then DMK if needed.  
7) Polishing: tests, docs.

## Getting started
1) Copy env and adjust if needed:
```bash
cp .env.example .env
```
2) Install deps (using [uv](https://github.com/astral-sh/uv), replace with `pip install -e .` if you prefer):
```bash
uv sync
```
3) Run API/UI locally:
```bash
make dev  # uv run python -m uvicorn app.main:app --reload
```
4) Trigger a manual sync from the CLI (connectors for all publishers by default):
```bash
uv run python -m app.services.sync
uv run python -m app.services.sync --publisher dmk --sources google_books open_library connectors --dry-run
```
Flags: `--publisher ID` (one publisher), `--sources` (any of `google_books`, `open_library`, `connectors`; default `connectors`), `--dry-run` (report counts, store nothing).

## Current state
- FastAPI app with `/books`, `/publishers`, `/sync/run`, `/sync/status`, `/stats`, `/health` plus a small HTML UI at `/`.
- Startup applies migrations and syncs the publishers table from the YAML, so the publisher filter is filled before the first sync.
- Sync runs in the background under one global lock (manual trigger, CLI and cron never overlap). The APScheduler daily job runs at 03:00 server time (`app/main.py`); a start missed while the machine slept runs once on wake-up.
- Dedup by ISBN-13, then ISBN-10, then the normalized dedupe_key for records without ISBN. Unique-ISBN conflicts skip the record (savepoint per record) instead of failing the sync.
- Search: SQLite FTS5 with a LIKE fallback over title, description and authors.
- HTTP: timeouts plus exponential-backoff retries honouring Retry-After for 429/5xx; aggregator pagination stops once a page leaves window_days.
- Sources: per-publisher connectors (default) and the Google Books / Open Library aggregators on request. Which connector serves which publisher is in `publishers.yml`; new connectors go into `CONNECTOR_MAP` with tests on saved fixtures. A failed connector marks the run `partial` instead of failing silently.
- Books dated in the future are not stored: a title appears once it is out (window_days). For "upcoming" books, drop `purge_future_books` and the future check in `_filter_recent_records`.

## Configuration
- Publishers live in `publishers.yml`; edit/add entries and restart the app. Startup and every sync insert/update the publishers table.
- Relative `DATABASE_URL` SQLite paths and `PUBLISHERS_FILE` resolve against the project root, not the current directory.
- Schema changes: edit models, then `make revision m="describe change"` (Alembic autogenerate) and review the file in `migrations/versions/`. `make migrate` or app startup applies pending migrations; a database created before Alembic is stamped at the baseline automatically.
- SQLite runs with `PRAGMA foreign_keys=ON`, so orphan rows are rejected.
- `window_days` in YAML (else `WINDOW_DAYS` env, default 90) controls how far back books are kept and shown.
- `GOOGLE_BOOKS_API_KEY` optional but recommended to avoid rate limits.

## API quick reference
- `GET /health`
- `GET /publishers`
- `GET /books?publisher_id=packt&language=en&subject=python&q=ml&date_from=2024-01-01`
- `GET /books/{book_id}`
- `POST /sync/run` body: `{"publisher_id":"packt","sources":["google_books","open_library"],"dry_run":false}` → 202, синк идёт в фоне
- `GET /sync/status` — running + последние 20 fetch_runs (status running/success/partial/error)
- `GET /stats` — total_books, разбивка по издательствам/источникам, последние fetch_runs
