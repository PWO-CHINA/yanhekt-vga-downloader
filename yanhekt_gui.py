#!/usr/bin/env python3
"""Small Tkinter launcher for the Yanhekt VGA downloader."""

from __future__ import annotations

import os
import queue
import re
import subprocess
import sys
import threading
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
import tkinter as tk

import yanhekt_downloader as downloader


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT = SCRIPT_DIR / "downloads"


class YanhektGui:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Yanhekt VGA 批量下载")
        self.root.geometry("900x620")
        self.root.minsize(760, 520)

        self.course_var = tk.StringVar(value="")
        self.output_var = tk.StringVar(value=str(DEFAULT_OUTPUT))
        self.estimate_var = tk.BooleanVar(value=True)
        self.overwrite_var = tk.BooleanVar(value=False)
        self.keep_browser_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value="准备就绪")
        self.progress_var = tk.DoubleVar(value=0.0)

        self.process: subprocess.Popen[str] | None = None
        self.events: queue.Queue[tuple[str, str | int]] = queue.Queue()

        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.after(100, self.poll_events)

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, padding=14)
        outer.grid(row=0, column=0, sticky="nsew")
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        outer.columnconfigure(1, weight=1)
        outer.rowconfigure(6, weight=1)

        intro = (
            "请粘贴课程列表链接，例如 https://www.yanhekt.cn/course/12345。"
            "这里要填 course/数字，不是单节 session/数字播放页。"
        )
        ttk.Label(outer, text=intro, wraplength=820).grid(
            row=0, column=0, columnspan=4, sticky="w", pady=(0, 12)
        )

        ttk.Label(outer, text="课程列表链接").grid(row=1, column=0, sticky="w", padx=(0, 8))
        course_entry = ttk.Entry(outer, textvariable=self.course_var)
        course_entry.grid(row=1, column=1, columnspan=3, sticky="ew")

        ttk.Label(outer, text="保存到").grid(row=2, column=0, sticky="w", padx=(0, 8), pady=(10, 0))
        ttk.Entry(outer, textvariable=self.output_var).grid(
            row=2, column=1, sticky="ew", pady=(10, 0)
        )
        ttk.Button(outer, text="选择文件夹", command=self.choose_output).grid(
            row=2, column=2, sticky="ew", padx=(8, 0), pady=(10, 0)
        )
        ttk.Button(outer, text="打开文件夹", command=self.open_output).grid(
            row=2, column=3, sticky="ew", padx=(8, 0), pady=(10, 0)
        )

        options = ttk.Frame(outer)
        options.grid(row=3, column=1, columnspan=3, sticky="w", pady=(10, 0))
        ttk.Checkbutton(options, text="下载前估算占用空间", variable=self.estimate_var).grid(
            row=0, column=0, sticky="w", padx=(0, 20)
        )
        ttk.Checkbutton(options, text="覆盖已有 mp4", variable=self.overwrite_var).grid(
            row=0, column=1, sticky="w", padx=(0, 20)
        )
        ttk.Checkbutton(options, text="结束后保留登录浏览器", variable=self.keep_browser_var).grid(
            row=0, column=2, sticky="w"
        )

        buttons = ttk.Frame(outer)
        buttons.grid(row=4, column=0, columnspan=4, sticky="ew", pady=(14, 8))
        buttons.columnconfigure(5, weight=1)
        self.start_button = ttk.Button(buttons, text="开始下载 VGA", command=self.start_download)
        self.start_button.grid(row=0, column=0, padx=(0, 8))
        self.list_button = ttk.Button(buttons, text="只列出清单", command=self.list_only)
        self.list_button.grid(row=0, column=1, padx=(0, 8))
        self.repair_button = ttk.Button(buttons, text="修复旧 .mp_ 文件", command=self.repair_legacy)
        self.repair_button.grid(row=0, column=2, padx=(0, 8))
        self.stop_button = ttk.Button(buttons, text="停止", command=self.stop_process, state="disabled")
        self.stop_button.grid(row=0, column=3, padx=(0, 8))
        ttk.Label(buttons, textvariable=self.status_var).grid(row=0, column=5, sticky="e")

        self.progress = ttk.Progressbar(
            outer,
            variable=self.progress_var,
            maximum=100,
            mode="determinate",
        )
        self.progress.grid(row=5, column=0, columnspan=4, sticky="ew", pady=(0, 8))

        log_frame = ttk.Frame(outer)
        log_frame.grid(row=6, column=0, columnspan=4, sticky="nsew")
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        self.log_text = tk.Text(log_frame, height=20, wrap="word", undo=False)
        self.log_text.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=scroll.set)

    def choose_output(self) -> None:
        selected = filedialog.askdirectory(initialdir=self.output_var.get() or str(DEFAULT_OUTPUT))
        if selected:
            self.output_var.set(selected)

    def open_output(self) -> None:
        output_dir = Path(self.output_var.get()).expanduser()
        output_dir.mkdir(parents=True, exist_ok=True)
        if os.name == "nt":
            os.startfile(output_dir)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(output_dir)])
        else:
            subprocess.Popen(["xdg-open", str(output_dir)])

    def append_log(self, text: str) -> None:
        self.log_text.insert("end", text)
        self.log_text.see("end")

    def validate_course(self) -> str | None:
        course = self.course_var.get().strip()
        if not course:
            messagebox.showerror("缺少课程链接", "请先填写课程列表链接，例如 https://www.yanhekt.cn/course/12345。")
            return None
        if "/session/" in course:
            messagebox.showerror("链接类型不对", "这里要填课程列表链接 course/数字，不是单节 session/数字播放页。")
            return None
        if not re.search(r"/course/\d+", course) and not re.fullmatch(r"\d+", course):
            messagebox.showwarning("确认链接", "没有识别到 course/数字。仍会尝试运行，但建议填课程列表页链接。")
        return course

    def set_running(self, running: bool) -> None:
        state = "disabled" if running else "normal"
        self.start_button.configure(state=state)
        self.list_button.configure(state=state)
        self.repair_button.configure(state=state)
        self.stop_button.configure(state="normal" if running else "disabled")

    def command_for(self, dry_run: bool) -> list[str]:
        command = [
            sys.executable,
            str(SCRIPT_DIR / "yanhekt_downloader.py"),
            self.course_var.get().strip(),
            "-o",
            self.output_var.get().strip() or str(DEFAULT_OUTPUT),
            "--progress-lines",
        ]
        if dry_run:
            command.append("--dry-run")
        if not self.estimate_var.get():
            command.append("--no-size-estimate")
        if self.overwrite_var.get():
            command.append("--overwrite")
        if self.keep_browser_var.get():
            command.append("--keep-browser-open")
        return command

    def start_process(self, dry_run: bool = False) -> None:
        if self.process is not None:
            return
        if self.validate_course() is None:
            return
        output_dir = Path(self.output_var.get().strip() or str(DEFAULT_OUTPUT)).expanduser()
        output_dir.mkdir(parents=True, exist_ok=True)

        self.progress_var.set(0.0)
        self.status_var.set("正在启动")
        self.set_running(True)
        self.append_log("\n=== 开始运行 ===\n")

        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        creationflags = 0
        if os.name == "nt":
            creationflags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
        try:
            self.process = subprocess.Popen(
                self.command_for(dry_run),
                cwd=str(SCRIPT_DIR),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                env=env,
                creationflags=creationflags,
            )
        except Exception as exc:
            self.process = None
            self.set_running(False)
            self.status_var.set("启动失败")
            messagebox.showerror("启动失败", str(exc))
            return

        threading.Thread(target=self.read_process_output, daemon=True).start()

    def start_download(self) -> None:
        self.start_process(dry_run=False)

    def list_only(self) -> None:
        self.start_process(dry_run=True)

    def read_process_output(self) -> None:
        assert self.process is not None
        if self.process.stdout is not None:
            for line in self.process.stdout:
                self.events.put(("line", line))
        return_code = self.process.wait()
        self.events.put(("done", return_code))

    def poll_events(self) -> None:
        while True:
            try:
                kind, payload = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == "line":
                line = str(payload).replace("\r", "\n")
                self.append_log(line)
                self.update_status_from_line(line)
            elif kind == "done":
                code = int(payload)
                self.process = None
                self.set_running(False)
                if code == 0:
                    self.progress_var.set(100.0)
                    self.status_var.set("完成")
                    self.append_log("=== 已完成 ===\n")
                else:
                    self.status_var.set(f"已退出，代码 {code}")
                    self.append_log(f"=== 已退出，代码 {code} ===\n")
        self.root.after(100, self.poll_events)

    def update_status_from_line(self, line: str) -> None:
        match = re.search(r"downloading\s+([0-9.]+)%", line)
        if match:
            self.progress_var.set(float(match.group(1)))
            self.status_var.set(line.strip())
            return
        if "estimating disk usage" in line:
            self.status_var.set("正在估算占用空间")
        elif "estimated size:" in line:
            self.status_var.set(line.strip())
        elif line.startswith("[skip existing]"):
            self.status_var.set(line.strip())
        elif line.startswith("[") and "/" in line:
            self.progress_var.set(0.0)
            self.status_var.set(line.strip())
        elif "saved:" in line:
            self.status_var.set(line.strip())

    def stop_process(self) -> None:
        if self.process is None:
            return
        self.append_log("\n[stop] 正在停止当前下载...\n")
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(self.process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        else:
            self.process.terminate()

    def repair_legacy(self) -> None:
        output_dir = Path(self.output_var.get().strip() or str(DEFAULT_OUTPUT)).expanduser()
        output_dir.mkdir(parents=True, exist_ok=True)
        renamed = downloader.repair_legacy_mp_extensions(output_dir)
        if not renamed:
            messagebox.showinfo("修复旧文件名", "没有找到需要修复的 .mp_ 成品文件。半成品 .part 不会被改名。")
            return
        self.append_log("\n=== 修复旧 .mp_ 文件 ===\n")
        for old, new in renamed:
            self.append_log(f"{old.name} -> {new.name}\n")
        messagebox.showinfo("修复旧文件名", f"已修复 {len(renamed)} 个文件。半成品 .part 没有改动。")

    def on_close(self) -> None:
        if self.process is not None:
            if not messagebox.askyesno("仍在运行", "下载仍在运行，要停止并退出吗？"):
                return
            self.stop_process()
        self.root.destroy()


def main() -> int:
    root = tk.Tk()
    YanhektGui(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
