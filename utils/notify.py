from __future__ import annotations

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
    except Exception as e:
        # HResult 错误或其他 COM 问题，静默禁用 Toast
        error_str = str(e)
        if "HResult" in error_str or "-2143420140" in error_str:
            logging.debug("Toast 通知不可用 (HResult error)，已禁用")
            _toast_available = False
        else:
            logging.debug("Toast 通知失败: %s", e)


def notify(title: str, message: str) -> None:
    """发送通知，仅尝试 Windows Toast，不弹其他窗口"""
    logging.info("通知: %s - %s", title, message)

    if not _toast_available or _win11toast is None:
        return

    t = threading.Thread(target=_send_toast, args=(title, message), daemon=True)
    t.start()
