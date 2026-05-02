#!/usr/bin/env python3
"""
Batch-download yanhekt/延河课堂 course classroom recordings you can already access in a Chromium browser.

Safety notes:
- Connects only to a local Chromium DevTools endpoint on 127.0.0.1.
- Uses the logged-in yanhekt.cn page context to call the same front-end APIs.
- Does not read browser profile databases or write auth tokens to its own files.
- The dedicated browser profile stores login state like a normal browser profile.
- Does not attempt to bypass DRM or access control.
"""

from __future__ import annotations

import argparse
import base64
import concurrent.futures
import json
import os
import re
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Iterable


YANHE_HOST = "https://www.yanhekt.cn"
DEFAULT_CDP = "http://127.0.0.1:9222"
PLAN_JSON_PREFIX = "__YANHEKT_PLAN_JSON__"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/136.0.0.0 Safari/537.36"
)
WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}
MAX_WINDOWS_PATH_CHARS = 240
MIN_FREE_SPACE_RESERVE = 500 * 1024 * 1024
CDP_PROBE_TIMEOUT = 2
FFMPEG_STALL_TIMEOUT = 90.0
SIGNED_URL_RETRIES = 2


def configure_standard_streams() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True, write_through=True)
        except Exception:
            pass


def log(message: str = "", *, err: bool = False) -> None:
    print(message, file=sys.stderr if err else sys.stdout, flush=True)


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def resource_dirs() -> list[Path]:
    dirs: list[Path] = []
    meipass = getattr(sys, "_MEIPASS", "")
    if meipass:
        dirs.append(Path(meipass).resolve())
    dirs.append(app_dir())
    source_dir = Path(__file__).resolve().parent
    if source_dir not in dirs:
        dirs.append(source_dir)
    return dirs


def default_profile_dir() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
    else:
        base = Path(os.environ.get("XDG_STATE_HOME") or (Path.home() / ".local" / "state"))
    return base / "YanhektDownloader" / "chrome-profile"


def default_output_dir() -> Path:
    downloads = Path.home() / "Downloads"
    if os.name != "nt":
        config = Path.home() / ".config" / "user-dirs.dirs"
        try:
            text = config.read_text(encoding="utf-8")
            match = re.search(r'XDG_DOWNLOAD_DIR="([^"]+)"', text)
            if match:
                downloads = Path(match.group(1).replace("$HOME", str(Path.home())))
        except OSError:
            pass
    return downloads / "YanhektDownloader"


def no_window_creationflags() -> int:
    if os.name != "nt":
        return 0
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


def terminate_process(proc: subprocess.Popen[Any], timeout: float = 5.0) -> None:
    if proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            creationflags=no_window_creationflags(),
        )
    else:
        proc.terminate()
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            pass


def is_managed_profile_dir(path: Path) -> bool:
    try:
        resolved = path.expanduser().resolve()
        default = default_profile_dir().expanduser().resolve()
    except OSError:
        return False
    return resolved == default or (
        resolved.name == "chrome-profile"
        and resolved.parent.name == "YanhektDownloader"
    )


class CdpError(RuntimeError):
    pass


class InsufficientSpaceError(OSError):
    pass


class MediaAccessError(RuntimeError):
    pass


class SimpleWebSocket:
    def __init__(self, ws_url: str, timeout: float = 30.0) -> None:
        parsed = urllib.parse.urlparse(ws_url)
        if parsed.scheme != "ws":
            raise CdpError(f"Only ws:// CDP endpoints are supported: {ws_url}")
        self.host = parsed.hostname or "127.0.0.1"
        self.port = parsed.port or 80
        self.path = parsed.path
        if parsed.query:
            self.path += "?" + parsed.query
        self.sock = socket.create_connection((self.host, self.port), timeout=timeout)
        self.sock.settimeout(timeout)
        self._handshake()

    def _handshake(self) -> None:
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        request = (
            f"GET {self.path} HTTP/1.1\r\n"
            f"Host: {self.host}:{self.port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            "Origin: http://127.0.0.1\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "\r\n"
        ).encode("ascii")
        self.sock.sendall(request)
        response = b""
        while b"\r\n\r\n" not in response:
            chunk = self.sock.recv(4096)
            if not chunk:
                break
            response += chunk
        first_line = response.split(b"\r\n", 1)[0]
        if b"101" not in first_line:
            raise CdpError(f"WebSocket handshake failed: {first_line!r}")

    def send_text(self, text: str) -> None:
        payload = text.encode("utf-8")
        header = bytearray([0x81])
        length = len(payload)
        if length < 126:
            header.append(0x80 | length)
        elif length < (1 << 16):
            header.append(0x80 | 126)
            header.extend(struct.pack("!H", length))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack("!Q", length))
        mask = os.urandom(4)
        header.extend(mask)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self.sock.sendall(bytes(header) + masked)

    def recv_text(self) -> str:
        chunks: list[bytes] = []
        while True:
            first = self._recv_exact(2)
            b1, b2 = first[0], first[1]
            opcode = b1 & 0x0F
            masked = bool(b2 & 0x80)
            length = b2 & 0x7F
            if length == 126:
                length = struct.unpack("!H", self._recv_exact(2))[0]
            elif length == 127:
                length = struct.unpack("!Q", self._recv_exact(8))[0]
            mask = self._recv_exact(4) if masked else b""
            payload = self._recv_exact(length) if length else b""
            if masked:
                payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
            if opcode == 0x8:
                raise CdpError("CDP WebSocket closed")
            if opcode == 0x9:
                self._send_pong(payload)
                continue
            if opcode in (0x1, 0x0):
                chunks.append(payload)
                if b1 & 0x80:
                    return b"".join(chunks).decode("utf-8")

    def _send_pong(self, payload: bytes) -> None:
        header = bytearray([0x8A])
        length = len(payload)
        if length >= 126:
            return
        header.append(0x80 | length)
        mask = os.urandom(4)
        header.extend(mask)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self.sock.sendall(bytes(header) + masked)

    def _recv_exact(self, n: int) -> bytes:
        data = b""
        while len(data) < n:
            chunk = self.sock.recv(n - len(data))
            if not chunk:
                raise CdpError("Unexpected EOF from CDP WebSocket")
            data += chunk
        return data

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


