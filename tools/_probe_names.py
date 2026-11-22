"""List identifier-shaped words that the pre-damage bytecode never knew.

``tokenize`` refuses to tokenise a file whose parens do not balance, which is why
the earlier probe reported nothing.  This scanner is deliberately dumb: it walks
the text, blanks out string literals and comments, and reports every word that
is not in the module's bytecode vocabulary or the builtins.
"""

from __future__ import annotations

import ast
import builtins
import importlib.util
import marshal
import os
import re
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UI = os.path.join(ROOT, "rrmod", "ui")
PYC = os.path.join(UI, "__pycache__")

WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def vocab(module: str) -> set:
    path = os.path.join(PYC, f"{module}.cpython-312.pyc")
    if not os.path.isfile(path):
        return set()
    with open(path, "rb") as fh:
        data = fh.read()
    if data[:4] != importlib.util.MAGIC_NUMBER:
        return set()
    names: set = set()

    def walk(code):
        if not isinstance(code, types.CodeType):
            return
        names.update(code.co_names)
        names.update(code.co_varnames)
        names.update(code.co_cellvars)
        names.update(code.co_freevars)
        for const in code.co_consts:
            if isinstance(const, types.CodeType):
                walk(const)

    walk(marshal.loads(data[16:]))
    return names


def mask(src: str) -> str:
    """Blank out string literals and comments, keeping offsets intact."""
    chars = list(src)
    i = 0
    n = len(src)
    while i < n:
        ch = src[i]
        if ch == "#":
            while i < n and src[i] != "\n":
                chars[i] = " "
                i += 1
            continue
        if ch in "'\"":
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
            for k in range(i, min(j, n)):
                if chars[k] != "\n":
                    chars[k] = " "
            i = j
            continue
        i += 1
    return "".join(chars)


def main() -> int:
    for name in sorted(os.listdir(UI)):
        if not name.endswith(".py"):
            continue
        module = name[:-3]
        known = vocab(module)
        if not known:
            print(f"{name}: no bytecode, skipped")
            continue
        known |= set(dir(builtins))
        src = open(os.path.join(UI, name), encoding="utf-8").read()
        text = mask(src)
        rows = []
        for m in WORD.finditer(text):
            word = m.group(0)
            if word in known:
                continue
            line = text.count("\n", 0, m.start()) + 1
            rows.append((line, word))
        if not rows:
            continue
        print(f"=== {name}: {len(rows)}")
        for line, word in rows:
            print(f"   {line:4d}  {word!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
