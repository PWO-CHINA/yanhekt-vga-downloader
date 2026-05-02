#!/usr/bin/env python3
"""Installer for the yanhekt/延河课堂 downloader release payload."""

from __future__ import annotations

import argparse
import ctypes
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Callable
import tkinter as tk
import uuid


APP_NAME = "yanhekt-延河课堂录屏下载器"
EXE_NAME = "YanhektDownloader.exe"
WORKER_EXE_NAME = "YanhektDownloaderWorker.exe"
APP_ICON_NAME = "yanhekt_downloader.ico"
PAYLOAD_NAME = "release_payload.zip"
LEGACY_SHORTCUT_NAMES = ["Yanhekt Downloader.lnk", "yanhekt 延河课堂录屏下载器.lnk"]
REQUIRED_PAYLOAD_FILES = [EXE_NAME, WORKER_EXE_NAME, "ffmpeg.exe", "README.md", "LICENSE", "VERSION"]
MIN_TEMP_FREE_BYTES = 350 * 1024 * 1024

CLSID_SHELL_LINK = "00021401-0000-0000-C000-000000000046"
IID_ISHELL_LINK_W = "000214F9-0000-0000-C000-000000000046"
IID_IPERSIST_FILE = "0000010b-0000-0000-C000-000000000046"
FOLDERID_DESKTOP = "B4BFCC3A-DB2C-424C-B029-7FE99A87C641"
CLSCTX_INPROC_SERVER = 1


class Guid(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_uint32),
        ("Data2", ctypes.c_uint16),
        ("Data3", ctypes.c_uint16),
        ("Data4", ctypes.c_ubyte * 8),
    ]

    def __init__(self, value: str) -> None:
        parsed = uuid.UUID(value)
        super().__init__(
            parsed.time_low,
            parsed.time_mid,
            parsed.time_hi_version,
            (ctypes.c_ubyte * 8).from_buffer_copy(parsed.bytes[8:]),
        )


def hresult_failed(value: int) -> bool:
    return ctypes.c_long(value).value < 0


def check_hresult(value: int, action: str) -> None:
    if hresult_failed(value):
        raise OSError(f"{action} failed with HRESULT 0x{value & 0xFFFFFFFF:08X}")


def default_install_dir() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(local_app_data) / "Programs" / "YanhektDownloader"


