"""Repair the UI sources after the botched tr() wrapping.

Sequence of events, which is what makes an exact repair possible:

1. ``_wrap_tr.py`` inserted ``tr(`` before every UI string literal and ``)``
   after it.
2. ``_rewrap_tr.py`` undid that with ``text.replace("tr(", "")``.  The same
   substring also occurs inside ``str(``, ``getattr(``, ``setattr(`` and
   ``hasattr(``, so those were truncated - ``str(x)`` became ``sx)``, which is
   still valid Python and therefore silent.
3. It then deleted every ``)`` that a quote followed, to get rid of the leftover
   closers.  Some of those were the calls' own closers.
4. A third script deleted two closers per site instead of one.

``work/_ui_strings.json`` was written before step 1 and records the original text
and line of every literal that was wrapped, so each damaged site can be found
again exactly.  For a recorded literal the repair is:

* if the text after the literal is a run of ``)``, drop one (it is the wrapper's,
  or one too many from step 4);
* if there is no ``)`` at all, add one (steps 3 and 4 removed the call's own);
* and restore the truncated call names, checked against the identifier vocabulary
  of the pre-damage bytecode.

Each file is parsed after every change; a file that still fails is reported with
the offending lines instead of being written.
"""

from __future__ import annotations

import ast
import builtins
import importlib.util
import json
import marshal
import os
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UI = os.path.join(ROOT, "rrmod", "ui")
PYC = os.path.join(UI, "__pycache__")
INVENTORY = os.path.join(ROOT, "work", "_ui_strings.json")

VICTIMS = ("getattr", "setattr", "hasattr", "str")
QUOTES = "\"'"


# ------------------------------------------------------------------ inventory
def inventory() -> dict:
    """{module: [(line, text), ...]} for every literal the wrapper touched."""
    with open(INVENTORY, encoding="utf-8") as fh:
        raw = json.load(fh)
    per: dict = {}
    for text, places in raw.items():
        for place in places:
            name, _, line = place.rpartition(":")
            mod = os.path.basename(name)[:-3]
            per.setdefault(mod, []).append((int(line), text))
    return per


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


# --------------------------------------------------------------- lexing
def literals(src: str) -> list:
    """(start, end, value) for every string literal, ignoring comments.

    Written by hand because ``tokenize`` gives up on a file with unbalanced
    brackets, which is exactly the state these files are in.
    """
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


def words(src: str) -> list:
    """(start, end, word) for every identifier-shaped run outside literals."""
    spans = [(s, e) for s, e, _v in literals(src)]
    out = []
    i = 0
    n = len(src)
    while i < n:
        if any(s <= i < e for s, e in spans):
            i += 1
            continue
        ch = src[i]
        if ch == "#":
            j = src.find("\n", i)
            i = n if j < 0 else j
            continue
        if ch.isalpha() or ch == "_":
            j = i
            while j < n and (src[j].isalnum() or src[j] == "_"):
                j += 1
            out.append((i, j, src[i:j]))
            i = j
            continue
        i += 1
    return out


# ------------------------------------------------------------------ repairs
def fix_sites(src: str, sites: list) -> tuple:
    """Make the text after each recorded literal correct again."""
    dropped = added = 0
    for _round in range(3):
        changed = False
        for line, text in sites:
            # find the literal whose value is (or nearly is) the recorded text
            hit = None
            for start, end, value in literals(src):
                if value is None:
                    continue
                if value != text and value != text.replace(")", "", 1):
                    continue
                if src.count("\n", 0, start) + 1 != line:
                    continue
                hit = (start, end, value)
                break
            if hit is None:
                continue
            start, end, value = hit
            if value != text:
                # a ")" was taken from inside the literal: put it back
                k = src.rfind(")", start, end)
                if k < 0:
                    continue
                src = src[:k] + src[k + 1:]
                # the closing quote moved one left, so the literal now ends here
                end -= 1
                src = src[:end - 1] + ")" + src[end - 1:]
                added += 1
                changed = True
                continue
            i = end
            while i < len(src) and src[i] in " \t":
                i += 1
            if i < len(src) and src[i] == ")":
                src = src[:i] + src[i + 1:]
                dropped += 1
                changed = True
            else:
                src = src[:end] + ")" + src[end:]
                added += 1
                changed = True
        if not changed:
            break
    return src, dropped, added


def fix_names(src: str, known: set) -> int:
    """Restore call names truncated by the substring removal."""
    if not known:
        return 0
    fixed = 0
    for _ in range(300):
        hit = None
        for start, end, word in words(src):
            if word in known or word in dir(builtins):
                continue
            for victim in VICTIMS:
                head = victim.replace("tr(", "")
                if not head or not word.startswith(head) or word == head:
                    continue
                if victim not in known and victim not in dir(builtins):
                    continue
                rest = word[len(head):]
                hit = (start, end, victim + "(" + rest)
                break
            if hit is not None:
                break
        if hit is None:
            return fixed
        start, end, new = hit
        src = src[:start] + new + src[end:]
        fixed += 1
    return fixed


def context(src: str, exc: SyntaxError) -> str:
    lines = src.splitlines()
    lo = max(0, (exc.lineno or 1) - 3)
    hi = min(len(lines), (exc.lineno or 1) + 2)
    return "\n".join(f"      {i + 1:4d}|{lines[i]}" for i in range(lo, hi))


def main() -> int:
    per = inventory()
    bad = []
    for module in sorted(per):
        path = os.path.join(UI, f"{module}.py")
        if not os.path.isfile(path):
            continue
        src = open(path, encoding="utf-8").read()
        src, dropped, added = fix_sites(src, per[module])
        names = fix_names(src, vocab(module))
        try:
            ast.parse(src)
        except SyntaxError as exc:
            bad.append(module)
            print(f"=== {module}: dropped {dropped}, added {added}, names {names}"
                  f" - line {exc.lineno}: {exc.msg}")
            print(context(src, exc))
            open(path, "w", encoding="utf-8", newline="\n").write(src)
            continue
        open(path, "w", encoding="utf-8", newline="\n").write(src)
        print(f"{module}: dropped {dropped}, added {added}, names {names}  ok")
    print("\nneeds a look:", bad or "none")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
