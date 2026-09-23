@echo off
setlocal
cd /d "%~dp0"
if not defined SKETCHARM_URL set /p "SKETCHARM_URL=Host URL (for example http://192.168.1.20:8000): "
if not defined SKETCHARM_API_TOKEN set /p "SKETCHARM_API_TOKEN=Bearer token: "
if "%~1"=="" (
  set /p "IMAGE_PATH=Image path: "
) else (
  set "IMAGE_PATH=%~1"
)
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 tools\remote_client.py "%IMAGE_PATH%" --url "%SKETCHARM_URL%" --token "%SKETCHARM_API_TOKEN%"
) else (
  python tools\remote_client.py "%IMAGE_PATH%" --url "%SKETCHARM_URL%" --token "%SKETCHARM_API_TOKEN%"
)
if errorlevel 1 pause
