"""Undo _wrap_tr.py and redo it with correct multi-line offsets.

What went wrong: ``ast`` reports ``end_col_offset`` as an offset into the *last*
line of a multi-line string literal, but the wrapper applied it to the *first*.
For a literal that spans lines the offset ran past the end of line 1, so the
closing paren was appended there:

    lay.addWidget(W.muted(tr("Point at the folder that contains "
                             ".depot and apk."))

The ``tr(`` half of the edit was always correct, so the repair is:

1. delete every ``from ..i18n import tr`` line and every ``tr(`` we inserted;
2. delete each ``)`` that is immediately followed by a string literal - that
   shape is never legal Python, so it can only be our stray paren;
3. re-wrap using ``(lineno, col_offset)`` .. ``(end_lineno, end_col_offset)``
   converted to absolute offsets, editing from the end of the file backwards.
"""

from __future__ import annotations

import ast
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UI = os.path.join(ROOT, "rrmod", "ui")

UI_CALLS = {
    "setText", "setPlaceholderText", "setToolTip", "setWindowTitle", "setTitle",
    "addTab", "addItem", "setHorizontalHeaderLabels", "heading", "muted",
    "button", "pill", "add", "note", "error", "ok", "question", "warning",
    "critical", "information", "setTabText", "addAction", "setStatusTip",
}

IMPORT_LINE = re.compile(r"^from \.\.i18n import tr\s*$\n?", re.MULTILINE)
#: a close paren with nothing but whitespace before a quote - always our mistake
STRAY = re.compile(r"\)(?=\s*[\"'])")


def unwrap(text: str) -> str:
    text = IMPORT_LINE.sub("", text)
    return text.replace("tr(", "")


def repair(text: str) -> tuple:
    removed = 0
    for _ in range(400):
        try:
            ast.parse(text)
            return text, removed
        except SyntaxError:
            pass
        m = STRAY.search(text)
        if not m:
            return text, removed
        text = text[:m.start()] + text[m.end():]
        removed += 1
    return text, removed


def wrap(text: str) -> tuple:
    tree = ast.parse(text)
    lines = text.splitlines(keepends=True)

    def offset(lineno: int, col: int) -> int:
        return sum(len(x) for x in lines[:lineno - 1]) + col

    edits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
        if name not in UI_CALLS:
            continue
        for arg in node.args:
            if not isinstance(arg, ast.Constant) or not isinstance(arg.value, str):
                continue
            if not arg.value.strip():
                continue
            edits.append((offset(arg.lineno, arg.col_offset),
                          offset(arg.end_lineno, arg.end_col_offset)))
    for start, end in sorted(edits, reverse=True):
        text = text[:start] + "tr(" + text[start:end] + ")" + text[end:]
    marker = "from __future__ import annotations\n"
    at = text.find(marker)
    at = at + len(marker) if at >= 0 else 0
    text = text[:at] + "\nfrom ..i18n import tr\n" + text[at:]
    return text, len(edits)


def main() -> int:
    bad = []
    for name in sorted(os.listdir(UI)):
        if not name.endswith(".py") or name == "widgets.py":
            continue
        path = os.path.join(UI, name)
        text = open(path, encoding="utf-8").read()
        if "tr(" in text or "from ..i18n import tr" in text:
            text = unwrap(text)
        text, removed = repair(text)
        try:
            ast.parse(text)
        except SyntaxError as exc:
            print(f"{name}: cannot repair ({removed} removed): {exc}")
            bad.append(name)
            open(path, "w", encoding="utf-8", newline="\n").write(text)
            continue
        text, n = wrap(text)
        open(path, "w", encoding="utf-8", newline="\n").write(text)
        try:
            ast.parse(text)
        except SyntaxError as exc:
            print(f"{name}: BROKEN after wrap: {exc}")
            bad.append(name)
            continue
        print(f"{name}: removed {removed}, wrapped {n}")
    print("broken:", bad or "none")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
