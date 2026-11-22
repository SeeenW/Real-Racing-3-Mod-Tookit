"""One-off: wrap interface string literals in tr(...) so they can be translated.

Only string constants that are the *direct argument* of a UI-facing call are
touched, and the rewrite is done from AST positions, so nothing else in the file
moves.  Running it twice is a no-op because the second pass sees a Call, not a
Constant.
"""

from __future__ import annotations

import ast
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG = os.path.join(ROOT, "rrmod")

UI_CALLS = {
    "setText", "setPlaceholderText", "setToolTip", "setWindowTitle", "setTitle",
    "addTab", "addItem", "setHorizontalHeaderLabels", "heading", "muted",
    "button", "pill", "add", "note", "error", "ok", "question", "warning",
    "critical", "information", "setTabText", "addAction", "setStatusTip",
    "setWindowTitle", "setText",
}

#: names that already return translated text - wrapping them again is harmless
#: but pointless, so they are skipped
SKIP = {"tr"}


def process(path: str) -> int:
    src = open(path, encoding="utf-8").read()
    tree = ast.parse(src)
    lines = src.splitlines(keepends=True)
    edits = []                                  # (lineno, col, end_col)
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
            edits.append((arg.lineno, arg.col_offset, arg.end_col_offset,
                          arg.value))
    if not edits:
        return 0
    # apply from the end so earlier offsets stay valid
    edits.sort(key=lambda e: (e[0], e[1]), reverse=True)
    for lineno, col, end_col, _value in edits:
        line = lines[lineno - 1]
        piece = line[col:end_col]
        lines[lineno - 1] = line[:col] + "tr(" + piece + ")" + line[end_col:]
    out = "".join(lines)
    if "from ..i18n import tr" not in out and "from .i18n import tr" not in out:
        # after the __future__ import, before the first blank-line-separated block
        marker = "from __future__ import annotations\n"
        at = out.find(marker)
        if at >= 0:
            at += len(marker)
            out = out[:at] + "\nfrom ..i18n import tr\n" + out[at:]
        else:
            out = "from ..i18n import tr\n" + out
    open(path, "w", encoding="utf-8", newline="\n").write(out)
    return len(edits)


def main(argv=None) -> int:
    total = 0
    for name in sorted(os.listdir(os.path.join(PKG, "ui"))):
        if not name.endswith(".py") or name == "widgets.py":
            continue
        path = os.path.join(PKG, "ui", name)
        n = process(path)
        if n:
            print(f"{name}: {n}")
            total += n
    print(f"total {total}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
