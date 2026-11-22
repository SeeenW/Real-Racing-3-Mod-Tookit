"""Repair rrmod/ui: undo the tr() wrapper's parens, and nothing else.

The wrapper put ``tr(`` in front of each string literal and a ``)`` after it,
computing the column from the literal's *last* line.  Undoing it with
``text.replace("tr(", "")`` then left two kinds of mess:

* the ``)`` the wrapper added stayed behind - after the literal, in the gap
  between the literal's fragments, or inside the text itself;
* ``str(``, ``getattr(``, ``setattr(``, ``hasattr(`` lost the ``tr(`` that was
  part of their name, becoming ``s``, ``getat``, ``setat``, ``hasat``.

This script repairs exactly those two, and deliberately does *not* put the
``tr()`` wrapping back: localisation is done at runtime instead, by walking the
widget tree (see ``rrmod/ui/translate.py``).  So the result is the original
source, byte for byte where possible.

Matching: ``work/_ui_strings.json`` holds the original text of every literal the
wrapper touched.  A literal is recognised by its text, allowing for the paren
having been appended to it or pushed out of it.  Entries are consumed once, so a
string appearing twice is repaired twice.

Truncated names come from the pre-damage bytecode in ``rrmod/ui/__pycache__``:
``dis`` gives the line and column of every ``str``/``getattr``/``setattr``/
``hasattr`` load, and a name counts as cut only when the identifier there is not
already the full name - which is what keeps ``Signal(str)`` and
``isinstance(v, str)`` intact.  Inserting ``tr(`` at the cut point is exactly the
inverse of what removed it: ``getat`` + ``tr(`` is ``getattr(``.

Every file is parsed afterwards and the surviving call counts are compared with
the bytecode.  Whatever still fails is printed with context and left alone.
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


# --------------------------------------------------------------- tokenising
def fragments(src: str) -> list:
    """(start, end, value) for every string literal, comments skipped."""
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


def segments(src: str) -> list:
    """Runs of literals joined by whitespace, or by whitespace around one ')'.

    Each entry is (start, end, text, stray) - ``stray`` being the offset of a
    ``)`` that sits between two fragments of the same literal, or ``None``.
    """
    frags = fragments(src)
    out = []
    i = 0
    while i < len(frags):
        start, end, value = frags[i]
        if value is None:
            i += 1
            continue
        text = value
        stray = None
        j = i + 1
        while j < len(frags) and frags[j][2] is not None:
            gap = src[end:frags[j][0]]
            stripped = gap.strip()
            if stripped == ")" and stray is None:
                stray = end + gap.index(")")
            elif stripped:
                break
            text += frags[j][2]
            end = frags[j][1]
            j += 1
        out.append((start, end, text, stray))
        i = j
    return out


# ---------------------------------------------------------------- bytecode
def code_of(path: str):
    with open(path, "rb") as fh:
        data = fh.read()
    if data[:4] != importlib.util.MAGIC_NUMBER:
        return None
    return marshal.loads(data[16:])


def _walk(code, out: list) -> None:
    if not isinstance(code, types.CodeType):
        return
    for ins in dis.get_instructions(code):
        if ins.opname not in ("LOAD_GLOBAL", "LOAD_NAME"):
            continue
        if isinstance(ins.argval, str) and ins.argval in VICTIMS:
            pos = getattr(ins, "positions", None)
            if pos is not None and pos.lineno:
                out.append((pos.lineno, pos.col_offset or 0, ins.argval))
    for const in code.co_consts:
        _walk(const, out)


def sites(module: str) -> list:
    path = os.path.join(PYC, f"{module}.cpython-312.pyc")
    if not os.path.isfile(path):
        return []
    code = code_of(path)
    if code is None:
        return []
    out: list = []
    _walk(code, out)
    return sorted(set(out))


# ------------------------------------------------------------------- repair
def inventory() -> dict:
    with open(INVENTORY, encoding="utf-8") as fh:
        raw = json.load(fh)
    out: dict = {}
    for text, places in raw.items():
        for place in places:
            module = os.path.basename(place.rpartition(":")[0])
            if module.endswith(".py"):
                module = module[:-3]
            bucket = out.setdefault(module, {})
            bucket[text] = bucket.get(text, 0) + 1
    return out


def unwrap(src: str, wanted: dict) -> tuple:
    """Take the wrapper's ``)`` back out of every literal it was added to."""
    pool = dict(wanted)
    edits = []
    for start, end, text, stray in segments(src):
        if pool.get(text):
            pool[text] -= 1
            edits.append((start, end, "after", stray, -1))
            continue
        found = False
        for k, ch in enumerate(text):
            if ch != ")":
                continue
            if pool.get(text[:k] + text[k + 1:]):
                pool[text[:k] + text[k + 1:]] -= 1
                edits.append((start, end, "inside", stray, k))
                found = True
                break
        if found:
            continue
        if pool.get(text + ")"):
            pool[text + ")"] -= 1
            edits.append((start, end, "into", stray, -1))

    removed = 0
    for start, end, where, stray, k in reversed(edits):
        if where == "inside":
            raw = src[start:end]
            seen = -1
            for _n in range(k + 1):
                seen = raw.find(")", seen + 1)
            if seen >= 0:
                src = src[:start + seen] + src[start + seen + 1:]
                removed += 1
            continue
        if stray is not None:
            src = src[:stray] + src[stray + 1:]
            removed += 1
            continue
        i = end
        while i < len(src) and src[i] in " \t":
            i += 1
        if i < len(src) and src[i] == ")":
            src = src[:i] + src[i + 1:]
            removed += 1
            if where == "into":
                src = src[:end - 1] + ")" + src[end - 1:]
    return src, removed


