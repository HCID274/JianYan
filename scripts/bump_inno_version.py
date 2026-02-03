from __future__ import annotations

import re
from pathlib import Path


VERSION_RE = re.compile(r'^(?P<prefix>\s*#define\s+MyAppVersion\s+")(?P<ver>\d+\.\d+\.\d+)(".*)$')


def _bump_patch(version: str) -> tuple[str, str]:
    major_s, minor_s, patch_s = version.split(".")
    major = int(major_s)
    minor = int(minor_s)
    patch = int(patch_s)
    new_version = f"{major}.{minor}.{patch + 1}"
    return version, new_version


def main() -> None:
    path = Path("installer") / "setup.iss"
    if not path.exists():
        raise SystemExit("[ERROR] installer/setup.iss not found")

    lines = path.read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(lines):
        m = VERSION_RE.match(line)
        if not m:
            continue
        old_version, new_version = _bump_patch(m.group("ver"))
        lines[i] = f'{m.group("prefix")}{new_version}{m.group(3)}'
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"{old_version}|{new_version}")
        return

    raise SystemExit("[ERROR] MyAppVersion define not found in installer/setup.iss")


if __name__ == "__main__":
    main()

