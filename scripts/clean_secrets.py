from __future__ import annotations

import json
from pathlib import Path


def _sanitize_config(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False

    changed = False
    if isinstance(data, dict) and "openai_api_key" in data and data["openai_api_key"]:
        data["openai_api_key"] = ""
        changed = True

    if changed:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return changed


def _delete_if_exists(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        path.unlink()
        return True
    except Exception:
        return False


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]

    targets = [
        repo_root / "data" / "config.json",
        repo_root / "dist" / "Jianyan" / "data" / "config.json",
        repo_root / "dist" / "Jianyan" / "_internal" / "data" / "config.json",
    ]

    any_changed = False
    for p in targets:
        if _sanitize_config(p):
            print(f"[CLEAN] sanitized: {p}")
            any_changed = True

    # Optional: remove local run logs from repo/dist
    log_targets = [
        repo_root / "run.log",
        repo_root / "dist" / "Jianyan" / "run.log",
    ]
    for p in log_targets:
        if _delete_if_exists(p):
            print(f"[CLEAN] deleted: {p}")
            any_changed = True

    if not any_changed:
        print("[CLEAN] nothing to do")


if __name__ == "__main__":
    main()

