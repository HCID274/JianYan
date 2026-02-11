from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from utils.paths import ensure_dir_exists, get_data_dir, get_model_cache_dir, get_temp_dir, require_writable_dir


def _get_config_path() -> Path:
    return get_data_dir() / "config.json"


@dataclass
class AppConfig:
    hotkey: str = "ctrl+shift+space"
    max_seconds: int = 300
    temp_dir: str = ""
    model_cache_dir: str = ""
    openai_api_key: str = ""
    openai_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    qwen_model: str = "qwen-flash"
    suppress_missing_llm_prompt: bool = False
    show_hotkey_hint_on_startup: bool = True
    update_manifest_urls: str = ""


def load_config() -> AppConfig:
    config_path = _get_config_path()
    if not config_path.exists():
        config = AppConfig()
        save_config(config)
        return config

    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        # 配置文件损坏时不要直接崩溃：备份后回退到默认值
        ts = time.strftime("%Y%m%d_%H%M%S", time.localtime())
        backup = config_path.with_name(f"config.corrupt.{ts}.json")
        try:
            config_path.replace(backup)
        except Exception:
            pass
        config = AppConfig()
        save_config(config)
        return config

    if not isinstance(data, dict):
        data = {}

    valid_keys = {f.name for f in fields(AppConfig)}
    filtered = {k: v for k, v in data.items() if k in valid_keys}
    config = AppConfig(**filtered)
    config = _coerce_config(config)
    config.temp_dir = _resolve_dir(config.temp_dir, get_temp_dir(), "临时文件", require_writable=True)
    config.model_cache_dir = _resolve_dir(config.model_cache_dir, get_model_cache_dir(), "模型缓存", require_writable=False)
    return config


def _coerce_config(config: AppConfig) -> AppConfig:
    def _as_str(v: object, default: str) -> str:
        if v is None:
            return default
        if isinstance(v, str):
            return v
        return str(v)

    def _as_int(v: object, default: int) -> int:
        if isinstance(v, bool) or v is None:
            return default
        if isinstance(v, int):
            return v
        try:
            return int(str(v).strip())
        except Exception:
            return default

    def _as_bool(v: object, default: bool) -> bool:
        if isinstance(v, bool):
            return v
        if isinstance(v, (int, float)):
            return bool(v)
        if isinstance(v, str):
            s = v.strip().lower()
            if s in {"1", "true", "yes", "y", "on"}:
                return True
            if s in {"0", "false", "no", "n", "off"}:
                return False
        return default

    max_seconds = _as_int(config.max_seconds, 300)
    if max_seconds <= 0:
        max_seconds = 300
    # 防止异常配置导致资源占用异常；仍保留较大的上限以满足重度用户
    max_seconds = min(max_seconds, 60 * 60)

    return AppConfig(
        hotkey=_as_str(config.hotkey, "ctrl+shift+space").strip() or "ctrl+shift+space",
        max_seconds=max_seconds,
        temp_dir=_as_str(config.temp_dir, ""),
        model_cache_dir=_as_str(config.model_cache_dir, ""),
        openai_api_key=_as_str(config.openai_api_key, ""),
        openai_base_url=_as_str(config.openai_base_url, "https://dashscope.aliyuncs.com/compatible-mode/v1").strip()
        or "https://dashscope.aliyuncs.com/compatible-mode/v1",
        qwen_model=_as_str(config.qwen_model, "qwen-flash").strip() or "qwen-flash",
        suppress_missing_llm_prompt=_as_bool(config.suppress_missing_llm_prompt, False),
        show_hotkey_hint_on_startup=_as_bool(getattr(config, "show_hotkey_hint_on_startup", True), True),
        update_manifest_urls=_as_str(getattr(config, "update_manifest_urls", ""), "").strip(),
    )


def _resolve_dir(value: str, fallback: Path, label: str, *, require_writable: bool) -> str:
    if not value:
        return str(fallback)
    path = Path(value)
    if not path.is_absolute():
        path = fallback.parent / path
    if require_writable:
        require_writable_dir(path, label)
    else:
        ensure_dir_exists(path, label)
    return str(path)


def save_config(config: AppConfig) -> None:
    config_path = _get_config_path()
    tmp = config_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(asdict(config), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(config_path)
