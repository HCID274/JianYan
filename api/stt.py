from __future__ import annotations

import os
import re
import threading
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Optional

import numpy as np
import soundfile as sf

try:
    from funasr import AutoModel
    from funasr.utils.postprocess_utils import rich_transcription_postprocess
except Exception:  # pragma: no cover - optional dependency
    AutoModel = None
    rich_transcription_postprocess = None

from utils.config import AppConfig
from utils.paths import get_bundled_models_dir, get_model_cache_dir


@dataclass
class LocalModelConfig:
    model: str = "iic/SenseVoiceSmall"
    vad_model: str = "fsmn-vad"
    punc_model: str = "ct-punc"


_MODEL_LOCK = threading.Lock()
_MODEL: Optional[AutoModel] = None
_MODEL_CACHE_KEY: str | None = None


def transcribe_audio(audio_bytes: bytes | None, temp_path: str | None, config: AppConfig) -> str:
    if audio_bytes is None and temp_path is None:
        raise ValueError("audio_bytes and temp_path are both None")
    if rich_transcription_postprocess is None:
        raise RuntimeError("未安装 funasr，请先安装本地模型依赖")

    wav_bytes = _load_bytes(audio_bytes, temp_path)
    if not wav_bytes:
        return ""

    audio, sample_rate = sf.read(BytesIO(wav_bytes), dtype="float32")
    if sample_rate != 16000:
        raise RuntimeError("录音采样率必须是 16kHz")

    if audio.ndim > 1:
        audio = np.mean(audio, axis=1)

    model = _get_model(config)
    result = model.generate(
        input=audio,
        language="auto",
        use_itn=True,
        batch_size_s=60,
        merge_vad=True,
        merge_length_s=15,
    )
    text = result[0].get("text", "") if result else ""
    return _clean_transcript(rich_transcription_postprocess(text))


def preload_model(config: AppConfig) -> None:
    _get_model(config)


def _load_bytes(audio_bytes: bytes | None, temp_path: str | None) -> bytes:
    if temp_path:
        with open(temp_path, "rb") as f:
            return f.read()
    return audio_bytes or b""


def _get_local_model_paths(config: AppConfig) -> dict[str, str | None]:
    """检测本地是否已下载所有模型，返回各模型的本地路径。

    兼容以下来源：
    - 应用配置的 `model_cache_dir`（以及其下的常见 ModelScope 缓存布局）
    - 用户目录默认 ModelScope 缓存：`%USERPROFILE%\\.cache\\modelscope\\hub\\models\\...`

    说明：打包版通常不包含 `modelscope` 包，因此必须尽量走“本地路径加载”，避免触发在线下载逻辑。
    """

    def _existing_model_dir(candidate: Path) -> Path | None:
        if candidate.exists() and (candidate / "model.pt").exists():
            return candidate
        return None

    def _candidate_roots() -> list[Path]:
        roots: list[Path] = []

        # 1) 配置目录（用户自定义；可能是只读的“安装包内模型目录”）
        if config.model_cache_dir:
            roots.append(Path(config.model_cache_dir))

        # 2) 安装包内随带模型（可能只读，但可用于加载）
        roots.append(get_bundled_models_dir())

        # 3) 环境变量（可能由 app/main.py 设置）
        env_cache = os.environ.get("MODELSCOPE_CACHE")
        if env_cache:
            roots.append(Path(env_cache))

        # 4) 默认可写缓存目录（用于下载/解压/缓存）
        roots.append(get_model_cache_dir())

        # 5) 用户目录默认缓存（通常已存在）
        roots.append(Path.home() / ".cache" / "modelscope")

        # 去重 + 过滤空
        seen: set[str] = set()
        uniq: list[Path] = []
        for r in roots:
            s = str(r.resolve()) if r.exists() else str(r)
            if s in seen:
                continue
            seen.add(s)
            uniq.append(r)
        return uniq

    def _candidate_iic_bases(root: Path) -> list[Path]:
        # 常见布局：
        # - <root>/hub/models/iic/<ModelName>
        # - <root>/models/iic/<ModelName>            (某些自定义方式)
        # - <root>/models/models/iic/<ModelName>     (历史遗留)
        # - <root>/iic/<ModelName>                   (手动平铺)
        return [
            root / "hub" / "models" / "iic",
            root / "models" / "iic",
            root / "models" / "models" / "iic",
            root / "iic",
        ]

    def _find_first(names: list[str]) -> Path | None:
        for root in _candidate_roots():
            for base in _candidate_iic_bases(root):
                for name in names:
                    found = _existing_model_dir(base / name)
                    if found:
                        return found
            # 同时支持“直接在 root 下放模型目录”的情况
            for name in names:
                found = _existing_model_dir(root / name)
                if found:
                    return found
        return None

    paths: dict[str, str | None] = {"model": None, "vad_model": None, "punc_model": None}

    sense_dir = _find_first(["SenseVoiceSmall"])
    if sense_dir:
        paths["model"] = str(sense_dir)

    vad_dir = _find_first(["speech_fsmn_vad_zh-cn-16k-common-pytorch", "fsmn-vad"])
    if vad_dir:
        paths["vad_model"] = str(vad_dir)

    punc_dir = _find_first(["punc_ct-transformer_cn-en-common-vocab471067-large", "ct-punc"])
    if punc_dir:
        paths["punc_model"] = str(punc_dir)

    return paths


