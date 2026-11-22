"""Translate the interface at runtime, by walking the widget tree.

Wrapping every literal in ``tr()`` turned out to be a bad trade: it touches
hundreds of lines of working code for a feature that only matters at the edges.
Instead the English text stays exactly as written and this module swaps the text
of live widgets when the language changes.

How it works: :func:`apply` walks every child of a window and, for each widget
that can hold text, remembers the English string in a dynamic property the first
time it sees it and then writes the translation.  Switching back to English
restores the remembered string, so repeated switches are lossless and no widget
has to be touched twice.

What is covered: window titles, QLabel, QAbstractButton (push, check, radio,
tool), QLineEdit placeholder text and tooltips, QTabWidget tab labels, QGroupBox
titles, QTableWidget/QTreeWidget header labels, and QAction text.  Anything a
page fills in later (table cells, detail panes) is rebuilt from the model on
refresh, so it does not need translating here.

What is deliberately left alone: QComboBox items.  Several pages read the item
text back as a value (``currentText()`` decides what to do), so translating it
would change behaviour, not just looks.

Strings with no entry in the table are left alone, which means a half-finished
translation degrades to English rather than to blanks.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QAbstractButton,
    QComboBox,
    QGroupBox,
    QLabel,
    QLineEdit,
    QTabWidget,
    QTableWidget,
    QTreeWidget,
    QWidget,
)

from .. import i18n

#: dynamic property that holds the English text of a widget
ORIGINAL = "rr3_original_text"

#: role that holds the English text of a table/tree header item.  Those are not
#: QObjects, so they cannot carry a dynamic property the way a widget can.
ITEM_ROLE = Qt.UserRole + 0x3F3

#: Set this property on a widget whose text is data rather than interface copy -
#: a car name, an id, a "540 cars" counter.  Translating those would put
#: generated text into the translation table and make every count a new string.
SKIP_PROPERTY = "rr3_skip_translate"

_SKIP_TYPES = (QComboBox,)


def _skipped(widget) -> bool:
    return bool(widget.property(SKIP_PROPERTY))


def _remember(widget, key: str, value: str) -> str:
    """Store the English text once, return it (the value to translate from)."""
    store = widget.property(ORIGINAL) or {}
    if not isinstance(store, dict):
        store = {}
    if key not in store:
        store[key] = value
        widget.setProperty(ORIGINAL, store)
    return store[key]


def _remember_item(item, value: str, column: int = 0) -> str:
    """Same, for a QTableWidgetItem / QTreeWidgetItem (not a QObject).

    The two differ: ``QTableWidgetItem.data(role)`` takes one argument and
    ``QTreeWidgetItem.data(column, role)`` takes two, so the column has to be
    passed through rather than defaulted inside a call that works for one and
    raises ``TypeError`` for the other.
    """
    try:
        stored = item.data(column, ITEM_ROLE)
    except TypeError:
        stored = item.data(ITEM_ROLE)
    if isinstance(stored, str) and stored:
        return stored
    try:
        item.setData(column, ITEM_ROLE, value)
    except TypeError:
        item.setData(ITEM_ROLE, value)
    return value


def _apply_text(widget, key: str, current: str, setter) -> None:
    english = _remember(widget, key, current)
    wanted = i18n.tr(english)
    if current != wanted:
        setter(wanted)


def _walk(root: QWidget):
    """Yield every widget under ``root``, minus the marked-off subtrees."""
    yield root
    for child in root.findChildren(QWidget):
        parent = child.parentWidget()
        hidden = False
        while parent is not None and parent is not root:
            if _skipped(parent):
                hidden = True
                break
            parent = parent.parentWidget()
        if hidden or _skipped(child):
            continue
        yield child


def apply(root: QWidget) -> int:
    """Translate every string under ``root``; returns how many were considered."""
    seen = 0
    for widget in _walk(root):
        if isinstance(widget, QLineEdit):
            text = widget.placeholderText()
            if text:
                seen += 1
                _apply_text(widget, "placeholder", text, widget.setPlaceholderText)
            tip = widget.toolTip()
            if tip:
                seen += 1
                _apply_text(widget, "tooltip", tip, widget.setToolTip)
            continue

        if isinstance(widget, QAbstractButton):
            text = widget.text()
            if text:
                seen += 1
                _apply_text(widget, "text", text, widget.setText)
            tip = widget.toolTip()
            if tip:
                seen += 1
                _apply_text(widget, "tooltip", tip, widget.setToolTip)
            continue

        if isinstance(widget, QLabel):
            text = widget.text()
            if text:
                seen += 1
                _apply_text(widget, "text", text, widget.setText)
            tip = widget.toolTip()
            if tip:
                seen += 1
                _apply_text(widget, "tooltip", tip, widget.setToolTip)
            continue

        if isinstance(widget, QGroupBox):
            text = widget.title()
            if text:
                seen += 1
                _apply_text(widget, "title", text, widget.setTitle)
            continue

        if isinstance(widget, QTabWidget):
            for index in range(widget.count()):
                text = widget.tabText(index)
                if not text:
                    continue
                seen += 1
                english = _remember(widget, f"tab{index}", text)
                wanted = i18n.tr(english)
                if text != wanted:
                    widget.setTabText(index, wanted)
            continue

        if isinstance(widget, QTableWidget):
            for index in range(widget.columnCount()):
                item = widget.horizontalHeaderItem(index)
                if item is None or not item.text():
                    continue
                seen += 1
                english = _remember_item(item, item.text())
                wanted = i18n.tr(english)
                if item.text() != wanted:
                    item.setText(wanted)
            # Deliberately no resizeColumnsToContents(): the Cars page remembers
            # the widths the user dragged, and resizing here would throw them
            # away every time the language changed.
            continue

        if isinstance(widget, QTreeWidget):
            header = widget.headerItem()
            if header is not None:
                for index in range(widget.columnCount()):
                    text = header.text(index)
                    if not text:
                        continue
                    seen += 1
                    english = _remember_item(header, text, index)
                    wanted = i18n.tr(english)
                    if text != wanted:
                        header.setText(index, wanted)
            continue

    for action in root.findChildren(QAction):
        text = action.text()
        if text:
            seen += 1
            _apply_text(action, "text", text, action.setText)
    return seen


def window_title(window: QWidget) -> None:
    """Translate the window title, which lives outside the child walk."""
    text = window.windowTitle()
    if not text:
        return
    english = _remember(window, "title", text)
    wanted = i18n.tr(english)
    if text != wanted:
        window.setWindowTitle(wanted)


def strings(root: QWidget) -> list:
    """Every English string under ``root`` that :func:`apply` would translate.

    Used by the dev tool that builds a translation table, and by the check in
    ``tools/test_rrmod.py`` that keeps the shipped table honest.
    """
    found = []

    def add(text: str) -> None:
        if text and text not in found:
            found.append(text)

    add(root.windowTitle())
    for widget in _walk(root):
        if isinstance(widget, (QLineEdit,)):
            add(widget.placeholderText())
            add(widget.toolTip())
        elif isinstance(widget, QAbstractButton):
            add(widget.text())
            add(widget.toolTip())
        elif isinstance(widget, QLabel):
            add(widget.text())
            add(widget.toolTip())
        elif isinstance(widget, QGroupBox):
            add(widget.title())
        elif isinstance(widget, QTabWidget):
            for index in range(widget.count()):
                add(widget.tabText(index))
        elif isinstance(widget, QTableWidget):
            for index in range(widget.columnCount()):
                item = widget.horizontalHeaderItem(index)
                if item is not None:
                    add(item.text())
        elif isinstance(widget, QTreeWidget):
            # apply() translates a tree's header, so the inventory has to see
            # the same text or a translation would be shipped for a column the
            # table never had - and the column that does exist would stay
            # English in a Chinese window.
            header = widget.headerItem()
            if header is not None:
                for index in range(widget.columnCount()):
                    add(header.text(index))
    for action in root.findChildren(QAction):
        add(action.text())
    return found
