from __future__ import annotations

import argparse
import hashlib
import math
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any, Iterable, Optional

import httpx


@dataclass(frozen=True)
class PackageInfo:
    filename: str
    path: Path
    size: int
    sha256: str


def _parse_csv(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


def _sha256_file(path: Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            buf = f.read(chunk_size)
            if not buf:
                break
            h.update(buf)
    return h.hexdigest()


def _http_json(
    client: httpx.Client,
    method: str,
    url: str,
    *,
    params: Optional[dict[str, Any]] = None,
    json_body: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    resp = client.request(method, url, params=params, json=json_body)
    if resp.status_code >= 400:
        raise RuntimeError(f"HTTP {resp.status_code} {method} {url}: {resp.text[:500]}")
    try:
        return resp.json()
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"Invalid JSON from {method} {url}: {resp.text[:500]}") from e


def _choose_base_url(base_urls: list[str], index: int) -> str:
    if not base_urls:
        raise ValueError("base_urls is empty")
    return base_urls[index % len(base_urls)].rstrip("/")


def _upload_one_chunk(
    *,
    file_path: Path,
    upload_id: str,
    base_url: str,
    token: str,
    index: int,
    offset: int,
    length: int,
    timeout_s: float,
    verify_tls: bool,
    max_retries: int,
) -> int:
    url = f"{base_url}/api/upload/{upload_id}/chunk"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/octet-stream",
    }

    backoff_s = 1.0
    retries_used = 0
    for attempt in range(1, max_retries + 1):
        try:
            with file_path.open("rb") as f:
                f.seek(offset)
                data = f.read(length)
                if len(data) != length:
                    raise RuntimeError(
                        f"Failed to read chunk index={index}: expected {length} bytes, got {len(data)}"
                    )

            with httpx.Client(
                timeout=httpx.Timeout(timeout_s),
                verify=verify_tls,
                headers=headers,
            ) as client:
                resp = client.put(url, params={"index": index, "offset": offset}, content=data)

            if resp.status_code < 400:
                return retries_used

            if resp.status_code in (408, 425, 429) or 500 <= resp.status_code <= 599:
                # retryable
                retries_used += 1
                time.sleep(backoff_s)
                backoff_s = min(backoff_s * 2, 20.0)
                continue

            raise RuntimeError(f"Chunk upload failed HTTP {resp.status_code}: {resp.text[:500]}")
        except (httpx.TransportError, httpx.TimeoutException) as e:
            if attempt >= max_retries:
                raise RuntimeError(f"Chunk upload failed after retries: index={index}") from e
            retries_used += 1
            time.sleep(backoff_s)
            backoff_s = min(backoff_s * 2, 20.0)

    return retries_used


def _iter_chunk_plan(size: int, chunk_size: int) -> Iterable[tuple[int, int, int]]:
    total_chunks = math.ceil(size / chunk_size)
    for index in range(total_chunks):
        offset = index * chunk_size
        length = min(chunk_size, size - offset)
        yield index, offset, length


def upload_package(
    *,
    api_bases: list[str],
    token: str,
    package: PackageInfo,
    chunk_size: Optional[int],
    overwrite: bool,
    concurrency: Optional[int],
    timeout_s: float,
    verify_tls: bool,
    max_retries: int,
) -> PackageInfo:
    init_base = api_bases[0].rstrip("/")
    with httpx.Client(
        timeout=httpx.Timeout(timeout_s),
        verify=verify_tls,
        headers={"Authorization": f"Bearer {token}"},
    ) as client:
        init_url = f"{init_base}/api/upload/init"
        init_body: dict[str, Any] = {
            "filename": package.filename,
            "size": package.size,
            "sha256": package.sha256,
            "overwrite": overwrite,
        }
        if chunk_size:
            init_body["chunk_size"] = chunk_size

        init_resp = _http_json(client, "POST", init_url, json_body=init_body)

    upload_id = str(init_resp["upload_id"])
    server_chunk_size = int(init_resp["chunk_size"])
    server_max_concurrency = int(init_resp.get("max_concurrency") or 0)
    init_base_urls = init_resp.get("base_urls") or []
    if not isinstance(init_base_urls, list):
        init_base_urls = []
    base_urls = [str(u).rstrip("/") for u in init_base_urls if str(u).strip()]
    if not base_urls:
        base_urls = [b.rstrip("/") for b in api_bases]
    already_uploaded = set(int(i) for i in (init_resp.get("already_uploaded") or []))

    planned = list(_iter_chunk_plan(package.size, server_chunk_size))
    todo = [(i, o, length) for (i, o, length) in planned if i not in already_uploaded]

    effective_concurrency = concurrency or 0
    if effective_concurrency <= 0:
        effective_concurrency = min(8, (os.cpu_count() or 4))
    if server_max_concurrency > 0:
        effective_concurrency = min(effective_concurrency, server_max_concurrency)
    if effective_concurrency <= 0:
        effective_concurrency = 1

    if not todo:
        print(f"[upload] {package.filename}: resume hit, all chunks already uploaded.")
    else:
        total_chunks = len(planned)
        print(
            f"[upload] {package.filename}: upload_id={upload_id} chunk_size={server_chunk_size} "
            f"chunks={total_chunks} todo={len(todo)} concurrency={effective_concurrency}"
        )

        start = time.time()
        done = len(already_uploaded)
        retries_total = 0
        retries_lock = Lock()
        shard_counts: dict[str, int] = {}
        shard_lock = Lock()

        with ThreadPoolExecutor(max_workers=effective_concurrency) as pool:
            futures = []
            for index, offset, length in todo:
                base_url = _choose_base_url(base_urls, index)
                with shard_lock:
                    shard_counts[base_url] = shard_counts.get(base_url, 0) + 1
                futures.append(
                    pool.submit(
                        _upload_one_chunk,
                        file_path=package.path,
                        upload_id=upload_id,
                        base_url=base_url,
                        token=token,
                        index=index,
                        offset=offset,
                        length=length,
                        timeout_s=timeout_s,
                        verify_tls=verify_tls,
                        max_retries=max_retries,
                    )
                )

            for fut in as_completed(futures):
                used = int(fut.result())
                if used:
                    with retries_lock:
                        retries_total += used
                done += 1
                if done % 25 == 0 or done == total_chunks:
                    elapsed = max(time.time() - start, 0.001)
                    rate = (done * server_chunk_size) / elapsed
                    print(
                        f"[upload] {package.filename}: {done}/{total_chunks} chunks "
                        f"({rate / (1024 * 1024):.1f} MB/s)"
                    )

        elapsed = max(time.time() - start, 0.001)
        avg_rate = package.size / elapsed
        shard_summary = ", ".join(
            f"{k.split(':')[-1]}={v}" for k, v in sorted(shard_counts.items(), key=lambda x: x[0])
        )
        print(
            f"[upload] {package.filename}: shards({shard_summary}) retries={retries_total} "
            f"elapsed={elapsed:.1f}s avg={avg_rate / (1024 * 1024):.1f} MB/s"
        )

    complete_base = api_bases[0].rstrip("/")
    with httpx.Client(
        timeout=httpx.Timeout(timeout_s),
        verify=verify_tls,
        headers={"Authorization": f"Bearer {token}"},
    ) as client:
        complete_url = f"{complete_base}/api/upload/{upload_id}/complete"
        complete_resp = _http_json(client, "POST", complete_url)

    returned_filename = str(complete_resp["filename"])
    returned_size = int(complete_resp["size"])
    returned_sha256 = str(complete_resp["sha256"]).lower()

    if returned_filename != package.filename:
        raise RuntimeError(
            f"Complete filename mismatch: expected={package.filename} got={returned_filename}"
        )
    if returned_size != package.size:
        raise RuntimeError(f"Complete size mismatch: expected={package.size} got={returned_size}")
    if returned_sha256 != package.sha256:
        raise RuntimeError(
            f"Complete sha256 mismatch: expected={package.sha256} got={returned_sha256}"
        )

    print(f"[upload] {package.filename}: complete OK (sha256={returned_sha256[:12]}...)")
    return package


def publish_release(
    *,
    api_base: str,
    token: str,
    version: str,
    full_pkg: PackageInfo,
    update_pkg: PackageInfo,
    keep_versions: int,
    download_base_url: Optional[str],
    timeout_s: float,
    verify_tls: bool,
) -> dict[str, Any]:
    api_base = api_base.rstrip("/")
    body: dict[str, Any] = {
        "version": version,
        "packages": {
            "full": {"size": full_pkg.size, "sha256": full_pkg.sha256},
            "update": {"size": update_pkg.size, "sha256": update_pkg.sha256},
        },
        "keep_versions": keep_versions,
    }
    if download_base_url:
        body["base_url"] = download_base_url.rstrip("/")

    with httpx.Client(
        timeout=httpx.Timeout(timeout_s),
        verify=verify_tls,
        headers={"Authorization": f"Bearer {token}"},
    ) as client:
        resp = _http_json(client, "POST", f"{api_base}/api/release/publish", json_body=body)
    return resp


def _resolve_package(path: Path) -> PackageInfo:
    if not path.exists():
        raise FileNotFoundError(str(path))
    size = path.stat().st_size
    sha256 = _sha256_file(path).lower()
    return PackageInfo(filename=path.name, path=path, size=size, sha256=sha256)


def main() -> int:
    parser = argparse.ArgumentParser(description="Upload installers via chunked upload API and publish release.")
    parser.add_argument("--version", required=True, help="App version, e.g. 0.1.29")
    parser.add_argument(
        "--api-bases",
        default=os.environ.get("UPLOAD_API_BASES", ""),
        help="Comma-separated API base URLs, e.g. https://host:4443,https://host:4444",
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("UPLOAD_TOKEN", ""),
        help="Bearer token (or set UPLOAD_TOKEN env var).",
    )
    parser.add_argument(
        "--download-base-url",
        default=os.environ.get("DOWNLOAD_BASE_URL", ""),
        help="Base URL for downloads (optional, passed to publish).",
    )
    parser.add_argument("--keep-versions", type=int, default=int(os.environ.get("KEEP_VERSIONS", "3")))
    parser.add_argument("--chunk-mb", type=int, default=int(os.environ.get("CHUNK_MB", "0")))
    parser.add_argument("--concurrency", type=int, default=int(os.environ.get("CONCURRENCY", "0")))
    parser.add_argument("--overwrite", action="store_true", default=os.environ.get("OVERWRITE", "") == "1")
    parser.add_argument("--timeout", type=float, default=float(os.environ.get("UPLOAD_TIMEOUT", "60")))
    parser.add_argument("--retries", type=int, default=int(os.environ.get("UPLOAD_RETRIES", "8")))
    parser.add_argument("--insecure", action="store_true", default=os.environ.get("UPLOAD_INSECURE", "") == "1")
    args = parser.parse_args()

    api_bases = _parse_csv(args.api_bases)
    if not api_bases:
        raise SystemExit("Missing --api-bases (or UPLOAD_API_BASES env var).")
    token = str(args.token).strip()
    if not token:
        raise SystemExit("Missing --token (or UPLOAD_TOKEN env var).")

    version = args.version.strip()
    out_dir = Path("installer") / "output"
    full_path = out_dir / f"JianyanSetup_full_{version}.exe"
    update_path = out_dir / f"JianyanSetup_update_{version}.exe"

    print(f"[hash] full:   {full_path}")
    full_pkg = _resolve_package(full_path)
    print(f"[hash] update: {update_path}")
    update_pkg = _resolve_package(update_path)

    requested_chunk_size = args.chunk_mb * 1024 * 1024 if args.chunk_mb > 0 else None
    verify_tls = not bool(args.insecure)

    upload_package(
        api_bases=api_bases,
        token=token,
        package=full_pkg,
        chunk_size=requested_chunk_size,
        overwrite=bool(args.overwrite),
        concurrency=int(args.concurrency) if args.concurrency else None,
        timeout_s=float(args.timeout),
        verify_tls=verify_tls,
        max_retries=int(args.retries),
    )
    upload_package(
        api_bases=api_bases,
        token=token,
        package=update_pkg,
        chunk_size=requested_chunk_size,
        overwrite=bool(args.overwrite),
        concurrency=int(args.concurrency) if args.concurrency else None,
        timeout_s=float(args.timeout),
        verify_tls=verify_tls,
        max_retries=int(args.retries),
    )

    publish_resp = publish_release(
        api_base=api_bases[0],
        token=token,
        version=version,
        full_pkg=full_pkg,
        update_pkg=update_pkg,
        keep_versions=int(args.keep_versions),
        download_base_url=args.download_base_url or None,
        timeout_s=float(args.timeout),
        verify_tls=verify_tls,
    )

    deleted = publish_resp.get("deleted") or []
    if isinstance(deleted, list) and deleted:
        print(f"[publish] deleted {len(deleted)} files")
    else:
        print("[publish] no deletions reported")

    print("[publish] done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
