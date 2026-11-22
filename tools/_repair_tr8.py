"""The last of the tr() damage: seven hand-checked edits.

After ``_repair_tr6.py`` put the ``tr(`` back into ``str(``/``getattr(`` and took
the wrapper's stray ``)`` out, eleven files still failed to parse.  Every one of
them is listed below with the exact line it is on and what is wrong; the edits are
literal string replacements so a re-run is a no-op once they have been applied.

``app.py:163`` is the one case of a paren pushed *into* a literal
(``"Rea)l Racing 3"``); the rest are either a ``)`` the wrapper added that is
still there, or a ``)`` that got swallowed.
"""

from __future__ import annotations

import ast
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UI = os.path.join(ROOT, "rrmod", "ui")

EDITS = [
    # a paren pushed inside the text
    ("app.py", "A manager for Rea)l Racing 3 car mods", "A manager for Real Racing 3 car mods"),
    # a closing paren that was swallowed
    ("app.py",
     '"A car that neither list knows about is left alone until you adopt it.")',
     '"A car that neither list knows about is left alone until you adopt it."))'),
    ("buildui.py", "problems.append(sexc))", "problems.append(str(exc)))"),
    ("cars.py", 'self.title = QLabel("No car selected"\n',
     'self.title = QLabel("No car selected")\n'),
    ("deployui.py", 'self.conn_label = QLabel("Not connected"\n',
     'self.conn_label = QLabel("Not connected")\n'),
    ("seriesui.py", 'row["group"], str(row["tiers"]), srow["events"]))',
     'row["group"], str(row["tiers"]), str(row["events"])))'),
    ("widgets.py", 'self.setPlaceholderText("Nothing yet."\n',
     'self.setPlaceholderText("Nothing yet.")\n'),
]


def main() -> int:
    touched = {}
    for name, old, new in EDITS:
        path = os.path.join(UI, name)
        src = open(path, encoding="utf-8").read()
        if old not in src:
            if new in src:
                print(f"{name}: already applied")
            else:
                print(f"=== {name}: pattern not found: {old[:60]!r}")
            continue
        src = src.replace(old, new, 1)
        open(path, "w", encoding="utf-8", newline="\n").write(src)
        touched[name] = touched.get(name, 0) + 1
    print("edited:", touched)

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
