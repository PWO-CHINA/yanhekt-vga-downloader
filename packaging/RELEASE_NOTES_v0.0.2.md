# Yanhekt Downloader v0.0.2

安装版乱码修复版。

## 下载

- `YanhektDownloader_Setup_v0.0.2.exe`

## 修复

- 修复安装版加载课程清单后，课程名、课堂标题和预览文件名显示为 `���` 乱码的问题。
- Worker 与 GUI 之间的课程清单 JSON 改为 ASCII-safe 传输，避免受 Windows 本地编码影响。
- Worker 启动时会主动把 stdout/stderr 设置为 UTF-8，降低日志输出乱码概率。

## 使用前请阅读

- 本项目不是 Yanhekt 官方工具，与 Yanhekt 官方无隶属、赞助或背书关系。
- 本项目主要由 OpenAI Codex 根据用户需求自动生成，并经过人工指令、审阅和本地测试后发布。
- 请只用于你本人已经有权限访问的课程内容。
- 本项目不会绕过登录、付费、权限校验或 DRM。
- 本项目不会授予下载、复制、传播、公开分享课程内容的权利。
