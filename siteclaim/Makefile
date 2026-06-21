# SiteSource — developer shortcuts.
.PHONY: demo seed install test build-frontend

# One-command offline demo: API (DEMO_MODE) + wizard, both local, zero network.
demo:
	./scripts/demo.sh

# Build the proprietary database (deterministic, offline) -> backend/db/sitesource.db.
seed:
	python -m backend.db.seed

# Install backend + frontend dependencies.
install:
	cd backend && pip install -r requirements.txt
	cd frontend && npm install

# Backend test suite (offline).
test:
	cd backend && python -m pytest -q

# Type-check + build the frontend.
build-frontend:
	cd frontend && npm run build
