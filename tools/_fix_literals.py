"""Step 1 of the repair: remove the ``)`` that landed *inside* string literals.

``_wrap_tr.py`` computed ``end_col_offset`` - an offset into the last line of a
literal - and applied it to the first line, so for every literal spanning several
lines the closing paren was appended to line 1 and the real closer was pushed
into the text::

    "Point at the extracted data pack)age: the folder that contains "

``work/_ui_strings.json`` holds the original text of every literal that was
wrapped, so a literal whose value minus one ``)`` is in that set is damaged in
exactly this way.  The repair deletes that one character and nothing else.
"""

from __future__ import annotations

import ast
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UI = os.path.join(ROOT, "rrmod", "ui")
INVENTORY = os.path.join(ROOT, "work", "_ui_strings.json")

QUOTES = "\"'"


def original() -> set:
    with open(INVENTORY, encoding="utf-8") as fh:
        return set(json.load(fh))


def literals(src: str) -> list:
    """(start, end, value) for every string literal, comments ignored."""
    out = []
    i = 0
    n = len(src)
    while i < n:
        ch = src[i]
        if ch == "#":
            j = src.find("\n", i)
            i = n if j < 0 else j
            continue
        if ch in QUOTES:
            q = ch
            triple = src[i:i + 3] == q * 3
            j = i + (3 if triple else 1)
            while j < n:
                if src[j] == "\\":
                    j += 2
                    continue
                if triple and src[j:j + 3] == q * 3:
                    j += 3
                    break
                if not triple and src[j] == q:
                    j += 1
                    break
                if not triple and src[j] == "\n":
                    break
                j += 1
            raw = src[i:j]
            try:
                value = ast.literal_eval(raw)
            except (ValueError, SyntaxError, MemoryError):
                value = None
            out.append((i, j, value if isinstance(value, str) else None))
            i = j
            continue
        i += 1
    return out


def main() -> int:
    known = original()
    print(f"{len(known)} original strings")
    total = 0
    for name in sorted(os.listdir(UI)):
        if not name.endswith(".py"):
            continue
        path = os.path.join(UI, name)
        src = open(path, encoding="utf-8").read()
        fixed = 0
        for _ in range(200):
            hit = None
            for start, end, value in literals(src):
                if value is None or value in known:
                    continue
                for k, ch in enumerate(value):
                    if ch != ")":
                        continue
                    if value[:k] + value[k + 1:] not in known:
                        continue
                    # find the same character inside the raw literal text
                    raw = src[start:end]
                    seen = -1
                    for _n in range(k + 1):
                        seen = raw.find(")", seen + 1)
                        if seen < 0:
                            break
                    if seen >= 0:
                        hit = start + seen
                    break
                if hit is not None:
                    break
            if hit is None:
                break
            src = src[:hit] + src[hit + 1:]
            fixed += 1
        if fixed:
            open(path, "w", encoding="utf-8", newline="\n").write(src)
            print(f"{name}: removed {fixed} paren(s) from inside literals")
            total += fixed
    print(f"total {total}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
