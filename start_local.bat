@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run setup_windows.bat first.
  pause
  exit /b 1
)
set "SKETCHARM_HOST=127.0.0.1"
start "Robot Sketch Studio" ".venv\Scripts\pythonw.exe" -m robot_sketch_studio
