from __future__ import annotations

import faulthandler
import logging
import os
import sys
import tempfile
import threading
import traceback
from pathlib import Path

from utils.console import is_debug_console_enabled
from utils.notify import alert
from utils.paths import get_log_dir


def _open_faulthandler_file() -> object | None:
    candidates: list[Path] = []
    try:
        candidates.append(get_log_dir() / "faulthandler.log")
    except Exception:
        pass
    try:
        candidates.append(Path(tempfile.gettempdir()) / "Jianyan" / "faulthandler.log")
    except Exception:
        pass

    for p in candidates:
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            return p.open("a", encoding="utf-8")
        except Exception:
            continue
    return None


def install_exception_hooks() -> None:
    """业界常用：安装全局异常钩子 + faulthandler，尽量把“闪退”变成可观测日志。"""
    # 1) 低层崩溃（如 segfault）时输出线程栈
    try:
        f = _open_faulthandler_file()
        if f is not None:
            faulthandler.enable(file=f, all_threads=True)
    except Exception:
        pass

    # 2) 主线程未捕获异常：记录并弹窗
    def _sys_excepthook(exc_type, exc, tb) -> None:  # type: ignore[no-untyped-def]
        logging.critical("[Fatal] Unhandled exception", exc_info=(exc_type, exc, tb))
        try:
            msg = "".join(traceback.format_exception(exc_type, exc, tb))
            # 避免过长：只保留末尾
            msg = msg[-8000:]
            alert("程序异常退出", msg, force_message_box=True)
        except Exception:
            pass

    sys.excepthook = _sys_excepthook

    # 3) 后台线程异常：至少落日志；调试模式下也弹一次提示
    def _thread_excepthook(args: threading.ExceptHookArgs) -> None:
        logging.error(
            "[Thread] Unhandled exception in %s",
            getattr(args.thread, "name", "thread"),
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )
        if not is_debug_console_enabled():
            return
        try:
            msg = "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback))
            msg = msg[-8000:]
            alert("后台线程异常", msg, force_message_box=False)
        except Exception:
            pass

    try:
        threading.excepthook = _thread_excepthook  # type: ignore[assignment]
    except Exception:
        pass

    # 4) 标记：便于日志确认 hooks 已安装
    try:
        if getattr(sys, "frozen", False):
            logging.info("[Crash] exception hooks installed (frozen)")
        else:
            logging.info("[Crash] exception hooks installed (dev)")
    except Exception:
        pass

