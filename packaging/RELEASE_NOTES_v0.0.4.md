# yanhekt/延河课堂 Downloader v0.0.4

浏览器兼容性改进版。

## 下载

- `YanhektDownloader_Setup_v0.0.4.exe`

## 改进

- 支持只安装 Microsoft Edge、没有安装 Google Chrome 的 Windows 电脑。
- 专用浏览器启动时会优先使用 Chrome；找不到 Chrome 时自动使用 Edge。
- 命令行新增 `--browser` 参数，可手动指定 `chrome.exe` 或 `msedge.exe` 路径。
- 旧的 `--chrome` 参数继续可用，避免破坏已有脚本。
- 本地 DevTools 自动发现现在也会检查 Edge 用户目录。
- GUI 和 README 文案改为 Chrome / Edge 兼容表述。
- 桌面快捷方式名称统一为 `yanhekt-延河课堂录屏下载器`。
- 桌面快捷方式会引用随安装包安装的高清 `.ico` 图标，避免显示为空白或模糊图标。

## 使用前请阅读

- 本项目不是 yanhekt/延河课堂官方工具，与 yanhekt/延河课堂官方无隶属、赞助或背书关系。
- 本项目主要由 OpenAI Codex 根据用户需求自动生成，并经过人工指令、审阅和本地测试后发布。
- 请只用于你本人已经有权限访问的课程内容。
- 本项目不会绕过登录、付费、权限校验或 DRM。
- 本项目不会授予下载、复制、传播、公开分享课程内容的权利。
