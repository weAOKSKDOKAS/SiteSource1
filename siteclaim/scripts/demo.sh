#!/usr/bin/env bash
# One-command offline demo: the API in DEMO_MODE + the wizard, both local, zero
# network. The seeded database and baked fixtures drive everything. Ctrl-C stops both.
#
#   bash scripts/demo.sh
#
# Then open http://localhost:5173 and pick a scenario: clean · hero · messy.
set -euo pipefail

cd "$(dirname "$0")/.."   # -> siteclaim/
ROOT="$(pwd)"
PORT_API="${PORT_API:-8000}"

echo "→ SiteSource demo (DEMO_MODE, offline, zero network)"

# Ensure the proprietary database exists (deterministic, offline build).
if [ ! -f "$ROOT/backend/db/sitesource.db" ]; then
  echo "→ seeding the database…"
  python -m backend.db.seed
fi

echo "→ starting the API on http://localhost:$PORT_API …"
( cd "$ROOT/backend" && exec env DEMO_MODE=true uvicorn api:app --port "$PORT_API" ) &
BACKEND_PID=$!
trap 'echo; echo "→ stopping…"; kill "$BACKEND_PID" 2>/dev/null || true' EXIT INT TERM

# Wait for the API to answer /health.
for _ in $(seq 1 40); do
  curl -sf "http://127.0.0.1:$PORT_API/health" >/dev/null 2>&1 && break
  sleep 0.5
done
echo "→ API healthy: $(curl -s "http://127.0.0.1:$PORT_API/health")"

cd "$ROOT/frontend"
if [ ! -d node_modules ]; then
  echo "→ installing frontend deps (first run)…"
  npm install --no-audit --no-fund
fi

echo "→ starting the wizard on http://localhost:5173"
echo "→ open it and pick a scenario:  clean · hero · messy"
npm run dev
