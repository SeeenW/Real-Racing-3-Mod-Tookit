"""Five more hand-checked repairs, each the inverse of one stray paren.

The pattern the wrapper left in a multi-line call: the ``)`` it appended landed
after the *first* fragment (``self, "Undo last edit"),``), so the call ends one
paren short while the argument list has one too many.  Each edit below is written
out in full so the intent is visible and a re-run does nothing.
"""

from __future__ import annotations

import ast
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UI = os.path.join(ROOT, "rrmod", "ui")

EDITS = [
    # the wrapper's paren sat after the first fragment of a multi-line call
    ("app.py",
     '            self, "Undo last edit"),\n',
     '            self, "Undo last edit",\n'),
    ("seriesui.py",
     'row["group"], str(row["tiers"]), str(row["events"])))',
     'row["group"], str(row["tiers"]), str(row["events"]))'),
    ("buildui.py",
     "problems.append(str(exc)))",
     "problems.append(str(exc))"),
    ("cars.py",
     'self.title.setText("No car selected"))',
     'self.title.setText("No car selected")'),
    # a paren that was swallowed at the end of a multi-line argument
    ("deployui.py",
     '            "asset lists are made read only again afterwards, as the engine expects."\n',
     '            "asset lists are made read only again afterwards, as the engine expects."))\n'),
]


def main() -> int:
    for name, old, new in EDITS:
        path = os.path.join(UI, name)
        src = open(path, encoding="utf-8").read()
        if old not in src:
            print(f"{name}: {'already applied' if new in src else 'NOT FOUND: ' + old[:50]!r}")
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
