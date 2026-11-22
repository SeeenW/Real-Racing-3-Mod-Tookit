# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the RR3 Mod Manager.

Written by hand rather than generated: letting PyInstaller write its own spec
from the command line puts ``manifest='PyInstaller'`` in it, and that string is
then resolved relative to the spec folder and cannot be found.

``RR3_ONEFILE=1`` in the environment builds a single self-extracting exe
instead of the one-folder layout.
"""

import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(SPEC)))
if not os.path.isdir(os.path.join(ROOT, "rrmod")):
    raise SystemExit(f"spec is not where it should be: {SPEC}")

from PyInstaller.utils.hooks import collect_submodules

ONEFILE = os.environ.get("RR3_ONEFILE", "") not in ("", "0")

hidden = ["rr3lib", "rrmod"]
hidden += collect_submodules("rr3lib")
hidden += collect_submodules("rrmod")

# Data files have to be listed by hand: ``rrmod/data`` is read with
# ``os.path.join(os.path.dirname(__file__), "data", ...)``, which resolves inside
# the frozen bundle, and nothing imports a .json or .csv - so without this the
# translation tables and the car spreadsheet simply are not there.  The first
# build shipped that way and the language menu did nothing.
datas = [
    (os.path.join(ROOT, "rrmod", "data"), "rrmod/data"),
]

excluded = [
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.Qt3DCore",
    "PySide6.QtQuick", "PySide6.QtQml", "PySide6.QtMultimedia",
    "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtPdf",
    "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtBluetooth",
    "PySide6.QtPositioning", "PySide6.QtSensors",
    "numpy", "PIL", "matplotlib", "tkinter", "unittest", "pydoc_data",
]

a = Analysis(
    [os.path.join(ROOT, "rrmod_launcher.py")],
    pathex=[ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excluded,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

common = dict(
    name="RR3ModManager",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    manifest=None,
)

if ONEFILE:
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], **common)
else:
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, **common)
    coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False,
                   name="RR3ModManager")
