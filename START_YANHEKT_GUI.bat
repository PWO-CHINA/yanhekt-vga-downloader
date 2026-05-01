@echo off
setlocal
cd /d "%~dp0"

where pyw >nul 2>nul
if not errorlevel 1 (
  start "" pyw -3 "%~dp0START_YANHEKT_GUI.pyw"
  exit /b 0
)

where pythonw >nul 2>nul
if not errorlevel 1 (
  start "" pythonw "%~dp0START_YANHEKT_GUI.pyw"
  exit /b 0
)

echo Pythonw was not found. Please install Python 3 from python.org and try again.
pause
exit /b 2
