from __future__ import annotations

import re
from pathlib import Path


INNO_VERSION_RE = re.compile(r'^(?P<prefix>\s*#define\s+MyAppVersion\s+")(?P<ver>\d+\.\d+\.\d+)(".*)$')
PY_VERSION_RE = re.compile(r'^(?P<prefix>\s*__version__\s*=\s*")(?P<ver>\d+\.\d+\.\d+)(".*)$')


def _bump_patch(version: str) -> tuple[str, str]:
    major_s, minor_s, patch_s = version.split(".")
    major = int(major_s)
    minor = int(minor_s)
    patch = int(patch_s)
    new_version = f"{major}.{minor}.{patch + 1}"
    return version, new_version


def main() -> None:
    inno_path = Path("installer") / "version.issinc"
    if not inno_path.exists():
        raise SystemExit("[ERROR] installer/version.issinc not found")

    lines = inno_path.read_text(encoding="utf-8").splitlines()
    old_version = None
    new_version = None
    for i, line in enumerate(lines):
        m = INNO_VERSION_RE.match(line)
        if not m:
            continue
        old_version, new_version = _bump_patch(m.group("ver"))
        lines[i] = f'{m.group("prefix")}{new_version}{m.group(3)}'
        break

    if not old_version or not new_version:
        raise SystemExit("[ERROR] MyAppVersion define not found in installer/version.issinc")

    inno_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    py_path = Path("app") / "version.py"
    if py_path.exists():
        py_lines = py_path.read_text(encoding="utf-8").splitlines()
        for i, line in enumerate(py_lines):
            m = PY_VERSION_RE.match(line)
            if not m:
                continue
            py_lines[i] = f'{m.group("prefix")}{new_version}{m.group(3)}'
            py_path.write_text("\n".join(py_lines) + "\n", encoding="utf-8")
            break

    print(f"{old_version}|{new_version}")
    return


if __name__ == "__main__":
    main()
