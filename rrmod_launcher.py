"""Frozen entry point for the RR3 Mod Manager.

PyInstaller needs a plain script, not a package ``__main__``.  This file only
exists so the build has one obvious thing to point at; running it from source
behaves exactly like ``python -m rrmod``.

Two things happen here that do not happen in a normal run:

* a windowed exe has no console, so ``--check`` output and any traceback would
  vanish.  Both are mirrored to ``rrmod_check.log`` / ``rrmod_crash.log`` next
  to the executable, which is the only way to debug a double-clicked launch.
"""

from __future__ import annotations

import os
import sys
import traceback


def _home() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def _bootstrap() -> None:
    """Make ``rrmod`` and ``rr3lib`` importable when frozen or run in place."""
    if getattr(sys, "frozen", False):
        # PyInstaller puts the packages beside the executable inside _MEIPASS,
        # which is already on sys.path; nothing to do.
        return
    here = _home()
    if here not in sys.path:
        sys.path.insert(0, here)


class _Tee:
    """Write to the real stdout and to a file, so a windowed run leaves a trace."""

    def __init__(self, stream, path: str):
        self.stream = stream
        self.fh = open(path, "w", encoding="utf-8", errors="replace")

    def write(self, text: str) -> int:
        self.fh.write(text)
        self.fh.flush()
        if self.stream is not None:
            try:
                self.stream.write(text)
            except Exception:                    # no console at all
                pass
        return len(text)

    def flush(self) -> None:
        self.fh.flush()


def _crash(exc_type, exc, tb) -> None:
    text = "".join(traceback.format_exception(exc_type, exc, tb))
    try:
        with open(os.path.join(_home(), "rrmod_crash.log"), "w",
                  encoding="utf-8", errors="replace") as fh:
            fh.write(text)
    except OSError:
        pass
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox
        app = QApplication.instance() or QApplication([])
        QMessageBox.critical(None, "RR3 Mod Manager crashed",
                             f"{exc_type.__name__}: {exc}\n\n{text[-3000:]}")
    except Exception:                            # no Qt, or already tearing down
        pass


if __name__ == "__main__":
    _bootstrap()
    if getattr(sys, "frozen", False):
        sys.excepthook = _crash
        if "--check" in sys.argv:
            sys.stdout = sys.stderr = _Tee(sys.stdout,
                                           os.path.join(_home(), "rrmod_check.log"))
    from rrmod.main import main

    raise SystemExit(main())
