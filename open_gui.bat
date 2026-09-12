@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Project Python is missing. See README.md.
  exit /b 1
)
".venv\Scripts\python.exe" app.py
