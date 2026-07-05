# Bookfindr — daily computer-book watcher

Single-user service that once a day (or on demand) pulls new computer/IT books for the last 90 days from aggregators (Google Books, Open Library) plus optional per-publisher scrapers, stores them in SQLite, and serves a small UI/API with filters by publisher, language, topic, and publication date.

## Stack and principles
- Python 3.14, FastAPI, SQLite (with FTS5 for search), APScheduler.
- HTTP clients: httpx with timeouts/retries; rate limiting per source.
- Schema/ORM: SQLAlchemy 2.x (or SQLModel if preferred, but stay on SQLA core).
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
    connectors: ["oreilly_new_upcoming"]  # optional HTML scraper
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
- Keep window_days in config for easy tuning; filter locally by date even if API lacks date filters.

## Data model (SQLite)
- publishers(id TEXT PK, name TEXT, aliases JSON, languages JSON, created_at, updated_at).
- books(
  id TEXT PK (ULID/UUID),
  title TEXT NOT NULL,
  subtitle TEXT,
  authors JSON,
  publisher_id TEXT FK,
  language TEXT,
  subjects JSON,
  topics JSON,
  description TEXT,
  isbn_10 TEXT,
  isbn_13 TEXT,
  page_count INTEGER,
  print_type TEXT,
  published_date DATE,
  cover_url TEXT,
  info_url TEXT,
  source_primary TEXT,      -- enum: google_books, open_library, oreilly_html, dmk_html
  source_keys JSON,         -- per-source ids
  created_at, updated_at
).
- book_sources(id TEXT PK, book_id FK, source TEXT, source_key TEXT, raw JSON, fetched_at).
- fetch_runs(id TEXT PK, source TEXT, publisher_id TEXT, started_at, finished_at, status, error TEXT, new_count INT, updated_count INT).
- Optional FTS table: books_fts(content=title, description, authors).
Indexes: publisher_id, published_date, language, isbn_13, isbn_10.

Dedup rules:
1) Prefer isbn_13; fallback to isbn_10.
2) If no ISBNs, normalize key = lower(trim(title)) + authors + publisher; use a hash to compare.
3) When merging, prefer richer fields (connector > Google Books > Open Library); do not downgrade existing non-null fields.

## Fetch pipeline (daily APScheduler + manual trigger)
1. For each publisher and enabled source:
   - Google Books: query `q=subject:{subject}+inpublisher:"{name}"&orderBy=newest&printType=books&maxResults=40` with pagination; collect within window_days.
   - Open Library: `/search.json?q=publisher:"{name}"&sort=new&language={lang}`; filter by publish_date locally.
   - Connector(s): e.g., O'Reilly “New and upcoming”, DMK catalog HTML.
2. Normalize each item into a canonical `BookRecord`.
3. Deduplicate using rules above; upsert `books`; insert/update `book_sources`; log `fetch_runs`.
4. Drop items older than window_days from the run (do not delete existing rows).

## API sketch (FastAPI)
- GET /health
- POST /sync/run (body: publisher_id? sources? dry_run?) — manual kick. Default sources now: `["connectors"]` (агрегаторы отключены по умолчанию).
- GET /publishers — list with config metadata.
- GET /books — filters: publisher_id, language, subject/topic, date_from, date_to, q (FTS), page/limit; sorted by published_date desc.
- GET /books/{book_id} — detail plus per-source payloads (optional include_raw flag).
- GET /stats — counts per publisher/source, last sync timestamps.

## UI concept (HTMX or minimal React)
- Page with filters (publisher multiselect, language, subject, date range) + search box.
- List view shows title, authors, publisher, date, language, subjects, badges for source.
- Detail modal/route with description, cover, ISBNs, links to original.
- Manual “Sync now” button that hits /sync/run.

## Error handling & observability
- Per-source timeouts + retry with backoff; 429 handling and pacing.
- Log fetch_runs with status and error; keep raw payloads for debugging.
- Validation layer to drop obviously bad rows (empty title, no date, etc.).

## Local dev bootstrap
- Use uv or Poetry with Python 3.14.
- Tasks: `make dev` (creates venv), `make lint`, `make test`, `make serve`, `make sync`.
- Env: `.env` with API keys (Google Books) and optional proxy; SQLite path configurable.

## Delivery plan (incremental)
1) Init repo: pyproject (uv/poetry), FastAPI skeleton, config loader, SQLite migrations (Alembic or SQLAlchemy DDL).  
2) Models + FTS + publisher config loader + sample data.  
3) Google Books/Open Library clients with normalization, dedup, upsert.  
4) APScheduler daily job + POST /sync/run.  
5) UI filters + list/detail.  
6) Add first special connector (O'Reilly), then DMK if needed.  
7) Polishing: tests, rate limiting, docs.

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
uv run uvicorn app.main:app --reload
```
4) Trigger a manual sync (runs Google Books + Open Library for all publishers):
```bash
uv run python -m app.services.sync
```

## Current state
- FastAPI app with `/books`, `/publishers`, `/sync/run`, `/health` plus a small HTML UI at `/`.
- SQLite schema via SQLAlchemy; dedup by ISBN-13/10 then normalized hash. Raw payloads saved to `book_sources`.
- APScheduler daily job at 03:00 server time (can be changed in `app/main.py`).
- Sources: Google Books + Open Library implemented; custom connectors are stubbed (log-only).
- Search uses simple `LIKE` over title/description; FTS table exists but not yet wired to queries.

## Configuration
- Publishers live in `publishers.yml`; edit/add entries and restart the app. On startup sync inserts/updates publishers table.
- `WINDOW_DAYS` env or `window_days` in YAML controls how far back to keep from sources.
- `GOOGLE_BOOKS_API_KEY` optional but recommended to avoid rate limits.

## API quick reference
- `GET /health`
- `GET /publishers`
- `GET /books?publisher_id=packt&language=en&subject=python&q=ml&date_from=2024-01-01`
- `GET /books/{book_id}`
- `POST /sync/run` body: `{"publisher_id":"packt","sources":["google_books","open_library"],"dry_run":false}`
