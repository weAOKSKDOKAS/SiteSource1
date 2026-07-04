# SiteSource — operator quickstart (Windows)

Two windows. One runs the backend and is left alone; the other runs the wizard. Most of
the live-testing accidents came from mixing them up — killing the server mid-request, or
starting the server in the window you were typing `curl` into.

## One-time setup

1. Install dependencies (from `siteclaim\`): `make install`, or manually —
   `cd backend && pip install -r requirements.txt` and `cd frontend && npm install`.
2. Create the backend config: copy `backend\.env.example` to `backend\.env` and fill it in.
   - `DEMO_MODE=true` runs everything offline on fixtures. Set it `false` for the live engine.
   - Live needs `ANTHROPIC_API_KEY`; real email needs the `SMTP_*` block (see
     `docs/EMAIL_SETUP.md`); point `SITESOURCE_DB` at the live DB for real firms only.

`backend\.env` is gitignored — never commit keys.

## Every run

1. **Window 1 — backend.** Double-click `scripts\start_backend.bat` (or run it).
   It serves the API on **http://localhost:8000**.
   **Leave this window open and do not touch it.** Do not press `Ctrl+C` in it while a
   request is in flight, and do not type other commands into it — that is the window that
   keeps the server alive.

2. **Window 2 — wizard.** Double-click `scripts\start_frontend.bat`.
   It serves the UI on **http://localhost:5173** and talks to the backend on :8000.

3. Open **http://localhost:5173** in a browser and work through the five steps
   (ingest → shortlist → dispatch → level → recommend).

## The two URLs

| What | URL |
| --- | --- |
| Wizard (open this) | http://localhost:5173 |
| API (leave running) | http://localhost:8000 — health at `/health`, docs at `/docs` |

To point the wizard at a non-default API, set `VITE_API_BASE` before starting it.

## Rules of thumb

- **Never `Ctrl+C` the backend window mid-request.** Wait for the request to finish, or
  just close the browser tab. If you must stop the server, do it when idle.
- **Anything else goes in a third window** — `curl`, git, `python -m pytest`. Keep the two
  server windows dedicated to their servers.
- Backend not responding from the wizard? Check Window 1 is still running and
  http://localhost:8000/health returns `{"status":"ok"}`.
