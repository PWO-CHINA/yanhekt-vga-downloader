from __future__ import annotations

import traceback
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent


try:
    from yanhekt_gui import main

    raise SystemExit(main())
except Exception:
    log_path = SCRIPT_DIR / "yanhekt_gui_error.log"
    log_path.write_text(traceback.format_exc(), encoding="utf-8")
    try:
        from tkinter import messagebox

        messagebox.showerror("GUI 启动失败", f"错误日志已保存到：\n{log_path}")
    except Exception:
        pass
    raise
