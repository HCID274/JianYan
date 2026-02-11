from __future__ import annotations

import ctypes
import logging
import threading

_toast_available = True

try:
    from win11toast import toast as _win11toast
except Exception:  # pragma: no cover - optional dependency
    _win11toast = None
    _toast_available = False


def _send_toast(title: str, message: str) -> None:
    """在后台线程中发送 toast 通知，避免阻塞主流程"""
    global _toast_available
    if not _toast_available or _win11toast is None:
        return
    try:
        _win11toast(title, message, duration="short")
    except Exception as exc:
        # HResult 错误或其他 COM 问题，静默禁用 Toast
        error_str = str(exc)
        if "HResult" in error_str or "-2143420140" in error_str:
            logging.debug("Toast 通知不可用 (HResult error)，已禁用")
            _toast_available = False
        else:
            logging.debug("Toast 通知失败: %s", exc)


def notify(title: str, message: str) -> bool:
    """发送通知，仅尝试 Windows Toast，不弹其他窗口。

    Returns:
        True if a toast send was attempted (toast backend available), otherwise False.
    """
    logging.info("通知: %s - %s", title, message)

    if not _toast_available or _win11toast is None:
        return False

    t = threading.Thread(target=_send_toast, args=(title, message), daemon=True)
    t.start()
    return True


def alert(title: str, message: str, *, force_message_box: bool = False) -> None:
    """向用户显示“必须能看到”的提示。

    - 优先 Toast（不阻塞）
    - Toast 不可用或 force_message_box=True 时，退化为 MessageBox
    """
    attempted_toast = False
    try:
        attempted_toast = bool(notify(title, message))
    except Exception:
        attempted_toast = False

    if attempted_toast and not force_message_box:
        return

    try:
        MB_OK = 0x00000000
        MB_ICONERROR = 0x00000010
        ctypes.windll.user32.MessageBoxW(0, message, title, MB_OK | MB_ICONERROR)
    except Exception:
        logging.debug("MessageBox 提示失败", exc_info=True)

