from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from app.state import AppState
from utils.console import enable_debug_console, is_pause_on_exit_enabled, pause
from utils.config import load_config
from utils.crash import install_exception_hooks
from utils.log import setup_logging
from utils.notify import alert, notify
from utils.paths import PathAccessError, get_log_dir, get_model_cache_dir, is_writable_dir
from utils.single_instance import SingleInstanceGuard


def _bootstrap_debug_flags(argv: list[str]) -> None:
    args = set(a.strip() for a in argv if a and a.strip())
    if "--debug-console" in args or os.environ.get("JIANYAN_DEBUG_CONSOLE", "").strip() == "1":
        os.environ["JIANYAN_DEBUG_CONSOLE"] = "1"
    if "--pause-on-exit" in args or os.environ.get("JIANYAN_DEBUG_PAUSE", "").strip() == "1":
        os.environ["JIANYAN_DEBUG_PAUSE"] = "1"


def _log_hint() -> str:
    if getattr(sys, "frozen", False):
        try:
            return str(get_log_dir() / "run.log")
        except Exception:
            return "run.log"
    return str(Path("run.log").resolve())


def _fatal(title: str, message: str) -> None:
    alert(title, f"{message}\n\n日志文件：{_log_hint()}", force_message_box=True)
    if is_pause_on_exit_enabled():
        pause()


def _select_writable_cache_dir(configured: str) -> Path:
    if configured:
        candidate = Path(configured)
        if is_writable_dir(candidate):
            return candidate
    return get_model_cache_dir()


def main() -> None:
    # 单实例守护：若已有实例，唤醒旧实例并退出
    def _wakeup_notice() -> None:
        notify("应用已在运行", "请在系统托盘使用现有实例")

    guard = SingleInstanceGuard(
        name="JianYan_SingleInstance",
        message_name="JianYan_Wakeup_Message",
        on_wakeup=_wakeup_notice,
    )
    if guard.already_running:
        guard.notify_existing()
        return
    guard.start_wakeup_listener()

    try:
        config = load_config()
    except PathAccessError as exc:
        _fatal("配置目录不可用", str(exc))
        return

    # MODELSCOPE_CACHE 仅用于 funasr 可能的缓存/下载；必须保证可写。
    cache_dir = _select_writable_cache_dir(config.model_cache_dir)
    os.environ["MODELSCOPE_CACHE"] = str(cache_dir)

    state = AppState(config=config, model_ready=False)

    from api.stt import preload_model
    from tray.tray_app import run_tray
    from ui.startup_win32 import show_startup_progress

    ok, error = show_startup_progress(lambda: preload_model(config), estimate_seconds=120)
    if not ok:
        err = error or "未知错误"
        _fatal(
            "模型加载失败",
            err
            + "\n\n如果你是首次安装：请使用 full 安装包（包含离线模型）。\n"
            "如果你已下载过模型：请在“设置-模型缓存目录”指向 ModelScope 缓存目录。",
        )
        return

    state.model_ready = True
    run_tray(state)


if __name__ == "__main__":
    _bootstrap_debug_flags(sys.argv[1:])
    if os.environ.get("JIANYAN_DEBUG_CONSOLE", "").strip() == "1":
        enable_debug_console()

    setup_logging()
    install_exception_hooks()
    logging.info(
        "[Env] frozen=%s exe=%s cwd=%s",
        getattr(sys, "frozen", False),
        sys.executable,
        os.getcwd(),
    )
    logging.info("[Env] argv=%s", sys.argv)

    try:
        main()
    except Exception as exc:
        logging.exception("[Fatal] 未处理异常")
        _fatal("启动失败", f"发生未处理异常：{exc}")
