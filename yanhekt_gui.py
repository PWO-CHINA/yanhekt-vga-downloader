#!/usr/bin/env python3
"""Small Tkinter launcher for the Yanhekt classroom recording downloader."""

from __future__ import annotations

import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import traceback
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
import tkinter as tk

import yanhekt_downloader as downloader


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT = SCRIPT_DIR / "downloads"
PLAN_PREFIX = "__YANHEKT_PLAN_JSON__"
CHECKED = "☑"
UNCHECKED = "☐"
APP_BG = "#f5f7fb"
PANEL_BG = "#ffffff"
TEXT = "#1f2937"
MUTED = "#64748b"
BORDER = "#d7dde8"
BLUE = "#2563eb"
BLUE_ACTIVE = "#1d4ed8"
GREEN = "#16803c"
GREEN_ACTIVE = "#11632f"
NEUTRAL = "#edf1f7"
NEUTRAL_ACTIVE = "#dfe6f0"
DISABLED_BG = "#e6ebf2"
DISABLED_TEXT = "#94a3b8"
FONT = ("Microsoft YaHei UI", 10)
FONT_BOLD = ("Microsoft YaHei UI", 10, "bold")


class YanhektGui:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Yanhekt 课堂录屏批量下载")
        self.root.geometry("1120x720")
        self.root.minsize(900, 560)

        self.course_var = tk.StringVar(value="")
        self.output_var = tk.StringVar(value=str(DEFAULT_OUTPUT))
        self.estimate_var = tk.BooleanVar(value=True)
        self.overwrite_var = tk.BooleanVar(value=False)
        self.keep_browser_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value="先加载课程清单")
        self.progress_var = tk.DoubleVar(value=0.0)

        self.process: subprocess.Popen[str] | None = None
        self.process_mode = ""
        self.events: queue.Queue[tuple[str, str | int | dict[str, object]]] = queue.Queue()
        self.plan_items: list[dict[str, object]] = []
        self.selected_session_ids: set[str] = set()
        self.plan_course_input = ""
        self.plan_output_dir = ""

        self.setup_styles()
        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.after(100, self.poll_events)

    def setup_styles(self) -> None:
        self.root.configure(bg=APP_BG)
        self.root.option_add("*Font", FONT)
        self.style = ttk.Style(self.root)
        try:
            self.style.theme_use("clam")
        except tk.TclError:
            pass

        self.style.configure(".", font=FONT, background=APP_BG, foreground=TEXT)
        self.style.configure("TFrame", background=APP_BG)
        self.style.configure("App.TFrame", background=APP_BG)
        self.style.configure("TLabel", background=APP_BG, foreground=TEXT)
        self.style.configure("Hint.TLabel", background=APP_BG, foreground=MUTED)
        self.style.configure("Status.TLabel", background=APP_BG, foreground=TEXT, font=FONT_BOLD)
        self.style.configure(
            "TEntry",
            fieldbackground=PANEL_BG,
            foreground=TEXT,
            bordercolor=BORDER,
            lightcolor=BORDER,
            darkcolor=BORDER,
            padding=(8, 5),
        )
        self.style.configure(
            "TButton",
            background=NEUTRAL,
            foreground=TEXT,
            bordercolor=BORDER,
            lightcolor=BORDER,
            darkcolor=BORDER,
            padding=(12, 6),
            relief="flat",
            focusthickness=0,
        )
        self.style.map(
            "TButton",
            background=[("disabled", DISABLED_BG), ("pressed", NEUTRAL_ACTIVE), ("active", NEUTRAL_ACTIVE)],
            foreground=[("disabled", DISABLED_TEXT)],
        )
        self.style.configure("Primary.TButton", background=BLUE, foreground="white", bordercolor=BLUE, padding=(14, 7))
        self.style.map(
            "Primary.TButton",
            background=[("disabled", DISABLED_BG), ("pressed", BLUE_ACTIVE), ("active", BLUE_ACTIVE)],
            foreground=[("disabled", DISABLED_TEXT)],
        )
        self.style.configure("Success.TButton", background=GREEN, foreground="white", bordercolor=GREEN, padding=(16, 7))
        self.style.map(
            "Success.TButton",
            background=[("disabled", DISABLED_BG), ("pressed", GREEN_ACTIVE), ("active", GREEN_ACTIVE)],
            foreground=[("disabled", DISABLED_TEXT)],
        )
        self.style.configure("Danger.TButton", background="#fee2e2", foreground="#991b1b", bordercolor="#fecaca")
        self.style.map(
            "Danger.TButton",
            background=[("disabled", DISABLED_BG), ("pressed", "#fecaca"), ("active", "#fecaca")],
            foreground=[("disabled", DISABLED_TEXT)],
        )
        self.style.configure("TCheckbutton", background=APP_BG, foreground=TEXT, padding=(0, 4))
        self.style.map("TCheckbutton", background=[("active", APP_BG)])
        self.style.configure(
            "Treeview",
            background=PANEL_BG,
            fieldbackground=PANEL_BG,
            foreground=TEXT,
            bordercolor=BORDER,
            rowheight=30,
            font=FONT,
        )
        self.style.configure(
            "Treeview.Heading",
            background="#eef2f7",
            foreground=TEXT,
            relief="flat",
            padding=(8, 6),
            font=FONT_BOLD,
        )
        self.style.map("Treeview.Heading", background=[("active", "#e4eaf2")])
        self.style.configure(
            "Horizontal.TProgressbar",
            troughcolor="#e8edf5",
            background=BLUE,
            bordercolor=BORDER,
            lightcolor=BLUE,
            darkcolor=BLUE,
        )

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, padding=16, style="App.TFrame")
        outer.grid(row=0, column=0, sticky="nsew")
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        outer.columnconfigure(1, weight=1)
        outer.rowconfigure(5, weight=3)
        outer.rowconfigure(7, weight=2)

        intro = (
            "请粘贴延河课堂课堂主页网址链接，例如 https://www.yanhekt.cn/course/12345。"
            "这里要填 course/数字，不是单节 session/数字播放页。"
        )
        ttk.Label(outer, text=intro, wraplength=980, style="Hint.TLabel").grid(
            row=0, column=0, columnspan=4, sticky="w", pady=(0, 12)
        )

        ttk.Label(outer, text="课堂主页网址链接").grid(row=1, column=0, sticky="w", padx=(0, 8))
        self.course_entry = ttk.Entry(outer, textvariable=self.course_var)
        self.course_entry.grid(row=1, column=1, sticky="ew")
        self.course_entry.bind("<Return>", self.on_course_enter)
        self.course_entry.bind("<KP_Enter>", self.on_course_enter)
        self.load_button = ttk.Button(
            outer,
            text="加载课程清单",
            command=self.load_plan,
            style="Primary.TButton",
            width=14,
        )
        self.load_button.grid(row=1, column=2, sticky="ew", padx=(8, 0))

        ttk.Label(outer, text="保存到").grid(row=2, column=0, sticky="w", padx=(0, 8), pady=(10, 0))
        ttk.Entry(outer, textvariable=self.output_var).grid(row=2, column=1, sticky="ew", pady=(10, 0))
        ttk.Button(outer, text="选择文件夹", command=self.choose_output, width=12).grid(
            row=2, column=2, sticky="ew", padx=(8, 0), pady=(10, 0)
        )
        ttk.Button(outer, text="打开文件夹", command=self.open_output, width=12).grid(
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
        ttk.Button(options, text="清除浏览器登录", command=self.clear_browser_login).grid(
            row=0, column=3, sticky="w"
        )

        buttons = ttk.Frame(outer)
        buttons.grid(row=4, column=0, columnspan=4, sticky="ew", pady=(14, 8))
        buttons.columnconfigure(7, weight=1)
        self.start_button = ttk.Button(
            buttons,
            text="开始下载勾选项",
            command=self.start_download,
            style="Success.TButton",
            state="disabled",
            width=16,
        )
        self.start_button.grid(row=0, column=0, sticky="w", padx=(0, 18))
        ttk.Separator(buttons, orient="vertical").grid(row=0, column=1, sticky="ns", padx=(0, 18))
        self.select_all_button = ttk.Button(buttons, text="全选", command=self.select_all, state="disabled", width=9)
        self.select_all_button.grid(row=0, column=2, padx=(0, 8))
        self.select_none_button = ttk.Button(buttons, text="全不选", command=self.select_none, state="disabled", width=9)
        self.select_none_button.grid(row=0, column=3, padx=(0, 8))
        self.repair_button = ttk.Button(buttons, text="修复旧文件名", command=self.repair_legacy, width=12)
        self.repair_button.grid(row=0, column=4, padx=(0, 8))
        self.stop_button = ttk.Button(
            buttons,
            text="停止",
            command=self.stop_process,
            state="disabled",
            style="Danger.TButton",
            width=8,
        )
        self.stop_button.grid(row=0, column=5, padx=(0, 8))
        ttk.Label(buttons, textvariable=self.status_var, style="Status.TLabel").grid(row=0, column=7, sticky="e")

        self.tree = ttk.Treeview(
            outer,
            columns=("selected", "started", "title", "filename", "status"),
            show="headings",
            selectmode="browse",
        )
        self.tree.heading("selected", text="下载")
        self.tree.heading("started", text="上课时间")
        self.tree.heading("title", text="课程标题")
        self.tree.heading("filename", text="预览文件名")
        self.tree.heading("status", text="状态")
        self.tree.column("selected", width=56, minwidth=48, anchor="center", stretch=False)
        self.tree.column("started", width=150, minwidth=120, stretch=False)
        self.tree.column("title", width=260, minwidth=160)
        self.tree.column("filename", width=430, minwidth=220)
        self.tree.column("status", width=120, minwidth=90, stretch=False)
        self.tree.grid(row=5, column=0, columnspan=4, sticky="nsew")
        tree_scroll = ttk.Scrollbar(outer, orient="vertical", command=self.tree.yview)
        tree_scroll.grid(row=5, column=4, sticky="ns")
        self.tree.configure(yscrollcommand=tree_scroll.set)
        self.tree.bind("<Button-1>", self.on_tree_click)
        self.tree.bind("<space>", self.on_tree_space)

        self.progress = ttk.Progressbar(outer, variable=self.progress_var, maximum=100, mode="determinate")
        self.progress.grid(row=6, column=0, columnspan=4, sticky="ew", pady=(10, 8))

        log_frame = ttk.Frame(outer)
        log_frame.grid(row=7, column=0, columnspan=4, sticky="nsew")
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        self.log_text = tk.Text(log_frame, height=10, wrap="word", undo=False)
        self.log_text.grid(row=0, column=0, sticky="nsew")
        log_scroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        log_scroll.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(
            yscrollcommand=log_scroll.set,
            bg=PANEL_BG,
            fg=TEXT,
            insertbackground=TEXT,
            relief="solid",
            bd=1,
            highlightthickness=0,
            padx=8,
            pady=8,
            font=FONT,
        )

    def choose_output(self) -> None:
        selected = filedialog.askdirectory(initialdir=self.output_var.get() or str(DEFAULT_OUTPUT))
        if selected:
            self.output_var.set(selected)
            self.clear_plan("保存目录已更改，请重新加载课程清单")

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
            messagebox.showerror("缺少课程链接", "请先填写延河课堂课堂主页网址链接，例如 https://www.yanhekt.cn/course/12345。")
            return None
        if "/session/" in course:
            messagebox.showerror("链接类型不对", "这里要填课程列表链接 course/数字，不是单节 session/数字播放页。")
            return None
        if not re.search(r"/course/\d+", course) and not re.fullmatch(r"\d+", course):
            messagebox.showwarning("确认链接", "没有识别到 course/数字。仍会尝试运行，但建议填课程列表页链接。")
        return course

    def resolved_output_dir(self) -> str:
        return str(Path(self.output_var.get().strip() or str(DEFAULT_OUTPUT)).expanduser().resolve())

    def set_running(self, running: bool) -> None:
        normal = "disabled" if running else "normal"
        self.load_button.configure(state=normal)
        self.repair_button.configure(state=normal)
        self.stop_button.configure(state="normal" if running else "disabled")
        self.set_plan_controls_enabled(bool(self.plan_items) and not running)

    def set_plan_controls_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        self.start_button.configure(state=state)
        self.select_all_button.configure(state=state)
        self.select_none_button.configure(state=state)

    def command_for(self, mode: str) -> list[str]:
        command = [
            sys.executable,
            str(SCRIPT_DIR / "yanhekt_downloader.py"),
            self.course_var.get().strip(),
            "-o",
            self.output_var.get().strip() or str(DEFAULT_OUTPUT),
            "--progress-lines",
        ]
        if mode == "plan":
            command.extend(["--plan-json", "--no-repair-legacy-names"])
        elif mode == "download":
            command.extend(["--session-ids", ",".join(self.selected_session_ids)])
            command.append("--background-browser")
        if not self.estimate_var.get():
            command.append("--no-size-estimate")
        if self.overwrite_var.get():
            command.append("--overwrite")
        if self.keep_browser_var.get():
            command.append("--keep-browser-open")
        return command

    def start_process(self, mode: str) -> None:
        if self.process is not None:
            return
        if self.validate_course() is None:
            return
        output_dir = Path(self.output_var.get().strip() or str(DEFAULT_OUTPUT)).expanduser()
        output_dir.mkdir(parents=True, exist_ok=True)

        self.progress_var.set(0.0)
        self.process_mode = mode
        self.status_var.set("正在加载课程清单" if mode == "plan" else "正在启动下载")
        self.set_running(True)
        self.append_log("\n=== 加载课程清单 ===\n" if mode == "plan" else "\n=== 开始下载勾选项 ===\n")

        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        creationflags = 0
        if os.name == "nt":
            creationflags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
        try:
            self.process = subprocess.Popen(
                self.command_for(mode),
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
            self.process_mode = ""
            self.set_running(False)
            self.status_var.set("启动失败")
            messagebox.showerror("启动失败", str(exc))
            return

        threading.Thread(target=self.read_process_output, daemon=True).start()

    def load_plan(self) -> None:
        self.clear_plan()
        self.start_process("plan")

    def on_course_enter(self, _event: tk.Event[tk.Misc]) -> str:
        if self.process is None:
            self.load_plan()
        return "break"

    def start_download(self) -> None:
        if not self.plan_items:
            messagebox.showinfo("还没有清单", "请先点击“加载课程清单”，确认要下载的课程。")
            return
        if self.plan_course_input != self.course_var.get().strip() or self.plan_output_dir != self.resolved_output_dir():
            messagebox.showinfo("清单需要刷新", "课程链接或保存目录已经变化，请重新加载课程清单。")
            return
        if not self.selected_session_ids:
            messagebox.showinfo("没有选择课程", "请至少勾选一节课。")
            return
        self.start_process("download")

    def clear_plan(self, status: str | None = None) -> None:
        self.plan_items = []
        self.selected_session_ids = set()
        self.plan_course_input = ""
        self.plan_output_dir = ""
        for row_id in self.tree.get_children():
            self.tree.delete(row_id)
        self.set_plan_controls_enabled(False)
        if status:
            self.status_var.set(status)

    def render_plan(self, payload: dict[str, object]) -> None:
        self.clear_plan()
        self.plan_items = list(payload.get("items", []))  # type: ignore[arg-type]
        self.plan_course_input = self.course_var.get().strip()
        self.plan_output_dir = self.resolved_output_dir()
        self.selected_session_ids = {str(item.get("session_id")) for item in self.plan_items}
        for item in self.plan_items:
            session_id = str(item.get("session_id"))
            status = "已存在" if item.get("complete_mp4") else ("文件存在" if item.get("exists") else "待下载")
            self.tree.insert(
                "",
                "end",
                iid=session_id,
                values=(
                    CHECKED,
                    str(item.get("started_at") or ""),
                    str(item.get("title") or ""),
                    str(item.get("filename") or ""),
                    status,
                ),
            )
        self.set_plan_controls_enabled(bool(self.plan_items))
        course_name = str(payload.get("course_name") or "课程")
        self.status_var.set(f"已加载 {len(self.plan_items)} 节课：{course_name}")
        self.append_log(f"已加载 {len(self.plan_items)} 节课，可在上方勾选后下载。\n")

    def set_checked(self, session_id: str, checked: bool) -> None:
        if checked:
            self.selected_session_ids.add(session_id)
            marker = CHECKED
        else:
            self.selected_session_ids.discard(session_id)
            marker = UNCHECKED
        values = list(self.tree.item(session_id, "values"))
        if values:
            values[0] = marker
            self.tree.item(session_id, values=values)
        self.status_var.set(f"已选择 {len(self.selected_session_ids)} / {len(self.plan_items)} 节课")

    def toggle_row(self, session_id: str) -> None:
        self.set_checked(session_id, session_id not in self.selected_session_ids)

    def on_tree_click(self, event: tk.Event[tk.Misc]) -> None:
        if self.process is not None:
            return
        row_id = self.tree.identify_row(event.y)
        column = self.tree.identify_column(event.x)
        if row_id and column == "#1":
            self.toggle_row(row_id)

    def on_tree_space(self, _event: tk.Event[tk.Misc]) -> str:
        focus = self.tree.focus()
        if focus and self.process is None:
            self.toggle_row(focus)
        return "break"

    def select_all(self) -> None:
        for item in self.plan_items:
            self.set_checked(str(item.get("session_id")), True)

    def select_none(self) -> None:
        for item in self.plan_items:
            self.set_checked(str(item.get("session_id")), False)

    def read_process_output(self) -> None:
        assert self.process is not None
        if self.process.stdout is not None:
            for line in self.process.stdout:
                if line.startswith(PLAN_PREFIX):
                    try:
                        self.events.put(("plan", json.loads(line[len(PLAN_PREFIX):])))
                    except json.JSONDecodeError as exc:
                        self.events.put(("line", f"课程清单解析失败：{exc}\n"))
                    continue
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
            elif kind == "plan":
                self.render_plan(payload)  # type: ignore[arg-type]
            elif kind == "done":
                code = int(payload)
                mode = self.process_mode
                self.process = None
                self.process_mode = ""
                self.set_running(False)
                if code == 0:
                    if mode == "download":
                        self.progress_var.set(100.0)
                        self.status_var.set("下载完成")
                        self.append_log("=== 下载完成 ===\n")
                    elif mode == "plan" and not self.plan_items:
                        self.status_var.set("没有读取到课程清单")
                    else:
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
        self.append_log("\n[stop] 正在停止当前任务...\n")
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(self.process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        else:
            self.process.terminate()

    def repair_legacy(self) -> None:
        output_dir = Path(self.output_var.get().strip() or str(DEFAULT_OUTPUT)).expanduser()
        output_dir.mkdir(parents=True, exist_ok=True)
        planned_paths = [Path(str(item.get("output_path"))) for item in self.plan_items if item.get("output_path")]
        renamed = downloader.repair_legacy_mp_extensions(output_dir, planned_paths)
        if not renamed:
            messagebox.showinfo("修复旧文件名", "没有找到需要修复的旧文件名。半成品 .part 不会被改名。")
            return
        self.append_log("\n=== 修复旧文件名 ===\n")
        for old, new in renamed:
            self.append_log(f"{old.name} -> {new.name}\n")
        messagebox.showinfo("修复旧文件名", f"已修复 {len(renamed)} 个文件。半成品 .part 没有改动。")
        if self.plan_items:
            self.status_var.set("文件名已修复，建议重新加载课程清单")

    def clear_browser_login(self) -> None:
        if self.process is not None:
            messagebox.showinfo("正在运行", "请先停止当前任务，再清除浏览器登录。")
            return
        profile_dir = downloader.default_profile_dir().expanduser().resolve()
        if not downloader.is_managed_profile_dir(profile_dir):
            messagebox.showerror("安全检查失败", f"拒绝清除非专用浏览器目录：\n{profile_dir}")
            return
        if not profile_dir.exists():
            messagebox.showinfo("无需清除", f"专用浏览器登录目录不存在：\n{profile_dir}")
            return
        ok = messagebox.askyesno(
            "清除浏览器登录",
            "这会删除本工具专用 Chrome 配置目录，包括 Yanhekt 登录状态、缓存和历史。\n\n"
            "不会影响你的主 Chrome 浏览器。\n\n"
            f"将删除：\n{profile_dir}\n\n"
            "确定继续吗？",
        )
        if not ok:
            return
        try:
            shutil.rmtree(profile_dir)
        except Exception as exc:
            messagebox.showerror("清除失败", f"无法删除专用浏览器目录：\n{profile_dir}\n\n{exc}")
            return
        self.clear_plan("已清除专用浏览器登录，请重新加载课程清单")
        self.append_log(f"\n=== 已清除专用浏览器登录 ===\n{profile_dir}\n")
        messagebox.showinfo("已清除", "专用浏览器登录状态已清除。下次运行会重新打开 Chrome 并要求登录。")

    def on_close(self) -> None:
        if self.process is not None:
            if not messagebox.askyesno("仍在运行", "当前任务仍在运行，要停止并退出吗？"):
                return
            self.stop_process()
        self.root.destroy()


def main() -> int:
    root = tk.Tk()
    YanhektGui(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        log_path = SCRIPT_DIR / "yanhekt_gui_error.log"
        log_path.write_text(traceback.format_exc(), encoding="utf-8")
        try:
            messagebox.showerror("GUI 启动失败", f"错误日志已保存到：\n{log_path}")
        except Exception:
            pass
        raise
