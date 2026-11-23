"""Build the two zips a release attaches, into ``_build/rel/``.

    python tools/make_release.py [--version 0.1.1]

Two artefacts, both self contained:

* ``RR3ModManager-<version>-windows.zip`` - the packaged workbench, taken from
  ``release/RR3ModManager``.  The user's own state is *not* shipped: the
  program keeps ``RR3ModManager_state/``, ``settings.ini`` and its logs beside
  the exe, and those belong to whoever ran it, not to a download.
* ``rr3_blender_addon-<version>.zip`` - the addon package Blender installs,
  copied from ``rr3_blender_addon.zip`` so there is only one place that decides
  what an addon contains (``tools/build_addon.py``).

The version is read from ``rrmod.__version__`` unless ``--version`` overrides it,
so the zip name cannot drift away from the title bar.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from rrmod import __version__                        # noqa: E402

#: Files and folders the workbench creates at run time.  Shipping them would
#: hand the next user someone else's install path and undo history.
SKIP_DIRS = {"RR3ModManager_state", "_internal_cache", "__pycache__"}
SKIP_FILES = {"settings.ini", "rrmod_check.log", "rrmod_crash.log"}


def _zip_tree(src: str, out: str, prefix: str) -> tuple[int, int]:
    count = total = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for dirpath, dirs, files in os.walk(src):
            dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
            for f in sorted(files):
                if f in SKIP_FILES:
                    continue
                path = os.path.join(dirpath, f)
                rel = os.path.relpath(path, src).replace(os.sep, "/")
                zf.write(path, f"{prefix}/{rel}")
                count += 1
                total += os.path.getsize(path)
    return count, total


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", default=__version__)
    ap.add_argument("--out", default=os.path.join(ROOT, "_build", "rel"))
    args = ap.parse_args()
    ver = args.version
    os.makedirs(args.out, exist_ok=True)

    exe_dir = os.path.join(ROOT, "release", "RR3ModManager")
    if not os.path.isfile(os.path.join(exe_dir, "RR3ModManager.exe")):
        print(f"no packaged workbench at {exe_dir} - run tools/build_exe.py first")
        return 1
    name = f"RR3ModManager-{ver}-windows.zip"
    dest = os.path.join(args.out, name)
    count, total = _zip_tree(exe_dir, dest, "RR3ModManager")
    print(f"{name}: {count} entries, {total / 1048576:.1f} MB unpacked, "
          f"{os.path.getsize(dest) / 1048576:.1f} MB zipped")

    addon_src = os.path.join(ROOT, "rr3_blender_addon.zip")
    if not os.path.isfile(addon_src):
        print(f"no addon package at {addon_src} - run tools/build_addon.py first")
        return 1
    addon = os.path.join(args.out, f"rr3_blender_addon-{ver}.zip")
    shutil.copyfile(addon_src, addon)
    with zipfile.ZipFile(addon) as zf:
        n = len(zf.namelist())
    print(f"{os.path.basename(addon)}: {n} entries, "
          f"{os.path.getsize(addon) / 1048576:.2f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
