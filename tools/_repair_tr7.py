"""Repair the UI sources the tr() wrapper damaged, with an explicit rule table.

The wrapper and the attempts to undo it left three kinds of scar, all mechanical:

* ``str(`` lost its ``tr(`` and became ``s`` - so ``str(exc)`` now reads
  ``sexc)``, ``str(e.car_id)`` reads ``se.car_id)``, ``getattr(sys, ...)`` reads
  ``getatsys, ...``;
* a ``)`` was added after a literal and never taken back out, so calls end in
  ``."))`` instead of ``.")``;
* a ``)`` was swallowed, so a call is left open.

Each rule below is the exact inverse of one of those.  Rules are applied one at
a time, and a rule is only accepted when the file still parses or when the
parser's complaint moves further down - that is what stops a rule from chewing
through correct code.  Whatever is left after every rule has been tried is
printed with context so it can be fixed by hand.
"""

from __future__ import annotations

import ast
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UI = os.path.join(ROOT, "rrmod", "ui")

# (name, pattern, replacement) - order matters, longest prefix first.
RULES = [
    # ---- names that lost the tr( that was part of them -------------------
    ("getattr", re.compile(r"(?<![\w.])getatsys\b"), "getattr(sys"),
    ("setattr", re.compile(r"(?<![\w.])setatsys\b"), "setattr(sys"),
    ("hasattr", re.compile(r"(?<![\w.])hasatsys\b"), "hasattr(sys"),
    ("str-exc", re.compile(r"(?<![\w.])sexc\b"), "str(exc"),
    ("str-msg", re.compile(r"(?<![\w.])smessage\b"), "str(message"),
    ("str-row", re.compile(r"(?<![\w.])srow\["), "str(row["),
    ("str-se", re.compile(r"(?<![\w.])se\.(car_id|liveries|label|name|status|sizes)\b"),
     r"str(e.\1"),
    ("str-text", re.compile(r"(?<![\w.])stext\b"), "str(text"),
    ("str-path", re.compile(r"(?<![\w.])spath\b"), "str(path"),
    ("str-value", re.compile(r"(?<![\w.])svalue\b"), "str(value"),
    ("str-other", re.compile(r"(?<![\w.])s([a-z_][a-z0-9_]*)\((?=[\w\"'])"),
     r"str(\1("),
    # ---- a paren added after a literal, never removed --------------------
    ("tail-paren", re.compile(r'(\.|,)(\s*)\)\)\s*$', re.MULTILINE), r"\1\2)\n"),
    ("tail-paren2", re.compile(r'("\)?)\)\)\s*$', re.MULTILINE), r"\1)\n"),
    # ---- a paren swallowed ------------------------------------------------
    ("open-call", re.compile(r'(QLabel|QLineEdit|QComboBox|W\.button|W\.muted|W\.heading|'
                             r'QCheckBox|QTableWidgetItem)\("([^"]*)"\s*$', re.MULTILINE),
     r'\1("\2")\n'),
]


def first_error(src: str):
    try:
        ast.parse(src)
    except SyntaxError as exc:
        return exc
    return None


def show(src: str, exc: SyntaxError) -> str:
    lines = src.splitlines()
    lo = max(0, (exc.lineno or 1) - 3)
    hi = min(len(lines), (exc.lineno or 1) + 2)
    return "\n".join(f"      {i + 1:4d}|{lines[i]}" for i in range(lo, hi))


def repair(src: str) -> tuple:
    applied = []
    for _round in range(400):
        exc = first_error(src)
        if exc is None:
            break
        before = exc.lineno or 0
        moved = False
        for name, pattern, repl in RULES:
            for match in pattern.finditer(src):
                trial = src[:match.start()] + match.expand(repl) + src[match.end():]
                after = first_error(trial)
                if after is None or (after.lineno or 0) > before:
                    src = trial
                    applied.append(name)
                    moved = True
                    break
            if moved:
                break
        if not moved:
            break
    return src, applied


def main() -> int:
    broken = []
    for name in sorted(os.listdir(UI)):
        if not name.endswith(".py"):
            continue
        path = os.path.join(UI, name)
        src = open(path, encoding="utf-8").read()
        if first_error(src) is None:
            print(f"{name}: parses")
            continue
        src, applied = repair(src)
        open(path, "w", encoding="utf-8", newline="\n").write(src)
        exc = first_error(src)
        if exc is None:
            print(f"{name}: fixed with {len(applied)} edit(s) {sorted(set(applied))}")
        else:
            broken.append(name)
            print(f"=== {name}: {len(applied)} edit(s), still line {exc.lineno}: {exc.msg}")
            print(show(src, exc))
    print("\nstill broken:", broken or "none")
    return 1 if broken else 0


if __name__ == "__main__":
    sys.exit(main())
