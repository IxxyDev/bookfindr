PY=uv
APP=app.main:app

.PHONY: install dev run serve lint fmt test sync

install:
	$(PY) sync

dev:
	$(PY) run python -m uvicorn $(APP) --reload

run: dev

serve:
	$(PY) run python -m uvicorn $(APP) --host 0.0.0.0 --port 8000

lint:
	$(PY) run ruff check app tests

fmt:
	$(PY) run ruff check --select I --fix app tests
	$(PY) run ruff format app tests

test:
	$(PY) run python -m pytest

sync:
	$(PY) run python -m app.services.sync
