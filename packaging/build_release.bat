@echo off
chcp 65001 >nul
setlocal

cd /d "%~dp0\.."
python packaging\build_release.py
if errorlevel 1 (
    echo.
    echo [错误] 打包失败，请查看上方日志。
    pause
    exit /b 1
)

echo.
echo [完成] release 目录中已经生成安装包。
pause
