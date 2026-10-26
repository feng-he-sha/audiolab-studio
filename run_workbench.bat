@echo off
cd /d "%~dp0"
set PYTHONPATH=%~dp0src;%PYTHONPATH%
if not exist ".venv\Scripts\python.exe" (
  echo Virtual environment not found. Run setup.ps1 first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m audiolab studio
pause
