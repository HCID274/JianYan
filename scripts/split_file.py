from __future__ import annotations

import argparse
from pathlib import Path


def split_file(input_path: Path, output_dir: Path, chunk_size_bytes: int) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)

    size = input_path.stat().st_size
    parts = (size + chunk_size_bytes - 1) // chunk_size_bytes

    part_paths: list[Path] = []
    with input_path.open("rb") as src:
        for idx in range(parts):
            part_path = output_dir / f"{input_path.name}.part{idx:03d}"
            part_paths.append(part_path)

            remaining = chunk_size_bytes
            with part_path.open("wb") as out:
                while remaining:
                    buf = src.read(min(8 * 1024 * 1024, remaining))
                    if not buf:
                        break
                    out.write(buf)
                    remaining -= len(buf)

    return part_paths


def main() -> int:
    parser = argparse.ArgumentParser(description="Split a large file into fixed-size parts.")
    parser.add_argument("--input", required=True, help="Input file path.")
    parser.add_argument("--output-dir", required=True, help="Directory to write part files into.")
    parser.add_argument("--chunk-mb", type=int, default=256, help="Chunk size in MB (default: 256).")
    args = parser.parse_args()

    input_path = Path(args.input)
    output_dir = Path(args.output_dir)
    chunk_size_bytes = int(args.chunk_mb) * 1024 * 1024

    part_paths = split_file(input_path, output_dir, chunk_size_bytes)
    for p in part_paths:
        print(f"{p.name}\t{p.stat().st_size}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
