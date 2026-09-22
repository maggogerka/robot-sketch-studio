$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path -LiteralPath ".venv\Scripts\python.exe")) {
    throw "Run setup_windows.bat first."
}

& ".venv\Scripts\python.exe" -m pip install --no-build-isolation -e ".[build]"
if ($LASTEXITCODE -ne 0) { throw "Could not install portable build dependencies." }
& ".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean "robot-sketch-studio.spec"
if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed." }

$zip = "dist\RobotSketchStudio-v0.1.0-windows-x64.zip"
if (Test-Path -LiteralPath $zip) { Remove-Item -LiteralPath $zip -Force }
Compress-Archive -Path "dist\RobotSketchStudio\*" -DestinationPath $zip
Write-Host "Portable build created: $zip"