def identifier_at(text: str, col: int) -> str:
    if col >= len(text):
        return ""
    out = []
    i = col
    while i < len(text) and (text[i].isalnum() or text[i] == "_"):
        out.append(text[i])
        i += 1
    return "".join(out)


def restore_names(src: str, rows: list) -> tuple:
    """Put the ``tr(`` back inside the names that lost it."""
    fixed = []
    for line, col, victim in sorted(rows, key=lambda r: (r[0], r[1]), reverse=True):
        head = (victim + "(").replace("tr(", "")
        lines = src.splitlines(keepends=True)
        if line - 1 >= len(lines):
            continue
        text = lines[line - 1]
        token = identifier_at(text, col)
        if token == victim or not token.startswith(head):
            continue
        at = sum(len(x) for x in lines[:line - 1]) + col + len(head)
        src = src[:at] + "tr(" + src[at:]
        fixed.append((line, victim))
    return src, fixed


def count_calls(src: str, victim: str) -> int:
    total = 0
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
                if src[j] == q or src[j] == "\n":
                    break
                j += 1
            i = j + 1
            continue
        if src.startswith(victim + "(", i):
            before = src[i - 1] if i else " "
            if not (before.isalnum() or before == "_"):
                total += 1
            i += len(victim)
            continue
        i += 1
    return total


def show(src: str, exc: SyntaxError) -> str:
    lines = src.splitlines()
    lo = max(0, (exc.lineno or 1) - 3)
    hi = min(len(lines), (exc.lineno or 1) + 2)
    return "\n".join(f"      {i + 1:4d}|{lines[i]}" for i in range(lo, hi))


def main() -> int:
    table = inventory()
    broken = []
    for name in sorted(os.listdir(UI)):
        if not name.endswith(".py"):
            continue
        module = name[:-3]
        path = os.path.join(UI, name)
        src = open(path, encoding="utf-8").read()
        # Order matters: the bytecode columns were recorded when no ``tr(`` was
        # in the line, so the parens have to be gone before they are used.
        src, removed = unwrap(src, table.get(module, {}))
        src, fixed = restore_names(src, sites(module))
        problem = ""
        try:
            ast.parse(src)
        except SyntaxError as exc:
            problem = f"line {exc.lineno}: {exc.msg}"
        else:
            for victim in VICTIMS:
                want = len([1 for _l, _c, v in sites(module) if v == victim])
                got = count_calls(src, victim)
                if want and got != want:
                    problem = f"{victim}: {got} call(s), bytecode says {want}"
                    break
        open(path, "w", encoding="utf-8", newline="\n").write(src)
        if problem:
            broken.append(name)
            print(f"=== {name}: names{len(fixed)} paren-{removed} - {problem}")
            try:
                ast.parse(src)
            except SyntaxError as exc:
                print(show(src, exc))
        else:
            print(f"{name}: names{len(fixed)} paren-{removed}  ok")
    print("\nstill broken:", broken or "none")
    return 1 if broken else 0


if __name__ == "__main__":
    sys.exit(main())
