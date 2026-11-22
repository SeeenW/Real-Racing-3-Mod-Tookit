"""Remembered settings: install folder, reference depot, adb path, window state.

Stored in an INI file rather than the registry.  The registry works fine for a
normal desktop launch but is denied inside a sandboxed process (Qt reports
``QSettings.AccessError`` and silently drops the value), and the manager is
useless if it forgets the game folder on every start.  A file also makes the
state easy to inspect and easy to delete.

Where the file lives, first writable wins:

1. ``%APPDATA%\\RR3ModManager\\settings.ini``  - the normal home
2. ``<folder holding the exe>\\settings.ini``  - portable / sandboxed
3. ``%TEMP%\\RR3ModManager\\settings.ini``     - last resort
"""

from __future__ import annotations

import json
import os
import sys

from PySide6.QtCore import QSettings

ORG = "rr3tools"
APP = "rrmod"
FILENAME = "settings.ini"

_cache: dict[str, str] = {}


def _candidates() -> list[str]:
    out = []
    appdata = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), "AppData",
                                                        "Roaming")
    out.append(os.path.join(appdata, "RR3ModManager"))
    if getattr(sys, "frozen", False):
        out.append(os.path.dirname(os.path.abspath(sys.executable)))
    else:
        out.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    out.append(os.path.join(os.environ.get("TEMP") or os.path.expanduser("~"), "RR3ModManager"))
    return out


def _writable(folder: str) -> bool:
    try:
        os.makedirs(folder, exist_ok=True)
        probe = os.path.join(folder, ".write_probe")
        with open(probe, "w", encoding="utf-8") as fh:
            fh.write("1")
        os.remove(probe)
        return True
    except OSError:
        return False


def _path() -> str:
    """The INI file to use, decided once and remembered."""
    if "path" in _cache:
        return _cache["path"]
    chosen = ""
    for folder in _candidates():
        if _writable(folder):
            chosen = os.path.join(folder, FILENAME)
            break
    if not chosen:
        chosen = os.path.join(os.environ.get("TEMP", "."), "RR3ModManager", FILENAME)
    _cache["path"] = chosen
    return chosen


def _store() -> QSettings:
    return QSettings(_path(), QSettings.IniFormat)


def path() -> str:
    """Where the settings file lives - shown in the About tab."""
    return _path()


def get(key: str, default=""):
    return _store().value(key, default)


def set(key: str, value) -> None:
    store = _store()
    store.setValue(key, value)
    store.sync()


def install() -> str:
    return str(get("install", "") or "")


def set_install(path_: str) -> None:
    set("install", path_)
    remember("recent_install", path_)


def reference() -> str:
    return str(get("reference", "") or "")


def set_reference(path_: str) -> None:
    set("reference", path_)


def icon() -> str:
    """A picture the user chose to stand in for the default window icon."""
    return str(get("icon", "") or "")


def set_icon(path_: str) -> None:
    set("icon", path_)


def adb() -> str:
    return str(get("adb", "") or "")


def set_adb(path_: str) -> None:
    set("adb", path_)


def remember(key: str, value: str) -> list:
    """Keep a short most-recently-used list under ``key``."""
    values = [v for v in recent(key) if v != value]
    values.insert(0, value)
    values = values[:8]
    set(key, json.dumps(values))
    return values


def recent(key: str) -> list:
    raw = get(key, "")
    if not raw:
        return []
    try:
        out = json.loads(raw)
    except (TypeError, ValueError):
        return []
    return [v for v in out if isinstance(v, str)]


def geometry():
    return get("geometry", None)


def set_geometry(data) -> None:
    set("geometry", data)


def splitter(name: str):
    return get("split_" + name, None)


def set_splitter(name: str, data) -> None:
    set("split_" + name, data)


def language() -> str:
    """The interface language, empty meaning "leave it at the default"."""
    return str(get("language", "") or "")


def set_language(code: str) -> None:
    set("language", code)


def history_dir() -> str:
    """Where undo steps are kept, empty meaning "inside the working copy".

    The working copy lives under the state folder, which is on whatever disk the
    program was installed to.  A user who wants the history somewhere else - a
    bigger disk, next to a project, a folder that gets backed up - points this at
    it, and ``rrmod.history`` appends a per-working-copy tag so two installs do
    not mix their steps.
    """
    return str(get("history_dir", "") or "")


def set_history_dir(path_: str) -> None:
    set("history_dir", path_)


def history_keep() -> int:
    """How many steps to keep.  Zero means the module default."""
    try:
        return int(get("history_keep", 0) or 0)
    except (TypeError, ValueError):
        return 0


def set_history_keep(count: int) -> None:
    set("history_keep", int(count or 0))


def texture_family() -> str:
    """Which GPU family an installed pack's pictures should be encoded into.

    ``"auto"`` (the default) means "whichever family this install already holds
    for that page", which is the only answer that is right without knowing the
    device.  The others are offered because a pack author who knows their own
    hardware should not have to argue with a guess.
    """
    got = str(get("texture_family", "") or "")
    return got if got in ("auto", "dxt", "etc", "atc") else "auto"


def set_texture_family(key: str) -> None:
    set("texture_family", key if key in ("auto", "dxt", "etc", "atc") else "auto")


def profile() -> str:
    """Which program the window is showing: ``studio``, ``manager`` or ``both``.

    An unknown value falls back to ``both`` rather than raising, because this is
    read during start-up and a bad settings file must not stop the window from
    opening.
    """
    from .. import profile as profilelib

    got = str(get("profile", "") or "")
    return got if got in profilelib.PROFILES else "both"


def set_profile(name: str) -> None:
    set("profile", name)
