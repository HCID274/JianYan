from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


INNO_VERSION_PREFIX = '#define MyAppVersion "'


@dataclass(frozen=True)
class Package:
    kind: str  # "full" | "update"
    path: Path


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_version_from_issinc(path: Path) -> str:
    text = path.read_text(encoding="utf-8", errors="strict")
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith(INNO_VERSION_PREFIX):
            continue
        v = line.removeprefix(INNO_VERSION_PREFIX)
        if not v.endswith('"'):
            continue
        return v[:-1]
    raise SystemExit(f"[ERROR] Cannot find MyAppVersion in: {path}")


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Generate latest.json for in-app updater.")
    p.add_argument("--version", default=None, help="Override version (default: read installer/version.issinc)")
    p.add_argument("--output", type=Path, default=Path("installer") / "output" / "latest.json")
    p.add_argument(
        "--base-url",
        default="https://happyhappyhappy.hcid274.xyz/downloads",
        help="Download base URL for your own site.",
    )
    p.add_argument(
        "--github-repo",
        default="HCID274/JianYan",
        help="GitHub repo in owner/name form.",
    )
    p.add_argument(
        "--github-tag-prefix",
        default="v",
        help="Tag prefix for GitHub releases, e.g. v0.1.12 (default: v).",
    )
    p.add_argument("--notes", default="", help="Optional release notes string to embed.")
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    version = args.version or _read_version_from_issinc(Path("installer") / "version.issinc")

    output_path: Path = args.output
    output_path.parent.mkdir(parents=True, exist_ok=True)

    full_path = Path("installer") / "output" / f"JianyanSetup_full_{version}.exe"
    update_path = Path("installer") / "output" / f"JianyanSetup_update_{version}.exe"
    packages = [
        Package("update", update_path),
        Package("full", full_path),
    ]

    for pkg in packages:
        if not pkg.path.exists():
            raise SystemExit(f"[ERROR] Missing installer: {pkg.path}")

    published_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    github_tag = f"{args.github_tag_prefix}{version}"

    manifest = {
        "app": "Jianyan",
        "channel": "stable",
        "version": version,
        "published_at": published_at,
        "notes": args.notes,
        "packages": {
            "update": {
                "sha256": _sha256(update_path),
                "size": update_path.stat().st_size,
                "urls": [
                    f"{args.base_url}/JianyanSetup_update_{version}.exe",
                    f"https://github.com/{args.github_repo}/releases/download/{github_tag}/JianyanSetup_update_{version}.exe",
                ],
            },
            "full": {
                "sha256": _sha256(full_path),
                "size": full_path.stat().st_size,
                "urls": [
                    f"{args.base_url}/JianyanSetup_full_{version}.exe",
                    f"https://github.com/{args.github_repo}/releases/download/{github_tag}/JianyanSetup_full_{version}.exe",
                ],
            },
        },
        "min_supported_version": "0.0.0",
    }

    output_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(str(output_path))


if __name__ == "__main__":
    main()
