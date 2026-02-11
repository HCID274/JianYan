from __future__ import annotations

import ctypes
import os
import sys


def is_debug_console_enabled() -> bool:
    return os.environ.get("JIANYAN_DEBUG_CONSOLE", "").strip() == "1"


def is_pause_on_exit_enabled() -> bool:
    return os.environ.get("JIANYAN_DEBUG_PAUSE", "").strip() == "1"


def enable_debug_console() -> bool:
    """为 windowed (console=False) 的 EXE 申请一个控制台窗口，便于排查“闪退”。"""
    try:
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        ATTACH_PARENT_PROCESS = -1
        # 先尝试附加到父进程控制台（从 cmd/pwsh 启动时有用），失败再新建
        attached = bool(kernel32.AttachConsole(ATTACH_PARENT_PROCESS))
        if not attached:
            if not kernel32.AllocConsole():
                return False

        try:
            kernel32.SetConsoleTitleW("Jianyan Debug Console")
        except Exception:
            pass

        # 重定向 stdout/stderr 到控制台
        try:
            sys.stdout = open("CONOUT$", "w", encoding="utf-8", buffering=1)
            sys.stderr = open("CONOUT$", "w", encoding="utf-8", buffering=1)
            sys.stdin = open("CONIN$", "r", encoding="utf-8", buffering=1)
        except Exception:
            # 即使重定向失败，也不应影响主流程
            pass

        return True
    except Exception:
        return False


def pause(message: str = "Press Enter to exit...") -> None:
    """调试用暂停，避免窗口一闪而过。"""
    try:
        sys.stdout.write(message + "\n")
        sys.stdout.flush()
    except Exception:
        pass
    try:
        input()
    except Exception:
        try:
            import msvcrt

            msvcrt.getch()
        except Exception:
            pass

