# Yanhekt Downloader v0.0.1

首个 Windows 安装包预览版。

## 下载

- `YanhektDownloader_Setup_v0.0.1.exe`

## 使用前请阅读

- 本项目不是 Yanhekt 官方工具，与 Yanhekt 官方无隶属、赞助或背书关系。
- 本项目主要由 OpenAI Codex 根据用户需求自动生成，并经过人工指令、审阅和本地测试后发布。
- 请只用于你本人已经有权限访问的课程内容。
- 本项目不会绕过登录、付费、权限校验或 DRM。
- 本项目不会授予下载、复制、传播、公开分享课程内容的权利。

## 本版内容

- 新增安装包：双击后可选择安装目录并创建桌面快捷方式。
- 新增 GUI 主程序 `YanhektDownloader.exe`。
- 新增后台 Worker `YanhektDownloaderWorker.exe`，GUI 下载时不会弹出控制台窗口。
- 安装包随附 `ffmpeg.exe`，无需用户手动配置 ffmpeg。
- 文件版本信息写入 Windows exe 属性，版本号为 `0.0.1`。

## 已验证

- 单元测试通过。
- Python 编译检查通过。
- 安装包可静默安装到带空格路径。
- 安装目录不包含浏览器登录目录、下载视频、测试产物或缓存目录。
