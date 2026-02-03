from __future__ import annotations

import argparse
import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ModelToBundle:
    name: str
    modelscope_dir_name: str


MODELS_TO_BUNDLE: tuple[ModelToBundle, ...] = (
    ModelToBundle(name="SenseVoiceSmall", modelscope_dir_name="SenseVoiceSmall"),
    ModelToBundle(
        name="speech_fsmn_vad_zh-cn-16k-common-pytorch",
        modelscope_dir_name="speech_fsmn_vad_zh-cn-16k-common-pytorch",
    ),
    ModelToBundle(
        name="punc_ct-transformer_cn-en-common-vocab471067-large",
        modelscope_dir_name="punc_ct-transformer_cn-en-common-vocab471067-large",
    ),
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _default_modelscope_cache() -> Path:
    # ModelScope 默认缓存路径（Windows/跨平台一般都在 ~/.cache/modelscope）
    return Path.home() / ".cache" / "modelscope" / "hub" / "models" / "iic"


def _bundled_models_iic_dir(repo_root: Path) -> Path:
    # 约定：把要打进安装包的模型放到 repo/models/hub/models/iic/...
    return repo_root / "models" / "hub" / "models" / "iic"


def _ensure_model_ready(path: Path, label: str) -> None:
    if not path.exists():
        raise SystemExit(f"[ERROR] 未找到模型目录: {label}: {path}")
    if not (path / "model.pt").exists():
        raise SystemExit(f"[ERROR] 模型目录缺少 model.pt: {label}: {path}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Copy ModelScope cached models into repo/models for bundling.")
    parser.add_argument(
        "--source-iic-dir",
        type=Path,
        default=None,
        help="Override source iic directory (default: ~/.cache/modelscope/hub/models/iic)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only verify and print copy plan; do not copy files.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    repo_root = _repo_root()

    # 优先使用用户指定；其次使用 MODELSCOPE_CACHE；最后回退到默认路径
    env_cache = None
    try:
        import os

        env_cache = os.environ.get("MODELSCOPE_CACHE")
    except Exception:
        env_cache = None

    if args.source_iic_dir is not None:
        source_iic_dir = args.source_iic_dir
    elif env_cache:
        source_iic_dir = Path(env_cache) / "hub" / "models" / "iic"
    else:
        source_iic_dir = _default_modelscope_cache()

    dest_iic_dir = _bundled_models_iic_dir(repo_root)

    print("========================================")
    print("  Prepare Models For Installer")
    print("========================================")
    print(f"[INFO] Repo root: {repo_root}")
    print(f"[INFO] Source (ModelScope cache): {source_iic_dir}")
    print(f"[INFO] Dest (to be bundled): {dest_iic_dir}")
    print()

    if not source_iic_dir.exists():
        raise SystemExit(
            "[ERROR] 未找到 ModelScope 缓存目录。\n"
            "请先运行一次 `python scripts/predownload_models.py` 下载模型，\n"
            "或确认模型已存在于: ~/.cache/modelscope/hub/models/iic/"
        )

    if not args.dry_run:
        dest_iic_dir.mkdir(parents=True, exist_ok=True)

    for m in MODELS_TO_BUNDLE:
        src = source_iic_dir / m.modelscope_dir_name
        _ensure_model_ready(src, m.name)
        dst = dest_iic_dir / m.modelscope_dir_name
        print(f"[COPY] {m.name}")
        print(f"  from: {src}")
        print(f"  to  : {dst}")
        if not args.dry_run:
            shutil.copytree(src, dst, dirs_exist_ok=True)

    print()
    if args.dry_run:
        print("[OK] Dry-run 完成：模型检查通过。")
    else:
        print("[OK] 模型已准备完成，可直接执行 build.cmd 生成包含模型的安装包。")


if __name__ == "__main__":
    main()
