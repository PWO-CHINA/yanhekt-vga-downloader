@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

where py >nul 2>nul
if errorlevel 1 goto try_python
py -3 "%~dp0yanhekt_downloader.py" %*
set "EXITCODE=%ERRORLEVEL%"
goto done

:try_python
where python >nul 2>nul
if errorlevel 1 goto no_python
python "%~dp0yanhekt_downloader.py" %*
set "EXITCODE=%ERRORLEVEL%"
goto done

:no_python
echo Python 3 was not found. Please install Python 3 and try again.
set "EXITCODE=2"

:done
if "%~1"=="" (
  echo.
  pause
)
exit /b %EXITCODE%