def resource_path(name: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / name


def format_bytes(value: int | float) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(value)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{size:.1f} TB"


def payload_size() -> int:
    payload = resource_path(PAYLOAD_NAME)
    if not payload.exists():
        return 0
    return payload.stat().st_size


def check_free_space(install_dir: Path) -> None:
    payload_bytes = payload_size()
    required_install = max(250 * 1024 * 1024, int(payload_bytes * 1.8))
    temp_dir = Path(os.environ.get("TEMP") or os.environ.get("TMP") or str(Path.home()))
    install_space_root = install_dir
    while not install_space_root.exists() and install_space_root.parent != install_space_root:
        install_space_root = install_space_root.parent
    checks = [
        (temp_dir, MIN_TEMP_FREE_BYTES, "系统临时目录"),
        (install_space_root, required_install, "安装目录所在磁盘"),
    ]
    for path, required, label in checks:
        try:
            free = shutil.disk_usage(path).free
        except OSError:
            continue
        if free < required:
            raise OSError(f"{label}可用空间不足：至少需要 {format_bytes(required)}，当前可用 {format_bytes(free)}。")


def ensure_safe_zip_target(base: Path, member: str) -> Path:
    target = (base / member).resolve()
    base_resolved = base.resolve()
    if target != base_resolved and base_resolved not in target.parents:
        raise ValueError(f"Refusing unsafe archive path: {member}")
    return target


def extract_payload(install_dir: Path, log: Callable[[str], None]) -> None:
    payload = resource_path(PAYLOAD_NAME)
    if not payload.exists():
        raise FileNotFoundError(f"Missing installer payload: {payload}")
    install_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(payload, "r") as archive:
        for info in archive.infolist():
            target = ensure_safe_zip_target(install_dir, info.filename)
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, target.open("wb") as dest:
                shutil.copyfileobj(source, dest)
    log(f"已安装到：{install_dir}")


def ensure_writable_install_dir(install_dir: Path) -> None:
    install_dir.mkdir(parents=True, exist_ok=True)
    probe = install_dir / ".yanhekt_install_write_test.tmp"
    try:
        probe.write_text("ok", encoding="utf-8")
    finally:
        try:
            probe.unlink()
        except FileNotFoundError:
            pass


def validate_installation(install_dir: Path) -> None:
    missing = [name for name in REQUIRED_PAYLOAD_FILES if not (install_dir / name).exists()]
    if missing:
        raise FileNotFoundError("安装不完整，缺少文件：" + ", ".join(missing))
    ffmpeg = install_dir / "ffmpeg.exe"
    try:
        subprocess.run(
            [str(ffmpeg), "-version"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
            timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception as exc:
        raise RuntimeError(
            "ffmpeg.exe 已安装但无法运行。请重新安装，或检查杀毒软件/系统策略是否拦截了 ffmpeg.exe。"
        ) from exc


def ensure_app_not_running(install_dir: Path) -> None:
    if os.name != "nt":
        return
    exe_paths = [
        str((install_dir / EXE_NAME).resolve()).lower(),
        str((install_dir / WORKER_EXE_NAME).resolve()).lower(),
    ]
    existing = [path for path in exe_paths if Path(path).exists()]
    if not existing:
        return
    try:
        output = subprocess.check_output(
            [
                "wmic",
                "process",
                "where",
                "(name='YanhektDownloader.exe' or name='YanhektDownloaderWorker.exe')",
                "get",
                "ExecutablePath",
                "/value",
            ],
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="ignore",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception:
        return
    running_paths = []
    for line in output.splitlines():
        if not line.lower().startswith("executablepath="):
            continue
        value = line.split("=", 1)[1].strip().lower()
        if value in existing:
            running_paths.append(value)
    if running_paths:
        raise RuntimeError("检测到旧版程序仍在运行。请先关闭 yanhekt/延河课堂录屏下载器和正在下载的任务，再重新安装。")


def known_folder_path(folder_id: str) -> Path | None:
    if os.name != "nt":
        return None
    shell32 = ctypes.windll.shell32
    ole32 = ctypes.windll.ole32
    path_ptr = ctypes.c_void_p()
    result = shell32.SHGetKnownFolderPath(
        ctypes.byref(Guid(folder_id)),
        0,
        None,
        ctypes.byref(path_ptr),
    )
    if hresult_failed(result) or not path_ptr.value:
        return None
    try:
        return Path(ctypes.wstring_at(path_ptr))
    finally:
        ole32.CoTaskMemFree(path_ptr)


def desktop_path() -> Path:
    known_desktop = known_folder_path(FOLDERID_DESKTOP)
    if known_desktop is not None:
        return known_desktop
    return Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Desktop"


def com_method(pointer: ctypes.c_void_p, index: int, restype: object, *argtypes: object) -> object:
    vtable = ctypes.cast(pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    prototype = ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)
    return prototype(vtable[index])


def release_com_object(pointer: ctypes.c_void_p | None) -> None:
    if pointer and pointer.value:
        release = com_method(pointer, 2, ctypes.c_ulong)
        release(pointer)


def save_shell_shortcut(
    target: Path,
    shortcut: Path,
    working_dir: Path,
    description: str,
    icon_location: str,
) -> None:
    if os.name != "nt":
        raise OSError("Windows shortcuts are only supported on Windows.")

    ole32 = ctypes.oledll.ole32
    shell_link = ctypes.c_void_p()
    persist_file = ctypes.c_void_p()
    initialized = False
    init_result = ole32.CoInitialize(None)
    if init_result in (0, 1):
        initialized = True
    try:
        check_hresult(
            ole32.CoCreateInstance(
                ctypes.byref(Guid(CLSID_SHELL_LINK)),
                None,
                CLSCTX_INPROC_SERVER,
                ctypes.byref(Guid(IID_ISHELL_LINK_W)),
                ctypes.byref(shell_link),
            ),
            "Create ShellLink",
        )
        set_description = com_method(shell_link, 7, ctypes.c_long, ctypes.c_wchar_p)
        set_working_dir = com_method(shell_link, 9, ctypes.c_long, ctypes.c_wchar_p)
        set_icon = com_method(shell_link, 17, ctypes.c_long, ctypes.c_wchar_p, ctypes.c_int)
        set_path = com_method(shell_link, 20, ctypes.c_long, ctypes.c_wchar_p)
        check_hresult(set_description(shell_link, description), "Set shortcut description")
        check_hresult(set_working_dir(shell_link, str(working_dir)), "Set shortcut working directory")
        check_hresult(set_icon(shell_link, icon_location, 0), "Set shortcut icon")
        check_hresult(set_path(shell_link, str(target)), "Set shortcut target")

        query_interface = com_method(
            shell_link,
            0,
            ctypes.c_long,
            ctypes.POINTER(Guid),
            ctypes.POINTER(ctypes.c_void_p),
        )
        check_hresult(
            query_interface(shell_link, ctypes.byref(Guid(IID_IPERSIST_FILE)), ctypes.byref(persist_file)),
            "Query IPersistFile",
        )
        save = com_method(persist_file, 6, ctypes.c_long, ctypes.c_wchar_p, ctypes.c_int)
        check_hresult(save(persist_file, str(shortcut), True), "Save shortcut")
    finally:
        release_com_object(persist_file)
        release_com_object(shell_link)
        if initialized:
            ole32.CoUninitialize()


def create_desktop_shortcut(install_dir: Path, log: Callable[[str], None]) -> bool:
    target = install_dir / EXE_NAME
    desktop = desktop_path()
    shortcut = desktop / f"{APP_NAME}.lnk"
    icon = install_dir / APP_ICON_NAME
    icon_location = str(icon if icon.exists() else target)
    try:
        shortcut.parent.mkdir(parents=True, exist_ok=True)
        for legacy_shortcut in [shortcut] + [desktop / legacy_name for legacy_name in LEGACY_SHORTCUT_NAMES]:
            if legacy_shortcut != shortcut and legacy_shortcut.exists():
                legacy_shortcut.unlink()
            elif legacy_shortcut == shortcut and legacy_shortcut.exists():
                legacy_shortcut.unlink()
        save_shell_shortcut(
            target,
            shortcut,
            install_dir,
            APP_NAME,
            icon_location,
        )
    except Exception as exc:
        log(f"桌面快捷方式创建失败：{exc}")
        return False
    if shortcut.exists():
        log(f"已创建桌面快捷方式：{shortcut}")
        return True
    log(f"桌面快捷方式创建失败：未找到生成的文件 {shortcut}")
    return False


def launch_app(install_dir: Path) -> None:
    target = install_dir / EXE_NAME
    if not target.exists():
        raise FileNotFoundError(f"找不到主程序：{target}")
    try:
        process = subprocess.Popen([str(target)], cwd=str(install_dir), creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except OSError as exc:
        raise OSError(f"安装完成，但启动主程序失败：{exc}") from exc
    try:
        return_code = process.wait(timeout=1.0)
    except subprocess.TimeoutExpired:
        return
    if return_code != 0:
        raise RuntimeError(f"安装完成，但主程序启动后立即退出，退出代码：{return_code}")


def install(install_dir: Path, shortcut: bool, launch: bool, log: Callable[[str], None]) -> list[str]:
    warnings: list[str] = []
    check_free_space(install_dir)
    ensure_writable_install_dir(install_dir)
    ensure_app_not_running(install_dir)
    extract_payload(install_dir, log)
    validate_installation(install_dir)
    if shortcut:
        if not create_desktop_shortcut(install_dir, log):
            warnings.append(f"桌面快捷方式创建失败。主程序位置：{install_dir / EXE_NAME}")
    if launch:
        launch_app(install_dir)
    return warnings


class InstallerUi:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title(f"{APP_NAME} 安装程序")
        self.root.geometry("620x360")
        self.root.minsize(560, 320)
        self.install_dir = tk.StringVar(value=str(default_install_dir()))
        self.shortcut_var = tk.BooleanVar(value=True)
        self.launch_var = tk.BooleanVar(value=True)
        self.busy = False
        self.build()

    def build(self) -> None:
        frame = ttk.Frame(self.root, padding=18)
        frame.grid(row=0, column=0, sticky="nsew")
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(5, weight=1)

        ttk.Label(frame, text="安装 yanhekt/延河课堂录屏下载器", font=("Microsoft YaHei UI", 13, "bold")).grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 10)
        )
        ttk.Label(frame, text="请选择安装文件夹。安装后可双击桌面快捷方式启动。").grid(
            row=1, column=0, columnspan=3, sticky="w", pady=(0, 14)
        )
        ttk.Label(frame, text="安装到").grid(row=2, column=0, sticky="w", padx=(0, 8))
        ttk.Entry(frame, textvariable=self.install_dir).grid(row=2, column=1, sticky="ew")
        ttk.Button(frame, text="选择...", command=self.choose_dir).grid(row=2, column=2, padx=(8, 0))
        ttk.Checkbutton(frame, text="创建桌面快捷方式", variable=self.shortcut_var).grid(
            row=3, column=1, sticky="w", pady=(12, 0)
        )
        ttk.Checkbutton(frame, text="安装完成后启动", variable=self.launch_var).grid(
            row=4, column=1, sticky="w"
        )
        self.log_text = tk.Text(frame, height=7, wrap="word", state="disabled")
        self.log_text.grid(row=5, column=0, columnspan=3, sticky="nsew", pady=(14, 12))
        self.install_button = ttk.Button(frame, text="安装", command=self.install_now)
        self.install_button.grid(row=6, column=1, sticky="e")
        ttk.Button(frame, text="退出", command=self.root.destroy).grid(row=6, column=2, padx=(8, 0))

    def choose_dir(self) -> None:
        selected = filedialog.askdirectory(initialdir=self.install_dir.get() or str(default_install_dir()))
        if selected:
            self.install_dir.set(selected)

    def log(self, text: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", text + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")
        self.root.update_idletasks()

    def install_now(self) -> None:
        if self.busy:
            return
        install_dir = Path(self.install_dir.get()).expanduser()
        if not install_dir:
            messagebox.showerror("缺少安装目录", "请选择安装目录。")
            return
        if install_dir.exists() and any(install_dir.iterdir()):
            ok = messagebox.askyesno("确认覆盖", "安装目录已经存在。继续安装会覆盖同名文件，是否继续？")
            if not ok:
                return
        self.busy = True
        self.install_button.configure(state="disabled")
        try:
            warnings = install(install_dir, self.shortcut_var.get(), self.launch_var.get(), self.log)
        except Exception as exc:
            messagebox.showerror("安装失败", str(exc))
            self.log(f"安装失败：{exc}")
        else:
            if warnings:
                message = f"{APP_NAME} 已安装完成，但有一个问题需要注意：\n\n" + "\n".join(warnings)
                messagebox.showwarning("安装完成", message)
            else:
                messagebox.showinfo("安装完成", f"{APP_NAME} 已安装完成。")
        finally:
            self.busy = False
            self.install_button.configure(state="normal")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=f"Install {APP_NAME}.")
    parser.add_argument("--silent", action="store_true", help="Install without showing the GUI.")
    parser.add_argument("--install-dir", default=str(default_install_dir()), help="Target install directory.")
    parser.add_argument("--no-shortcut", action="store_true", help="Do not create a desktop shortcut.")
    parser.add_argument("--no-launch", action="store_true", help="Do not launch the app after installation.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.silent:
        try:
            warnings = install(
                Path(args.install_dir).expanduser(),
                shortcut=not args.no_shortcut,
                launch=not args.no_launch,
                log=print,
            )
            for warning in warnings:
                print(f"Warning: {warning}", file=sys.stderr)
        except Exception as exc:
            print(f"Install failed: {exc}", file=sys.stderr)
            return 1
        return 0

    root = tk.Tk()
    InstallerUi(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
