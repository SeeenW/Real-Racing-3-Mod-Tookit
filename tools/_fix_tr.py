"""Repair the damage done by _wrap_tr.py on multi-line string literals.

ast gives ``end_col_offset`` as an offset into the *last* line of a multi-line
string, but the wrapper applied it to the *first* line, so the closing paren
landed inside the literal.  The insertion itself (``tr(`` at the start) is
correct, so all that is needed is to find and delete the stray ``)``.

Because the stray paren is the only unknown, the repair tries candidate parens
one at a time and keeps the first removal that makes the whole file parse.  A
file with several broken literals needs several passes, which the loop below
handles.
"""

from __future__ import annotations

import ast
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UI = os.path.join(ROOT, "rrmod", "ui")


def parses(text: str) -> bool:
    try:
        ast.parse(text)
        return True
    except SyntaxError:
        return False


def candidates(lines: list) -> list:
    """(row, col) of every ``)`` on a line that also contains ``tr(``."""
    out = []
    for row, line in enumerate(lines):
        if "tr(" not in line:
            continue
        for col, ch in enumerate(line):
            if ch == ")":
                out.append((row, col))
    return out


def repair(path: str) -> int:
    text = open(path, encoding="utf-8").read()
    if parses(text):
        return 0
    fixed = 0
    for _ in range(40):
        lines = text.splitlines(keepends=True)
        done = False
        for row, col in candidates(lines):
            line = lines[row]
            trial = list(lines)
            trial[row] = line[:col] + line[col + 1:]
            if parses("".join(trial)):
                text = "".join(trial)
                fixed += 1
                done = True
                break
        if not done:
            break
    if parses(text):
        open(path, "w", encoding="utf-8", newline="\n").write(text)
    return fixed


def main() -> int:
    bad = []
    for name in sorted(os.listdir(UI)):
        if not name.endswith(".py"):
            continue
        path = os.path.join(UI, name)
        n = repair(path)
        ok = parses(open(path, encoding="utf-8").read())
        if n or not ok:
            print(f"{name}: removed {n} stray paren(s), parses={ok}")
        if not ok:
            bad.append(name)
    print("still broken:", bad or "none")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
