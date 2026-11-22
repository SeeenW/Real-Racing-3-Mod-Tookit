"""Pack ``rr3_blender_addon/`` into the zip Blender installs.

Blender installs an addon as a zip and unpacks it into its own
``scripts/addons`` folder, so the package has to be self contained - which is
why ``rr3lib`` exists twice (see ``tools/sync_rr3lib.py``).  This script is the
other half of that arrangement: it makes sure the two copies agree, then writes
``rr3_blender_addon.zip`` with exactly the files the addon needs.

    python tools/build_addon.py            # sync, then pack
    python tools/build_addon.py --check    # verify the zip is current
    python tools/build_addon.py --no-sync  # pack whatever is on disk

The zip is written atomically (temp file + replace), so a failed build cannot
leave a half-written package that Blender would install as a broken addon.
"""

from __future__ import annotations

import argparse
import os
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "rr3_blender_addon")
ZIP = os.path.join(ROOT, "rr3_blender_addon.zip")
#: Top-level folder inside the zip.  Blender uses it as the module name, so it
#: has to stay ``rr3_blender_addon``.
PACKAGE = "rr3_blender_addon"

SKIP_DIRS = {"__pycache__", ".git"}
SKIP_EXT = {".pyc", ".pyo"}


def files() -> list[str]:
    """Every file the addon needs, as paths relative to the addon folder."""
    out = []
    for base, dirs, names in os.walk(SRC):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        for name in sorted(names):
            if os.path.splitext(name)[1] in SKIP_EXT:
                continue
            full = os.path.join(base, name)
            out.append(os.path.relpath(full, SRC).replace(os.sep, "/"))
    return out


def current() -> dict:
    """``{name in zip: crc}`` for the existing package, or ``{}``."""
    if not os.path.isfile(ZIP):
        return {}
    try:
        with zipfile.ZipFile(ZIP) as zf:
            return {info.filename: info.CRC for info in zf.infolist()}
    except (OSError, zipfile.BadZipFile):
        return {}


def wanted() -> dict:
    """``{name in zip: crc}`` for what the package should contain."""
    out = {}
    for rel in files():
        out[f"{PACKAGE}/{rel}"] = _crc(os.path.join(SRC, rel))
    return out


def _crc(path: str) -> int:
    import zlib

    crc = 0
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            crc = zlib.crc32(chunk, crc)
    return crc & 0xFFFFFFFF


def build() -> int:
    tmp = ZIP + ".part"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel in files():
            zf.write(os.path.join(SRC, rel), f"{PACKAGE}/{rel}")
    os.replace(tmp, ZIP)
    return os.path.getsize(ZIP)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="report whether the zip matches the folder, change nothing")
    ap.add_argument("--no-sync", action="store_true",
                    help="do not run tools/sync_rr3lib.py first")
    a = ap.parse_args(argv)

    if not a.no_sync:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import sync_rr3lib  # noqa: E402 - local script, not a package

        rc = sync_rr3lib.main(["--check"])
        if rc != 0:
            if a.check:
                print("the two rr3lib copies disagree - run tools/sync_rr3lib.py")
                return 1
            print("syncing rr3lib into the addon")
            sync_rr3lib.main([])

    have, want = current(), wanted()
    missing = sorted(set(want) - set(have))
    extra = sorted(set(have) - set(want))
    changed = sorted(n for n in want if n in have and want[n] != have[n])

    if a.check:
        if missing or extra or changed:
            for label, names in (("missing", missing), ("stale", changed),
                                 ("no longer needed", extra)):
                if names:
                    print(f"  {label}: {len(names)}")
                    for n in names[:8]:
                        print(f"    {n}")
            print(f"{os.path.basename(ZIP)} is not current - run tools/build_addon.py")
            return 1
        print(f"{os.path.basename(ZIP)} is current ({len(want)} files)")
        return 0

    size = build()
    print(f"wrote {ZIP}")
    print(f"  {len(want)} files, {size:,} bytes")
    if missing or changed:
        print(f"  refreshed: {len(missing)} new, {len(changed)} changed")
    if extra:
        print(f"  dropped: {len(extra)} (no longer in the folder)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
