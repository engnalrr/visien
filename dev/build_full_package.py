"""Build a shareable Visien package from a Visien folder (the same as Settings › Share Visien).

    python dev/build_full_package.py slim <output .zip>
    python dev/build_full_package.py full <output .zip>

Run it with the Python that runs Visien (runtime\\python\\python.exe or .venv\\Scripts\\python.exe) from the Visien
folder. See visien/package.py for what each package contains.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from visien import package  # noqa: E402


def main() -> None:
    if len(sys.argv) != 3 or sys.argv[1] not in ("slim", "full"):
        raise SystemExit(__doc__)
    plan = package.plan_for(sys.argv[1], ROOT)

    def report(files: int, total_files: int, done: int, total: int) -> None:
        print(f"\r  {files}/{total_files} files, {done / 1024 ** 3:.2f}/{total / 1024 ** 3:.2f} GB", end="", flush=True)

    target = package.write(plan, Path(sys.argv[2]), report)
    print(f"\n{target} ({target.stat().st_size / 1024 ** 2:.0f} MB)")


if __name__ == "__main__":
    main()