def _get_model(config: AppConfig) -> AutoModel:
    global _MODEL
    global _MODEL_CACHE_KEY
    if AutoModel is None:
        raise RuntimeError("未安装 funasr，请先安装本地模型依赖")

    cache_key = config.model_cache_dir or ""
    if _MODEL is not None and _MODEL_CACHE_KEY is not None and _MODEL_CACHE_KEY != cache_key:
        # 配置变更时重载（例如用户在设置中修改了模型目录）
        _MODEL = None
        _MODEL_CACHE_KEY = None

    if _MODEL is None:
        with _MODEL_LOCK:
            if _MODEL is None:
                model_cfg = LocalModelConfig()
                local_paths = _get_local_model_paths(config)

                model_path = local_paths["model"]
                vad_path = local_paths["vad_model"]
                punc_path = local_paths["punc_model"]

                # 若缺失本地模型：
                # - 开发环境可依赖 modelscope 自动下载
                # - 打包版通常不包含 modelscope，应给出明确提示
                if not model_path or not vad_path or not punc_path:
                    try:
                        import modelscope  # noqa: F401
                        allow_download = True
                    except Exception:
                        allow_download = False

                    if allow_download:
                        model_path = model_path or model_cfg.model
                        vad_path = vad_path or model_cfg.vad_model
                        punc_path = punc_path or model_cfg.punc_model
                    else:
                        missing = []
                        if not model_path:
                            missing.append("SenseVoiceSmall")
                        if not vad_path:
                            missing.append("VAD(fsmn-vad)")
                        if not punc_path:
                            missing.append("标点(ct-punc)")
                        raise RuntimeError(
                            "本地模型未就绪（缺少: "
                            + ", ".join(missing)
                            + "）。请先在开发环境运行 `python scripts/predownload_models.py` 下载模型，"
                            "或将已下载的 ModelScope 缓存目录复制到“设置-模型缓存目录”。"
                        )

                _MODEL = AutoModel(
                    model=model_path,
                    vad_model=vad_path,
                    vad_kwargs={"max_single_segment_time": 30000},
                    punc_model=punc_path,
                    device=_detect_device(),
                    disable_pbar=True,
                    disable_update=True,  # 禁用更新检查
                    check_latest=False,  # 禁止联网检查模型更新
                )
                _MODEL_CACHE_KEY = cache_key
    return _MODEL


def _detect_device() -> str:
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda:0"
    except Exception:
        return "cpu"
    return "cpu"


def _clean_transcript(text: str) -> str:
    if not text:
        return ""
    # 兼容两种标记格式: "<| zh |>" 和 "<|zh|>"
    text = re.sub(r"<\s*\|\s*[^|]+?\s*\|\s*>", "", text)
    text = re.sub(r"<\|\s*[^|]+?\s*\|>", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()
