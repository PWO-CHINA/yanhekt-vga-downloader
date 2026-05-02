@echo off
chcp 65001 >nul
setlocal

cd /d "%~dp0\.."
set PYTHON_CMD=
where py >nul 2>nul
if not errorlevel 1 set PYTHON_CMD=py -3
if not defined PYTHON_CMD (
    where python >nul 2>nul
    if not errorlevel 1 set PYTHON_CMD=python
)
if not defined PYTHON_CMD (
    echo [ERROR] Python 3 was not found. Please install Python 3.10+ or add it to PATH.
    pause
    exit /b 1
)

%PYTHON_CMD% packaging\build_release.py
if errorlevel 1 (
    echo.
    echo [ERROR] Build failed. See the log above.
    pause
    exit /b 1
)

echo.
echo [DONE] Installer has been generated in the release directory.
pause
