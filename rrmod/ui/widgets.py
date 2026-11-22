"""Small shared widgets: headings, status pills, the log pane, path pickers.

Kept in one place because the car list, the detail pane and the music editor all
want the same "label, value, pill, log" vocabulary, and repeating it three times
is how a GUI ends up with three different font sizes.
"""

from __future__ import annotations

import html
import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QGuiApplication
from PySide6.QtWidgets import (QComboBox, QFileDialog, QFrame, QHBoxLayout,
                               QLabel, QPlainTextEdit, QPushButton, QSizePolicy,
                               QToolButton, QVBoxLayout, QWidget)

#: Pill colours per car status.
STATUS_COLOURS = {
    "vanilla": ("#2c5c8a", "#eaf2fa"),
    "mod": ("#1f6f43", "#e8f6ee"),
    "unknown": ("#8a5a00", "#fdf3e2"),
    "modified": ("#8a2c2c", "#fdeaea"),
}


def heading(text: str, level: int = 2) -> QLabel:
    lab = QLabel(text)
    f = lab.font()
    f.setPointSize({1: 15, 2: 12, 3: 10}.get(level, 11))
    f.setWeight(QFont.DemiBold)
    lab.setFont(f)
    lab.setContentsMargins(0, 6 if level == 1 else 4, 0, 2)
    return lab


def muted(text: str = "") -> QLabel:
    lab = QLabel(text)
    lab.setStyleSheet("color: #666;")
    lab.setWordWrap(True)
    return lab


def pill(text: str, kind: str = "vanilla") -> QLabel:
    """A small rounded status tag."""
    fg, bg = STATUS_COLOURS.get(kind, STATUS_COLOURS["vanilla"])
    lab = QLabel(text)
    lab.setStyleSheet(
        f"color:{fg}; background:{bg}; border:1px solid {fg}33;"
        "border-radius:7px; padding:1px 7px;")
    lab.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Maximum)
    return lab


class KeyValue(QWidget):
    """A two column read-only table of ``label: value`` rows."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._grid = QVBoxLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(2)
        self._rows = {}

    def set(self, key: str, value) -> None:
        row = self._rows.get(key)
        if row is None:
            row = QWidget()
            lay = QHBoxLayout(row)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(8)
            k = QLabel(key)
            k.setStyleSheet("color:#666;")
            k.setFixedWidth(112)
            v = QLabel()
            v.setTextInteractionFlags(Qt.TextSelectableByMouse)
            v.setWordWrap(True)
            # The value is data - a car name, a byte count - so the language
            # walker must leave it alone.  The key beside it is interface copy
            # and is translated normally.
            v.setProperty("rr3_skip_translate", True)
            lay.addWidget(k)
            lay.addWidget(v, 1)
            self._grid.addWidget(row)
            self._rows[key] = (row, v)
        self._rows[key][1].setText(str(value))

    def clear(self) -> None:
        for row, _v in self._rows.values():
            row.setParent(None)
        self._rows.clear()

    def update_all(self, mapping: dict) -> None:
        self.clear()
        for k, v in mapping.items():
            if v not in ("", None, [], ()):
                self.set(k, v)


def separator() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.HLine)
    line.setFrameShadow(QFrame.Sunken)
    line.setStyleSheet("color:#ddd;")
    return line


# ------------------------------------------------------------------- log pane
class LogPane(QPlainTextEdit):
    """Append-only, monospace, capped at a few thousand lines."""

    def __init__(self, parent=None, limit: int = 4000):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setMaximumBlockCount(limit)
        self.setFont(QFont("Consolas", 9))
        self.setPlaceholderText("Nothing yet.")
        self.setMinimumHeight(90)

    def add(self, text: str) -> None:
        for line in str(text).rstrip("\n").splitlines():
            self.appendPlainText(line)

    def note(self, text: str) -> None:
        self.appendHtml(f'<span style="color:#888">{html.escape(str(text))}</span>')

    def error(self, text: str) -> None:
        for line in str(text).rstrip("\n").splitlines():
            self.appendHtml(f'<span style="color:#a22">{html.escape(line)}</span>')

    def ok(self, text: str) -> None:
        self.appendHtml(f'<span style="color:#1f6f43">{html.escape(str(text))}</span>')


# ---------------------------------------------------------------- path picker
class PathPicker(QWidget):
    """A line edit with a Browse button, for a folder."""

    changed = Signal(str)

    def __init__(self, label: str = "", parent=None, *, folder: bool = True,
                 caption: str = "Choose a folder"):
        super().__init__(parent)
        self._folder = folder
        self._caption = caption
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        if label:
            lab = QLabel(label)
            lab.setFixedWidth(96)
            lay.addWidget(lab)
        self.edit = QComboBox()
        self.edit.setEditable(True)
        self.edit.setInsertPolicy(QComboBox.NoInsert)
        lay.addWidget(self.edit, 1)
        btn = QToolButton()
        btn.setText("...")
        btn.clicked.connect(self._browse)
        lay.addWidget(btn)
        self.edit.currentTextChanged.connect(self.changed.emit)

    def _browse(self):
        start = self.text() or os.path.expanduser("~")
        if self._folder:
            got = QFileDialog.getExistingDirectory(self, self._caption, start)
        else:
            got, _ = QFileDialog.getOpenFileName(self, self._caption, start)
        if got:
            self.set_text(got)

    def text(self) -> str:
        return self.edit.currentText().strip()

    def set_text(self, text: str) -> None:
        self.edit.setCurrentText(text)

    def add_history(self, values) -> None:
        current = self.text()
        self.edit.clear()
        for v in values:
            if v:
                self.edit.addItem(v)
        if current:
            self.edit.setCurrentText(current)


def button(text: str, slot=None, *, primary: bool = False, tip: str = "") -> QPushButton:
    b = QPushButton(text)
    if primary:
        b.setDefault(True)
        f = b.font()
        f.setWeight(QFont.DemiBold)
        b.setFont(f)
    if slot:
        b.clicked.connect(slot)
    if tip:
        b.setToolTip(tip)
    return b


def copy_to_clipboard(text: str) -> None:
    QGuiApplication.clipboard().setText(text)
