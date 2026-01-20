from __future__ import annotations

import atexit
import ctypes
import logging
import threading
from ctypes import wintypes
from typing import Callable, Optional

# LRESULT/LPARAM/WPARAM 在 ctypes.wintypes 里可能不全，手动补全
LRESULT = getattr(wintypes, "LRESULT", ctypes.c_ssize_t)
LPARAM = getattr(wintypes, "LPARAM", ctypes.c_ssize_t)
WPARAM = getattr(wintypes, "WPARAM", ctypes.c_size_t)
# 兼容旧 Python：wintypes 里可能没有 HCURSOR/HICON/HBRUSH
HCURSOR = getattr(wintypes, "HCURSOR", wintypes.HANDLE)
HICON = getattr(wintypes, "HICON", wintypes.HANDLE)
HBRUSH = getattr(wintypes, "HBRUSH", wintypes.HANDLE)


class SingleInstanceGuard:
    """Windows 单实例守护：命名 Mutex + 消息广播唤醒"""

    def __init__(self, name: str, message_name: str, on_wakeup: Optional[Callable[[], None]] = None) -> None:
        self.name = name
        self.message_name = message_name
        self.on_wakeup = on_wakeup
        self._mutex = None
        self._already_running = False
        self._hwnd = None
        self._msg_id = None
        self._thread: Optional[threading.Thread] = None
        self._class_name = f"{self.name}_WNDCLASS"

        self._init_mutex()
        atexit.register(self.close)

    @property
    def already_running(self) -> bool:
        return self._already_running

    def _init_mutex(self) -> None:
        kernel32 = ctypes.windll.kernel32
        kernel32.SetLastError(0)
        handle = kernel32.CreateMutexW(None, False, self.name)
        last_error = kernel32.GetLastError()
        self._mutex = handle
        if last_error == 183:  # ERROR_ALREADY_EXISTS
            self._already_running = True
            logging.info("[SingleInstance] 已检测到互斥量存在，判定为已运行实例")
        else:
            logging.info("[SingleInstance] 创建互斥量成功，作为主实例运行")

    def start_wakeup_listener(self) -> None:
        """在主实例里启动隐藏窗口，监听唤醒消息"""
        if self._already_running or self._thread:
            return
        self._msg_id = self._register_message(self.message_name)
        self._thread = threading.Thread(target=self._message_loop, daemon=True)
        self._thread.start()

    def notify_existing(self) -> None:
        """新实例广播唤醒消息后退出"""
        if self._msg_id is None:
            self._msg_id = self._register_message(self.message_name)
        user32 = ctypes.windll.user32
        SMTO_ABORTIFHUNG = 0x0002
        HWND_BROADCAST = 0xFFFF
        logging.info("[SingleInstance] 发送唤醒广播并退出新实例")
        user32.SendMessageTimeoutW(HWND_BROADCAST, self._msg_id, 0, 0, SMTO_ABORTIFHUNG, 1000, None)
        # 兜底：按类名查找窗口并 PostMessage
        hwnd = user32.FindWindowW(self._class_name, self._class_name)
        if hwnd:
            logging.info("[SingleInstance] 找到旧实例窗口，直接发送唤醒消息")
            user32.PostMessageW(hwnd, self._msg_id, 0, 0)

    def close(self) -> None:
        if self._hwnd:
            user32 = ctypes.windll.user32
            user32.PostMessageW(self._hwnd, 0x0012, 0, 0)  # WM_QUIT
            self._hwnd = None
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        if self._mutex:
            ctypes.windll.kernel32.ReleaseMutex(self._mutex)
            ctypes.windll.kernel32.CloseHandle(self._mutex)
            self._mutex = None

    def _register_message(self, name: str) -> int:
        user32 = ctypes.windll.user32
        msg = user32.RegisterWindowMessageW(name)
        if msg == 0:
            raise OSError("RegisterWindowMessageW failed")
        return msg

    def _message_loop(self) -> None:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, WPARAM, LPARAM]
        user32.DefWindowProcW.restype = LRESULT

        WNDPROCTYPE = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, WPARAM, LPARAM)

        def _wnd_proc(hwnd, msg, wparam, lparam):
            if msg == self._msg_id:
                logging.info("[SingleInstance] 收到唤醒消息")
                try:
                    if self.on_wakeup:
                        self.on_wakeup()
                    else:
                        logging.debug("[SingleInstance] 未配置唤醒回调，忽略消息")
                except Exception:
                    logging.exception("[SingleInstance] 执行唤醒回调失败")
                return 0
            return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

        wnd_proc = WNDPROCTYPE(_wnd_proc)

        class WNDCLASS(ctypes.Structure):
            _fields_ = [
                ("style", wintypes.UINT),
                ("lpfnWndProc", WNDPROCTYPE),
                ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int),
                ("hInstance", wintypes.HINSTANCE),
                ("hIcon", HICON),
                ("hCursor", HCURSOR),
                ("hbrBackground", HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR),
                ("lpszClassName", wintypes.LPCWSTR),
            ]

        hinstance = kernel32.GetModuleHandleW(None)
        class_name = self._class_name
        wndclass = WNDCLASS()
        wndclass.style = 0
        wndclass.lpfnWndProc = wnd_proc
        wndclass.cbClsExtra = 0
        wndclass.cbWndExtra = 0
        wndclass.hInstance = hinstance
        wndclass.hIcon = None
        wndclass.hCursor = None
        wndclass.hbrBackground = None
        wndclass.lpszMenuName = None
        wndclass.lpszClassName = class_name

        if not user32.RegisterClassW(ctypes.byref(wndclass)):
            logging.debug("[SingleInstance] RegisterClassW 返回 0，可能已注册，继续")

        hwnd = user32.CreateWindowExW(
            0,
            class_name,
            class_name,
            0,
            0,
            0,
            0,
            0,
            None,
            None,
            hinstance,
            None,
        )
        self._hwnd = hwnd
        logging.info("[SingleInstance] 唤醒窗口创建成功 hwnd=%s", hwnd)

        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
