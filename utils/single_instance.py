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

DWORD_PTR = ctypes.c_size_t
PDWORD_PTR = ctypes.POINTER(DWORD_PTR)

# 兼容旧 Python：wintypes 里可能没有 HCURSOR/HICON/HBRUSH
HCURSOR = getattr(wintypes, "HCURSOR", wintypes.HANDLE)
HICON = getattr(wintypes, "HICON", wintypes.HANDLE)
HBRUSH = getattr(wintypes, "HBRUSH", wintypes.HANDLE)

ERROR_ALREADY_EXISTS = 183
ERROR_CLASS_ALREADY_EXISTS = 1410

WM_QUIT = 0x0012

SMTO_ABORTIFHUNG = 0x0002
HWND_BROADCAST = 0xFFFF

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

_kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
_kernel32.CreateMutexW.restype = wintypes.HANDLE
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
_kernel32.CloseHandle.restype = wintypes.BOOL
_kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
_kernel32.GetModuleHandleW.restype = wintypes.HMODULE
_kernel32.GetCurrentThreadId.argtypes = []
_kernel32.GetCurrentThreadId.restype = wintypes.DWORD

_user32.RegisterWindowMessageW.argtypes = [wintypes.LPCWSTR]
_user32.RegisterWindowMessageW.restype = wintypes.UINT
_user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
_user32.FindWindowW.restype = wintypes.HWND
_user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, WPARAM, LPARAM]
_user32.PostMessageW.restype = wintypes.BOOL
_user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, WPARAM, LPARAM]
_user32.PostThreadMessageW.restype = wintypes.BOOL
_user32.SendMessageTimeoutW.argtypes = [
    wintypes.HWND,
    wintypes.UINT,
    WPARAM,
    LPARAM,
    wintypes.UINT,
    wintypes.UINT,
    PDWORD_PTR,
]
_user32.SendMessageTimeoutW.restype = LRESULT
_user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, WPARAM, LPARAM]
_user32.DefWindowProcW.restype = LRESULT
_user32.CreateWindowExW.argtypes = [
    wintypes.DWORD,
    wintypes.LPCWSTR,
    wintypes.LPCWSTR,
    wintypes.DWORD,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.HWND,
    wintypes.HMENU,
    wintypes.HINSTANCE,
    wintypes.LPVOID,
]
_user32.CreateWindowExW.restype = wintypes.HWND
_user32.DestroyWindow.argtypes = [wintypes.HWND]
_user32.DestroyWindow.restype = wintypes.BOOL
_user32.UnregisterClassW.argtypes = [wintypes.LPCWSTR, wintypes.HINSTANCE]
_user32.UnregisterClassW.restype = wintypes.BOOL
_user32.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT]
_user32.PeekMessageW.restype = wintypes.BOOL
_user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
_user32.GetMessageW.restype = ctypes.c_int
_user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
_user32.TranslateMessage.restype = wintypes.BOOL
_user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
_user32.DispatchMessageW.restype = LRESULT


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
        self._thread_id: Optional[int] = None
        self._class_atom: Optional[int] = None
        self._class_name = f"{self.name}_WNDCLASS"

        self._init_mutex()
        atexit.register(self.close)

    @property
    def already_running(self) -> bool:
        return self._already_running

    def _init_mutex(self) -> None:
        ctypes.set_last_error(0)
        handle = _kernel32.CreateMutexW(None, False, self.name)
        if not handle:
            err = ctypes.get_last_error()
            raise OSError(f"CreateMutexW failed: err={err}")

        last_error = ctypes.get_last_error()
        self._mutex = handle
        if last_error == ERROR_ALREADY_EXISTS:
            self._already_running = True
            logging.info("[SingleInstance] 已检测到互斥量存在，判定为已运行实例")
        else:
            logging.info("[SingleInstance] 创建互斥量成功，作为主实例运行")

    def start_wakeup_listener(self) -> None:
        """在主实例里启动隐藏窗口，监听唤醒消息"""
        if self._already_running or self._thread:
            return
        self._msg_id = self._register_message(self.message_name)
        self._thread = threading.Thread(target=self._message_loop, daemon=True, name="SingleInstanceListener")
        self._thread.start()

    def notify_existing(self) -> None:
        """新实例广播唤醒消息后退出"""
        if self._msg_id is None:
            self._msg_id = self._register_message(self.message_name)

        logging.info("[SingleInstance] 发送唤醒广播并退出新实例")
        try:
            result = DWORD_PTR()
            _user32.SendMessageTimeoutW(HWND_BROADCAST, self._msg_id, 0, 0, SMTO_ABORTIFHUNG, 1000, ctypes.byref(result))
        except Exception:
            logging.debug("[SingleInstance] SendMessageTimeoutW 失败", exc_info=True)

        try:
            hwnd = _user32.FindWindowW(self._class_name, self._class_name)
            if hwnd:
                logging.info("[SingleInstance] 找到旧实例窗口，直接发送唤醒消息")
                _user32.PostMessageW(hwnd, self._msg_id, 0, 0)
        except Exception:
            logging.debug("[SingleInstance] FindWindowW/PostMessageW 失败", exc_info=True)

    def close(self) -> None:
        thread_id = self._thread_id
        if thread_id:
            try:
                _user32.PostThreadMessageW(int(thread_id), WM_QUIT, 0, 0)
            except Exception:
                logging.debug("[SingleInstance] PostThreadMessageW(WM_QUIT) 失败", exc_info=True)

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)

        self._thread = None
        self._thread_id = None
        self._hwnd = None
        self._class_atom = None

        if self._mutex:
            _kernel32.CloseHandle(self._mutex)
            self._mutex = None

    def _register_message(self, name: str) -> int:
        msg = _user32.RegisterWindowMessageW(name)
        if msg == 0:
            err = ctypes.get_last_error()
            raise OSError(f"RegisterWindowMessageW failed: err={err}")
        return int(msg)

    def _message_loop(self) -> None:
        self._thread_id = int(_kernel32.GetCurrentThreadId())

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
            return _user32.DefWindowProcW(hwnd, msg, wparam, lparam)

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

        _user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASS)]
        _user32.RegisterClassW.restype = wintypes.ATOM

        hinstance = _kernel32.GetModuleHandleW(None)
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

        atom = int(_user32.RegisterClassW(ctypes.byref(wndclass)) or 0)
        if not atom:
            err = ctypes.get_last_error()
            if err != ERROR_CLASS_ALREADY_EXISTS:
                logging.error("[SingleInstance] RegisterClassW 失败: err=%s", err)
                return
            logging.debug("[SingleInstance] RegisterClassW: class already exists, continue")
        else:
            self._class_atom = atom

        hwnd = _user32.CreateWindowExW(
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
        if not hwnd:
            err = ctypes.get_last_error()
            logging.error("[SingleInstance] CreateWindowExW 失败: err=%s", err)
            return

        self._hwnd = hwnd
        logging.info("[SingleInstance] 唤醒窗口创建成功 hwnd=%s", hwnd)

        # 确保该线程消息队列已创建（否则 PostThreadMessage 可能失败）
        try:
            tmp = wintypes.MSG()
            _user32.PeekMessageW(ctypes.byref(tmp), None, 0, 0, 0)
        except Exception:
            pass

        try:
            msg = wintypes.MSG()
            while True:
                ret = _user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if ret == 0:
                    break  # WM_QUIT
                if ret == -1:
                    err = ctypes.get_last_error()
                    logging.error("[SingleInstance] GetMessageW 失败: err=%s", err)
                    break
                _user32.TranslateMessage(ctypes.byref(msg))
                _user32.DispatchMessageW(ctypes.byref(msg))
        except Exception:
            logging.exception("[SingleInstance] message loop crashed")
        finally:
            try:
                _user32.DestroyWindow(hwnd)
            except Exception:
                logging.debug("[SingleInstance] DestroyWindow 失败", exc_info=True)
            try:
                _user32.UnregisterClassW(class_name, hinstance)
            except Exception:
                logging.debug("[SingleInstance] UnregisterClassW 失败", exc_info=True)
