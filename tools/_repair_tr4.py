"""Undo the tr() wrapping exactly, using the record of what it touched.

``_wrap_tr.py`` added two things per string literal: ``tr(`` before it and ``)``
after it.  ``_rewrap_tr.py`` removed the ``tr(`` half with a plain
``text.replace("tr(", "")``, which also bit ``str(``, ``getattr(``, ``setattr(``
and ``hasattr(`` - cutting them to ``s``, ``getat``, ``setat``, ``hasat``.

So exactly two repairs are needed, both mechanical:

1. delete the ``)`` that immediately follows each wrapped literal
   (``work/_ui_strings.json`` lists them all, with line numbers);
2. re-insert the ``tr(`` into each truncated call name, located from the
   pre-damage bytecode's ``(line, column)`` of the original call.

Nothing else is touched.  Files that still do not parse are printed with their
context and left alone - guessing a third kind of damage is what broke them
further last time.
"""

from __future__ import annotations

import ast
import dis
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


# ------------------------------------------------------------------ bytecode
def code_of(path: str):
    with open(path, "rb") as fh:
        data = fh.read()
    if data[:4] != importlib.util.MAGIC_NUMBER:
        return None
    return marshal.loads(data[16:])


def call_sites(code, out: list) -> None:
    if not isinstance(code, types.CodeType):
        return
    for ins in dis.get_instructions(code):
        if ins.opname not in ("LOAD_GLOBAL", "LOAD_NAME", "LOAD_ATTR", "LOAD_METHOD"):
            continue
        name = ins.argval if isinstance(ins.argval, str) else None
        if name not in VICTIMS:
            continue
        pos = getattr(ins, "positions", None)
        if pos is None or pos.lineno is None:
            continue
        out.append((pos.lineno, pos.col_offset or 0, name))
    for const in code.co_consts:
        if isinstance(const, types.CodeType):
            call_sites(const, out)


def sites_for(module: str) -> list:
    path = os.path.join(PYC, f"{module}.cpython-312.pyc")
    if not os.path.isfile(path):
        return []
    code = code_of(path)
    if code is None:
        return []
    out: list = []
    call_sites(code, out)
    return sorted(set(out), reverse=True)


def victim_counts(module: str) -> dict:
    out = {v: 0 for v in VICTIMS}
    for _line, _col, name in sites_for(module):
        out[name] = out.get(name, 0) + 1
    return out


# ------------------------------------------------------------------ literals
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


def wrapped(module: str) -> list:
    """[(line, text)] of the literals the wrapper put tr(...) around."""
    if not os.path.isfile(INVENTORY):
        return []
    with open(INVENTORY, encoding="utf-8") as fh:
        raw = json.load(fh)
    out = []
    for text, places in raw.items():
        for place in places:
            name, _, line = place.rpartition(":")
            if os.path.basename(name)[:-3] == module:
                out.append((int(line), text))
    return out


# ------------------------------------------------------------------- repair
def drop_parens(src: str, sites: list) -> tuple:
    """Delete the ``)`` the wrapper appended to each wrapped literal."""
    dropped = []
    for line, text in sites:
        for start, end, value in literals(src):
            if value != text:
                continue
            if src.count("\n", 0, start) + 1 != line:
                continue
            i = end
            while i < len(src) and src[i] in " \t":
                i += 1
            if i < len(src) and src[i] == ")":
                src = src[:i] + src[i + 1:]
                dropped.append(line)
            break
    return src, dropped


def restore_names(src: str, sites: list) -> tuple:
    """Put ``tr(`` back where a call name was cut short."""
    fixed = []
    for line, col, victim in sites:
        head = victim.replace("tr(", "")            # str -> s, getattr -> getat
        lines = src.splitlines(keepends=True)
        if line - 1 >= len(lines):
            continue
        text = lines[line - 1]
        for start in range(max(0, col - 3), min(len(text), col + 4)):
            if not text.startswith(head, start):
                continue
            if text.startswith(victim + "(", start):
                break                               # already intact
            after = start + len(head)
            if after >= len(text):
                break
            nxt = text[after]
            if not (nxt.isalnum() or nxt == "_"):
                break                               # complete name, not a call
            at = sum(len(x) for x in lines[:line - 1]) + after
            src = src[:at] + "tr(" + src[at:]
            fixed.append((line, victim))
            break
    return src, fixed


def count_calls(src: str, victim: str) -> int:
    out = 0
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
            j = i + 1
            while j < n:
                if src[j] == "\\":
                    j += 2
                    continue
                if src[j] == q:
                    break
                if src[j] == "\n":
                    break
                j += 1
            i = j + 1
            continue
        if src.startswith(victim + "(", i):
            before = src[i - 1] if i else " "
            if not (before.isalnum() or before == "_"):
                out += 1
            i += len(victim)
            continue
        i += 1
    return out


def context(src: str, exc: SyntaxError) -> str:
    lines = src.splitlines()
    lo = max(0, (exc.lineno or 1) - 3)
    hi = min(len(lines), (exc.lineno or 1) + 2)
    return "\n".join(f"      {i + 1:4d}|{lines[i]}" for i in range(lo, hi))


def main() -> int:
    bad = []
    for name in sorted(os.listdir(UI)):
        if not name.endswith(".py"):
            continue
        module = name[:-3]
        path = os.path.join(UI, name)
        src = open(path, encoding="utf-8").read()
        src, dropped = drop_parens(src, wrapped(module))
        src, names = restore_names(src, sites_for(module))
        problem = ""
        try:
            ast.parse(src)
        except SyntaxError as exc:
            problem = f"line {exc.lineno}: {exc.msg}"
        else:
            for victim, want in victim_counts(module).items():
                got = count_calls(src, victim)
                if want and got != want:
                    problem = f"{victim}: {got} call(s), bytecode says {want}"
                    break
        if problem:
            bad.append(name)
            print(f"=== {name}: dropped {len(dropped)}, names {len(names)} - {problem}")
            try:
                ast.parse(src)
            except SyntaxError as exc:
                print(context(src, exc))
            open(path, "w", encoding="utf-8", newline="\n").write(src)
            continue
        open(path, "w", encoding="utf-8", newline="\n").write(src)
        print(f"{name}: dropped {len(dropped)}, names {len(names)}  ok")
    print("\nstill broken:", bad or "none")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
