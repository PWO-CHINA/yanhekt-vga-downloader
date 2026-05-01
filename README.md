# Yanhekt 课堂录屏下载器

![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)
![Platform](https://img.shields.io/badge/Platform-Windows-0078D4?logo=windows&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-green)
![AI Generated](https://img.shields.io/badge/AI-generated-8A2BE2)

一个 Windows 优先的小工具，用于把本人已登录、已获授权访问的 Yanhekt 课程课堂录屏批量保存为 `.mp4`。项目提供 Tkinter 图形界面，也保留命令行入口。

> **AI 生成声明**  
> 本项目的代码与文档主要由 OpenAI Codex 根据用户需求自动生成，并经过人工指令、审阅和本地测试后公开。请在使用前自行阅读源码、确认风险，并遵守你所在地区法律法规、课程平台条款和内容授权范围。

## 重要声明

- 本项目不是 Yanhekt 官方工具，与 Yanhekt 官方无隶属、赞助或背书关系。
- 本项目只面向你本人已经有权限访问的课程内容。
- 本项目不会绕过登录、付费、权限校验或 DRM。
- 本项目不会读取你的主 Chrome 浏览器数据库。
- 本项目不会授予你下载、复制、传播、公开分享课程内容的权利。
- 请只在平台条款、课程授权和相关法律允许的范围内使用。

## 功能

- 从课程列表链接批量读取课堂录屏条目。
- 在 GUI 中勾选要下载的课程，并预览最终文件名。
- 下载课堂录屏为 `.mp4` 文件。
- 按课程标题自动命名，空格会转换为下划线，例如 `第1周_星期二_第4大节_课堂录屏.mp4`。
- 显示下载进度、预计剩余时间和估算占用空间。
- 支持 GUI 一键启动，也支持命令行批处理。
- 自动修复早期版本生成的 `.mp_` 或 `_VGA.mp4` 旧文件名。

## 环境要求

- Windows 10/11
- Python 3.10 或更新版本
- Google Chrome
- ffmpeg

本项目不依赖第三方 Python 包。Tkinter 通常随 Windows 版 Python 一起安装。

ffmpeg 可以放在以下任一位置：

- 已加入系统 `PATH`
- 项目目录下的 `ffmpeg-*full_build/bin/ffmpeg.exe`
- 运行命令行时通过 `--ffmpeg` 指定路径

## 快速开始

下载或克隆仓库：

```powershell
git clone https://github.com/PWO-CHINA/yanhekt-vga-downloader.git
cd yanhekt-vga-downloader
```

双击启动 GUI：

```bat
START_YANHEKT_GUI.bat
```

如果你的系统已经正确关联 `.pyw`，也可以直接双击 `START_YANHEKT_GUI.pyw`，启动时不会显示命令行窗口。

在窗口中：

1. 输入课程列表链接，例如 `https://www.yanhekt.cn/course/12345`。
2. 选择保存目录，默认是 `downloads/`。
3. 点击“加载课程清单”。
4. 在表格中勾选要下载的课程，并预览每个文件的保存名称。
5. 点击“下载勾选项”。

注意：这里需要的是课程列表页 `course/数字`，不是单节播放页 `session/数字`。也可以直接输入课程 ID，例如 `12345`。

## 首次登录

首次运行时，如果程序无法连接到已打开的本地 Chrome DevTools，会启动一个独立 Chrome 配置目录。Windows 默认位置：

```text
%LOCALAPPDATA%\YanhektDownloader\chrome-profile
```

请在这个独立 Chrome 窗口中登录 Yanhekt。登录后，程序会在该已登录页面上下文中读取你有权访问的课程列表和课堂录屏地址，再调用 ffmpeg 保存为 mp4。

这个独立 Chrome 配置会像普通浏览器一样保存登录状态。不要上传、打包或分享该目录。

如果需要退出该专用浏览器登录，可在 GUI 中点击“清除浏览器登录”。这个操作只删除本工具的专用 Chrome 配置目录，不会影响你的主 Chrome 浏览器。

## 命令行用法

交互式入口：

```bat
download_yanhekt_vga.bat
```

兼容入口：

```bat
START_YANHEKT_VGA.bat
```

直接运行 Python：

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

| 参数 | 说明 |
| --- | --- |
| `course_url` | 课程列表链接或课程 ID。省略时进入交互式输入。 |
| `-o, --output` | 保存目录，默认是 `downloads/`。 |
| `--dry-run` | 只列出将要下载的视频和文件名，不实际下载。 |
| `--session-ids` | 只下载指定 session id，多个 id 用逗号或空格分隔。 |
| `--newest-first` | 按最新课程优先下载。 |
| `--limit N` | 只下载排序后的前 N 个视频。 |
| `--overwrite` | 覆盖已存在的 mp4 文件。 |
| `--no-size-estimate` | 跳过下载前占用空间估算。 |
| `--keep-browser-open` | 脚本结束后保留独立 Chrome 窗口。 |

## 隐私与安全边界

这个工具的工作方式是连接本机 `127.0.0.1` 上的 Chrome DevTools Protocol，并在已登录的 Yanhekt 页面上下文中执行正常的前端请求。

它的边界：

- 不读取主 Chrome 用户数据目录或浏览器数据库。
- 不把 Yanhekt 登录 token 写入自己的配置文件或日志。
- 不尝试绕过访问控制、付费权限或 DRM。
- 默认把独立 Chrome 配置放在源码目录外，降低误提交风险。
- `.gitignore` 已排除下载产物、浏览器配置、缓存和大体积二进制文件。

仍需注意：

- 独立 Chrome 配置会保存登录态。
- 下载的视频可能受课程平台条款、版权或课堂授权限制。
- 你需要自行判断是否允许离线保存和如何保存。

## 故障排查

### 双击 GUI 没反应

先检查同目录是否生成了：

```text
yanhekt_gui_error.log
```

常见原因：

- Python 没有安装。
- Python 启动器 `py` / `pyw` 不可用。
- Tkinter 缺失。
- 杀毒或系统策略拦截脚本启动。

也可以在命令行中运行：

```powershell
python yanhekt_gui.py
```

这样可以看到更完整的错误信息。

### 下载时要求登录

请在程序打开的独立 Chrome 窗口里登录 Yanhekt。登录完成后不要关闭窗口，程序会继续等待并读取课程信息。

### ffmpeg 找不到

请把 `ffmpeg.exe` 放入系统 `PATH`，或使用：

```powershell
python yanhekt_downloader.py 12345 --ffmpeg C:\path\to\ffmpeg.exe
```

## 开发自检

运行不联网单元测试：

```powershell
python -m unittest discover -s . -p "test_*.py"
```

检查 Python 文件语法：

```powershell
python -m py_compile yanhekt_downloader.py yanhekt_gui.py test_yanhekt_downloader.py
```

## 仓库卫生

以下内容不应进入公开仓库，已在 `.gitignore` 中排除：

- `downloads/`
- `chrome-profile/`
- `ffmpeg-*full_build/`
- `test-output/`
- `__pycache__/`
- 视频文件、临时下载文件和日志

公开提交前建议运行：

```powershell
git status --short --ignored
git ls-files
```

确认只提交源码、文档和启动脚本。

## 许可证

本项目源码使用 [MIT License](LICENSE)。

MIT License 只覆盖本仓库中的源码和文档，不授予任何 Yanhekt 平台、课程视频、课程资料、商标或第三方内容的使用权。课程内容的权利归其合法权利人所有。
