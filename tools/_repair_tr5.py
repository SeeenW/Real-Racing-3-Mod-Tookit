"""Restore the tr() wrapping on the damaged UI sources.

What the wrapper did to every string literal it touched:

* put ``tr(`` in front of it, and
* put a ``)`` after it - at a column computed from the literal's *last* line.

So for a single-line literal the paren landed where it belongs and only the
``tr(`` is missing; for a literal spanning several lines the paren landed inside
the text (``"...data pack)age..."``) or at the end of the first line, and both it
and the ``tr(`` have to be put right.

``work/_ui_strings.json`` records the original text of each wrapped literal, so a
literal is recognised by its text alone; entries are consumed once, so a string
that occurs twice is wrapped twice and no more.

The second kind of damage is ``str(`` -> ``s``, ``getattr(`` -> ``getat``: the
undo step removed ``tr(`` with a plain string replace and those names contain it.
The pre-damage bytecode in ``rrmod/ui/__pycache__`` gives the line and column of
every ``str``/``getattr``/``setattr``/``hasattr`` load; a name counts as cut only
when the identifier there is not already the full name, which is what keeps
``Signal(str)`` and ``isinstance(v, str)`` intact.  Putting ``tr(`` back at the
cut point is exactly the inverse: ``getat`` + ``tr(`` = ``getattr(``.

Every file is parsed after the edit and the surviving call counts are compared
with the bytecode.  Anything still broken is printed with context and left alone.
"""

from __future__ import annotations

import ast
import dis
import importlib.util
import json
import marshal
import os
import re
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UI = os.path.join(ROOT, "rrmod", "ui")
PYC = os.path.join(UI, "__pycache__")
INVENTORY = os.path.join(ROOT, "work", "_ui_strings.json")

VICTIMS = ("getattr", "setattr", "hasattr", "str")
QUOTES = "\"'"
GAP_PAREN = re.compile(r"^\s*\)\s*$")


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

    Each entry is (start, end, text, stray) where ``stray`` is the offset of a
    ``)`` that sits between two fragments (``None`` when there is none).
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
            if GAP_PAREN.match(gap) and stray is None:
                stray = end + gap.index(")")
            elif gap.strip():
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
            name = place.rpartition(":")[0]
            module = os.path.basename(name)
            if module.endswith(".py"):
                module = module[:-3]
            out.setdefault(module, {})
            out[module][text] = out[module].get(text, 0) + 1
    return out


def rewrap(src: str, wanted: dict) -> tuple:
    pool = dict(wanted)
    edits = []
    for start, end, text, stray in segments(src):
        if pool.get(text):
            pool[text] -= 1
            edits.append((start, end, None, stray))
            continue
        hit = None
        for k, ch in enumerate(text):
            if ch != ")":
                continue
            trimmed = text[:k] + text[k + 1:]
            if pool.get(trimmed):
                hit = (k, trimmed)
                break
        if hit is None:
            continue
        k, trimmed = hit
        pool[trimmed] -= 1
        edits.append((start, end, k, stray))

    added = 0
    moved = 0
    for start, end, inside, stray in reversed(edits):
        if inside is not None:
            raw = src[start:end]
            seen = -1
            for _n in range(inside + 1):
                seen = raw.find(")", seen + 1)
            if seen >= 0:
                src = src[:start + seen] + src[start + seen + 1:]
                end -= 1
            moved += 1
        elif stray is not None:
            src = src[:stray] + src[stray + 1:]
            end -= 1
            moved += 1
        if inside is not None or stray is not None:
            src = src[:end] + ")" + src[end:]
        src = src[:start] + "tr(" + src[start:]
        added += 1
    return src, added, moved


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
    fixed = []
    for line, col, victim in rows:
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
        src, added, moved = rewrap(src, table.get(module, {}))
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
            print(f"=== {name}: tr+{added} moved{moved} names{len(fixed)} - {problem}")
            try:
                ast.parse(src)
            except SyntaxError as exc:
                print(show(src, exc))
        else:
            print(f"{name}: tr+{added} moved{moved} names{len(fixed)}  ok")
    print("\nstill broken:", broken or "none")
    return 1 if broken else 0


if __name__ == "__main__":
    sys.exit(main())
