@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run setup_windows.bat first.
  pause
  exit /b 1
)
set "CHOICE=%~1"
if not defined CHOICE (
  echo 1 - Background removal models
  echo 2 - Clean AI Sketch ^(Informative Drawings^)
  echo 3 - All optional models
  set /p "CHOICE=Select 1, 2, or 3: "
)
call .venv\Scripts\activate.bat
if /i "%CHOICE%"=="1" goto background
if /i "%CHOICE%"=="background" goto background
if /i "%CHOICE%"=="2" goto lineart
if /i "%CHOICE%"=="lineart" goto lineart
if /i "%CHOICE%"=="3" goto all
if /i "%CHOICE%"=="all" goto all
echo Unknown selection.
exit /b 2

:background
python -m pip install -e ".[background]" || exit /b 1
robot-sketch-studio models download rembg-u2net || exit /b 1
robot-sketch-studio models download rembg-u2net-human || exit /b 1
goto done

:lineart
python -m pip install -e ".[ai]" || exit /b 1
robot-sketch-studio models download informative-drawings || exit /b 1
goto done

:all
python -m pip install -e ".[background,ai]" || exit /b 1
robot-sketch-studio models download rembg-u2net || exit /b 1
robot-sketch-studio models download rembg-u2net-human || exit /b 1
robot-sketch-studio models download informative-drawings || exit /b 1

:done
echo Optional models are ready.
pause
