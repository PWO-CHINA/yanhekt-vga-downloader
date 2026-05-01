# Yanhekt VGA Downloader

一个用于下载 Yanhekt 课程 VGA 回放的小工具，包含 Tkinter 图形界面和命令行入口。

本工具只适用于下载你本人已经登录、并且账号有权限访问的 Yanhekt 课程 VGA 视频。它不会绕过访问控制，也不会读取你的主 Chrome 浏览器数据库。脚本不主动保存登录 token，但独立 Chrome 配置会像正常浏览器一样保存登录状态。

## 适用场景

- 你已经拥有某门 Yanhekt 课程的访问权限。
- 你希望把课程列表中的 VGA 回放批量保存为 `.mp4`。
- 你能提供课程列表链接，例如 `https://www.yanhekt.cn/course/12345`。

请注意：这里需要的是 `course/数字` 课程列表链接，不是单节播放页的 `session/数字` 链接。也可以直接输入课程 ID，例如 `12345`。

## 运行环境

- Windows
- Python 3.10 或更新版本
- Google Chrome
- ffmpeg

本项目不依赖第三方 Python 包，Tkinter 通常随 Python 一起安装。

ffmpeg 可以放在以下任一位置：

- 已加入系统 `PATH`
- 项目目录下的 `ffmpeg-*full_build/bin/ffmpeg.exe`
- 运行 CLI 时通过 `--ffmpeg` 指定路径

## 图形界面用法

双击：

```bat
START_YANHEKT_GUI.bat
```

然后：

1. 粘贴课程列表链接，格式如 `https://www.yanhekt.cn/course/12345`。
2. 选择保存文件夹，默认是 `getvideo/downloads`。
3. 点击“开始下载 VGA”。

首次运行时，如果当前没有可用的本地 Chrome DevTools 连接，程序会打开一个独立的 Chrome 配置目录。Windows 默认位置在 `%LOCALAPPDATA%\YanhektDownloader\chrome-profile`。请在这个独立浏览器窗口中登录 Yanhekt。登录完成后，程序会读取你有权访问的课程列表和 VGA m3u8 签名链接，然后调用 ffmpeg 下载为 mp4。

GUI 会显示：

- 当前下载进度
- 每个视频的估算占用空间
- 下载日志和保存结果

## 命令行用法

交互式入口：

```bat
download_yanhekt_vga.bat
```

或：

```bat
START_YANHEKT_VGA.bat
```

也可以直接运行 Python 脚本：

```powershell
python yanhekt_downloader.py https://www.yanhekt.cn/course/12345
```

常用参数：

```powershell
python yanhekt_downloader.py 12345 -o downloads
python yanhekt_downloader.py 12345 --dry-run
python yanhekt_downloader.py 12345 --newest-first --limit 3
python yanhekt_downloader.py 12345 --overwrite
python yanhekt_downloader.py 12345 --no-size-estimate
python yanhekt_downloader.py 12345 --ffmpeg C:\path\to\ffmpeg.exe
```

参数说明：

- `course_url`：课程列表链接或课程 ID。
- `-o, --output`：保存目录，默认是 `getvideo/downloads`。
- `--dry-run`：只列出将要下载的视频和文件名，不实际下载。
- `--newest-first`：按最新课程优先下载。
- `--limit N`：只下载排序后的前 N 个视频。
- `--overwrite`：覆盖已存在的 mp4 文件。
- `--no-size-estimate`：跳过下载前占用空间估算。
- `--keep-browser-open`：脚本结束后保留独立 Chrome 窗口。

## 安全边界

这个工具的工作方式是连接本机 `127.0.0.1` 上的 Chrome DevTools Protocol，并在已经登录的 Yanhekt 页面上下文中调用前端同源 API。

它的边界是：

- 不读取主 Chrome 用户数据目录或浏览器数据库。
- 脚本不主动把 Yanhekt 登录 token 写入自己的配置文件或日志。
- 独立 Chrome 配置会像正常浏览器一样保存登录状态，请不要把该目录上传、打包或分享。
- 不绕过 Yanhekt 的访问控制、付费权限或 DRM。
- 只下载当前登录账号已经有权限访问的课程 VGA 视频。
- 默认使用源码目录外的独立 Chrome 配置目录，便于和日常浏览器数据隔离，也避免误提交到仓库。

请只下载和保存你有权访问、并被允许离线保存的课程内容。

## 开发自检

仓库包含少量不联网的单元测试，可用于检查文件名生成和旧临时文件修复逻辑：

```powershell
python -m unittest test_yanhekt_downloader.py
```

## 不应提交到 GitHub 的文件

以下内容包含个人登录状态、大体积二进制文件或下载产物，已经在 `.gitignore` 中排除：

- `chrome-profile/`
- `downloads/`
- `ffmpeg-*full_build/`
- `test-output/`
- `__pycache__/`
- 视频文件和临时下载文件
