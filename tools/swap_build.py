"""Put a freshly built copy of the manager in place of the one in ``release``.

Windows will not let a folder be replaced while a program inside it is running:
``_internal`` is open, so the delete fails and PyInstaller refuses to build into
a non-empty folder.  Rather than making the user guess, the build can go
somewhere else (``build_exe.py --dist``) and this script does the swap once the
window is closed.

    python tools\\swap_build.py                  # swap release\\RR3ModManager-next in
    python tools\\swap_build.py --from X --to Y   # any pair of folders

Exit codes: 0 swapped, 1 the old copy is still in use, 2 nothing to swap.
"""

from __future__ import annotations

import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(ROOT, "release")
NAME = "RR3ModManager"


def _in_use(folder: str) -> str:
    """``""`` when ``folder`` can be renamed, else the file that is holding it.

    Renaming the folder itself is the only test that matches what the swap does:
    on Windows a running program keeps its own image open, so the directory
    cannot move even though the files inside it can still be renamed one by one.
    """
    probe = folder + ".probe"
    try:
        os.rename(folder, probe)
    except OSError:
        for dirpath, _dirs, files in os.walk(folder):
            for f in files:
                p = os.path.join(dirpath, f)
                one = p + ".probe"
                try:
                    os.rename(p, one)
                except OSError:
                    return p
                os.rename(one, p)
        return folder
    os.rename(probe, folder)
    return ""


def main(argv: list[str]) -> int:
    source = os.path.join(DIST, NAME + "-next")
    target = os.path.join(DIST, NAME)
    if "--from" in argv:
        source = argv[argv.index("--from") + 1]
        if not os.path.isabs(source):
            source = os.path.join(ROOT, source)
    if "--to" in argv:
        target = argv[argv.index("--to") + 1]
        if not os.path.isabs(target):
            target = os.path.join(ROOT, target)

    if not os.path.isdir(source):
        print(f"nothing to swap: {source} does not exist")
        return 2
    # PyInstaller writes <dist>/<name>/ when COLLECT is used, so a build asked for
    # with --dist dist\RR3ModManager-next lands one level down.
    nested = os.path.join(source, NAME)
    if (not os.path.isfile(os.path.join(source, NAME + ".exe"))
            and os.path.isfile(os.path.join(nested, NAME + ".exe"))):
        source = nested
    if os.path.isdir(target):
        busy = _in_use(target)
        if busy:
            print("the copy in place is still running - close the window first")
            print(f"  locked: {busy}")
            return 1
        # A leftover ".old" from an earlier swap may itself contain a window
        # that is still open, in which case deleting it would gut it the way a
        # half-finished rmtree always does.  Rename it out of the way instead
        # and let the user clear it later.
        old = target + ".old"
        if os.path.exists(old):
            spare = f"{old}-{time.strftime('%Y%m%d-%H%M%S')}"
            try:
                os.rename(old, spare)
            except OSError as exc:
                print(f"could not move the previous old copy aside: {exc}")
                return 1
        try:
            os.rename(target, old)
        except OSError as exc:
            print(f"could not move the old build aside: {exc}")
            return 1
        print("moved the old build to", os.path.basename(old))
    os.rename(source, target)
    print("swapped in", target)
    exe = os.path.join(target, NAME + ".exe")
    print("run:", exe)
    return 0 if os.path.isfile(exe) else 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
