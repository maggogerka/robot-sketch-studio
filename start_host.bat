@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run setup_windows.bat first.
  pause
  exit /b 1
)
if not defined SKETCHARM_API_TOKEN (
  for /f %%i in ('powershell -NoProfile -Command "[Convert]::ToHexString([Security.Cryptography.RandomNumberGenerator]::GetBytes(24))"') do set "SKETCHARM_API_TOKEN=%%i"
)
set "SKETCHARM_HOST=0.0.0.0"
if not defined SKETCHARM_PORT set "SKETCHARM_PORT=8000"
echo.
echo SECURITY WARNING: do not expose this server directly to the public internet.
echo Prefer Tailscale and allow only trusted devices.
echo API URL: http://THIS-PC-IP:%SKETCHARM_PORT%/api/v1
echo Bearer token for this session: %SKETCHARM_API_TOKEN%
echo.
powershell -NoProfile -Command "Get-NetIPAddress -AddressFamily IPv4 ^| Where-Object {$_.IPAddress -notlike '169.254*' -and $_.IPAddress -ne '127.0.0.1'} ^| ForEach-Object {'Local URL: http://' + $_.IPAddress + ':%SKETCHARM_PORT%'}"
call .venv\Scripts\activate.bat
python -m robot_sketch_studio --host 0.0.0.0 --port %SKETCHARM_PORT% --no-browser
if errorlevel 1 pause

