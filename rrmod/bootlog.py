"""What the engine actually ended up with, read back from its own log.

The graphics files are a wish list, not a result.  ``gfx.plan`` says what we
*want* the engine to use; only the engine can say what it *did* use, and it
does say so: right after ``Loaded settings file: AndroidHigh.plist`` it prints
every key it resolved, one per two lines::

    I/libRealRacing3(13799):   "AA_LEVEL" -
    I/libRealRacing3(13799): 4 : INT

Comparing that dump with the file we pushed is the only honest way to answer
"did my profile take effect", and it is what this module does.

Why it exists
-------------
``MIPMAP_BIAS`` sat in the backlog for a week as "written as -2.0, read back as
0" - a suspected writer bug.  It is not one.  The dump from a boot with the
ultra profile live matches that profile on 99 of 101 keys, so the file was read
correctly; ``MIPMAP_BIAS`` and ``3D_SCENE_SCALE`` are the only two the engine
resolves to something else.  ``3D_SCENE_SCALE`` differs from the *shipped*
value too, on every boot in the archive, which proves the engine overrides some
keys after loading rather than ignoring the file.  ``MIPMAP_BIAS`` goes to the
shaders - see ``texture2DWithBias`` and the ``NOBIAS`` feature in
``shaders_src/`` - and the device that produced the log lists
``GL_EXT_shader_texture_lod`` but no way to bias in GL state, so a bias it
cannot apply is reported as 0.  ``AndroidXtraHigh`` ships ``-2.0`` on Android,
so the value itself is legal; it is the device that cannot honour it.

Two details of the dump that cost an hour each:

* **Multi line strings are printed whole**, so the ``: STRING`` suffix lands on
  the last line only.  A value like ``"Menu wheels high\\nA, 1000\\nC, 0"`` reads
  back as ``C, 0``.  Compare the tail, not the whole string.
* **A key the file does not name is absent from the dump**, not zero: the
  engine keeps its own default, so absence means "not overridden", not "off".

Nothing here touches a device: the log is a file the caller already has.
"""

from __future__ import annotations

import re

#: ``"KEY" - `` starts a pair, the value and its type are on the next line.
_KEY = re.compile(r'\):\s*"([^"]*)"\s*-\s*$')
_VALUE = re.compile(r"\):\s*(.*?)\s*:\s*(BOOL|INT|FLOAT|STRING)\s*$")
#: older logs prefix every line with a timestamp, newer ones with a pid only
_LOADED = re.compile(r"Loaded settings file:\s*(\S+)")
_PLATFORM = re.compile(r"=+\s*platform\s+(\S+)")

#: the engine prints this once, then one extension per line
_EXT_HEADER = "Supported extensions:"

#: Keys the engine is known to resolve to its own value whatever the file says.
#: Listed so the UI can say "this is the engine, not your edit" instead of
#: reporting a mismatch the user cannot fix.
ENGINE_OWN = {
    "MIPMAP_BIAS":
        "Applied through the shaders (texture2DWithBias / the NOBIAS "
        "feature). A device that cannot bias a texture lookup reports 0, so "
        "this reads back as 0 even though the file says -2.0.",
    "3D_SCENE_SCALE":
        "The engine recomputes this from the screen shape after loading, so "
        "the shipped profiles do not get their own value back either.",
}

#: verdicts, in the order a report lists them
TOOK = "took"
DIFFERS = "differs"
ABSENT = "absent"
ORDER = {DIFFERS: 0, ABSENT: 1, TOOK: 2}


class BootLogError(Exception):
    pass


# ------------------------------------------------------------------ parsing
def parse_dump(text: str) -> dict:
    """``{key: value}`` for every key the engine printed, typed."""
    out = {}
    want = None
    for line in text.splitlines():
        key = _KEY.search(line)
        if key:
            # A key with no value under it loses the race to the next key
            # rather than swallowing that key's value.
            want = key.group(1)
            continue
        if want is None:
            continue
        m = _VALUE.search(line)
        if not m:
            continue
        raw, kind = m.group(1), m.group(2)
        try:
            if kind == "BOOL":
                value = raw == "true"
            elif kind == "INT":
                value = int(raw)
            elif kind == "FLOAT":
                value = float(raw)
            else:
                value = raw.strip('"')
        except ValueError:
            value = raw
        out[want] = value
        want = None
    return out


