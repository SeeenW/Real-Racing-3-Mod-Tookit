"""Repair the UI sources after the botched tr() wrapping - driven by the parser.

The three earlier scripts left two kinds of damage, and both are now repaired
from information the parser itself supplies:

* **truncated call names.**  ``str(``, ``getattr(``, ``setattr(`` and ``hasattr(``
  all contain ``tr(``, so ``text.replace("tr(", "")`` cut them short:
  ``str(x)`` became ``sx)``, ``getattr(sys, ...)`` became ``getatsys, ...``.
  The ``__pycache__`` bytecode predates the damage, so its identifier vocabulary
  says which words are real; a word that only exists because of the truncation is
  put back as ``victim + "(" + rest``.

* **wrong parens.**  The undo step deleted ``)`` both where the wrapper had added
  one and where the code needed it.  Python reports the exact line and column of
  the offending paren, so each error is fixed where it is:

  - ``unmatched ')'``                  -> delete the ``)`` at (lineno, offset)
  - ``closing parenthesis ')' does not
    match opening parenthesis ...``     -> delete the ``)`` at (lineno, offset)
  - ``'(' was never closed``           -> append ``)`` to that line

  The loop re-parses after every single change and gives up (leaving the file
  untouched) if it stops making progress.
"""

from __future__ import annotations

import ast
import builtins
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
    """Blank out comments and string literals, keeping every offset intact."""
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
            for k in range(i, min(j, n)):
                if chars[k] != "\n":
                    chars[k] = " "
            i = j
            continue
        i += 1
    return "".join(chars)


def fix_names(src: str, known: set) -> tuple:
    """Put back the call names the substring removal truncated."""
    if not known:
        return src, []
    fixed = []
    for _ in range(300):
        text = mask(src)
        hit = None
        i = 0
        n = len(text)
        while i < n:
            ch = text[i]
            if ch.isalpha() or ch == "_":
                j = i
                while j < n and (text[j].isalnum() or text[j] == "_"):
                    j += 1
                word = text[i:j]
                if word not in known and word not in dir(builtins):
                    for victim in VICTIMS:
                        head = victim.replace("tr(", "")
                        if not head or not word.startswith(head) or word == head:
                            continue
                        rest = word[len(head):]
                        if rest and rest not in known and rest not in dir(builtins):
                            continue
                        hit = (i, j, victim + "(" + rest)
                        break
                if hit is not None:
                    break
                i = j
                continue
            i += 1
        if hit is None:
            return src, fixed
        start, end, new = hit
        fixed.append((new, src.count("\n", 0, start) + 1))
        src = src[:start] + new + src[end:]
    return src, fixed


def fix_parse(src: str) -> tuple:
    """Repair parens one parser error at a time."""
    fixes = []
    for _ in range(400):
        try:
            ast.parse(src)
            return src, fixes
        except SyntaxError as exc:
            msg = exc.msg or ""
            lines = src.splitlines(keepends=True)
            row = (exc.lineno or 1) - 1
            col = (exc.offset or 1) - 1
            if row >= len(lines):
                return src, fixes
            line = lines[row]
            if "unmatched ')'" in msg or "does not match opening" in msg:
                if col < len(line) and line[col] == ")":
                    lines[row] = line[:col] + line[col + 1:]
                else:
                    at = line.rfind(")")
                    if at < 0:
                        return src, fixes
                    lines[row] = line[:at] + line[at + 1:]
                fixes.append((row + 1, "dropped a ')'"))
            elif "was never closed" in msg:
                body = line.rstrip("\r\n")
                lines[row] = body + ")" + line[len(body):]
                fixes.append((row + 1, "added a ')'"))
            elif "invalid syntax" in msg and col >= len(line.rstrip("\r\n")):
                # a closer is missing at the end of this line
                body = line.rstrip("\r\n")
                lines[row] = body + ")" + line[len(body):]
                fixes.append((row + 1, "added a ')' at end of line"))
            else:
                return src, fixes
            src = "".join(lines)
    return src, fixes


def main() -> int:
    bad = []
    for name in sorted(os.listdir(UI)):
        if not name.endswith(".py"):
            continue
        module = name[:-3]
        path = os.path.join(UI, name)
        src = open(path, encoding="utf-8").read()
        src, names = fix_names(src, vocab(module))
        src, parens = fix_parse(src)
        try:
            ast.parse(src)
        except SyntaxError as exc:
            bad.append(name)
            print(f"=== {name}: names {len(names)}, parens {len(parens)}"
                  f" - line {exc.lineno}: {exc.msg}")
            for line, what in (names + parens)[:6]:
                print(f"      line {line}: {what}")
            continue
        open(path, "w", encoding="utf-8", newline="\n").write(src)
        print(f"{name}: names {len(names)}, parens {len(parens)}  ok")
    print("\nstill broken:", bad or "none")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
