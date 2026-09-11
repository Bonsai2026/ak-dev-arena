@echo off
REM ============================================================
REM  AK Dev Studio — Windows one-click dev launcher
REM  Starts the Python backend, then the React frontend.
REM  Close both windows to shut down (backend also exits).
REM ============================================================
setlocal

REM Prefer the project virtualenv if it exists, else system Python.
set "PY=python"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"

where %PY% >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Python not found. Install Python 3.11+ from https://www.python.org/downloads/
  echo         and tick "Add python.exe to PATH" during install.
  pause
  exit /b 1
)

echo [1/2] Starting backend on http://127.0.0.1:8000 ...
start "AK Dev Studio - Backend" cmd /k "%PY% -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000"

echo [2/2] Starting frontend on http://localhost:1420 ...
cd frontend
call npm run dev
echo.
echo Frontend stopped. Close the backend window too, or re-run start.bat.
pause
