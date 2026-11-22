"""Run slow work off the GUI thread.

Scanning 540 cars takes 0.8 s and building a car about a second, so nothing here
is strictly necessary - but deploying pushes a few hundred files over adb and
*that* would freeze the window for a minute.  A single helper keeps the calling
code uniform:

    task = Task(lambda: depotlib.scan(root), parent=self)
    task.done.connect(self._scanned)
    task.fail.connect(self._error)
    task.start()

``QThread`` subclasses are used rather than ``QRunnable`` because the result
travels back through a signal either way, and this way the task can be waited on
without touching a thread pool.
"""

from __future__ import annotations

import traceback
import weakref

from PySide6.QtCore import QThread, Signal

#: Every task ever made.  A ``QThread`` that is destroyed while it is still
#: running kills the process, and the task a page leaks is exactly the one whose
#: page-level reference was overwritten - so the registry is kept here instead.
_ALL: "weakref.WeakSet[Task]" = weakref.WeakSet()

#: Set once the window is closing.  Anything that starts afterwards does nothing:
#: a queued result arriving during shutdown used to start six more threads.
_SHUTDOWN = [False]


def shutdown() -> None:
    """Stop accepting new work.  Called from ``MainWindow.closeEvent``."""
    _SHUTDOWN[0] = True


def wait_all(timeout_ms: int = 30000) -> list:
    """Wait for every running task; return the ones that did not finish."""
    stuck = []
    for task in list(_ALL):
        if task.isRunning():
            task.cancel()
            if not task.wait(timeout_ms):
                stuck.append(task)
    return stuck


class Task(QThread):
    """Call ``fn`` on a worker thread; emit its return value or its traceback."""

    done = Signal(object)
    fail = Signal(str)
    note = Signal(str)

    def __init__(self, fn, *args, parent=None, **kwargs):
        super().__init__(parent)
        self._fn = fn
        self._args = args
        self._kwargs = kwargs
        self._cancelled = False
        self._skipped = _SHUTDOWN[0]
        _ALL.add(self)

    # ---- cooperative cancellation -----------------------------------
    def cancel(self):
        self._cancelled = True

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    # ---- the worker ---------------------------------------------------
    def run(self):
        if self._skipped:
            return
        try:
            out = self._fn(*self._args, **self._kwargs)
        except Exception as exc:                 # noqa: BLE001 - reported to the UI
            text = f"{type(exc).__name__}: {exc}"
            detail = traceback.format_exc()
            self.fail.emit(f"{text}\n\n{detail}")
            return
        if not self._cancelled:
            self.done.emit(out)

    # ---- convenience --------------------------------------------------
    def log(self, message: str):
        """Emit a progress line from inside the worker."""
        self.note.emit(str(message))


def run(fn, *, on_done=None, on_fail=None, parent=None, args=(), kwargs=None) -> Task:
    """Start a task and wire the callbacks in one line."""
    task = Task(fn, *args, parent=parent, **(kwargs or {}))
    if on_done:
        task.done.connect(on_done)
    if on_fail:
        task.fail.connect(on_fail)
    task.start()
    return task
