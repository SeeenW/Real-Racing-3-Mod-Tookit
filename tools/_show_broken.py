"""Show every UI file that does not parse, with the error and its context."""

from __future__ import annotations

import ast
import os
import sys

UI = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                  "rrmod", "ui")


def main() -> int:
    bad = 0
    for name in sorted(os.listdir(UI)):
        if not name.endswith(".py"):
            continue
        path = os.path.join(UI, name)
        src = open(path, encoding="utf-8").read()
        try:
            ast.parse(src)
            continue
        except SyntaxError as exc:
            bad += 1
            lines = src.splitlines()
            print("=" * 12, name, f"line {exc.lineno}: {exc.msg}")
            lo = max(0, (exc.lineno or 1) - 5)
            hi = min(len(lines), (exc.lineno or 1) + 3)
            for i in range(lo, hi):
                mark = ">>" if i + 1 == exc.lineno else "  "
                print(f"{mark}{i + 1:4d}|{lines[i]}")
    print(f"\n{bad} broken file(s)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
