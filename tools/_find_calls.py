"""Find the exact lines where ``str(``, ``getattr(``, ``setattr(`` or ``hasattr(``
was called, according to the pre-damage bytecode.

Deleting the substring ``tr(`` also cut those four call names short, and the
result (``sx)``, ``getatsys, ...``) is often still valid Python.  Guessing which
words were truncated is ambiguous - ``self`` looks like ``str(elf`` - but the
bytecode compiled before the damage records every call with its line number, so
the sites can be listed exactly.
"""

from __future__ import annotations

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


def load(pyc_path: str):
    with open(pyc_path, "rb") as fh:
        data = fh.read()
    if data[:4] != importlib.util.MAGIC_NUMBER:
        return None
    return marshal.loads(data[16:])


def calls(code, out: list) -> None:
    if not isinstance(code, types.CodeType):
        return
    for ins in dis.get_instructions(code):
        name = None
        if ins.opname in ("LOAD_GLOBAL", "LOAD_NAME", "LOAD_ATTR", "LOAD_METHOD"):
            arg = ins.argval
            name = arg if isinstance(arg, str) else None
        if name in VICTIMS:
            line = None
            pos = getattr(ins, "positions", None)
            if pos is not None:
                line = pos.lineno
            out.append((line, name))
    for const in code.co_consts:
        if isinstance(const, types.CodeType):
            calls(const, out)


def main() -> int:
    for name in sorted(os.listdir(PYC)):
        if not name.endswith(".pyc"):
            continue
        module = name.split(".")[0]
        code = load(os.path.join(PYC, name))
        if code is None:
            print(f"{module}: unusable bytecode")
            continue
        out: list = []
        calls(code, out)
        if not out:
            continue
        src = os.path.join(UI, f"{module}.py")
        lines = open(src, encoding="utf-8").read().splitlines() \
            if os.path.isfile(src) else []
        print(f"=== {module}: {len(out)} call(s)")
        for line, victim in sorted(out, key=lambda x: (x[0] or 0)):
            now = lines[line - 1].strip() if line and line <= len(lines) else ""
            print(f"   line {line:4d}  {victim:9}  | {now[:96]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
