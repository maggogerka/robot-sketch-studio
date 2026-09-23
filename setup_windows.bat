@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (
  py -3.11 -c "import sys" >nul 2>nul
  if %errorlevel%==0 set "PYTHON=py -3.11"
)
if not defined PYTHON set "PYTHON=python"

%PYTHON% -c "import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)"
if errorlevel 1 (
  echo Python 3.11 or newer is required.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" %PYTHON% -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -e ".[dev,ai]"
if errorlevel 1 (
  echo Installation failed. Check the network connection and the message above.
  pause
  exit /b 1
)
if not exist ".env" copy /y ".env.example" ".env" >nul
echo.
echo Robot Sketch Studio is ready.
echo Double-click start_local.bat, then download Informative Drawings in Models.
pause
