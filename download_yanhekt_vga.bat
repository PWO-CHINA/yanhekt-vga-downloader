@echo off
chcp 65001 >nul
setlocal EnableExtensions EnableDelayedExpansion
set "SCRIPT_DIR=%~dp0"
if "%~1"=="" (
  echo Yanhekt VGA 批量下载
  echo.
  echo 请粘贴“课程列表链接”（course/数字），不是单节视频播放页（session/数字）。
  echo 例子：
  echo   https://www.yanhekt.cn/course/12345
  echo.
  set /p "COURSE_URL=课程列表链接或课程 ID: "
  if "!COURSE_URL!"=="" (
    echo 没有输入课程链接。
    pause
    exit /b 2
  )
  echo.
  echo 直接回车会保存到默认文件夹：
  echo   %SCRIPT_DIR%downloads
  set /p "OUT_DIR=保存文件夹: "
  echo.
  if "!OUT_DIR!"=="" (
    python "%SCRIPT_DIR%yanhekt_downloader.py" "!COURSE_URL!"
  ) else (
    python "%SCRIPT_DIR%yanhekt_downloader.py" "!COURSE_URL!" -o "!OUT_DIR!"
  )
  echo.
  pause
  exit /b !ERRORLEVEL!
)
python "%SCRIPT_DIR%yanhekt_downloader.py" %*
