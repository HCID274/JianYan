from __future__ import annotations

import ctypes
import logging
import re
import sys
import threading
from collections.abc import Callable

_logger = logging.getLogger(__name__)


def start_hotkey_listener(on_toggle: Callable[[], None], hotkey: str) -> None:
    _logger.info("[Hotkey] 注册快捷键: %s", hotkey)
    stop_hotkey_listener()

    if sys.platform == "win32":
        _logger.info("[Hotkey] 使用 Win32 RegisterHotKey 后端")
        _start_win32_hotkey_listener(on_toggle, hotkey)
        return

    _logger.info("[Hotkey] 使用 keyboard 后端（非 Windows）")
    _start_keyboard_hotkey_listener(on_toggle, hotkey)


def stop_hotkey_listener() -> None:
    _stop_win32_hotkey_listener()
    _stop_keyboard_hotkey_listener()


# =========================
# Fallback backend: keyboard
# =========================

_keyboard_hotkey_id: int | None = None


def _start_keyboard_hotkey_listener(on_toggle: Callable[[], None], hotkey: str) -> None:
    global _keyboard_hotkey_id

    import keyboard

    def _wrapped_callback() -> None:
        _logger.info("[Hotkey] >>> 快捷键被触发! <<<")
        try:
            on_toggle()
            _logger.info("[Hotkey] on_toggle 回调完成")
        except Exception as exc:
            _logger.exception("[Hotkey] on_toggle 回调异常: %s", exc)

    _keyboard_hotkey_id = keyboard.add_hotkey(hotkey, _wrapped_callback, suppress=True)
    _logger.info("[Hotkey] keyboard 快捷键注册成功, id=%s", _keyboard_hotkey_id)


def _stop_keyboard_hotkey_listener() -> None:
    global _keyboard_hotkey_id
    if _keyboard_hotkey_id is None:
        return

    import keyboard

    try:
        _logger.info("[Hotkey] 移除 keyboard 快捷键, id=%s", _keyboard_hotkey_id)
        keyboard.remove_hotkey(_keyboard_hotkey_id)
    except Exception:
        _logger.exception("[Hotkey] 移除 keyboard 快捷键失败")
    finally:
        _keyboard_hotkey_id = None


# =========================
# Windows backend: RegisterHotKey
# =========================

_WIN32_HOTKEY_ID = 1
_WM_HOTKEY = 0x0312
_WM_QUIT = 0x0012

_MOD_ALT = 0x0001
_MOD_CONTROL = 0x0002
_MOD_SHIFT = 0x0004
_MOD_WIN = 0x0008
_MOD_NOREPEAT = 0x4000

_win32_thread: threading.Thread | None = None
_win32_thread_id: int | None = None
_win32_ready: threading.Event | None = None
_win32_start_error: Exception | None = None
_win32_lock = threading.Lock()


class Win32HotkeyError(RuntimeError):
    pass


def _start_win32_hotkey_listener(on_toggle: Callable[[], None], hotkey: str) -> None:
    global _win32_thread, _win32_thread_id, _win32_ready, _win32_start_error

    try:
        modifiers, vk = _parse_win32_hotkey(hotkey)
    except ValueError as exc:
        raise Win32HotkeyError(
            "热键格式不受支持。仅支持：ctrl/shift/alt/win + 单键（A-Z, 0-9, F1-F24, space/enter/tab/esc 等）"
        ) from exc

    with _win32_lock:
        ready = threading.Event()
        _win32_ready = ready
        _win32_start_error = None
        _win32_thread_id = None

        def _thread_main() -> None:
            _run_win32_hotkey_thread(on_toggle, modifiers, vk)

        _win32_thread = threading.Thread(target=_thread_main, name="Win32Hotkey", daemon=True)
        _win32_thread.start()

    if not ready.wait(timeout=3.0):
        raise Win32HotkeyError("快捷键注册超时（Win32 热键线程未就绪）")
    if _win32_start_error is not None:
        raise _win32_start_error


def _stop_win32_hotkey_listener() -> None:
    global _win32_thread, _win32_thread_id, _win32_ready, _win32_start_error

    with _win32_lock:
        thread = _win32_thread
        thread_id = _win32_thread_id
        _win32_thread = None
        _win32_thread_id = None
        _win32_ready = None
        _win32_start_error = None

    if thread_id is not None:
        try:
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            if not user32.PostThreadMessageW(int(thread_id), _WM_QUIT, 0, 0):
                err = ctypes.get_last_error()
                _logger.debug("[Hotkey] PostThreadMessage(WM_QUIT) 失败: err=%s", err)
        except Exception:
            _logger.debug("[Hotkey] 请求停止 Win32 热键线程失败", exc_info=True)

    if thread is not None:
        thread.join(timeout=2.0)
        if thread.is_alive():
            _logger.warning("[Hotkey] Win32 快捷键线程未能在超时内退出")