class CdpClient:
    def __init__(self, ws_url: str) -> None:
        self.ws = SimpleWebSocket(ws_url)
        self.next_id = 1

    def call(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        msg_id = self.next_id
        self.next_id += 1
        payload: dict[str, Any] = {"id": msg_id, "method": method, "params": params or {}}
        if session_id:
            payload["sessionId"] = session_id
        self.ws.send_text(json.dumps(payload))
        while True:
            message = json.loads(self.ws.recv_text())
            if message.get("id") != msg_id:
                continue
            if "error" in message:
                raise CdpError(json.dumps(message["error"], ensure_ascii=False))
            return message.get("result", {})

    def evaluate(
        self,
        expression: str,
        timeout: float = 60.0,
        session_id: str | None = None,
    ) -> Any:
        old_timeout = self.ws.sock.gettimeout()
        self.ws.sock.settimeout(timeout)
        try:
            result = self.call(
                "Runtime.evaluate",
                {
                    "expression": expression,
                    "awaitPromise": True,
                    "returnByValue": True,
                    "userGesture": False,
                },
                session_id=session_id,
            )
        finally:
            self.ws.sock.settimeout(old_timeout)
        if "exceptionDetails" in result:
            details = result["exceptionDetails"]
            text = details.get("text") or "Runtime.evaluate failed"
            value = details.get("exception", {}).get("description")
            raise CdpError(value or text)
        remote = result.get("result", {})
        if remote.get("subtype") == "error":
            raise CdpError(remote.get("description") or remote.get("value") or "JS error")
        return remote.get("value")

    def close(self) -> None:
        self.ws.close()


def http_json(url: str, method: str = "GET", timeout: float = 10) -> Any:
    req = urllib.request.Request(url, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def read_devtools_port(profile_dir: Path) -> str | None:
    port_file = profile_dir / "DevToolsActivePort"
    if not port_file.exists():
        return None
    try:
        port = port_file.read_text(encoding="utf-8").splitlines()[0].strip()
    except (OSError, IndexError):
        return None
    return port or None


def local_browser_profile_dirs() -> list[Path]:
    return []


def discover_cdp_base(user_base: str | None, profile_dir: Path | None = None) -> str:
    if user_base:
        return user_base.rstrip("/")
    env = os.environ.get("CHROME_DEVTOOLS_URL")
    if env:
        return env.rstrip("/")
    if profile_dir is not None:
        port = read_devtools_port(profile_dir)
        if port:
            cdp_base = f"http://127.0.0.1:{port}"
            try:
                http_json(cdp_base + "/json/version", timeout=CDP_PROBE_TIMEOUT)
                return cdp_base
            except Exception:
                if is_managed_profile_dir(profile_dir):
                    try:
                        (profile_dir / "DevToolsActivePort").unlink()
                    except FileNotFoundError:
                        pass
                    except OSError:
                        pass
                pass
    return DEFAULT_CDP


def chromium_browser_candidates() -> list[Path]:
    candidates: list[Path] = []
    program_files = Path(os.environ.get("PROGRAMFILES", "C:/Program Files"))
    program_files_x86 = Path(os.environ.get("PROGRAMFILES(X86)", "C:/Program Files (x86)"))
    local_app_data = os.environ.get("LOCALAPPDATA")

    candidates.extend(
        [
            program_files / "Google" / "Chrome" / "Application" / "chrome.exe",
            program_files_x86 / "Google" / "Chrome" / "Application" / "chrome.exe",
        ]
    )
    if local_app_data:
        candidates.append(Path(local_app_data) / "Google" / "Chrome" / "Application" / "chrome.exe")

    candidates.extend(
        [
            program_files_x86 / "Microsoft" / "Edge" / "Application" / "msedge.exe",
            program_files / "Microsoft" / "Edge" / "Application" / "msedge.exe",
        ]
    )
    if local_app_data:
        candidates.append(Path(local_app_data) / "Microsoft" / "Edge" / "Application" / "msedge.exe")

    for executable in ("chrome.exe", "chrome", "msedge.exe", "msedge"):
        found = shutil.which(executable)
        if found:
            candidates.append(Path(found))

    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate).lower()
        if key not in seen:
            unique.append(candidate)
            seen.add(key)
    return unique


def find_browser(user_path: str | None) -> str:
    if user_path:
        return str(Path(user_path))
    for candidate in chromium_browser_candidates():
        if candidate.exists():
            return str(candidate)
    raise FileNotFoundError("Chrome or Microsoft Edge not found. Pass --browser PATH.")


def find_chrome(user_path: str | None) -> str:
    return find_browser(user_path)


def chrome_launch_args(chrome_path: str, profile_dir: Path, url: str, headless: bool = False) -> list[str]:
    args = [
        chrome_path,
        f"--user-data-dir={profile_dir}",
        "--remote-debugging-address=127.0.0.1",
        "--remote-debugging-port=0",
        "--remote-allow-origins=http://127.0.0.1",
        "--no-first-run",
        "--no-default-browser-check",
        "--test-type",
        "--disable-infobars",
    ]
    if headless:
        args.extend(
            [
                "--headless=new",
                "--disable-gpu",
                "--window-size=1280,900",
            ]
        )
    args.append(url)
    return args


def launch_dedicated_chrome(
    chrome_path: str,
    profile_dir: Path,
    url: str,
    headless: bool = False,
) -> tuple[subprocess.Popen[Any], str]:
    profile_dir.mkdir(parents=True, exist_ok=True)
    port_file = profile_dir / "DevToolsActivePort"
    if port_file.exists():
        port_file.unlink()

    proc = subprocess.Popen(
        chrome_launch_args(chrome_path, profile_dir, url, headless=headless),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=no_window_creationflags(),
    )

    deadline = time.time() + 30
    while time.time() < deadline:
        if proc.poll() is not None:
            raise CdpError(f"Browser exited early with code {proc.returncode}")
        if port_file.exists():
            lines = port_file.read_text(encoding="utf-8").splitlines()
            if lines:
                return proc, f"http://127.0.0.1:{lines[0].strip()}"
        time.sleep(0.25)
    proc.terminate()
    raise CdpError("Timed out waiting for dedicated browser DevToolsActivePort")


def list_pages(cdp_base: str) -> list[dict[str, Any]]:
    return http_json(cdp_base + "/json/list")


def open_tab(cdp_base: str, url: str) -> dict[str, Any]:
    quoted = urllib.parse.quote(url, safe="")
    try:
        return http_json(cdp_base + "/json/new?" + quoted, method="PUT")
    except Exception:
        return http_json(cdp_base + "/json/new?" + quoted)


def browser_ws_url(cdp_base: str) -> str:
    try:
        version = http_json(cdp_base + "/json/version", timeout=CDP_PROBE_TIMEOUT)
        ws_url = version.get("webSocketDebuggerUrl")
        if ws_url:
            return ws_url
    except Exception:
        pass

    parsed = urllib.parse.urlparse(cdp_base)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port
    if not port:
        port = 80 if parsed.scheme == "http" else 443

    raise CdpError(f"Could not discover browser WebSocket URL from {cdp_base}")


def target_infos(browser: CdpClient) -> list[dict[str, Any]]:
    return browser.call("Target.getTargets").get("targetInfos", [])


def choose_or_open_yanhe_target(browser: CdpClient, course_url: str) -> dict[str, Any]:
    targets = target_infos(browser)
    preferred = []
    fallback = []
    for target in targets:
        url = target.get("url", "")
        if target.get("type") != "page":
            continue
        if url == course_url:
            preferred.append(target)
        elif url.startswith(YANHE_HOST):
            fallback.append(target)
    if preferred:
        return preferred[0]
    if fallback:
        return fallback[0]

    created = browser.call("Target.createTarget", {"url": course_url})
    target_id = created.get("targetId")
    deadline = time.time() + 20
    while time.time() < deadline:
        for target in target_infos(browser):
            if target.get("targetId") == target_id:
                return target
        time.sleep(0.5)
    raise CdpError(f"Created yanhekt tab but could not find target {target_id}")


def attach_to_target(browser: CdpClient, target: dict[str, Any]) -> str:
    result = browser.call(
        "Target.attachToTarget",
        {"targetId": target["targetId"], "flatten": True},
    )
    return result["sessionId"]


def connect_yanhe_session(cdp_base: str, course_url: str) -> tuple[CdpClient, str, dict[str, Any]]:
    browser = CdpClient(browser_ws_url(cdp_base))
    target = choose_or_open_yanhe_target(browser, course_url)
    session_id = attach_to_target(browser, target)
    return browser, session_id, target


def js_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def course_info_expression(course_input: str) -> str:
    return f"""
(async () => {{
  const courseInput = {js_string(course_input)};
  const match = String(courseInput).match(/course\\/(\\d+)/) || String(courseInput).match(/^(\\d+)$/);
  if (!match) throw new Error("Could not find course id in input: " + courseInput);
  const courseId = match[1];
  const auth = JSON.parse(localStorage.getItem("auth") || "{{}}");
  if (!auth.token || !auth.expired_at || auth.expired_at <= Date.now()) {{
    throw new Error("yanhekt/延河课堂 login is missing or expired in this browser profile.");
  }}
  const headers = {{
    "Authorization": "Bearer " + auth.token,
    "Content-Type": "application/json",
    "Xdomain-Client": "web_user"
  }};
  async function api(path, params) {{
    const url = new URL("https://cbiz.yanhekt.cn" + path);
    for (const [key, value] of Object.entries(params || {{}})) {{
      if (value !== undefined && value !== null && value !== "") url.searchParams.set(key, value);
    }}
    const response = await fetch(url.toString(), {{ headers }});
    const body = await response.json();
    if (!response.ok || body.code !== 0) {{
      throw new Error(path + " failed: " + response.status + " " + JSON.stringify(body).slice(0, 400));
    }}
    return body.data;
  }}
  const [course, user] = await Promise.all([
    api("/v1/course", {{ id: courseId, with_professor_badges: "true" }}),
    api("/v1/user", {{}})
  ]);
  const sessions = [];
  for (let page = 1; page <= 50; page++) {{
    const data = await api("/v2/course/session/list", {{
      course_id: courseId,
      with_page: "true",
      page: String(page),
      page_size: "100",
      order_type: "desc",
      order_type_weight: "desc"
    }});
    const rows = Array.isArray(data) ? data : (data.data || []);
    sessions.push(...rows);
    if (Array.isArray(data) || !data.last_page || page >= data.last_page) break;
  }}
  const items = [];
  for (const session of sessions) {{
    const videos = Array.isArray(session.videos) ? session.videos : [];
    const video = videos.find(v => v && (v.vga || v.vga_origin)) || null;
    if (!video) continue;
    items.push({{
      session_id: session.id,
      course_id: Number(courseId),
      course_name: course.name_zh || course.name_en || ("course-" + courseId),
      title: session.title || session.section_group_title || ("session-" + session.id),
      started_at: session.started_at || "",
      ended_at: session.ended_at || "",
      video_id: video.id || null,
      duration: video.duration || "",
      raw_vga: video.vga || video.vga_origin,
      session_url: "https://www.yanhekt.cn/session/" + session.id
    }});
  }}
  return {{
    course_id: Number(courseId),
    course_name: course.name_zh || course.name_en || ("course-" + courseId),
    user_badge: user.badge,
    count: items.length,
    items
  }};
}})()
"""


def sign_url_expression(raw_url: str, user_badge: str) -> str:
    return f"""
(async () => {{
  const rawUrl = {js_string(raw_url)};
  const userBadge = {js_string(user_badge)};
  const auth = JSON.parse(localStorage.getItem("auth") || "{{}}");
  if (!auth.token || !auth.expired_at || auth.expired_at <= Date.now()) {{
    throw new Error("yanhekt/延河课堂 login is missing or expired in this browser profile.");
  }}
  let req;
  window.webpackChunkyanhe_web.push([[Math.floor(Math.random() * 1e9)], {{}}, (r) => {{ req = r; }}]);
  const signer = new (req(854015).A)();
  const headers = {{
    "Authorization": "Bearer " + auth.token,
    "Content-Type": "application/json",
    "Xdomain-Client": "web_user"
  }};
  const tokenResp = await fetch(
    "https://cbiz.yanhekt.cn/v1/auth/video/token?id=" + encodeURIComponent(userBadge),
    {{ headers }}
  ).then(r => r.json());
  if (tokenResp.code !== 0 || !tokenResp.data || !tokenResp.data.token) {{
    throw new Error("Failed to get video token: " + JSON.stringify(tokenResp).slice(0, 400));
  }}
  const ts = String(signer.t());
  const query = new URLSearchParams({{
    Xvideo_Token: tokenResp.data.token,
    Xclient_Timestamp: ts,
    Xclient_Signature: signer.s(ts),
    Xclient_Version: signer.v(),
    Platform: "yhkt_user"
  }});
  return signer.p(rawUrl) + "?" + query.toString();
}})()
"""


def wait_for_page_ready(cdp: CdpClient, session_id: str | None = None, timeout: float = 30.0) -> None:
    deadline = time.time() + timeout
    last_error = ""
    while time.time() < deadline:
        try:
            ok = cdp.evaluate(
                "Boolean(window.webpackChunkyanhe_web && localStorage.getItem('auth'))",
                timeout=10,
                session_id=session_id,
            )
            if ok:
                return
        except Exception as exc:
            last_error = str(exc)
        time.sleep(1)
    raise CdpError("yanhekt/延河课堂 page is not ready or not logged in. " + last_error)


def split_filename_suffix(name: str) -> tuple[str, str]:
    suffix_match = re.search(r"(\.[A-Za-z0-9]{1,10})$", name)
    if not suffix_match:
        return name, ""
    suffix = suffix_match.group(1)
    return name[: -len(suffix)].rstrip(" ."), suffix


def clamp_filename(name: str, max_len: int) -> str:
    stem, suffix = split_filename_suffix(name)
    stem = stem or "video"
    if stem.upper() in WINDOWS_RESERVED_NAMES:
        stem = f"{stem}_file"
    if len(stem) + len(suffix) > max_len:
        stem = stem[: max(1, max_len - len(suffix))].rstrip(" .") or "video"
        if stem.upper() in WINDOWS_RESERVED_NAMES:
            stem = (stem + "_file")[: max(1, max_len - len(suffix))].rstrip(" .") or "video"
    return stem + suffix


def sanitize_filename(name: str, max_len: int = 180) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    if not name:
        return "video"
    return clamp_filename(name, max_len)


def title_filename_stem(title: str, fallback: str = "课堂录屏", max_len: int = 160) -> str:
    stem = sanitize_filename(title or fallback, max_len=max_len)
    stem = re.sub(r"\s+", "_", stem)
    stem = re.sub(r"_+", "_", stem).strip("_ .")
    return stem or fallback


def filename_for(item: dict[str, Any], index: int) -> str:
    del index
    title = item.get("title") or f"session-{item.get('session_id')}"
    course_name = str(item.get("course_name") or "").strip()
    if course_name:
        course_stem = title_filename_stem(course_name, max_len=80)
        title_stem = title_filename_stem(str(title), max_len=90)
        stem = f"{course_stem}_{title_stem}"
    else:
        stem = title_filename_stem(str(title), max_len=160)
    return sanitize_filename(f"{stem}_课堂录屏.mp4")


def fit_filename_for_directory(filename: str, output_dir: Path, max_path_chars: int = MAX_WINDOWS_PATH_CHARS) -> str:
    base = str(output_dir)
    minimum_filename_len = len("video.mp4")
    max_filename_len = max(minimum_filename_len, max_path_chars - len(base) - 1)
    if len(base) + 1 + len(filename) <= max_path_chars:
        return filename
    return sanitize_filename(filename, max_len=max_filename_len)


def ensure_writable_directory(path: Path) -> None:
    max_output_dir_chars = MAX_WINDOWS_PATH_CHARS - len("video.mp4") - 1
    if os.name == "nt" and len(str(path)) > max_output_dir_chars:
        raise OSError(
            "保存目录路径太深，可能导致 Windows 或 ffmpeg 无法写入。"
            "请换到更短的路径，例如 Downloads\\YanhektDownloader。"
        )
    path.mkdir(parents=True, exist_ok=True)
    if not path.is_dir():
        raise NotADirectoryError(f"保存路径不是文件夹：{path}")
    probe = path / ".yanhekt_write_test.tmp"
    try:
        probe.write_text("ok", encoding="utf-8")
    finally:
        try:
            probe.unlink()
        except FileNotFoundError:
            pass


def ensure_enough_free_space(output_dir: Path, expected_size: int | None) -> None:
    if expected_size is None or expected_size <= 0:
        return
    free = shutil.disk_usage(output_dir).free
    required = int(expected_size * 1.1) + MIN_FREE_SPACE_RESERVE
    if free < required:
        raise InsufficientSpaceError(
            "保存目录所在磁盘空间不足："
            f"预计需要至少 {format_bytes(required)}，当前可用 {format_bytes(free)}。"
        )


def find_ffmpeg(user_path: str | None) -> str:
    if user_path:
        path = Path(user_path).expanduser()
        if not path.is_file():
            raise FileNotFoundError(f"ffmpeg not found at: {path}")
        return str(path)
    for root in resource_dirs():
        bundled = root / "ffmpeg.exe"
        if bundled.exists():
            return str(bundled)
        candidates = sorted(root.glob("ffmpeg-*full_build/bin/ffmpeg.exe"))
        if candidates:
            return str(candidates[-1])
    found = shutil.which("ffmpeg")
    if found:
        return found
    raise FileNotFoundError("ffmpeg not found. Pass --ffmpeg PATH.")


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    for index in range(2, 1000):
        candidate = path.with_name(f"{stem} ({index}){suffix}")
        if not candidate.exists():
            return candidate
    raise FileExistsError(f"Could not find an unused filename for {path}")


def unique_planned_path(path: Path, reserved_names: set[str]) -> Path:
    if path.name.casefold() not in reserved_names:
        return path
    stem = path.stem
    suffix = path.suffix
    for index in range(2, 1000):
        candidate = path.with_name(f"{stem} ({index}){suffix}")
        if candidate.name.casefold() not in reserved_names:
            return candidate
    raise FileExistsError(f"Could not find an unused planned filename for {path}")


def is_probably_complete_mp4(path: Path) -> bool:
    try:
        size = path.stat().st_size
        if size < 32:
            return False
        with path.open("rb") as handle:
            head = handle.read(min(size, 1024 * 1024))
            if b"ftyp" not in head[:128]:
                return False
            if b"moov" in head:
                return True
            if size > len(head):
                handle.seek(max(0, size - 1024 * 1024))
                return b"moov" in handle.read()
        return False
    except OSError:
        return False


def legacy_long_recording_target(path: Path) -> Path | None:
    match = re.match(
        r"^\d+_\d{4}-\d{2}-\d{2}_\d{4}_(.+)_session-\d+_课堂录屏\.mp4$",
        path.name,
    )
    if not match:
        return None
    title_stem = title_filename_stem(match.group(1), max_len=160)
    return path.with_name(sanitize_filename(f"{title_stem}_课堂录屏.mp4"))


def repair_legacy_mp_extensions(
    output_dir: Path,
    target_paths: Iterable[Path] | None = None,
) -> list[tuple[Path, Path]]:
    renamed: list[tuple[Path, Path]] = []
    if not output_dir.exists():
        return renamed
    targets = list(target_paths or [])
    target_index = 0
    legacy_files = [
        path
        for path in sorted(output_dir.iterdir(), key=lambda item: (item.stat().st_mtime, item.name.casefold()))
        if path.is_file()
        and path.name.lower().endswith(".mp_")
        and not path.name.lower().endswith(".part")
    ]
    for path in legacy_files:
        if not path.is_file():
            continue
        if not is_probably_complete_mp4(path):
            continue
        target: Path | None = None
        while target_index < len(targets):
            candidate = targets[target_index]
            target_index += 1
            if candidate.exists():
                continue
            target = candidate
            break
        if target is None:
            target = path.with_name(path.name[:-4] + ".mp4")
        target = unique_path(target)
        path.rename(target)
        renamed.append((path, target))
    for path in sorted(output_dir.glob("*_VGA.mp4")):
        if not path.is_file() or not is_probably_complete_mp4(path):
            continue
        target = unique_path(path.with_name(path.name[: -len("_VGA.mp4")] + "_课堂录屏.mp4"))
        if target == path:
            continue
        path.rename(target)
        renamed.append((path, target))
    for path in sorted(output_dir.glob("*_课堂录屏.mp4")):
        if not path.is_file() or not is_probably_complete_mp4(path):
            continue
        target = legacy_long_recording_target(path)
        if target is None or target == path:
            continue
        target = unique_path(target)
        path.rename(target)
        renamed.append((path, target))
    return renamed


def build_download_plan(
    items: list[dict[str, Any]],
    output_dir: Path,
) -> list[tuple[dict[str, Any], Path]]:
    planned: list[tuple[dict[str, Any], Path]] = []
    reserved_names: set[str] = set()
    for idx, item in enumerate(items, start=1):
        filename = fit_filename_for_directory(filename_for(item, idx), output_dir)
        output = unique_planned_path(output_dir / filename, reserved_names)
        reserved_names.add(output.name.casefold())
        planned.append((item, output))
    return planned


def parse_session_ids(value: str | None) -> set[str]:
    if not value:
        return set()
    return {part.strip() for part in re.split(r"[,;\s]+", value) if part.strip()}


def filter_plan_by_session_ids(
    planned: list[tuple[dict[str, Any], Path]],
    session_ids: set[str],
) -> list[tuple[dict[str, Any], Path]]:
    if not session_ids:
        return planned
    return [
        (item, output)
        for item, output in planned
        if str(item.get("session_id")) in session_ids
    ]


def plan_json_payload(
    info: dict[str, Any],
    planned: list[tuple[dict[str, Any], Path]],
    output_dir: Path,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for item, output in planned:
        exists = output.exists()
        size = output.stat().st_size if exists and output.is_file() else 0
        rows.append(
            {
                "session_id": item.get("session_id"),
                "title": item.get("title") or f"session-{item.get('session_id')}",
                "started_at": item.get("started_at") or "",
                "duration": item.get("duration") or "",
                "session_url": item.get("session_url") or "",
                "filename": output.name,
                "output_path": str(output),
                "exists": exists,
                "complete_mp4": bool(exists and is_probably_complete_mp4(output)),
                "size": size,
            }
        )
    return {
        "course_id": info.get("course_id"),
        "course_name": info.get("course_name"),
        "output_dir": str(output_dir),
        "count": len(rows),
        "items": rows,
    }


def plan_json_line(payload: dict[str, Any]) -> str:
    return PLAN_JSON_PREFIX + json.dumps(payload, ensure_ascii=True)


def format_bytes(value: int | float | None) -> str:
    if value is None or value < 0:
        return "unknown"
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(value)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{size:.1f} TB"


def format_seconds(value: float | int | None) -> str:
    if value is None or value < 0:
        return "--:--"
    total = int(value)
    hours, rem = divmod(total, 3600)
    minutes, seconds = divmod(rem, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def parse_duration(value: Any) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, str) and ":" in value:
        parts = value.strip().split(":")
        try:
            numbers = [float(part) for part in parts]
        except ValueError:
            return None
        if len(numbers) == 3:
            duration = numbers[0] * 3600 + numbers[1] * 60 + numbers[2]
        elif len(numbers) == 2:
            duration = numbers[0] * 60 + numbers[1]
        else:
            return None
        return duration if duration > 0 else None
    try:
        duration = float(value)
        return duration if duration > 0 else None
    except (TypeError, ValueError):
        return None


def ffmpeg_headers(referer: str) -> str:
    return "".join(f"{key}: {value}\r\n" for key, value in video_request_headers(referer).items())


def video_request_headers(referer: str, extra: dict[str, str] | None = None) -> dict[str, str]:
    headers = {
        "User-Agent": USER_AGENT,
        "Referer": referer,
        "Origin": "https://www.yanhekt.cn",
        "Accept": "*/*",
        "Sec-Fetch-Site": "cross-site",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Dest": "empty",
    }
    if extra:
        headers.update(extra)
    return headers


def read_text_url(url: str, referer: str) -> str:
    req = urllib.request.Request(url, headers=video_request_headers(referer))
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", "replace")


def merge_query_values(base_query: str, extra_query: str) -> str:
    if not base_query:
        return extra_query
    if not extra_query:
        return base_query
    pairs = urllib.parse.parse_qsl(extra_query, keep_blank_values=True)
    existing = {key for key, _value in pairs}
    for key, value in urllib.parse.parse_qsl(base_query, keep_blank_values=True):
        if key not in existing:
            pairs.append((key, value))
            existing.add(key)
    return urllib.parse.urlencode(pairs, doseq=True)


def with_playlist_query(playlist_url: str, segment_url: str) -> str:
    if urllib.parse.urlparse(segment_url).scheme:
        absolute = segment_url
    else:
        base = playlist_url.split("?", 1)[0]
        absolute = urllib.parse.urljoin(base, segment_url)

    playlist_query = urllib.parse.urlparse(playlist_url).query
    parsed = urllib.parse.urlparse(absolute)
    query = merge_query_values(playlist_query, parsed.query)
    if query != parsed.query:
        absolute = urllib.parse.urlunparse(parsed._replace(query=query))
    return absolute


def parse_playlist_urls(playlist_url: str, playlist_text: str) -> list[str]:
    _rewritten_text, urls, _resources = rewrite_playlist_text(playlist_url, playlist_text)
    return urls


def is_hls_playlist_url(url: str) -> bool:
    return urllib.parse.urlparse(url).path.lower().endswith(".m3u8")


def first_text_prefix(data: bytes, limit: int = 160) -> str:
    text = data[:limit].decode("utf-8", "replace")
    return re.sub(r"\s+", " ", text).strip()


def redact_media_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if not parsed.query:
        return urllib.parse.urlunparse(parsed)
    sensitive_keys = {
        "xvideo_token",
        "xclient_signature",
        "xclient_timestamp",
        "xclient_version",
        "platform",
        "token",
        "signature",
        "sign",
        "auth",
        "authorization",
        "key",
    }
    redacted_pairs = []
    for key, value in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True):
        redacted_pairs.append((key, "redacted" if key.lower() in sensitive_keys else value))
    return urllib.parse.urlunparse(parsed._replace(query=urllib.parse.urlencode(redacted_pairs)))


def redact_media_urls_in_text(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        url = match.group(0).rstrip(".,;:)")
        suffix = match.group(0)[len(url):]
        return redact_media_url(url) + suffix

    return re.sub(r"https?://[^\s'\"<>]+", replace, text)


def parse_hls_attributes(value: str) -> dict[str, str]:
    attrs: dict[str, str] = {}
    for match in re.finditer(r'([A-Z0-9-]+)=((?:"[^"]*")|[^,]*)', value):
        raw = match.group(2)
        attrs[match.group(1).upper()] = raw[1:-1] if raw.startswith('"') and raw.endswith('"') else raw
    return attrs


def rewrite_hls_uri_attributes(line: str, playlist_url: str) -> str:
    def replace(match: re.Match[str]) -> str:
        rewritten = with_playlist_query(playlist_url, match.group(1))
        return f'URI="{rewritten}"'

    return re.sub(r'URI="([^"]+)"', replace, line)


def rewrite_playlist_text(playlist_url: str, playlist_text: str) -> tuple[str, list[str], list[str]]:
    rewritten_lines: list[str] = []
    playlist_urls: list[str] = []
    resource_urls: list[str] = []
    for raw_line in playlist_text.splitlines():
        line = raw_line.strip()
        if not line:
            rewritten_lines.append(raw_line)
            continue
        if line.startswith("#"):
            rewritten = rewrite_hls_uri_attributes(raw_line, playlist_url)
            rewritten_lines.append(rewritten)
            if "URI=" in line and not line.startswith("#EXT-X-STREAM-INF"):
                for match in re.finditer(r'URI="([^"]+)"', line):
                    resource_urls.append(with_playlist_query(playlist_url, match.group(1)))
            continue
        rewritten = with_playlist_query(playlist_url, line)
        rewritten_lines.append(rewritten)
        playlist_urls.append(rewritten)
    trailing_newline = "\n" if playlist_text.endswith(("\n", "\r")) else ""
    return "\n".join(rewritten_lines) + trailing_newline, playlist_urls, resource_urls


def fetch_bytes_range(url: str, referer: str, length: int = 188) -> tuple[bytes, str]:
    req = urllib.request.Request(
        url,
        headers=video_request_headers(referer, {"Range": f"bytes=0-{max(0, length - 1)}"}),
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read(length)
            return data, resp.headers.get("Content-Type", "")
    except urllib.error.HTTPError as exc:
        data = exc.read(length)
        content_type = exc.headers.get("Content-Type", "")
        raise media_access_error(url, f"HTTP {exc.code} {content_type}".strip(), data) from exc


def looks_like_media_segment(data: bytes, content_type: str = "") -> bool:
    stripped = data.lstrip()
    if not stripped:
        return False
    if stripped.startswith((b"\x47", b"ftyp", b"styp")):
        return True
    lowered = content_type.lower()
    if any(token in lowered for token in ("text", "json", "xml", "html")):
        return False
    if stripped.startswith((b"<", b"{", b"[")):
        return False
    prefix = stripped[:80].lower()
    if any(
        marker in prefix
        for marker in (b"forbidden", b"unauthorized", b"access denied", b"invalid", b"error")
    ):
        return False
    if any(token in lowered for token in ("video", "mpeg", "mp2t", "octet-stream", "binary")):
        return True
    return len(stripped) >= 16


def media_access_error(url: str, content_type: str, data: bytes) -> MediaAccessError:
    prefix = first_text_prefix(data)
    details = [
        "视频分片没有返回有效媒体数据。",
        f"分片地址：{redact_media_url(url)}",
        f"Content-Type：{content_type or 'unknown'}",
    ]
    if prefix:
        details.append(f"响应开头：{prefix}")
    details.append("常见原因：电脑时间不准、当前网络/CDN 拦截了视频分片、登录状态过期，或该账号无权访问这节课。")
    details.append("建议先同步 Windows 时间，换到稳定网络后重新登录本工具打开的 Chrome/Edge 专用窗口再试。")
    return MediaAccessError("\n".join(details))


def read_playlist_text_checked(url: str, referer: str, label: str) -> str:
    try:
        playlist_text = read_text_url(url, referer)
    except urllib.error.HTTPError as exc:
        data = exc.read(160)
        raise MediaAccessError(
            f"{label}读取失败。\n"
            f"清单地址：{redact_media_url(url)}\n"
            f"HTTP 状态：{exc.code}\n"
            f"响应开头：{first_text_prefix(data)}\n"
            "常见原因：电脑时间不准、当前网络/CDN 拦截，或登录状态过期。"
        ) from exc
    except Exception as exc:
        raise MediaAccessError(
            f"{label}读取失败。\n"
            f"清单地址：{redact_media_url(url)}\n"
            f"错误：{exc}\n"
            "常见原因：当前网络不稳定、系统代理/安全软件拦截，或登录状态过期。"
        ) from exc
    if not playlist_text.lstrip().startswith("#EXTM3U"):
        raise MediaAccessError(
            f"{label}没有返回 HLS 内容，可能是登录过期或网络返回了错误页。\n"
            f"清单地址：{redact_media_url(url)}\n"
            f"响应开头：{first_text_prefix(playlist_text.encode('utf-8', 'replace'))}"
        )
    return playlist_text


def stream_variant_score(stream_inf: str) -> tuple[int, int, int]:
    attrs = parse_hls_attributes(stream_inf)
    codecs = attrs.get("CODECS", "").lower()
    resolution = attrs.get("RESOLUTION", "")
    bandwidth = int(attrs.get("BANDWIDTH", "0") or 0)
    has_video_codec = any(codec in codecs for codec in ("avc1", "hev1", "hvc1", "vp09", "av01"))
    has_resolution = bool(re.fullmatch(r"\d+x\d+", resolution))
    if codecs and not has_video_codec and "mp4a" in codecs and not has_resolution:
        video_score = 0
    else:
        video_score = 2 if has_video_codec else (1 if has_resolution else 0)
    pixels = 0
    if has_resolution:
        width, height = (int(part) for part in resolution.lower().split("x", 1))
        pixels = width * height
    return video_score, pixels, bandwidth


def choose_nested_playlist(urls: list[str], playlist_text: str, playlist_url: str) -> str | None:
    nested = [url for url in urls if is_hls_playlist_url(url)]
    if not nested:
        return None
    if len(nested) == 1:
        return nested[0]

    ranked: list[tuple[tuple[int, int, int], str]] = []
    lines = playlist_text.splitlines()
    for index, raw_line in enumerate(lines):
        line = raw_line.strip()
        if not line.startswith("#EXT-X-STREAM-INF:"):
            continue
        score = stream_variant_score(line.split(":", 1)[1])
        for candidate in lines[index + 1:]:
            candidate = candidate.strip()
            if not candidate or candidate.startswith("#"):
                continue
            resolved = with_playlist_query(playlist_url, candidate)
            if is_hls_playlist_url(resolved):
                ranked.append((score, resolved))
            break
    if ranked:
        return max(ranked, key=lambda item: item[0])[1]
    return nested[0]


def is_segment_url(url: str) -> bool:
    path = urllib.parse.urlparse(url).path.lower()
    return bool(path) and not path.endswith((".m3u8", ".key", ".bin"))


def prepare_ffmpeg_hls_input(signed_url: str, referer: str, work_dir: Path) -> Path:
    playlist_text = read_playlist_text_checked(signed_url, referer, "视频清单")
    rewritten_text, playlist_urls, _resource_urls = rewrite_playlist_text(signed_url, playlist_text)
    nested_url = choose_nested_playlist(playlist_urls, playlist_text, signed_url)
    if nested_url is not None:
        playlist_text = read_playlist_text_checked(nested_url, referer, "子视频清单")
        rewritten_text, playlist_urls, _resource_urls = rewrite_playlist_text(nested_url, playlist_text)

    segments = [url for url in playlist_urls if is_segment_url(url)]
    if not segments:
        raise MediaAccessError("视频清单里没有找到可下载的视频分片。")

    first_segment = segments[0]
    try:
        data, content_type = fetch_bytes_range(first_segment, referer)
    except MediaAccessError:
        raise
    except Exception as exc:
        raise MediaAccessError(
            "读取第一个视频分片失败。\n"
            f"分片地址：{redact_media_url(first_segment)}\n"
            f"错误：{exc}\n"
            "常见原因：电脑时间不准、当前网络/CDN 拦截了视频分片，或登录状态过期。"
        ) from exc
    if not looks_like_media_segment(data, content_type):
        raise media_access_error(first_segment, content_type, data)

    playlist_path = work_dir / "yanhekt_signed_input.m3u8"
    playlist_path.write_text(rewritten_text, encoding="utf-8", newline="\n")
    return playlist_path


def content_length(url: str, referer: str) -> int | None:
    try:
        req = urllib.request.Request(url, method="HEAD", headers=video_request_headers(referer))
        with urllib.request.urlopen(req, timeout=20) as resp:
            length = resp.headers.get("Content-Length")
            if length and length.isdigit():
                return int(length)
    except Exception:
        pass

    try:
        req = urllib.request.Request(
            url,
            headers=video_request_headers(referer, {"Range": "bytes=0-0"}),
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            content_range = resp.headers.get("Content-Range", "")
            match = re.search(r"/(\d+)$", content_range)
            if match:
                return int(match.group(1))
            length = resp.headers.get("Content-Length")
            if length and length.isdigit() and int(length) > 1:
                return int(length)
    except Exception:
        pass
    return None


def estimate_hls_size(
    signed_url: str,
    referer: str,
    sample_segments: int = 24,
    workers: int = 8,
) -> tuple[int | None, int]:
    playlist_text = read_text_url(signed_url, referer)
    urls = parse_playlist_urls(signed_url, playlist_text)
    nested_url = choose_nested_playlist(urls, playlist_text, signed_url)
    if nested_url is not None:
        signed_url = nested_url
        playlist_text = read_text_url(signed_url, referer)
        urls = parse_playlist_urls(signed_url, playlist_text)

    segments = [
        url
        for url in urls
        if not urllib.parse.urlparse(url).path.lower().endswith(".m3u8")
    ]
    if not segments:
        return None, 0

    if sample_segments <= 0 or sample_segments >= len(segments):
        sample = segments
    else:
        step = max(1, len(segments) // sample_segments)
        sample = segments[::step][:sample_segments]

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        sizes = list(executor.map(lambda url: content_length(url, referer), sample))
    known_sizes = [size for size in sizes if size is not None and size > 0]
    if not known_sizes:
        return None, len(segments)

    average_size = sum(known_sizes) / len(known_sizes)
    return int(average_size * len(segments)), len(segments)


def seconds_from_ffmpeg_time(value: str) -> float | None:
    if not value or value == "N/A":
        return None
    if value.isdigit():
        return int(value) / 1_000_000
    match = re.match(r"(\d+):(\d+):(\d+(?:\.\d+)?)", value)
    if not match:
        return None
    return int(match.group(1)) * 3600 + int(match.group(2)) * 60 + float(match.group(3))


def print_progress_line(
    prefix: str,
    current_time: float | None,
    duration: float | None,
    current_size: int | None,
    expected_size: int | None,
    speed: str,
    start_time: float,
    final: bool = False,
    progress_lines: bool = False,
) -> None:
    percent = None
    if current_time is not None and duration:
        percent = max(0.0, min(100.0, current_time * 100 / duration))
    elif current_size is not None and expected_size:
        percent = max(0.0, min(100.0, current_size * 100 / expected_size))

    eta_text = "--:--"
    if percent and percent > 0 and not final:
        elapsed = time.time() - start_time
        eta = elapsed * (100 - percent) / percent
        eta_text = format_seconds(eta)

    pct_text = f"{percent:5.1f}%" if percent is not None else "  ---%"
    time_text = f"{format_seconds(current_time)}/{format_seconds(duration)}"
    size_text = f"{format_bytes(current_size)} / ~{format_bytes(expected_size)}"
    text = f"{prefix} {pct_text}  {time_text}  {size_text}  ETA {eta_text}  {speed or ''}"
    if progress_lines:
        print(text.rstrip(), flush=True)
        return
    line = "\r" + text
    width = shutil.get_terminal_size((120, 20)).columns
    print(line[: max(20, width - 1)].ljust(max(20, width - 1)), end="", flush=True)
    if final:
        print()


def run_ffmpeg(
    ffmpeg: str,
    signed_url: str,
    output: Path,
    referer: str,
    overwrite: bool,
    duration: float | None,
    expected_size: int | None,
    progress_prefix: str,
    progress_lines: bool = False,
) -> None:
    temp = output.with_suffix(output.suffix + ".part")
    if temp.exists():
        temp.unlink()
    cmd = [
        ffmpeg,
        "-hide_banner",
        "-y" if overwrite else "-n",
        "-nostdin",
        "-loglevel",
        "error",
        "-stats_period",
        "1",
        "-progress",
        "pipe:1",
        "-protocol_whitelist",
        "file,http,https,tcp,tls,crypto",
        "-rw_timeout",
        "30000000",
        "-reconnect",
        "1",
        "-reconnect_streamed",
        "1",
        "-reconnect_delay_max",
        "10",
        "-user_agent",
        USER_AGENT,
        "-referer",
        referer,
        "-headers",
        ffmpeg_headers(referer),
        "-i",
        signed_url,
        "-c",
        "copy",
        "-movflags",
        "+faststart",
        "-f",
        "mp4",
        str(temp),
    ]
    ffmpeg_messages: list[str] = []
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        creationflags=no_window_creationflags(),
    )
    start_time = time.time()
    last_output_time = [start_time]
    stalled = [False]

    def watchdog() -> None:
        while process.poll() is None:
            if time.time() - last_output_time[0] > FFMPEG_STALL_TIMEOUT:
                stalled[0] = True
                terminate_process(process)
                return
            time.sleep(5)

    threading.Thread(target=watchdog, daemon=True).start()
    current_time: float | None = None
    current_size: int | None = None
    speed = ""
    assert process.stdout is not None
    for raw_line in process.stdout:
        line = raw_line.strip()
        if not line:
            continue
        last_output_time[0] = time.time()
        if "=" not in line:
            ffmpeg_messages.append(redact_media_urls_in_text(line))
            ffmpeg_messages = ffmpeg_messages[-30:]
            continue
        key, value = line.split("=", 1)
        if key in {"out_time_ms", "out_time_us"}:
            current_time = seconds_from_ffmpeg_time(value)
        elif key == "out_time":
            parsed = seconds_from_ffmpeg_time(value)
            if parsed is not None:
                current_time = parsed
        elif key == "total_size" and value.isdigit():
            current_size = int(value)
        elif key == "speed":
            speed = f"speed {value}"
        elif key == "progress" and value == "end":
            break

        if current_size is None and temp.exists():
            current_size = temp.stat().st_size
        print_progress_line(
            progress_prefix,
            current_time,
            duration,
            current_size,
            expected_size,
            speed,
            start_time,
            progress_lines=progress_lines,
        )

    if stalled[0]:
        raise subprocess.TimeoutExpired(cmd, FFMPEG_STALL_TIMEOUT)

    return_code = process.wait()
    if temp.exists():
        current_size = temp.stat().st_size
    print_progress_line(
        progress_prefix,
        duration if return_code == 0 and duration else current_time,
        duration,
        current_size,
        expected_size,
        speed,
        start_time,
        final=True,
        progress_lines=progress_lines,
    )
    if return_code != 0:
        if ffmpeg_messages:
            print("\n".join(ffmpeg_messages), file=sys.stderr)
        raise subprocess.CalledProcessError(return_code, cmd)
    if output.exists() and overwrite:
        output.unlink()
    temp.replace(output)
    if not is_probably_complete_mp4(output):
        raise MediaAccessError(
            f"ffmpeg 已退出但生成的文件不是完整 mp4：{output.name}\n"
            "请重新下载；如果多次出现，请换一个保存目录或检查磁盘/杀毒软件是否拦截写入。"
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download classroom recordings from a yanhekt/延河课堂 course page using your Chrome or Edge login."
    )
    parser.add_argument("course_url", nargs="?", help="Example: https://www.yanhekt.cn/course/12345")
    parser.add_argument(
        "-o",
        "--output",
        default=str(default_output_dir()),
        help="Output directory. Default: ~/Downloads/YanhektDownloader",
    )
    parser.add_argument(
        "--cdp",
        default=None,
        help="Chromium DevTools base URL. Default: auto or http://127.0.0.1:9222",
    )
    parser.add_argument(
        "--chrome",
        "--browser",
        dest="browser",
        default=None,
        help="Path to chrome.exe or msedge.exe for the dedicated browser fallback.",
    )
    parser.add_argument(
        "--profile-dir",
        default=str(default_profile_dir()),
        help="Dedicated browser profile directory. Default: user-local YanhektDownloader state folder.",
    )
    parser.add_argument("--ffmpeg", default=None, help="Path to ffmpeg.exe")
    parser.add_argument("--limit", type=int, default=0, help="Download only the first N items after sorting.")
    parser.add_argument("--newest-first", action="store_true", help="Download newest lessons first.")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing mp4 files.")
    parser.add_argument("--dry-run", action="store_true", help="List videos and filenames without downloading.")
    parser.add_argument(
        "--plan-json",
        action="store_true",
        help="Print a machine-readable download plan for GUI selection and exit.",
    )
    parser.add_argument(
        "--session-ids",
        default="",
        help="Comma/space separated session ids to download. Filenames keep their full-course numbering.",
    )
    parser.add_argument(
        "--no-size-estimate",
        action="store_true",
        help="Skip estimated disk usage checks before each download.",
    )
    parser.add_argument(
        "--no-repair-legacy-names",
        action="store_true",
        help="Do not auto-rename completed legacy .mp_ files to .mp4 in the output folder.",
    )
    parser.add_argument(
        "--progress-lines",
        action="store_true",
        help="Print download progress as newline records. Useful for the GUI launcher.",
    )
    parser.add_argument(
        "--size-sample-segments",
        type=int,
        default=24,
        help="How many HLS segments to sample for size estimation. 0 means all segments. Default: 24",
    )
    parser.add_argument(
        "--size-workers",
        type=int,
        default=8,
        help="Concurrent HEAD/Range requests used for size estimation. Default: 8",
    )
    parser.add_argument(
        "--no-launch",
        action="store_true",
        help="Do not launch a dedicated browser if the current DevTools endpoint is unavailable.",
    )
    parser.add_argument(
        "--login-timeout",
        type=int,
        default=600,
        help="Seconds to wait for you to log in when a dedicated browser opens. Default: 600",
    )
    parser.add_argument(
        "--keep-browser-open",
        action="store_true",
        help="Keep the dedicated browser window open after the script finishes.",
    )
    parser.add_argument(
        "--background-browser",
        action="store_true",
        help="Launch the dedicated browser fallback in headless background mode when possible.",
    )
    return parser.parse_args()


def prompt_for_missing_args(args: argparse.Namespace) -> bool:
    if args.course_url:
        return True
    print("yanhekt/延河课堂录屏批量下载")
    print()
    print("请粘贴“课程列表链接”（course/数字），不是单节视频播放页（session/数字）。")
    print("例子：https://www.yanhekt.cn/course/12345")
    print()
    try:
        args.course_url = input("课程列表链接或课程 ID: ").strip()
        if not args.course_url:
            print("没有输入课程链接。", file=sys.stderr)
            return False
        print()
        print("直接回车会保存到默认文件夹：")
        print(f"  {args.output}")
        output = input("保存文件夹: ").strip()
        if output:
            args.output = output
        print()
        return True
    except (EOFError, KeyboardInterrupt):
        print("\n已取消。", file=sys.stderr)
        return False


def main() -> int:
    configure_standard_streams()
    args = parse_args()
    if not prompt_for_missing_args(args):
        return 2
    profile_dir = Path(args.profile_dir).expanduser().resolve()
    cdp_base = discover_cdp_base(args.cdp, profile_dir)
    course_url = args.course_url
    if re.fullmatch(r"\d+", course_url):
        course_url = f"{YANHE_HOST}/course/{course_url}"

    launched_proc: subprocess.Popen[Any] | None = None
    launched_headless = False
    def cleanup_launched() -> None:
        if launched_proc is not None and not args.keep_browser_open:
            terminate_process(launched_proc)

    def stop_launched_for_reconnect() -> None:
        nonlocal launched_proc, launched_headless
        if launched_proc is not None and launched_proc.poll() is None:
            terminate_process(launched_proc)
        launched_proc = None
        launched_headless = False

    def launch_chrome(headless: bool) -> None:
        nonlocal launched_proc, launched_headless, cdp_base
        launched_proc, cdp_base = launch_dedicated_chrome(
            find_browser(args.browser),
            profile_dir,
            course_url,
            headless=headless,
        )
        launched_headless = headless

    def relaunch_dedicated_chrome(reason: str, visible_for_login: bool = False) -> None:
        if args.no_launch:
            raise CdpError(reason)
        log(reason)
        if args.background_browser and not visible_for_login:
            log("Opening a background browser session and continuing...")
        else:
            log("Reopening the dedicated browser window and continuing...")
        stop_launched_for_reconnect()
        launch_chrome(headless=args.background_browser and not visible_for_login)

    def connect_or_reopen_chrome() -> tuple[CdpClient, str, dict[str, Any]]:
        try:
            return connect_yanhe_session(cdp_base, course_url)
        except Exception as exc:
            relaunch_dedicated_chrome(
                "Browser connection is unavailable or was closed while the task was running. "
                f"Details: {exc}"
            )
            return connect_yanhe_session(cdp_base, course_url)

    def wait_ready_or_login(
        cdp_client: CdpClient,
        attached_session_id: str,
        timeout: int,
    ) -> tuple[CdpClient, str]:
        try:
            wait_for_page_ready(cdp_client, session_id=attached_session_id, timeout=timeout)
            return cdp_client, attached_session_id
        except CdpError:
            if args.no_launch:
                raise
            if launched_headless or launched_proc is None:
                try:
                    cdp_client.close()
                except Exception:
                    pass
                relaunch_dedicated_chrome(
                    "Background browser is not logged in or the login expired. "
                    "A visible browser window is needed once for login.",
                    visible_for_login=True,
                )
                cdp_client, attached_session_id, _target = connect_yanhe_session(cdp_base, course_url)
            log("Please log in to yanhekt/延河课堂 (yanhekt.cn) in the browser window that just opened.")
            log(f"Waiting up to {args.login_timeout} seconds...")
            wait_for_page_ready(
                cdp_client,
                session_id=attached_session_id,
                timeout=args.login_timeout,
            )
            return cdp_client, attached_session_id

    def sign_recording_url(item: dict[str, Any], user_badge: str) -> str:
        last_error: Exception | None = None
        for attempt in range(2):
            cdp_client: CdpClient | None = None
            try:
                cdp_client, attached_session_id, _target = connect_or_reopen_chrome()
                cdp_client, attached_session_id = wait_ready_or_login(cdp_client, attached_session_id, timeout=15)
                signed = cdp_client.evaluate(
                    sign_url_expression(item["raw_vga"], user_badge),
                    timeout=30,
                    session_id=attached_session_id,
                )
                return str(signed)
            except Exception as exc:
                last_error = exc
                if attempt == 0 and not args.no_launch:
                    try:
                        relaunch_dedicated_chrome(
                            "Browser was closed or disconnected while preparing this video. "
                            "The downloader will retry once."
                        )
                    except Exception as relaunch_exc:
                        last_error = relaunch_exc
                        break
                    continue
                break
            finally:
                if cdp_client is not None:
                    try:
                        cdp_client.close()
                    except Exception:
                        pass
        raise CdpError(
            "Could not prepare the video URL. If the browser window was closed, "
            "please keep the reopened browser window open and retry. "
            f"Details: {last_error}"
        )

    try:
        cdp, session_id, _target = connect_yanhe_session(cdp_base, course_url)
    except Exception as exc:
        if args.no_launch:
            log(f"Could not connect to Chromium DevTools at {cdp_base}: {exc}", err=True)
            log("Open Chrome or Edge with a logged-in yanhekt.cn page, then retry.", err=True)
            return 2
        log("Current Chromium DevTools endpoint is not usable from this script.")
        if args.background_browser:
            log("Launching a background browser session for yanhekt/延河课堂 downloads...")
        else:
            log("Launching a dedicated local browser profile for yanhekt/延河课堂 downloads...")
        try:
            launch_chrome(headless=args.background_browser)
            cdp, session_id, _target = connect_yanhe_session(cdp_base, course_url)
        except Exception as launch_exc:
            log(f"Could not launch/connect to dedicated browser: {launch_exc}", err=True)
            cleanup_launched()
            return 2

    try:
        log("Reading yanhekt/延河课堂 course list from the logged-in browser...")
        cdp, session_id = wait_ready_or_login(cdp, session_id, timeout=10)
        info = cdp.evaluate(course_info_expression(course_url), timeout=90, session_id=session_id)
    except Exception as exc:
        log(f"Could not read course info from yanhekt.cn: {exc}", err=True)
        cleanup_launched()
        return 2
    finally:
        cdp.close()

    items = info.get("items", [])
    items.sort(key=lambda x: x.get("started_at") or "")
    if args.newest_first:
        items.reverse()
    if args.limit:
        items = items[: args.limit]

    try:
        output_dir = Path(args.output).expanduser().resolve()
        ensure_writable_directory(output_dir)
    except OSError as exc:
        log(f"保存目录不可用：{exc}", err=True)
        cleanup_launched()
        return 2
    planned = build_download_plan(items, output_dir)
    session_ids = parse_session_ids(args.session_ids)
    selected_planned = filter_plan_by_session_ids(planned, session_ids)
    if session_ids and not selected_planned:
        log("No matching session ids were found in this course plan.", err=True)
        cleanup_launched()
        return 2
    if args.plan_json:
        print(
            plan_json_line(plan_json_payload(info, planned, output_dir)),
            flush=True,
        )
        cleanup_launched()
        return 0
    planned = selected_planned
    if not args.dry_run and not args.no_repair_legacy_names:
        renamed = repair_legacy_mp_extensions(output_dir, [output for _, output in planned])
        if renamed:
            log(f"Repaired legacy .mp_ files: {len(renamed)}")
            for old, new in renamed:
                log(f"  renamed: {old.name} -> {new.name}")

    log(f"Course: {info.get('course_name')} ({info.get('course_id')})")
    log(f"Found classroom recordings: {len(items)}")
    log(f"Output: {output_dir}")

    if args.dry_run:
        for _, output in planned:
            log(f"[dry-run] {output.name}")
        cleanup_launched()
        return 0

    ffmpeg = find_ffmpeg(args.ffmpeg)
    try:
        total_count = len(planned)
        log(f"Selected classroom recordings: {total_count}")
        for item_index, (item, output) in enumerate(planned, start=1):
            if output.exists() and not args.overwrite:
                size = output.stat().st_size if output.is_file() else 0
                if size > 0 and is_probably_complete_mp4(output):
                    log(f"[skip existing] {output.name} ({format_bytes(size)})")
                    continue
                log(f"[replace invalid] {output.name}")
            duration = parse_duration(item.get("duration"))
            log(f"[{item_index}/{total_count}] {output.name}")
            try:
                log("  preparing video URL from the logged-in browser...")
                signed_url = sign_recording_url(item, str(info["user_badge"]))
            except CdpError as exc:
                log(f"[failed] {output.name}: {exc}", err=True)
                return 2

            referer = item.get("session_url") or course_url
            expected_size = None
            if not args.no_size_estimate:
                log("  estimating disk usage...")
                try:
                    expected_size, segment_count = estimate_hls_size(
                        signed_url,
                        referer,
                        sample_segments=args.size_sample_segments,
                        workers=args.size_workers,
                    )
                    sample_note = (
                        "all segments"
                        if args.size_sample_segments <= 0
                        else f"{min(args.size_sample_segments, segment_count)} segment sample"
                    )
                    log(
                        f"  estimated size: ~{format_bytes(expected_size)} "
                        f"({segment_count} segments, {sample_note})"
                    )
                    ensure_enough_free_space(output_dir, expected_size)
                except Exception as exc:
                    if isinstance(exc, InsufficientSpaceError):
                        log(f"[failed] {output.name}: {exc}", err=True)
                        return 2
                    log(f"  estimated size: unknown ({exc})")

            last_error: Exception | None = None
            for attempt in range(1, SIGNED_URL_RETRIES + 1):
                if attempt > 1:
                    log("  retrying with a fresh video URL...")
                    try:
                        signed_url = sign_recording_url(item, str(info["user_badge"]))
                    except CdpError as exc:
                        last_error = exc
                        break
                try:
                    with tempfile.TemporaryDirectory(prefix="yanhekt-hls-") as tmp:
                        log("  validating video access...")
                        ffmpeg_input = prepare_ffmpeg_hls_input(signed_url, referer, Path(tmp))
                        run_ffmpeg(
                            ffmpeg,
                            str(ffmpeg_input),
                            output,
                            referer,
                            args.overwrite,
                            duration,
                            expected_size,
                            f"  downloading",
                            progress_lines=args.progress_lines,
                        )
                    last_error = None
                    break
                except MediaAccessError as exc:
                    last_error = exc
                    if attempt >= SIGNED_URL_RETRIES:
                        break
                    log(f"  download attempt failed, will retry once: {exc}")
                except subprocess.TimeoutExpired as exc:
                    last_error = exc
                    if attempt >= SIGNED_URL_RETRIES:
                        break
                    log("  ffmpeg made no progress for too long; retrying once...")
                except subprocess.CalledProcessError as exc:
                    last_error = exc
                    if attempt >= SIGNED_URL_RETRIES:
                        break
                    log(f"  ffmpeg exited with {exc.returncode}; retrying once with a fresh URL...")
            if last_error is not None:
                if isinstance(last_error, MediaAccessError):
                    log(f"[failed] {output.name}: {last_error}", err=True)
                    return 2
                if isinstance(last_error, subprocess.TimeoutExpired):
                    log(
                        f"[failed] {output.name}: ffmpeg had no progress for {int(FFMPEG_STALL_TIMEOUT)} seconds. "
                        "Please retry on a stable network.",
                        err=True,
                    )
                    return 2
                if isinstance(last_error, subprocess.CalledProcessError):
                    log(f"[failed] {output.name}: ffmpeg exited with {last_error.returncode}", err=True)
                    return last_error.returncode or 1
                log(f"[failed] {output.name}: {last_error}", err=True)
                return 2
            log(f"  saved: {output} ({format_bytes(output.stat().st_size)})")
        log("Done.")
        return 0
    finally:
        cleanup_launched()


if __name__ == "__main__":
    raise SystemExit(main())
