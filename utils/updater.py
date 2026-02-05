from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

import httpx

from app.version import __version__
from utils.paths import APP_ROOT, get_data_dir


DEFAULT_MANIFEST_URLS = (
    "https://happyhappyhappy.hcid274.xyz/downloads/latest.json",
    "https://jianyan.hcid274.xyz/downloads/latest.json",
    "https://github.com/HCID274/JianYan/releases/latest/download/latest.json",
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _parse_version(v: str) -> tuple[int, int, int]:
    parts = v.strip().split(".")
    if len(parts) != 3:
        raise ValueError(f"Invalid version: {v!r}")
    return int(parts[0]), int(parts[1]), int(parts[2])


def is_newer_version(latest: str, current: str) -> bool:
    try:
        return _parse_version(latest) > _parse_version(current)
    except Exception:
        return latest.strip() != current.strip()


@dataclass(frozen=True)
class PackageInfo:
    sha256: str
    urls: tuple[str, ...]
    size: int | None = None


@dataclass(frozen=True)
class UpdateInfo:
    version: str
    notes: str
    update_pkg: PackageInfo
    full_pkg: PackageInfo


@dataclass
class UpdateState:
    last_checked_at: str | None = None
    remind_at: str | None = None
    skip_version: str | None = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_iso(ts: str) -> float:
    # Zulu time or offset.
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    return datetime.fromisoformat(ts).timestamp()


def _state_path() -> Path:
    return get_data_dir() / "update_state.json"


def load_update_state() -> UpdateState:
    path = _state_path()
    if not path.exists():
        return UpdateState()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return UpdateState(
            last_checked_at=data.get("last_checked_at"),
            remind_at=data.get("remind_at"),
            skip_version=data.get("skip_version"),
        )
    except Exception:
        logging.exception("[Updater] 读取 update_state.json 失败，已忽略")
        return UpdateState()


def save_update_state(state: UpdateState) -> None:
    path = _state_path()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(
            {
                "last_checked_at": state.last_checked_at,
                "remind_at": state.remind_at,
                "skip_version": state.skip_version,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def _manifest_urls_from_env() -> Optional[tuple[str, ...]]:
    raw = os.environ.get("JIANYAN_UPDATE_MANIFEST_URLS", "").strip()
    if not raw:
        return None
    parts = [p.strip() for p in raw.split(";") if p.strip()]
    return tuple(parts) if parts else None


def _is_https_url(url: str) -> bool:
    try:
        p = urlparse(url)
    except Exception:
        return False
    return p.scheme.lower() == "https" and bool(p.netloc)


def _ensure_https_response(resp: httpx.Response) -> None:
    # follow_redirects=True 时 resp.history 里包含重定向链
    chain = list(resp.history) + [resp]
    for r in chain:
        try:
            if r.url.scheme.lower() != "https":
                raise RuntimeError(f"Redirected to non-https URL: {r.url!s}")
        except Exception as e:
            raise RuntimeError("Invalid redirect URL") from e


def _http_timeout(connect_s: float, read_s: float) -> httpx.Timeout:
    # read timeout 为“单次读操作”超时：大文件下载只要持续有数据流入就不会触发
    return httpx.Timeout(connect=connect_s, read=read_s, write=read_s, pool=connect_s)


def _load_manifest(url: str, timeout_s: float = 6.0) -> dict[str, Any]:
    if not _is_https_url(url):
        raise ValueError(f"Manifest URL must be https: {url!r}")
    with httpx.Client(follow_redirects=True, timeout=_http_timeout(timeout_s, timeout_s)) as client:
        r = client.get(url, headers={"Cache-Control": "no-cache"})
        _ensure_https_response(r)
        r.raise_for_status()
        return r.json()


def fetch_latest_update_info() -> Optional[UpdateInfo]:
    urls = _manifest_urls_from_env() or DEFAULT_MANIFEST_URLS
    last_err: Exception | None = None
    for url in urls:
        try:
            data = _load_manifest(url)
            latest = str(data.get("version", "")).strip()
            if not latest:
                raise ValueError("manifest missing version")

            # Support both schemas:
            # - v1: {"packages": {"update": {"sha256","size","urls":[...]}, "full": {...}}}
            # - v2: {"files": {"update": {"sha256","size","url"}, "full": {...}}}
            pkgs = data.get("packages") or {}
            files = data.get("files") or {}

            if pkgs:
                update_pkg = pkgs.get("update") or {}
                full_pkg = pkgs.get("full") or {}
                update_urls = tuple(update_pkg.get("urls") or ())
                full_urls = tuple(full_pkg.get("urls") or ())
            elif files:
                update_pkg = files.get("update") or {}
                full_pkg = files.get("full") or {}
                update_urls = tuple(update_pkg.get("urls") or ()) or (
                    (str(update_pkg.get("url")).strip(),) if str(update_pkg.get("url") or "").strip() else ()
                )
                full_urls = tuple(full_pkg.get("urls") or ()) or (
                    (str(full_pkg.get("url")).strip(),) if str(full_pkg.get("url") or "").strip() else ()
                )
            else:
                raise ValueError("manifest missing packages/files")

            info = UpdateInfo(
                version=latest,
                notes=str(data.get("notes") or "").strip(),
                update_pkg=PackageInfo(
                    sha256=str(update_pkg.get("sha256") or "").lower(),
                    urls=update_urls,
                    size=update_pkg.get("size"),
                ),
                full_pkg=PackageInfo(
                    sha256=str(full_pkg.get("sha256") or "").lower(),
                    urls=full_urls,
                    size=full_pkg.get("size"),
                ),
            )
            if not info.update_pkg.sha256 or not info.update_pkg.urls:
                raise ValueError("manifest missing update package fields")
            if not info.full_pkg.sha256 or not info.full_pkg.urls:
                raise ValueError("manifest missing full package fields")
            return info
        except Exception as exc:
            last_err = exc
            logging.warning("[Updater] 拉取 manifest 失败: %s (%s)", url, exc)
            continue
    if last_err:
        logging.info("[Updater] 所有更新源均不可用（最后错误: %s）", last_err)
    return None


def should_prompt_update(info: UpdateInfo, state: UpdateState, *, force_prompt: bool) -> bool:
    if not is_newer_version(info.version, __version__):
        return False

    if force_prompt:
        return True

    if state.skip_version and not is_newer_version(info.version, state.skip_version):
        return False

    if state.remind_at:
        try:
            if time.time() < _parse_iso(state.remind_at):
                return False
        except Exception:
            pass

    return True


def _download_with_sha256(url: str, dest: Path, expected_sha256: str, expected_size: int | None = None) -> None:
    expected = expected_sha256.lower().strip()
    if not _SHA256_RE.match(expected):
        raise RuntimeError(f"Invalid sha256: {expected_sha256!r}")
    if not _is_https_url(url):
        raise RuntimeError(f"Download URL must be https: {url!r}")

    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".tmp")
    h = hashlib.sha256()
    written = 0

    with httpx.Client(follow_redirects=True, timeout=_http_timeout(10.0, 60.0)) as client:
        with client.stream("GET", url) as r:
            _ensure_https_response(r)
            r.raise_for_status()
            with tmp.open("wb") as f:
                for chunk in r.iter_bytes(chunk_size=1024 * 1024):
                    if not chunk:
                        continue
                    f.write(chunk)
                    written += len(chunk)
                    h.update(chunk)

    got = h.hexdigest().lower()

    if expected_size is not None and written != int(expected_size):
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        raise RuntimeError(f"Size mismatch: expected {expected_size}, got {written}")

    if got != expected:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        raise RuntimeError(f"SHA256 mismatch: expected {expected}, got {got}")

    tmp.replace(dest)


def download_package(pkg: PackageInfo, version: str, kind: str) -> Path:
    temp_root = Path(tempfile.gettempdir()) / "JianyanUpdate"
    dest = temp_root / f"JianyanSetup_{kind}_{version}.exe"
    last_err: Exception | None = None
    for url in pkg.urls:
        try:
            logging.info("[Updater] 下载更新包: %s", url)
            _download_with_sha256(url, dest, pkg.sha256, pkg.size)
            return dest
        except Exception as exc:
            last_err = exc
            logging.warning("[Updater] 下载失败: %s (%s)", url, exc)
            continue
    raise RuntimeError(f"All download urls failed: {last_err}")


def launch_silent_installer(installer_path: Path) -> None:
    if not getattr(sys, "frozen", False):
        raise RuntimeError("只能在打包后的程序中执行一键更新（开发环境已禁止）")

    app_dir = str(APP_ROOT)
    log_path = str(get_data_dir() / "installer_update.log")
    args = [
        str(installer_path),
        "/SP-",
        "/VERYSILENT",
        "/NORESTART",
        "/SUPPRESSMSGBOXES",
        f'/DIR="{app_dir}"',
        f'/LOG="{log_path}"',
    ]
    logging.info("[Updater] 启动安装包: %s", " ".join(args))
    subprocess.Popen(args, close_fds=True)
