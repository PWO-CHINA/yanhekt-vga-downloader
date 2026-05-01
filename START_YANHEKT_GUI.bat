@echo off
chcp 65001 >nul
cd /d "%~dp0"
python "%~dp0yanhekt_gui.py"
if errorlevel 1 (
  echo.
  echo GUI 启动失败。请确认已经安装 Python 3。
  pause
)
