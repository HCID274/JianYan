from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path


def _get_app_root() -> Path:
    """获取应用根目录，兼容打包和开发环境"""
    if getattr(sys, 'frozen', False):
        # PyInstaller 打包后，使用 EXE 所在目录
        return Path(sys.executable).parent
    else:
        # 开发环境，使用源码目录
        return Path(__file__).resolve().parents[1]


APP_ROOT = _get_app_root()


class PathAccessError(RuntimeError):
    pass


APP_DIR_NAME = "Jianyan"


def _fallback_roaming() -> Path:
    return Path.home() / "AppData" / "Roaming"


def _fallback_local() -> Path:
    return Path.home() / "AppData" / "Local"


def get_roaming_root() -> Path:
    """每用户可写配置根目录（Roaming）。"""
    base = os.environ.get("APPDATA")
    return (Path(base) if base else _fallback_roaming()) / APP_DIR_NAME


def get_local_root() -> Path:
    """每用户可写缓存根目录（Local）。"""
    base = os.environ.get("LOCALAPPDATA")
    return (Path(base) if base else _fallback_local()) / APP_DIR_NAME


def is_writable_dir(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=path, delete=True):
            return True
    except Exception:
        return False


def require_writable_dir(path: Path, label: str) -> Path:
    if is_writable_dir(path):
        return path
    raise PathAccessError(
        f"{label} 目录不可写：{path}"
    )


def get_data_dir() -> Path:
    if getattr(sys, "frozen", False):
        # 安装版：放到 Roaming，避免安装目录权限问题（安装版常在只读位置）。
        return require_writable_dir(get_roaming_root() / "data", "数据")
    # 开发环境：保留项目内 data/，便于调试与迁移（符合仓库约定）。
    return require_writable_dir(APP_ROOT / "data", "数据")


def get_model_cache_dir() -> Path:
    if getattr(sys, "frozen", False):
        # 安装版：缓存/下载目录放到 Local，便于写入与体积较大数据管理。
        return require_writable_dir(get_local_root() / "model_cache", "模型缓存")
    return require_writable_dir(APP_ROOT / "models", "模型缓存")


def get_temp_dir() -> Path:
    if getattr(sys, "frozen", False):
        return require_writable_dir(get_local_root() / "temp", "临时文件")
    return require_writable_dir(APP_ROOT / "temp", "临时文件")


def get_log_dir() -> Path:
    if getattr(sys, "frozen", False):
        return require_writable_dir(get_local_root() / "logs", "日志")
    return require_writable_dir(APP_ROOT / "logs", "日志")


def get_bundled_models_dir() -> Path:
    """安装目录内随包携带的模型目录（可能只读）。"""
    return APP_ROOT / "models"


def ensure_dir_exists(path: Path, label: str) -> Path:
    """确保目录存在（不强制要求可写，用于“仅作为读取/搜索路径”的场景）。"""
    try:
        path.mkdir(parents=True, exist_ok=True)
        return path
    except Exception as exc:
        raise PathAccessError(f"{label} 目录不可访问：{path} ({exc})") from exc
