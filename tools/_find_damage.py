"""Locate the corruption caused by a naive ``text.replace("tr(", "")``.

``str(``, ``getattr(``, ``setattr(`` and ``hasattr(`` all contain ``tr(``, so the
undo step deleted that substring inside them as well:

    str(message)     ->  smessage)
    getattr(a, "b")  ->  getata, "b")
    tr("x")          ->  "x")

Only the first of those is a syntax error; ``sx)`` parses fine, so a compiler run
does not find every site.  The ``__pycache__`` entries for these modules predate
the damage, so their code objects hold the real identifier vocabulary; a NAME
token in the source that the bytecode never heard of is a corruption site.

Reports ``file:line  damaged -> restored`` so the repair can be mechanical.
"""

from __future__ import annotations

import builtins
import importlib.util
import io
import marshal
import os
import sys
import tokenize
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UI = os.path.join(ROOT, "rrmod", "ui")
PYC = os.path.join(UI, "__pycache__")

#: what the deleted substring belonged to, longest first
VICTIMS = ("getattr", "setattr", "hasattr", "str", "tr")


def code_of(pyc_path: str):
    with open(pyc_path, "rb") as fh:
        data = fh.read()
    if data[:4] != importlib.util.MAGIC_NUMBER:
        return None
    return marshal.loads(data[16:])


def collect(code, names: set) -> None:
    if not isinstance(code, types.CodeType):
        return
    names.update(code.co_names)
    names.update(code.co_varnames)
    names.update(code.co_cellvars)
    names.update(code.co_freevars)
    for const in code.co_consts:
        if isinstance(const, types.CodeType):
            collect(const, names)


def vocab(module: str) -> set:
    path = os.path.join(PYC, f"{module}.cpython-312.pyc")
    if not os.path.isfile(path):
        return set()
    code = code_of(path)
    if code is None:
        return set()
    out = set()
    collect(code, out)
    return out


def name_tokens(path: str) -> list:
    """(line, column, word) for every NAME token, comments and strings ignored."""
    out = []
    with open(path, "rb") as fh:
        try:
            for tok in tokenize.tokenize(fh.readline):
                if tok.type == tokenize.NAME:
                    out.append((tok.start[0], tok.start[1], tok.string))
        except (tokenize.TokenError, IndentationError, SyntaxError):
            pass
    return out


def main() -> int:
    total = 0
    for name in sorted(os.listdir(UI)):
        if not name.endswith(".py"):
            continue
        module = name[:-3]
        path = os.path.join(UI, name)
        known = vocab(module)
        if not known:
            print(f"=== {module}: NO CLEAN BYTECODE - needs another source")
            continue
        known |= set(dir(builtins))
        hits = []
        for line, col, word in name_tokens(path):
            if word in known:
                continue
            # is the word a truncated form of something the bytecode knows?
            for victim in VICTIMS:
                if victim.startswith(word) and word != victim:
                    hits.append((line, col, word, victim))
                    break
        if not hits:
            continue
        total += len(hits)
        print(f"=== {module}: {len(hits)} site(s)")
        for line, col, word, victim in hits:
            print(f"   {line:4d}:{col:3d}  {word!r:14} -> {victim!r}")
    print(f"total {total}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
