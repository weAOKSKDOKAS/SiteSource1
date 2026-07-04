@echo off
REM =====================================================================
REM  SiteSource backend (FastAPI / uvicorn) on http://localhost:8000
REM
REM  Leave THIS window open and ALONE while you work — do NOT press Ctrl+C
REM  in it mid-request, and do NOT type curl / other commands here. Use a
REM  SEPARATE window for anything else. Closing or interrupting this window
REM  kills the server (the repeated live-testing accident).
REM
REM  Configuration lives in backend\.env (DEMO_MODE, ANTHROPIC_API_KEY,
REM  SMTP_*, SITESOURCE_DB, ...). Copy backend\.env.example to backend\.env
REM  first and fill it in. DEMO_MODE=true runs fully offline; set it false
REM  for the live engine.
REM =====================================================================
setlocal
cd /d "%~dp0..\backend"

REM Activate a local virtualenv if one exists (backend\.venv); otherwise use
REM whatever Python/uvicorn is already on PATH.
if exist ".venv\Scripts\activate.bat" call ".venv\Scripts\activate.bat"

echo.
echo Starting the SiteSource API on http://localhost:8000
echo (edit backend\.env to switch DEMO_MODE or add keys; leave this window open)
echo.
uvicorn api:app --port 8000
