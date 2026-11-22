"""Balance the brackets in rrmod/ui, one line at a time, under the parser's eye.

The damage is all of one family - the wrapper added or lost a ``)`` - so instead
of guessing at patterns this walks the parser's own complaints: take the line the
parser objects to, try the handful of plausible one-line repairs (add a paren,
drop a paren, on that line or the one before), and keep the first that moves the
error further down the file.  Anything that does not move it is rejected, so a
correct line is never touched.

The three name repairs (``sexc`` -> ``str(exc)`` and friends) run first, since a
missing ``tr(`` is not a bracket problem.
"""

from __future__ import annotations

import ast
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UI = os.path.join(ROOT, "rrmod", "ui")

NAME_RULES = [
    (re.compile(r"(?<![\w.])sexc\b"), "str(exc)"),
    (re.compile(r"(?<![\w.])smessage\b"), "str(message)"),
    (re.compile(r"(?<![\w.])srow\b"), "str(row)"),
    (re.compile(r"(?<![\w.])slaps\b"), "str(laps)"),
    (re.compile(r"(?<![\w.])sfame\b"), "str(fame)"),
    (re.compile(r"(?<![\w.])sreward\b"), "str(reward)"),
    (re.compile(r"(?<![\w.])stext\b"), "str(text)"),
    (re.compile(r"(?<![\w.])spath\b"), "str(path)"),
    (re.compile(r"(?<![\w.])svalue\b"), "str(value)"),
    (re.compile(r"(?<![\w.])sname\b"), "str(name)"),
    (re.compile(r"(?<![\w.])sindex\b"), "str(index)"),
    (re.compile(r"(?<![\w.])se\."), "str(e."),
    (re.compile(r"(?<![\w.])getatsys\b"), "getattr(sys"),
    (re.compile(r"(?<![\w.])setatsys\b"), "setattr(sys"),
    (re.compile(r"(?<![\w.])hasatsys\b"), "hasattr(sys"),
]


def error_line(src: str) -> int:
    try:
        ast.parse(src)
    except SyntaxError as exc:
        return exc.lineno or 0
    return 0


def show(src: str, line: int) -> str:
    lines = src.splitlines()
    lo = max(0, line - 3)
    hi = min(len(lines), line + 2)
    return "\n".join(f"      {i + 1:4d}|{lines[i]}" for i in range(lo, hi))


def candidates(src: str, line: int) -> list:
    """Plausible one-line bracket repairs, nearest line first."""
    lines = src.splitlines(keepends=True)
    out = []
    for target in (line, line - 1, line + 1):
        if not 1 <= target <= len(lines):
            continue
        text = lines[target - 1]
        body = text.rstrip("\n")
        tail = text[len(body):]
        if body.strip() and not body.lstrip().startswith("#"):
            out.append((target, body + ")" + tail))
        cut = body.rfind(")")
        if cut >= 0:
            out.append((target, body[:cut] + body[cut + 1:] + tail))
    return out


def repair(src: str, limit: int = 400) -> tuple:
    applied = []
    for _ in range(limit):
        before = error_line(src)
        if not before:
            break
        lines = src.splitlines(keepends=True)
        done = False
        for target, text in candidates(src, before):
            trial = "".join(lines[:target - 1]) + text + "".join(lines[target:])
            after = error_line(trial)
            if after and after > before:
                src = trial
                applied.append((before, target))
                done = True
                break
            if not after:
                src = trial
                applied.append((before, target))
                return src, applied
        if not done:
            break
    return src, applied


def main() -> int:
    for name in sorted(os.listdir(UI)):
        if not name.endswith(".py"):
            continue
        path = os.path.join(UI, name)
        src = open(path, encoding="utf-8").read()
        for pattern, repl in NAME_RULES:
            src = pattern.sub(repl, src)
        if error_line(src):
            src, applied = repair(src)
            print(f"{name}: {len(applied)} bracket edit(s)")
        else:
            applied = []
        open(path, "w", encoding="utf-8", newline="\n").write(src)
        line = error_line(src)
        if line:
            print(f"=== {name}: still line {line}")
            print(show(src, line))

    broken = []
    for name in sorted(os.listdir(UI)):
        if not name.endswith(".py"):
            continue
        src = open(os.path.join(UI, name), encoding="utf-8").read()
        if error_line(src):
            broken.append(name)
    print("\nstill broken:", broken or "none")
    return 1 if broken else 0


if __name__ == "__main__":
    sys.exit(main())
