"""Who still needs each shared texture page.

A page under ``vehicles/common/`` is not owned by any one car: the livery table
of every car that uses it names it, and two cars naming the same page are two
reasons to keep it.  That is the whole dependency story for this game - there is
no version range, no transitive dependency, no solver.  A file is either named
by somebody or it is not.

So this module keeps two facts apart:

* **who names it now** - read from the 540 livery tables, always the truth, and
  cheap enough to recompute (0.23 s for all of them) that it is never stale.
* **where it came from** - recorded when a mod brings a page of its own, so
  removing that mod knows what to ask about.  A page the game shipped is
  ``shipped`` and is never a dependency and never deleted.

The key is the **stem**: ``common/car_windows_04`` covers all four GPU families
(``.dxt.dds.z``, ``.etc.dds.z``, ``.atc.dds.z``, ``.ptc.pvr.z``).  Four rows in
four asset lists describe one resource, and counting them separately would
report a page as used four times by one car.

The same two questions are asked about the track side, and it works differently
enough to be worth saying: a track's shared pages are not named in any table.
The only record of them is the absolute artist path stored inside the track's own
``.m3g``, so that is where they are read from.  See :func:`scan_tracks`.
"""

import json
import os
import re
import time

from rr3lib import livery as liverylib
from rr3lib import manifest as manifestlib

#: Bumped when the shape of ``deps.json`` changes.
VERSION = 1

#: The file sits beside ``rr3mods.json``, wherever that ended up.
DEPS_FILE = "deps.json"

#: Owner name used for pages the game's own fallback table names.
DEFAULT_OWNER = "<default>"

#: ``{depot: {stem: [owner, ...]}}`` - the live scan, thrown away on demand.
_SCAN: dict = {}


class DepsError(Exception):
    """Something about the dependency file or its arguments is wrong."""


# --------------------------------------------------------------- the stem


#: Every suffix a page name can end with.  The four families are the ones the
#: asset lists have a column for; ``.rgb.pvr.z`` is a fifth form the livery
#: tables use for a handful of pages (``car_tyre_slick_pirelli_f1`` and three
#: others) and has no asset list of its own - those pages ship as ``.dxt.dds.z``
#: on disk, so the suffix in the table is a hint about the page, not the file.
#: ``.ptc.pvr`` without the ``.z`` shows up in one table too, so the bare forms
#: are stripped as well rather than left on the stem.  ``.dds`` alone is what a
#: dozen of the track pages are stored as.
SUFFIXES = manifestlib.FAMILIES + (".rgb.pvr.z",)
BARE_SUFFIXES = (".ptc.pvr", ".dxt.dds", ".etc.dds", ".atc.dds", ".dds")


def stem_of(path: str) -> str:
    """``vehicles/common/car_windows_04.dxt.dds.z`` -> ``common/car_windows_04``.

    The four families are one resource, so they share a stem.  A path with no
    known family suffix is returned unchanged apart from a leading
    ``vehicles/``, which the livery tables leave out anyway.
    """
    text = str(path).replace("\\", "/").lstrip("/")
    if text.startswith("vehicles/"):
        text = text[len("vehicles/"):]
    for suffix in SUFFIXES + BARE_SUFFIXES:
        if text.endswith(suffix):
            return text[:-len(suffix)]
    for suffix in SUFFIXES:
        if suffix in text:
            return text[:text.index(suffix)]
    return text


def is_shared(path: str) -> bool:
    """True for a page that lives outside any one car's folder."""
    return stem_of(path).startswith("common/")


def families_of(stem: str) -> list:
    """The four asset list paths one shared page needs rows for."""
    return [f"/vehicles/{stem}{suffix}" for suffix in manifestlib.FAMILIES]


