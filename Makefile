# AK Dev Arena — dev shortcuts
#   make setup     → install everything (backend + optional engines + frontend)
#   make backend   → run API sidecar on :8000
#   make frontend  → run UI on :1420
#   make test      → backend tests
#   make build     → frontend production build

VENV   := .venv
PY     := $(VENV)/bin/python
PIP    := $(VENV)/bin/pip

.PHONY: setup backend frontend test build

setup: ## One-command setup (recommended)
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r backend/requirements.txt
	$(PIP) install -r backend/requirements-optional.txt   # voice, web search, MCP, Aider repo maps
	cd frontend && npm install

backend: ## API brain → http://127.0.0.1:8000/docs (ARENA_HOST=0.0.0.0 for LAN/preview)
	$(PY) -m uvicorn backend.app.main:app --host $${ARENA_HOST:-127.0.0.1} --port 8000 --reload

frontend: ## App face → http://localhost:1420
	cd frontend && npm run dev

test:
	$(PY) -m pytest backend/tests -q

build:
	cd frontend && npm run build
