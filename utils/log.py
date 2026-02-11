from __future__ import annotations

import logging
import sys
import tempfile
from pathlib import Path

from utils.paths import get_log_dir


def setup_logging() -> None:
    log_file = _pick_log_file()

    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if log_file is not None:
        try:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            handlers.append(logging.FileHandler(log_file, encoding="utf-8-sig"))
        except Exception:
            # 如果没权限写文件，至少保留控制台输出（windowed exe 下可能看不到，但不应崩溃）。
            pass

    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(levelname)s %(message)s",
        handlers=handlers,
        force=True,
    )


def _pick_log_file() -> Path | None:
    """选择一个最可能可写的日志路径。

    重要：这里必须做到“永不抛异常”，否则 windowed 程序会在启动阶段直接无声退出。
    """
    candidates: list[Path] = []

    if getattr(sys, "frozen", False):
        # 1) 首选 AppData（稳定可写）
        try:
            candidates.append(get_log_dir() / "run.log")
        except Exception:
            pass

        # 2) 备用：系统临时目录
        try:
            candidates.append(Path(tempfile.gettempdir()) / "Jianyan" / "run.log")
        except Exception:
            pass

        # 3) 最后：exe 同级目录（可能只读，但也许用户安装在可写盘）
        try:
            candidates.append(Path(sys.executable).resolve().parent / "run.log")
        except Exception:
            pass
    else:
        # 开发环境：保留项目目录的 run.log，方便直接查看。
        candidates.append(Path("run.log"))

    for p in candidates:
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            # 轻量写入测试
            with p.open("a", encoding="utf-8") as f:
                f.write("")
            return p
        except Exception:
            continue

    return None