# --------------------------------------------------------- the track side
#
# A track's shared pages are referenced from the track's own ``.m3g``, and the
# reference is not a short name: the file stores the artist's absolute Windows
# path, ``C:\\MobileDevelopment\\...\\Tracks\\common\\crowd\\2d crowd\\crowd_group.psd``.
# So the track side cannot be read from a table the way the car side is - the
# only place the link exists is inside the model.
#
# Two decisions follow from that:
#
# * **the model is scanned as bytes, not parsed.**  Parsing all thirty track
#   models takes eighteen seconds; a regular expression over the same files takes
#   half of one, and all this needs is the strings.  The references sit in plain
#   text in the file, which is what makes that safe.
# * **the suffix is thrown away.**  The artist's file says ``.psd``, and 133 of
#   the references say ``.png``; the game ships ``.dxt.dds.z`` (or one of the
#   other three families) under the same stem.  The stem is the identity, exactly
#   as it is on the car side.

#: Where a track's shared pages live, relative to ``.depot``.
TRACK_COMMON = "Tracks/common"

#: The prefix every track page's stem carries.  Keeping it means one record file
#: can hold both kinds without a track page ever colliding with a car page.
TRACK_PREFIX = "tracks/common/"

#: ``...\\Tracks\\common\\<rel>.<ext>``, with either slash and any of the
#: extensions the artists' files carry.
_TRACK_REF = re.compile(
    rb"Tracks[\\/]common[\\/]([^\x00]{1,240}?)\.[A-Za-z0-9]{2,5}\x00")


def track_common_dir(depot: str) -> str:
    """``<depot>/Tracks/common`` - the track side's shared folder."""
    return os.path.join(depot, *TRACK_COMMON.split("/"))


def track_models(depot: str) -> list:
    """Every track body model, ``Tracks/<track>/processed/high/*.m3g``.

    A track can have several layouts (``gp``, ``national``, ``short``) and each
    has its own ``processed/high`` folder; the minimap and sky models sit beside
    them and are skipped, because neither draws world geometry.
    """
    base = os.path.join(depot, "Tracks")
    out = []
    if not os.path.isdir(base):
        return out
    for name in sorted(os.listdir(base)):
        if name.lower() == "common":
            continue
        folder = os.path.join(base, name, "processed", "high")
        if not os.path.isdir(folder):
            continue
        for leaf in sorted(os.listdir(folder)):
            low = leaf.lower()
            if not low.endswith(".m3g"):
                continue
            if low.endswith("_minimap.m3g") or low.endswith("_sky.m3g"):
                continue
            out.append(os.path.join(folder, leaf))
    return out


def _track_name(path: str) -> str:
    """``.../Tracks/Bathurst/processed/high/bathurst.m3g`` -> ``Bathurst``."""
    parts = os.path.abspath(path).replace("\\", "/").split("/")
    try:
        at = len(parts) - 1 - parts[::-1].index("Tracks")
    except ValueError:
        return ""
    return parts[at + 1] if at + 1 < len(parts) else ""


def scan_tracks(depot: str, *, refresh: bool = False) -> dict:
    """``{stem: [track, ...]}`` for every page the track models name.

    The stem keeps the folder the artist put it in, ``tracks/common/mat/...``, so
    two tracks naming the same page are two reasons to keep it - the same rule
    the car side uses.
    """
    key = "tracks:" + os.path.abspath(depot)
    if not refresh and key in _SCAN:
        return _SCAN[key]
    out: dict = {}
    for path in track_models(depot):
        track = _track_name(path)
        try:
            with open(path, "rb") as fh:
                raw = fh.read()
        except OSError:
            continue
        for hit in _TRACK_REF.finditer(raw):
            rel = hit.group(1).decode("latin-1").replace("\\", "/")
            rel = "/".join(part for part in rel.split("/") if part)
            if not rel:
                continue
            out.setdefault(TRACK_PREFIX + rel.lower(), set()).add(track)
    clean = {stem: sorted(owners) for stem, owners in out.items()}
    _SCAN[key] = clean
    return clean


