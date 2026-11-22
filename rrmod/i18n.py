"""Translations for the manager's own interface.

English is the source language: the code says ``tr("Push to device")`` and the
dictionary maps that exact string to the chosen language.  A missing entry falls
back to the English text, so a half-finished translation degrades to mixed
language rather than to blank labels.

Adding a language means dropping ``data/i18n/<code>.json`` next to this file:

    {"Push to device": "推送到设备", ...}

and nothing else - the file name is the code shown in the menu.  Strings that
are deliberately identical to English (product names, ids) can be left out.
"""

from __future__ import annotations

import json
import os
import re

#: code -> name shown in the language menu.  English is first and is the source.
LANGUAGES = {
    "en": "English",
    "zh-Hans": "简体中文",
}

DEFAULT = "en"

_HERE = os.path.dirname(os.path.abspath(__file__))
I18N_DIR = os.path.join(_HERE, "data", "i18n")

#: ``"Event 2034"`` -> ``("Event", "2034")``.  Used to translate the word a
#: run-time label puts in front of a number; a number in the middle of a
#: sentence never matches, so ordinary copy still needs its own entry.
_TAIL_DIGITS = re.compile(r"^(.*?\D)\s+(\d+)$")

_state = {"language": DEFAULT, "table": {}}
_cache: dict = {}


def available() -> dict:
    """Every language we can actually switch to, ``{code: name}``.

    A language is only offered when its table loads with entries in it.  The
    first frozen build shipped without ``data/i18n`` at all and the menu still
    listed "简体中文", because the name here is hard coded - picking it did
    nothing at all and looked like a broken switch rather than a missing file.
    Better to leave the entry out and let the menu say what is really there.
    """
    out = {}
    for code, name in LANGUAGES.items():
        if code == DEFAULT or table(code):
            out[code] = name
    if os.path.isdir(I18N_DIR):
        for leaf in sorted(os.listdir(I18N_DIR)):
            if not leaf.endswith(".json") or leaf.startswith("_"):
                continue
            code = leaf[:-5]
            if code in out:
                continue
            if table(code):
                out[code] = code
    return out


def table(code: str = "") -> dict:
    """The translation table for ``code`` (empty for English)."""
    code = code or _state["language"]
    if code in _cache:
        return _cache[code]
    data = {}
    path = os.path.join(I18N_DIR, f"{code}.json")
    if code != DEFAULT and os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
            data = {k: v for k, v in raw.items()
                    if isinstance(k, str) and isinstance(v, str) and v}
        except (OSError, ValueError):
            data = {}
    _cache[code] = data
    return data


def language() -> str:
    return _state["language"]


def set_language(code: str) -> str:
    """Switch language; returns the code actually in force."""
    code = code or DEFAULT
    if code not in available():
        code = DEFAULT
    _state["language"] = code
    _state["table"] = table(code)
    return code


def tr(text: str) -> str:
    """Translate one interface string (English in, chosen language out)."""
    if not text:
        return text
    table_ = _state["table"]
    if not table_:
        return text
    hit = table_.get(text)
    if hit:
        return hit
    # tolerate the odd stray space, which is easy to introduce while editing
    stripped = text.strip()
    if stripped != text:
        hit = table_.get(stripped)
        if hit:
            return hit
    # Labels built at run time ("Event 2034", "Slot 2") have no entry of their
    # own; the word in front of the number is the part that needs translating.
    # Only a trailing run of digits is peeled off, so an ordinary sentence with
    # a number in the middle still needs its own entry.
    tail = _TAIL_DIGITS.search(stripped)
    if tail:
        stem = table_.get(tail.group(1))
        if stem:
            return stem + " " + tail.group(2)
    return text


def missing(code: str = "") -> list:
    """English strings the table has no entry for - used by the checker.

    Reads ``data/i18n/_source.json`` (written by ``tools/gen_i18n.py``) so the
    answer covers every string the interface can show, not just the ones a page
    happened to be displaying when the check ran.

    A run-time label like ``"Event 2034"`` counts as covered when its stem
    (``"Event"``) is in the table, because that is exactly what :func:`tr` does
    with it - reporting it here would ask for a translation that would never be
    used.
    """
    code = code or _state["language"]
    if code == DEFAULT:
        return []
    wanted = source()
    if not wanted:
        return []
    have = table(code)
    out = []
    for text in wanted:
        if text in have:
            continue
        tail = _TAIL_DIGITS.search(text)
        if tail and tail.group(1) in have:
            continue
        out.append(text)
    return out


def source() -> list:
    """Every interface string, from the inventory ``tools/gen_i18n.py`` writes."""
    path = os.path.join(I18N_DIR, "_source.json")
    if not os.path.isfile(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
    except (OSError, ValueError):
        return []
    if isinstance(raw, dict):
        return list(raw)
    return [text for text in raw if isinstance(text, str)]


def summary() -> dict:
    return {
        "language": _state["language"],
        "languages": available(),
        "entries": len(_state["table"]),
        "dir": I18N_DIR,
    }


def selftest() -> int:
    print(summary())
    for code in available():
        t = table(code)
        print(f"  {code}: {len(t)} entries")
    return 0
