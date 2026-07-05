PY=uv
APP=app.main:app

.PHONY: install dev run serve lint fmt test sync

install:
	$(PY) sync

dev:
	$(PY) run uvicorn $(APP) --reload

run: dev

serve:
	$(PY) run uvicorn $(APP) --host 0.0.0.0 --port 8000

lint:
	$(PY) run ruff check app

fmt:
	$(PY) run ruff check --select I --fix app
	$(PY) run ruff format app

test:
	$(PY) run pytest

sync:
	$(PY) run python -m app.services.sync
