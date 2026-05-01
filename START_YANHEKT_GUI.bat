@echo off
setlocal
cd /d "%~dp0"

where pyw >nul 2>nul
if not errorlevel 1 (
  start "" pyw -3 "%~dp0yanhekt_gui.py"
  exit /b 0
)

where pythonw >nul 2>nul
if not errorlevel 1 (
  start "" pythonw "%~dp0yanhekt_gui.py"
  exit /b 0
)

where py >nul 2>nul
if not errorlevel 1 (
  start "" py -3 "%~dp0yanhekt_gui.py"
  exit /b 0
)

where python >nul 2>nul
if not errorlevel 1 (
  start "" python "%~dp0yanhekt_gui.py"
  exit /b 0
)

echo Python 3 was not found. Please install Python 3 and try again.
pause
exit /b 2