def track_files_on_disk(depot: str, *, install: str = "") -> dict:
    """``{stem: real relative path}`` for the pages ``Tracks/common`` carries.

    The real path is kept because the stem is lower-cased for matching and the
    device's file system cares about case, so anything that has to open one of
    these files needs the spelling that is actually there.
    """
    folder = os.path.join(install or _install_depot(depot) or depot,
                          *TRACK_COMMON.split("/"))
    out: dict = {}
    if not os.path.isdir(folder):
        return out
    for dirpath, _dirs, files in os.walk(folder):
        for leaf in files:
            full = os.path.join(dirpath, leaf)
            rel = os.path.relpath(full, folder).replace("\\", "/")
            bare = rel
            for suffix in SUFFIXES + BARE_SUFFIXES:
                if bare.lower().endswith(suffix):
                    bare = bare[:-len(suffix)]
                    break
            out.setdefault(TRACK_PREFIX + bare.lower(), rel)
    return out


def shipped_tracks(depot: str, *, install: str = "") -> set:
    """The stems of the track pages the install itself carries.

    Same story as :func:`shipped` for ``vehicles/common``: a page a mod added is
    on disk in the same folder now that edits land in the install, so the record
    of what this program brought is what keeps it from being called the game's
    own - and a page called the game's own is one that can never be removed.
    """
    on_disk = track_files_on_disk(depot, install=install)
    recorded = (load(depot) or {}).get("pages") or {}
    out = set()
    for stem in on_disk:
        row = recorded.get(stem) or {}
        if row and row.get("shipped") is False:
            continue
        out.add(stem)
    return out


def is_track(stem: str) -> bool:
    """True for a stem that names a page under ``Tracks/common``."""
    return stem_of(stem).startswith(TRACK_PREFIX)


def track_key(stem: str) -> str:
    """A track stem with its ``tracks/common/`` prefix, however it was written.

    Two spellings are in use and both are correct: the record and the Dependencies
    tab write ``tracks/common/mat/metal/mat_metal_black``, because one file holds
    both kinds of page and the prefix is what keeps them apart; a person reading
    the folder off disk writes ``mat/metal/mat_metal_black``, because that is the
    path below ``Tracks/common``.  Callers that take a stem from a user take both.
    """
    key = stem_of(stem)
    return key if key.startswith(TRACK_PREFIX) else TRACK_PREFIX + key


def track_missing(depot: str, *, refresh: bool = False) -> list:
    """Pages a track model names that ``Tracks/common`` does not carry.

    Two of them are like this in the shipped game
    (``mat/branding/billboards/billboard_d/..._base_e`` and ``_base_f``), which
    is why they are reported rather than treated as a fault.
    """
    used = scan_tracks(depot, refresh=refresh)
    have = shipped_tracks(depot)
    return sorted(stem for stem in used if stem not in have)


def track_status(depot: str, stem: str, *, refresh: bool = False) -> dict:
    """The same four answers :func:`status` gives, for a track page."""
    key = track_key(stem)
    live = scan_tracks(depot, refresh=refresh).get(key, [])
    row = load(depot)["pages"].get(key) or {}
    game = key in shipped_tracks(depot)
    return {
        "stem": key,
        "shipped": game,
        "live": live,
        "brought_by": list(row.get("owners") or []),
        "files": list(row.get("files") or []),
        "source": row.get("source", ""),
        "needed": bool(game or live),
    }


def track_orphans(depot: str, *, refresh: bool = False) -> list:
    """Track pages this program added that no track model names any more."""
    used = scan_tracks(depot, refresh=refresh)
    game = shipped_tracks(depot)
    out = []
    for stem, row in load(depot)["pages"].items():
        if not is_track(stem) or stem in game or stem in used:
            continue
        out.append({"stem": stem, "files": list(row.get("files") or []),
                    "source": row.get("source", "")})
    return sorted(out, key=lambda r: r["stem"])


def track_report(depot: str, *, refresh: bool = False) -> dict:
    """The numbers the track half of the Dependencies page shows."""
    used = scan_tracks(depot, refresh=refresh)
    have = shipped_tracks(depot)
    return {
        "pages": len(used),
        "on_disk": len(have),
        "unreferenced": len([s for s in have if s not in used]),
        "missing": len(track_missing(depot, refresh=refresh)),
        "models": len(track_models(depot)),
        "recorded": len([s for s in load(depot)["pages"] if is_track(s)]),
        "orphans": len(track_orphans(depot, refresh=refresh)),
        "busiest": sorted(used.items(), key=lambda kv: (-len(kv[1]), kv[0]))[:8],
    }


