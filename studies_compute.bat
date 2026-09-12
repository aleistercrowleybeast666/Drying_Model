@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Project Python is missing. See README.md.
  exit /b 1
)
if "%~1"=="" (
  ".venv\Scripts\python.exe" compute_studies.py --dry-run
  echo To compute explicitly: studies_compute.bat --group all --resume
  pause
  exit /b 0
)
".venv\Scripts\python.exe" compute_studies.py %*
