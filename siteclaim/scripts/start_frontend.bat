@echo off
REM =====================================================================
REM  SiteSource wizard (Vite dev server) on http://localhost:5173
REM
REM  Run this in a SECOND window, after the backend window is already up.
REM  It talks to the backend at http://localhost:8000 by default; set
REM  VITE_API_BASE to point elsewhere.
REM =====================================================================
setlocal
cd /d "%~dp0..\frontend"

REM First run: install node dependencies.
if not exist "node_modules" (
  echo Installing frontend dependencies (first run, one-off)...
  call npm install
)

echo.
echo Starting the wizard on http://localhost:5173
echo (backend expected on http://localhost:8000 — start_backend.bat first)
echo.
call npm run dev
