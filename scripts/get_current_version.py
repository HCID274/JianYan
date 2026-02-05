from __future__ import annotations

import re
from pathlib import Path


def main() -> None:
    path = Path("installer") / "version.issinc"
    if not path.exists():
        raise SystemExit("[ERROR] installer/version.issinc not found")
    m = re.search(r'MyAppVersion\s+"(?P<ver>\d+\.\d+\.\d+)"', path.read_text(encoding="utf-8"))
    if not m:
        raise SystemExit("[ERROR] MyAppVersion not found in installer/version.issinc")
    print(m.group("ver"))


if __name__ == "__main__":
    main()

