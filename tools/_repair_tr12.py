"""Take the last seven parens out of the middle of words.

The wrapper pushed its closing paren *inside* a multi-line literal in a handful of
places; ``_repair_tr6.py`` could only recognise those whose text it had a record
of, and these were not in the inventory.  Each one is written out in full below so
the correction is visible rather than inferred.
"""

from __future__ import annotations

import ast
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UI = os.path.join(ROOT, "rrmod", "ui")

EDITS = [
    ("animui.py",
     "Without this )flag in the car's spec",
     "Without this flag in the car's spec"),
    ("animui.py",
     "Behaviour: none. )The game will never play",
     "Behaviour: none. The game will never play"),
    ("app.py",
     "go to _r)rmod_backup in the game folder",
     "go to _rrmod_backup in the game folder"),
    ("cars.py",
     "Hide the 76 cars that) borrow another car's body",
     "Hide the 76 cars that borrow another car's body"),
    ("gfxui.py",
     "applying a profile replaces eve)ry key it names",
     "applying a profile replaces every key it names"),
    ("gfxui.py",
     "Double click )a value in the After column",
     "Double click a value in the After column"),
    ("musicbatch.py",
     "That plan matches w)hat the playlists already say",
     "That plan matches what the playlists already say"),
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

    bad = []
    for name in sorted(os.listdir(UI)):
        if not name.endswith(".py"):
            continue
        path = os.path.join(UI, name)
        try:
            ast.parse(open(path, encoding="utf-8").read())
        except SyntaxError as exc:
            bad.append((name, exc.lineno, exc.msg))
    print("parse errors:", bad or "none")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
