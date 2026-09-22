@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run setup_windows.bat first.
  pause
  exit /b 1
)
set "SKETCHARM_HOST=127.0.0.1"
call .venv\Scripts\activate.bat
python -m robot_sketch_studio
if errorlevel 1 pause