# ------------------------------------------------------------- the scan


def _livery_dir(depot: str) -> str:
    return os.path.join(depot, *liverylib.LIVERY_DIR.split("/"))


def scan(depot: str, *, refresh: bool = False) -> dict:
    """``{stem: [owner, ...]}`` for every page any livery table names.

    ``depot`` is the ``.depot`` folder.  Reading all 540 tables takes about a
    quarter of a second, and the answer is remembered until :func:`forget` is
    called or ``refresh`` is passed, because the pages page asks for it on every
    repaint.
    """
    if not refresh and depot in _SCAN:
        return _SCAN[depot]
    folder = _livery_dir(depot)
    out: dict = {}
    if os.path.isdir(folder):
        for leaf in sorted(os.listdir(folder)):
            if not leaf.endswith(".liveries.bin.nct"):
                continue
            path = os.path.join(folder, leaf)
            if leaf.startswith("default."):
                try:
                    table = liverylib.load_default(depot)
                except Exception:                    # noqa: BLE001
                    continue
                for _slot, page in table.textures:
                    out.setdefault(stem_of(page.decode("latin-1")),
                                   set()).add(DEFAULT_OWNER)
                continue
            car = leaf[:-len(".liveries.bin.nct")]
            try:
                L = liverylib.load(path)
            except Exception:                        # noqa: BLE001
                # A table this program cannot read tells us nothing; skipping it
                # is better than failing the whole page over one bad file.
                continue
            for _slot, page in L.textures:
                out.setdefault(stem_of(page.decode("latin-1")), set()).add(car)
            for paint in L.paints:
                for _slot, page in paint.overrides:
                    out.setdefault(stem_of(page.decode("latin-1")),
                                   set()).add(car)
    clean = {stem: sorted(owners) for stem, owners in out.items()}
    _SCAN[depot] = clean
    return clean


def forget() -> None:
    """Drop the cached scan (after an edit that changes a livery table)."""
    _SCAN.clear()


def live_owners(depot: str, stem: str, *, refresh: bool = False) -> list:
    """The cars that name this page right now."""
    return scan(depot, refresh=refresh).get(stem_of(stem), [])


# -------------------------------------------------------- what the game has


