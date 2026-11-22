"""Build ``release\RR3ModManager\RR3ModManager.exe`` with PyInstaller.

Why this is a script and not one command
---------------------------------------
``tempfile.mkdtemp`` asks for mode ``0o700`` and on this machine a directory
created with that mode is not writable at all - ``os.listdir`` on it raises
``PermissionError: [WinError 5]``.  pip and PyInstaller both make scratch
directories that way, so both fail unless the mode is neutralised first.  The
patch below only widens the requested mode; it does not change where anything
goes.

Usage::

    python tools\\build_exe.py              # one folder (default)
    python tools\\build_exe.py --onefile    # a single .exe
    python tools\\build_exe.py --dist X     # write under X instead of release/

``--dist`` exists because a running copy of the program locks ``_internal`` on
Windows and the folder cannot be replaced while it is open; building somewhere
else first lets the swap happen later, in one go.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = os.path.join(ROOT, "work")
BUILD = os.path.join(WORK, "pyinstaller")
# The release lives beside the source, not in a ``dist/`` that sits next to it:
# the workspace root is for the notes and the reference dumps, so the one folder
# that gets handed to someone else is ``source/release/RR3ModManager``.
DIST = os.path.join(ROOT, "release")
ENTRY = os.path.join(ROOT, "rrmod_launcher.py")
LIBS = os.path.join(WORK, "pylibs")
NAME = "RR3ModManager"


def patch_tempfile() -> None:
    """Make ``mkdtemp`` produce a directory we can actually write into."""
    real_mkdtemp = tempfile.mkdtemp

    def mkdtemp(suffix: str = "", prefix: str = "tmp", dir: str | None = None) -> str:
        path = real_mkdtemp(suffix=suffix, prefix=prefix, dir=dir)
        try:
            os.chmod(path, 0o777)
        except OSError:
            pass
        return path

    tempfile.mkdtemp = mkdtemp


def main(argv: list[str]) -> int:
    onefile = "--onefile" in argv
    dist = DIST
    if "--dist" in argv:
        dist = argv[argv.index("--dist") + 1]
        if not os.path.isabs(dist):
            dist = os.path.join(ROOT, dist)
    if not os.path.isfile(ENTRY):
        print(f"missing entry point: {ENTRY}")
        return 2

    env = dict(os.environ)
    if os.path.isdir(LIBS):
        env["PYTHONPATH"] = LIBS + (os.pathsep + env["PYTHONPATH"]
                                    if env.get("PYTHONPATH") else "")
    env["TMP"] = env["TEMP"] = env["TMPDIR"] = os.path.join(WORK, "pyi_tmp")
    os.makedirs(env["TMP"], exist_ok=True)
    os.makedirs(BUILD, exist_ok=True)
    os.makedirs(dist, exist_ok=True)
    if onefile:
        env["RR3_ONEFILE"] = "1"
    # COLLECT refuses to write into a folder that already has something in it,
    # and it does not honour --noconfirm for that, so move the old build out of
    # the way ourselves.
    #
    # Rename, never delete.  An earlier version did ``shutil.rmtree(...,
    # ignore_errors=True)`` first and only then tried the rename: a running copy
    # of the program locks its own image and the folder, so the delete removed
    # every *unlocked* file - emptying ``_internal`` - and then the rename
    # failed.  What was left could not start ("Failed to start embedded python
    # interpreter!"), and the user was looking at a program that had been broken
    # by the act of building a new one.  A folder that cannot be renamed is a
    # folder we must not touch at all.
    stale = os.path.join(dist, NAME)
    if os.path.isdir(stale):
        aside = os.path.join(dist, f"{NAME}.old-{time.strftime('%Y%m%d-%H%M%S')}")
        try:
            os.rename(stale, aside)
        except OSError:
            print(f"cannot replace {stale}: it is still in use.  Close the "
                  f"running {NAME} window and build again, or build with "
                  f"--dist somewhere else.")
            return 1
        print("moved the old build aside to", os.path.basename(aside))

    spec = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rrmod.spec")
    # PyInstaller parses sys.argv[1:], so the driver below gets just the flags
    args = [
        "--noconfirm", "--clean",
        "--distpath", dist,
        "--workpath", BUILD,
        spec,
    ]

    # The patch has to be live inside the process that imports PyInstaller, so
    # run the build in a child that installs it first.
    driver = (
        "import os, sys, tempfile\n"
        "real = tempfile.mkdtemp\n"
        "def mkdtemp(suffix='', prefix='tmp', dir=None):\n"
        "    p = real(suffix=suffix, prefix=prefix, dir=dir)\n"
        "    try: os.chmod(p, 0o777)\n"
        "    except OSError: pass\n"
        "    return p\n"
        "tempfile.mkdtemp = mkdtemp\n"
        "sys.argv = " + repr(args) + "\n"
        "from PyInstaller.__main__ import run\n"
        "run()\n"
    )
    print("building", NAME, "(onefile)" if onefile else "(onedir)")
    proc = subprocess.run([sys.executable, "-c", driver], env=env, cwd=ROOT)
    if proc.returncode != 0:
        return proc.returncode

    target = os.path.join(dist, NAME + (".exe" if onefile else ""))
    if os.path.isdir(target):
        exe = os.path.join(target, NAME + ".exe")
        size = sum(os.path.getsize(os.path.join(d, f))
                   for d, _s, fs in os.walk(target) for f in fs)
    else:
        exe = target
        size = os.path.getsize(exe) if os.path.isfile(exe) else 0
    print()
    print("built:", exe)
    print("size :", f"{size / 1024 / 1024:.1f} MB")
    return 0 if os.path.isfile(exe) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