def parse_extensions(text: str) -> list:
    """The GL extension list the engine printed, or ``[]``."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if _EXT_HEADER not in line:
            continue
        out = []
        for follow in lines[i + 1:]:
            body = follow.split("): ", 1)[-1].strip()
            if not body.startswith("GL_"):
                break
            out.append(body)
        return out
    return []


def loaded_profile(text: str) -> str:
    m = _LOADED.search(text)
    return m.group(1) if m else ""


def loaded_platform(text: str) -> str:
    m = _PLATFORM.search(text)
    return m.group(1) if m else ""


# --------------------------------------------------------------- comparison
def _tail(value) -> str:
    """The part of a value the dump can be compared against."""
    if isinstance(value, str):
        return value.splitlines()[-1].strip() if value.splitlines() else ""
    return str(value)


def _same(wanted, got) -> bool:
    if isinstance(wanted, bool) or isinstance(got, bool):
        return wanted is got or wanted == got
    if isinstance(wanted, (int, float)) and isinstance(got, (int, float)):
        return abs(float(wanted) - float(got)) < 1e-6
    return _tail(wanted) == _tail(got)


def compare(wanted: dict, dump: dict) -> list:
    """One row per key we wrote: did the engine end up with it?

    Returns dicts with ``key``, ``wanted``, ``got``, ``state`` and, for the
    keys the engine owns, ``note``.  ``state`` is :data:`TOOK`,
    :data:`DIFFERS` or :data:`ABSENT`; absence is not a failure, because a key
    the file does not name is one the engine keeps its own default for.
    """
    rows = []
    for key, value in wanted.items():
        if key not in dump:
            state, got = ABSENT, None
        elif _same(value, dump[key]):
            state, got = TOOK, dump[key]
        else:
            state, got = DIFFERS, dump[key]
        row = {"key": key, "wanted": value, "got": got, "state": state}
        if key in ENGINE_OWN:
            row["note"] = ENGINE_OWN[key]
        rows.append(row)
    rows.sort(key=lambda r: (ORDER[r["state"]], r["key"]))
    return rows


def report(plist_text: str, log_text: str, wanted: dict | None = None) -> dict:
    """Compare a boot log against a plist.

    ``wanted`` defaults to every key in ``plist_text``; pass the plan's changes
    to ask a narrower question - "did *my edits* take effect" - and leave the
    hundreds of keys the profile inherited out of the answer.
    """
    from rrmod import gfx

    dump = parse_dump(log_text)
    if not dump:
        raise BootLogError(
            "That file has no settings dump in it. Look for the lines after "
            "\"Loaded settings file\" - a logcat taken while the game started "
            "up has them.")
    if wanted is None:
        wanted = gfx.parse_plist(plist_text)
    rows = compare(wanted, dump)
    counts = {TOOK: 0, DIFFERS: 0, ABSENT: 0}
    for row in rows:
        counts[row["state"]] += 1
    return {
        "profile": loaded_profile(log_text),
        "platform": loaded_platform(log_text),
        "extensions": parse_extensions(log_text),
        "keys": len(dump),
        "rows": rows,
        "counts": counts,
        "notes": [row["note"] for row in rows if row.get("note")],
    }


def from_file(plist_path: str, log_path: str, wanted: dict | None = None) -> dict:
    with open(plist_path, encoding="utf-8", errors="replace") as fh:
        plist_text = fh.read()
    with open(log_path, encoding="utf-8", errors="replace") as fh:
        log_text = fh.read()
    return report(plist_text, log_text, wanted)


# ------------------------------------------------------------------ summary
def summarise(result: dict) -> str:
    """One line for the log pane."""
    counts = result["counts"]
    total = sum(counts.values())
    bits = [f"{counts[TOOK]} of {total} keys took"]
    if counts[DIFFERS]:
        bits.append(f"{counts[DIFFERS]} the engine resolved itself")
    if counts[ABSENT]:
        bits.append(f"{counts[ABSENT]} not in the dump")
    where = result.get("profile") or "no profile name"
    return f"{where}: " + ", ".join(bits)