def _install_depot(depot: str) -> str:
    """The install's ``.depot`` for a working copy, or ``""`` for the install.

    A working copy carries a ``pending.json`` next to ``.depot`` naming the
    install it was made from.  Reading it here is what lets every caller ask
    "did the game ship this page" without having to thread the install through.
    """
    pending = os.path.join(os.path.dirname(os.path.abspath(depot)), "pending.json")
    if not os.path.isfile(pending):
        return ""
    try:
        with open(pending, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return ""
    install = str(data.get("install") or "")
    if not install:
        return ""
    return os.path.join(install, ".depot")


def shipped(depot: str, *, install: str = "") -> set:
    """The stems of the pages the install itself carries.

    The keys match :func:`scan`, i.e. ``common/car_windows_04`` - the folder
    prefix is part of the stem because that is how a livery table writes it.

    ``install`` matters when ``depot`` is a working copy: a page a mod added is
    on disk there too, so asking the working copy would call it the game's own.
    The install is found from the working copy's ``pending.json`` unless one is
    passed, which is what makes this answer "did the game ship this" rather than
    "is this file here now".

    Edits are written straight into the install now, so there is usually no
    working copy to fall back on and the folder alone cannot tell a page the
    game shipped from one a mod copied in a minute ago.  ``deps.json`` can: it
    is written when a page is added and it records whether the target was
    already there.  A row that says ``shipped: False`` is therefore left out of
    this set even though its file is sitting in the folder.
    """
    folder = os.path.join(install or _install_depot(depot) or depot,
                          "vehicles", "common")
    out = set()
    if not os.path.isdir(folder):
        return out
    recorded = (load(depot) or {}).get("pages") or {}
    for leaf in os.listdir(folder):
        key = "common/" + stem_of(leaf)
        row = recorded.get(key) or {}
        if row and row.get("shipped") is False:
            continue                    # ours, however long it has been there
        out.add(key)
    return out


def unreferenced(depot: str, *, refresh: bool = False) -> list:
    """Pages on disk that no livery table names.

    These are the game's own leftovers - ``arms*`` and a few aluminium weaves
    nobody uses.  Reported, never deleted: they are shipped files, and the
    engine may still ask for one by a path this program has not seen.
    """
    used = scan(depot, refresh=refresh)
    return sorted(stem for stem in shipped(depot) if stem not in used)


# ---------------------------------------------------------- the record


def deps_path(depot: str) -> str:
    """``deps.json`` beside ``rr3mods.json``, so both travel together."""
    from . import depot as depotlib

    return os.path.join(depotlib.state_dir(depot), DEPS_FILE)


def _empty() -> dict:
    return {"version": VERSION, "pages": {}}


def load(depot: str) -> dict:
    """The recorded pages, or an empty record when there is no file yet."""
    path = deps_path(depot)
    if not os.path.isfile(path):
        return _empty()
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as exc:
        raise DepsError(f"{path}: {exc}") from exc
    data.setdefault("version", VERSION)
    data.setdefault("pages", {})
    return data


def save(depot: str, data: dict) -> str:
    path = deps_path(depot)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(data, fh, indent=1, sort_keys=True, ensure_ascii=False)
        fh.write("\n")
    os.replace(tmp, path)
    return path


def record(depot: str, stem: str, owner: str, *, files=None, source: str = "",
           shipped=None) -> dict:
    """Note that ``owner`` brought this page in.

    Called when a mod writes a page of its own into ``vehicles/common``.  A page
    the install already had is marked ``shipped`` and is then never a dependency
    and never a candidate for deletion, no matter who names it.

    ``shipped`` has to be passed by the caller when the file has just been
    copied in: after the copy the working copy carries it, so asking the folder
    would say "the game shipped this" about a page that was added a moment ago.
    The caller knows the answer - it is "was the target already there" - so it
    passes it and this function does not guess.
    """
    key = stem_of(stem)
    if not key:
        raise DepsError("a page needs a name")
    data = load(depot)
    row = data["pages"].get(key)
    fresh = row is None
    if fresh:
        row = data["pages"][key] = {
            "owners": [], "files": [], "source": "", "shipped": False,
            "added": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
    if shipped is None:
        row["shipped"] = bool(key in shipped(depot))
    elif fresh:
        # Only a first sighting may be called shipped.  A second copy-in sees the
        # file already on disk and would otherwise relabel a page this program
        # brought as the game's own, which is exactly the page a user may want to
        # take out again.
        row["shipped"] = bool(shipped)
    owners = row.setdefault("owners", [])
    if owner and owner not in owners:
        owners.append(owner)
        owners.sort()
    if files:
        known = row.setdefault("files", [])
        for path in files:
            if path not in known:
                known.append(path)
        known.sort()
    if source:
        row["source"] = source
    save(depot, data)
    return row


def release(depot: str, stem: str, owner: str) -> dict:
    """Forget one owner; returns the row with what is left of it."""
    key = stem_of(stem)
    data = load(depot)
    row = data["pages"].get(key)
    if row is None:
        return {}
    owners = [o for o in row.get("owners", []) if o != owner]
    row["owners"] = owners
    save(depot, data)
    return row


def drop(depot: str, stem: str) -> bool:
    """Remove a page from the record entirely."""
    key = stem_of(stem)
    data = load(depot)
    if data["pages"].pop(key, None) is None:
        return False
    save(depot, data)
    return True


# ------------------------------------------------------------- questions


def status(depot: str, stem: str, *, refresh: bool = False) -> dict:
    """Everything known about one page, for a page that has to explain it.

    ``needed`` is the answer to "may this be deleted": a shipped page never may,
    and a page somebody still names never may.
    """
    key = stem_of(stem)
    live = live_owners(depot, key, refresh=refresh)
    row = load(depot)["pages"].get(key) or {}
    game = key in shipped(depot)
    return {
        "stem": key,
        "shipped": game,
        "live": live,
        "brought_by": list(row.get("owners") or []),
        "files": list(row.get("files") or []),
        "source": row.get("source", ""),
        "needed": bool(game or live),
    }


def missing(depot: str, *, refresh: bool = False) -> list:
    """Pages a livery table names that the install does not carry.

    Two of the game's own are like this (``common/car_tyre_01`` and
    ``common/car_windows_banner_nascar_2021``), which is why they are reported
    rather than treated as an error: the engine copes, and a mod that supplies
    one of them is doing the game a favour.
    """
    used = scan(depot, refresh=refresh)
    game = shipped(depot)
    return sorted(stem for stem in used
                  if is_shared(stem) and stem not in game)


def orphans(depot: str, *, refresh: bool = False) -> list:
    """Pages this program added that nothing names any more.

    These are the only candidates for deletion: not shipped, recorded as ours,
    and no livery table mentions them.  A page that is merely unreferenced but
    shipped is the game's own and is left alone.

    Track pages are skipped even though they are recorded in the same file: they
    are shared by a completely different rule, and ``track_orphans`` answers for
    them.  Listing one here would offer to delete it from the wrong half of the
    page, and the wrong half does not know which asset list holds its rows.
    """
    used = scan(depot, refresh=refresh)
    game = shipped(depot)
    out = []
    for stem, row in load(depot)["pages"].items():
        if is_track(stem) or stem in game or stem in used:
            continue
        out.append({"stem": stem, "files": list(row.get("files") or []),
                    "source": row.get("source", "")})
    return sorted(out, key=lambda r: r["stem"])


def report(depot: str, *, refresh: bool = False) -> dict:
    """The numbers the Dependencies page shows."""
    used = scan(depot, refresh=refresh)
    game = shipped(depot)
    shared = {stem: owners for stem, owners in used.items()
              if is_shared(stem)}
    return {
        "pages": len(used),
        "shared": len(shared),
        "shipped": len(game),
        "unreferenced": len([s for s in game if s not in used]),
        "missing": len(missing(depot, refresh=refresh)),
        "recorded": len(load(depot)["pages"]),
        "orphans": len(orphans(depot, refresh=refresh)),
        "busiest": sorted(shared.items(), key=lambda kv: (-len(kv[1]), kv[0]))[:8],
    }


def selftest(depot: str) -> int:
    """Read-only sanity pass; returns the number of checks that ran."""
    n = 0
    got = scan(depot)
    assert isinstance(got, dict), "scan must return a dict"
    n += 1
    for stem, owners in list(got.items())[:50]:
        assert isinstance(stem, str) and stem, "stems are non-empty strings"
        assert owners and all(isinstance(o, str) for o in owners), stem
        n += 1
    game = shipped(depot)
    n += 1
    for stem in list(game)[:20]:
        assert not stem.endswith(".z"), f"{stem} kept its suffix"
        n += 1
    assert stem_of("vehicles/common/car_windows_04.dxt.dds.z") == "common/car_windows_04"
    assert stem_of("common/car_windows_04") == "common/car_windows_04"
    assert stem_of("2012_lexus_lfa_ext.dxt.dds.z") == "2012_lexus_lfa_ext"
    assert stem_of("common/car_tyre_slick_pirelli_f1_2019.rgb.pvr.z") == \
        "common/car_tyre_slick_pirelli_f1_2019"
    assert stem_of("common/car_tyre_tread_pirelli.ptc.pvr") == \
        "common/car_tyre_tread_pirelli"
    n += 5
    assert is_shared("common/car_windows_04") and not is_shared("car_windows_04")
    n += 1
    assert len(families_of("common/car_windows_04")) == 4
    n += 1
    tracks = scan_tracks(depot)
    n += 1
    for stem in list(tracks)[:20]:
        assert stem.startswith(TRACK_PREFIX), stem
        n += 1
    assert is_track("tracks/common/mat/metal/mat_metal_black")
    assert not is_track("common/car_windows_04")
    n += 2
    return n
