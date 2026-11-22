"""The last four: a call split across two lines, and three lost ``str(`` names.

``_scan_failed`` in two files lost the ``)`` of its first statement and grew an
extra one in the second - the wrapper's paren ended up one line too low.  The
other two are a duplicated ``)`` and a line where ``str(laps)``, ``str(fame)`` and
``str(reward)`` all lost the ``tr(`` that was part of ``str(``.
"""

from __future__ import annotations

import ast
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UI = os.path.join(ROOT, "rrmod", "ui")

EDITS = [
    ("app.py",
     '        self.message("Scan failed"\n'
     '        QMessageBox.critical(self, "Scan failed"), text[:2000])',
     '        self.message("Scan failed")\n'
     '        QMessageBox.critical(self, "Scan failed", text[:2000])'),
    ("cars.py",
     '        self.status.emit("Scan failed"\n'
     '        QMessageBox.critical(self, "Scan failed"), text[:2000])',
     '        self.status.emit("Scan failed")\n'
     '        QMessageBox.critical(self, "Scan failed", text[:2000])'),
    ("deployui.py",
     '            "asset lists are made read only again afterwards, as the engine expects."))',
     '            "asset lists are made read only again afterwards, as the engine expects.")'),
    ("seriesui.py",
     'cells = (str(index), name, track, slaps), sfame), sreward))',
     'cells = (str(index), name, track, str(laps), str(fame), str(reward))'),
]


def main() -> int:
    for name, old, new in EDITS:
        path = os.path.join(UI, name)
        src = open(path, encoding="utf-8").read()
        if old not in src:
            print(f"{name}: {'already applied' if new in src else 'NOT FOUND'}")
            continue
        open(path, "w", encoding="utf-8", newline="\n").write(src.replace(old, new, 1))
        print(f"{name}: edited")

    broken = []
    for name in sorted(os.listdir(UI)):
        if not name.endswith(".py"):
            continue
        src = open(os.path.join(UI, name), encoding="utf-8").read()
        try:
            ast.parse(src)
        except SyntaxError as exc:
            broken.append(name)
            lines = src.splitlines()
            lo = max(0, (exc.lineno or 1) - 3)
            hi = min(len(lines), (exc.lineno or 1) + 2)
            print(f"=== {name}: line {exc.lineno}: {exc.msg}")
            for i in range(lo, hi):
                print(f"      {i + 1:4d}|{lines[i]}")
    print("\nstill broken:", broken or "none")
    return 1 if broken else 0


if __name__ == "__main__":
    sys.exit(main())
