"""Repair the UI sources using the pre-damage bytecode as ground truth.

What happened, and why the repair can be exact:

1. ``_wrap_tr.py`` inserted ``tr(`` before every UI string literal and ``)``
   after it.
2. ``_rewrap_tr.py`` undid that with ``text.replace("tr(", "")``.  That substring
   also occurs inside ``str(``, ``getattr(``, ``setattr(`` and ``hasattr(``, so
   those calls were cut short: ``str(x)`` became ``sx)`` - still valid Python,
   hence silent.
3. Two more passes then removed ``)`` in places where the code needed them.

The ``__pycache__`` bytecode predates all of it, so it records both the
identifier vocabulary and the ``(line, column)`` of every call to those four
names.  Three rules follow:

**names.**  At each recorded site, a truncated name is one where the victim's
head (``str`` -> ``s``, ``getattr`` -> ``getat``) is followed by an *identifier
character* - that is exactly the signature of the missing ``tr(``.  ``Signal(str)``
is left alone because ``)`` follows.

**parens.**  Python reports the position of the offending paren, so each error is
repaired where it is: an unmatched or mismatched ``)`` is deleted; a ``(`` that
was never closed gets one ``)`` at the end of its logical line - but only when
that line really has more ``(`` than ``)``.

**verification.**  Every file must parse, and the number of ``str(``/``getattr(``
calls must match the bytecode count, before it is written.
"""

from __future__ import annotations

import ast
import dis
import importlib.util
import marshal
import os
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UI = os.path.join(ROOT, "rrmod", "ui")
PYC = os.path.join(UI, "__pycache__")

VICTIMS = ("getattr", "setattr", "hasattr", "str")
QUOTES = "\"'"


# ------------------------------------------------------------------ bytecode
def code_of(pyc_path: str):
    with open(pyc_path, "rb") as fh:
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


# ------------------------------------------------------------------- repair
def restore_names(src: str, sites: list) -> tuple:
    """Insert the missing ``tr(`` where a call name was cut short."""
    fixed = []
    for line, col, victim in sites:
        head = victim.replace("tr(", "")           # str -> s, getattr -> getat
        lines = src.splitlines(keepends=True)
        if line - 1 >= len(lines):
            continue
        text = lines[line - 1]
        for start in range(max(0, col - 3), min(len(text), col + 4)):
            if not text.startswith(head, start):
                continue
            after = start + len(head)
            if text.startswith(victim + "(", start):
                break                              # already intact
            if after >= len(text):
                break
            nxt = text[after]
            if not (nxt.isalnum() or nxt == "_"):
                break                              # complete name, not a call
            at = sum(len(x) for x in lines[:line - 1]) + after
            src = src[:at] + "tr(" + src[at:]
            fixed.append((line, victim))
            break
    return src, fixed


def balance(line: str) -> int:
    """How many ``(`` are still open at the end of this line."""
    text = line
    i = 0
    n = len(text)
    depth = 0
    while i < n:
        ch = text[i]
        if ch == "#":
            break
        if ch in QUOTES:
            q = ch
            j = i + 1
            while j < n:
                if text[j] == "\\":
                    j += 2
                    continue
                if text[j] == q:
                    break
                j += 1
            i = j + 1
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        i += 1
    return depth


def fix_parse(src: str) -> tuple:
    """Repair parens one parser error at a time."""
    fixes = []
    for _ in range(600):
        try:
            ast.parse(src)
            return src, fixes
        except SyntaxError as exc:
            msg = exc.msg or ""
            lines = src.splitlines(keepends=True)
            row = (exc.lineno or 1) - 1
            if row < 0 or row >= len(lines):
                return src, fixes
            col = (exc.offset or 1) - 1
            line = lines[row]
            if "unmatched ')'" in msg or "does not match opening" in msg:
                if 0 <= col < len(line) and line[col] == ")":
                    lines[row] = line[:col] + line[col + 1:]
                else:
                    at = line.rfind(")")
                    if at < 0:
                        return src, fixes
                    lines[row] = line[:at] + line[at + 1:]
                fixes.append((row + 1, "dropped ')'"))
            elif "was never closed" in msg or (
                    "invalid syntax" in msg and balance(line) > 0):
                body = line.rstrip("\r\n")
                lines[row] = body + ")" + line[len(body):]
                fixes.append((row + 1, "added ')'"))
            else:
                return src, fixes
            src = "".join(lines)
    return src, fixes


def context(src: str, exc: SyntaxError) -> str:
    lines = src.splitlines()
    lo = max(0, (exc.lineno or 1) - 3)
    hi = min(len(lines), (exc.lineno or 1) + 2)
    return "\n".join(f"      {i + 1:4d}|{lines[i]}" for i in range(lo, hi))


def count_calls(src: str, victim: str) -> int:
    """How often ``victim(`` appears outside strings and comments."""
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


def main() -> int:
    bad = []
    for name in sorted(os.listdir(UI)):
        if not name.endswith(".py"):
            continue
        module = name[:-3]
        path = os.path.join(UI, name)
        src = open(path, encoding="utf-8").read()
        src, names = restore_names(src, sites_for(module))
        src, parens = fix_parse(src)
        problem = ""
        try:
            ast.parse(src)
        except SyntaxError as exc:
            problem = f"line {exc.lineno}: {exc.msg}"
        else:
            want = victim_counts(module)
            for victim, count in want.items():
                got = count_calls(src, victim)
                if count and got != count:
                    problem = f"{victim}: {got} call(s), bytecode says {count}"
                    break
        if problem:
            bad.append(name)
            print(f"=== {name}: names {len(names)}, parens {len(parens)} - {problem}")
            try:
                ast.parse(src)
            except SyntaxError as exc:
                print(context(src, exc))
            open(path, "w", encoding="utf-8", newline="\n").write(src)
            continue
        open(path, "w", encoding="utf-8", newline="\n").write(src)
        print(f"{name}: names {len(names)}, parens {len(parens)}  ok")
    print("\nstill broken:", bad or "none")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
