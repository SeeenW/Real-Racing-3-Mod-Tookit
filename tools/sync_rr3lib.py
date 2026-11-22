"""Keep the two ``rr3lib`` copies in sync.

The package exists twice on purpose:

* ``rr3lib/``               - used by the analysis scripts and by ``rr3dump.py``
* ``rr3_blender_addon/rr3lib/`` - the copy that ships inside the Blender addon

The addon has to be self contained (Blender installs it as a zip into its own
``scripts/addons`` folder, so it cannot import from the repository), which means
the same modules live in both places.  Rather than hope they stay equal, this
script copies the canonical version over and reports what changed::

    python tools/sync_rr3lib.py            # copy, report
    python tools/sync_rr3lib.py --check    # report differences, exit 1 if any
    python tools/sync_rr3lib.py --from-addon   # reverse direction (rarely wanted)

The canonical copy is the root ``rr3lib/`` - it is the one the analysis scripts
import, so a bug shows up there first.
"""

from __future__ import annotations

import argparse
import filecmp
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "rr3lib")
DST = os.path.join(ROOT, "rr3_blender_addon", "rr3lib")

#: Files that only exist on one side and are not part of the shared set.
ONLY_ROOT = {"__pycache__"}
SKIP = {"__pycache__"}


def modules(folder: str) -> list[str]:
    return sorted(f for f in os.listdir(folder)
                  if f.endswith(".py") and f not in SKIP)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="only report, do not copy")
    ap.add_argument("--from-addon", action="store_true",
                    help="copy addon -> root instead of root -> addon")
    a = ap.parse_args(argv)

    src, dst = (DST, SRC) if a.from_addon else (SRC, DST)
    if not os.path.isdir(src) or not os.path.isdir(dst):
        print(f"missing folder: {src} or {dst}")
        return 2

    src_files = modules(src)
    dst_files = modules(dst)
    only_src = [f for f in src_files if f not in dst_files]
    only_dst = [f for f in dst_files if f not in src_files]
    differ = [f for f in src_files
              if f in dst_files and not filecmp.cmp(
                  os.path.join(src, f), os.path.join(dst, f), shallow=False)]

    label = "addon -> root" if a.from_addon else "root -> addon"
    print(f"sync {label}: {len(src_files)} modules")
    if only_src:
        print("  only in source:", ", ".join(only_src))
    if only_dst:
        print("  only in destination:", ", ".join(only_dst))
    if differ:
        print("  differs:", ", ".join(differ))
    if not (only_src or only_dst or differ):
        print("  already in sync")
        return 0

    if a.check:
        return 1

    for f in only_src + differ:
        shutil.copy2(os.path.join(src, f), os.path.join(dst, f))
        print(f"  copied {f}")
    # never delete: a stale module on the destination side is harmless, and
    # deleting could remove something a future version still imports
    if only_dst:
        print("  left in place (not deleted):", ", ".join(only_dst))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
