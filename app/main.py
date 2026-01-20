from __future__ import annotations

import os

from app.state import AppState
from utils.config import load_config
from utils.log import setup_logging
from utils.notify import notify
from utils.paths import PathAccessError
from utils.single_instance import SingleInstanceGuard


def main() -> None:
    setup_logging()
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
        notify("安装目录不可写", str(exc))
        return
    if config.model_cache_dir:
        os.environ["MODELSCOPE_CACHE"] = config.model_cache_dir
    state = AppState(config=config, model_ready=False)

    from api.stt import preload_model
    from tray.tray_app import run_tray
    from ui.startup_win32 import show_startup_progress

    ok, error = show_startup_progress(preload_model, estimate_seconds=120)
    if not ok:
        notify("模型加载失败", error or "未知错误")
        return

    state.model_ready = True
    run_tray(state)


if __name__ == "__main__":
    main()