def _run_win32_hotkey_thread(on_toggle: Callable[[], None], modifiers: int, vk: int) -> None:
    global _win32_thread_id, _win32_start_error

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    class POINT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

    class MSG(ctypes.Structure):
        _fields_ = [
            ("hwnd", ctypes.c_void_p),
            ("message", ctypes.c_uint),
            ("wParam", ctypes.c_size_t),
            ("lParam", ctypes.c_size_t),
            ("time", ctypes.c_uint),
            ("pt", POINT),
        ]

    try:
        _win32_thread_id = int(kernel32.GetCurrentThreadId())

        # 确保线程消息队列已创建（否则 PostThreadMessage 可能失败）
        msg = MSG()
        user32.PeekMessageW(ctypes.byref(msg), 0, 0, 0, 0)

        flags = int(modifiers | _MOD_NOREPEAT)
        if not user32.RegisterHotKey(0, _WIN32_HOTKEY_ID, flags, int(vk)):
            err = ctypes.get_last_error()
            if err == 1409:  # ERROR_HOTKEY_ALREADY_REGISTERED
                raise Win32HotkeyError("快捷键已被其他程序占用，请在配置中更换组合键")
            raise Win32HotkeyError(f"注册快捷键失败（Win32 错误码: {err}）")

        _logger.info("[Hotkey] Win32 快捷键注册成功, thread_id=%s", _win32_thread_id)
    except Exception as exc:
        _win32_start_error = exc
        ready = _win32_ready
        if ready is not None:
            ready.set()
        _logger.exception("[Hotkey] Win32 快捷键启动失败: %s", exc)
        return

    ready = _win32_ready
    if ready is not None:
        ready.set()

    def _wrapped_callback() -> None:
        _logger.info("[Hotkey] >>> 快捷键被触发! <<<")
        try:
            on_toggle()
            _logger.info("[Hotkey] on_toggle 回调完成")
        except Exception as exc:
            _logger.exception("[Hotkey] on_toggle 回调异常: %s", exc)

    msg = MSG()
    try:
        while True:
            ret = user32.GetMessageW(ctypes.byref(msg), 0, 0, 0)
            if ret == 0:
                break  # WM_QUIT
            if ret == -1:
                err = ctypes.get_last_error()
                _logger.warning("[Hotkey] GetMessageW 失败: err=%s", err)
                break
            if msg.message == _WM_HOTKEY and int(msg.wParam) == _WIN32_HOTKEY_ID:
                _wrapped_callback()
    finally:
        try:
            user32.UnregisterHotKey(0, _WIN32_HOTKEY_ID)
        except Exception:
            _logger.debug("[Hotkey] UnregisterHotKey 失败", exc_info=True)
        _logger.info("[Hotkey] Win32 快捷键线程退出")


def _parse_win32_hotkey(hotkey: str) -> tuple[int, int]:
    if not hotkey or not hotkey.strip():
        raise ValueError("hotkey 不能为空")

    tokens = [t.strip().lower() for t in hotkey.split("+") if t.strip()]
    if not tokens:
        raise ValueError("hotkey 不能为空")

    modifiers = 0
    key_token: str | None = None

    for t in tokens:
        if t in {"ctrl", "control"}:
            modifiers |= _MOD_CONTROL
            continue
        if t == "shift":
            modifiers |= _MOD_SHIFT
            continue
        if t in {"alt", "menu"}:
            modifiers |= _MOD_ALT
            continue
        if t in {"win", "windows"}:
            modifiers |= _MOD_WIN
            continue

        if key_token is not None:
            raise ValueError(f"热键格式不支持多个主键: {hotkey}")
        key_token = t

    if key_token is None:
        raise ValueError(f"热键缺少主键: {hotkey}")

    vk = _parse_vk(key_token)
    return modifiers, vk


_VK_SPECIAL: dict[str, int] = {
    "space": 0x20,
    "tab": 0x09,
    "enter": 0x0D,
    "return": 0x0D,
    "esc": 0x1B,
    "escape": 0x1B,
    "backspace": 0x08,
    "delete": 0x2E,
    "del": 0x2E,
    "insert": 0x2D,
    "ins": 0x2D,
    "home": 0x24,
    "end": 0x23,
    "pageup": 0x21,
    "pgup": 0x21,
    "pagedown": 0x22,
    "pgdn": 0x22,
    "up": 0x26,
    "down": 0x28,
    "left": 0x25,
    "right": 0x27,
}


def _parse_vk(key: str) -> int:
    if key in _VK_SPECIAL:
        return _VK_SPECIAL[key]

    m = re.fullmatch(r"f(\d{1,2})", key)
    if m:
        n = int(m.group(1))
        if 1 <= n <= 24:
            return 0x70 + (n - 1)  # VK_F1..VK_F24

    if len(key) == 1:
        ch = key.upper()
        if "A" <= ch <= "Z" or "0" <= ch <= "9":
            return ord(ch)

    raise ValueError(f"不支持的主键: {key}")
