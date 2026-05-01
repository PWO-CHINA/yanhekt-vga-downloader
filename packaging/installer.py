#!/usr/bin/env python3
"""Installer for the Yanhekt Downloader release payload."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Callable
import tkinter as tk


APP_NAME = "Yanhekt Downloader"
EXE_NAME = "YanhektDownloader.exe"
PAYLOAD_NAME = "release_payload.zip"


def default_install_dir() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(local_app_data) / "Programs" / "YanhektDownloader"


def resource_path(name: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / name


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


def desktop_path() -> Path:
    return Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Desktop"


def ps_quote(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def create_desktop_shortcut(install_dir: Path, log: Callable[[str], None]) -> bool:
    target = install_dir / EXE_NAME
    shortcut = desktop_path() / f"{APP_NAME}.lnk"
    script = "\n".join(
        [
            "$shell = New-Object -ComObject WScript.Shell",
            f"$shortcut = $shell.CreateShortcut({ps_quote(shortcut)})",
            f"$shortcut.TargetPath = {ps_quote(target)}",
            f"$shortcut.WorkingDirectory = {ps_quote(install_dir)}",
            f"$shortcut.IconLocation = {ps_quote(str(target) + ',0')}",
            "$shortcut.Save()",
        ]
    )
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    result = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=flags,
        check=False,
    )
    if result.returncode == 0:
        log(f"已创建桌面快捷方式：{shortcut}")
        return True
    log("桌面快捷方式创建失败，但程序已经安装完成。")
    return False


def launch_app(install_dir: Path) -> None:
    target = install_dir / EXE_NAME
    if target.exists():
        subprocess.Popen([str(target)], cwd=str(install_dir), creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def install(install_dir: Path, shortcut: bool, launch: bool, log: Callable[[str], None]) -> None:
    extract_payload(install_dir, log)
    if shortcut:
        create_desktop_shortcut(install_dir, log)
    if launch:
        launch_app(install_dir)


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

        ttk.Label(frame, text="安装 Yanhekt Downloader", font=("Microsoft YaHei UI", 13, "bold")).grid(
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
            install(install_dir, self.shortcut_var.get(), self.launch_var.get(), self.log)
        except Exception as exc:
            messagebox.showerror("安装失败", str(exc))
            self.log(f"安装失败：{exc}")
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
            install(
                Path(args.install_dir).expanduser(),
                shortcut=not args.no_shortcut,
                launch=not args.no_launch,
                log=print,
            )
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
