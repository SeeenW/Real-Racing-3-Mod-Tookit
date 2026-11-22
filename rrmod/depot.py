"""Scan a Real Racing 3 install and tell the vanilla cars from our mods.

The install folder (``files``) contains three things::

    .depot/          every asset, unpacked
    apk/res/         the manifests that tell the engine what to load
    doc/

A car is *not* identified by its spec file name.  The chain the game itself
uses is::

    vehicles/data/<id>_<something>.bin.nct   spec
      -> spec.appearance_id()
        -> vehicles/data/carappearances.appearances.nct record
          -> record.name == the folder under vehicles/ == the livery file name
             == apk/res/asset_list_vehicle_<name>.txt

352 of the 540 cars have a spec file name that differs from their appearance
name, so everything here goes through the appearance record.

Vanilla vs mod
--------------
``<depot>/rr3mods.json`` remembers both sides::

    {"version": 1,
     "reference": "E:/.../.depot",      # optional pristine copy, may be ""
     "vanilla": {"2012_lexus_lfa": {"id": 88, "sig": "..."} , ...},
     "mods":    {"2020_my_car":    {"id": 611, "kind": "new",
                                    "donor": "2012_lexus_lfa",
                                    "created": "..."}, ...}}

A car whose name is in ``mods`` is a mod and may be edited or deleted.  A car
whose name is in ``vanilla`` is read only.  A car in neither list is *unknown*:
it was installed by some other tool, and the manager offers to adopt it as a
mod rather than silently treating it as vanilla.  ``sig`` is a cheap
fingerprint (spec id + the size of every m3g in the folder) so a vanilla car
whose files were replaced behind our back shows up as "modified" instead of
being trusted.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field

from rr3lib import appearance as appearlib
from rr3lib import catalog as catlib
from rr3lib import link as linklib
from rr3lib import livery as liverylib
from rr3lib import spec as speclib
from rr3lib import texts as textlib

from . import cars as carlib

MODS_FILE = "rr3mods.json"
MODS_VERSION = 1

#: Body levels, best first.  ``shared``/``int_a``/``int_b`` are complete models
#: rather than levels, so they are listed separately.
BODY_LODS = "ABCDEFGH"
_BODY_LOWER = BODY_LODS.lower()
STANDALONE = ("shared", "int_a", "int_b")

_SPEC_RE = re.compile(r"^(\d+)_(.+)\.bin\.nct$")
#: Longest suffixes first, or ``_int_a.m3g`` would be read as LOD A.
_LOD_RE = re.compile(r"_(int_a|int_b|shared|[a-h])\.m3g$")


class DepotError(Exception):
    pass


# --------------------------------------------------------------------- entries
@dataclass
class CarEntry:
    """One car as the manager sees it."""

    name: str                      # appearance record name == folder name
    car_id: int
    spec_stem: str = ""
    year: int = 0
    make: str = ""
    model: str = ""
    display_key: str = ""
    appearance_id: int = 0
    aero_flag: str = ""
    lods: list = field(default_factory=list)      # ['A','B',...,'shared']
    #: lod suffix (lower case) -> file size, for the signature
    sizes: dict = field(default_factory=dict)
    liveries: int = 0
    #: files under ``vehicles/<name>/livery`` (the paint textures)
    livery_textures: int = 0
    body_bytes: int = 0
    #: every file in the car folder, and their total size - part of the signature
    file_count: int = 0
    folder_bytes: int = 0
    folder: str = ""
    #: "vanilla" | "mod" | "unknown"
    status: str = "vanilla"
    #: True when a vanilla car's files no longer match the baseline.
    modified: bool = False
    #: Why this car is in the list even though it has no body model.
    note: str = ""
    #: The folder that actually holds this car's geometry.  Usually ``name``
    #: itself, but 368 of the 540 cars borrow another car's body through
    #: ``appearances.link.nct`` (all Formula 1 cars share one monocoque, every
    #: Formula E team shares one chassis).
    model_folder: str = ""
    #: Names tried before the hit, outermost first.  Empty when the car has its
    #: own geometry; two entries mean "uses A's body, which uses B's".
    model_chain: list = field(default_factory=list)
    #: The game's own name for the car, from ``gametext.txt``.  Empty for the
    #: ~100 cars whose spec carries no display-name key.
    display_name: str = ""
    #: PR / class / price / event membership, from the bundled reference table.
    ref: object = None
    #: How :attr:`ref` was found: "exact", "display", "model" or "".
    ref_rule: str = ""

    # ---- presentation ------------------------------------------------
    @property
    def label(self) -> str:
        if self.display_name:
            bits = [str(self.year) if self.year else "", self.make,
                    self.display_name]
        else:
            bits = [str(self.year) if self.year else "", self.make, self.model]
        text = " ".join(b for b in bits if b)
        return text or self.name

    @property
    def car_class(self) -> str:
        return getattr(self.ref, "car_class", "") if self.ref else ""

    @property
    def pr(self):
        return getattr(self.ref, "pr", None) if self.ref else None

    @property
    def has_body(self) -> bool:
        return any(l in BODY_LODS for l in self.lods)

    @property
    def shares_body(self) -> bool:
        """True when the geometry lives in another car's folder."""
        return bool(self.model_folder) and self.model_folder != self.name

    @property
    def best_lod(self) -> str:
        for l in BODY_LODS:
            if l in self.lods:
                return l
        return ""

    def signature(self) -> str:
        """Cheap fingerprint: id, body size, per-LOD sizes, file count, paints."""
        parts = [str(self.car_id), str(self.body_bytes), str(self.liveries),
                 str(self.file_count), str(self.folder_bytes)]
        parts += [f"{l}:{self.sizes.get(l, 0)}" for l in sorted(self.lods)]
        return "|".join(parts)

    def as_dict(self) -> dict:
        return {"id": self.car_id, "sig": self.signature()}


# ------------------------------------------------------------------ inventory
@dataclass
class Inventory:
    """Everything one scan found."""

    root: str                                  # the ``files`` folder
    depot: str
    apk: str
    cars: list = field(default_factory=list)   # CarEntry, sorted by name
    #: name -> appearance record, for the detail pane
    appearances: dict = field(default_factory=dict)
    #: names in the vanilla baseline that have no folder any more
    missing: list = field(default_factory=list)
    #: ids already taken, so the build dialog can propose the next one
    used_ids: set = field(default_factory=set)
    scan_seconds: float = 0.0
    warnings: list = field(default_factory=list)
    #: ``CAR_NAME_*`` -> english text, so the list can show "Lexus LFA" rather
    #: than "2012 Lexus LFA"; empty when gametext.txt is missing.
    names: dict = field(default_factory=dict)
    #: False when the bundled reference table could not be read.
    reference_ok: bool = True

    # ---- partitions --------------------------------------------------
    def by_status(self, status: str) -> list:
        return [c for c in self.cars if c.status == status]

    @property
    def vanilla(self) -> list:
        return self.by_status("vanilla")

    @property
    def mods(self) -> list:
        return self.by_status("mod")

    @property
    def unknown(self) -> list:
        return self.by_status("unknown")

    def get(self, name: str):
        for c in self.cars:
            if c.name == name:
                return c
        return None

    def free_id(self) -> int:
        ids = set(self.used_ids) or {0}
        return max(ids) + 1

    def makes(self) -> list:
        """Every manufacturer we have a car from, alphabetically."""
        return sorted({c.make for c in self.cars if c.make})

    def classes(self) -> list:
        """The classes the reference table gave us, in the game's own order."""
        return [c for c in carlib.classes()
                if any(e.car_class == c for e in self.cars)]

    def summary(self) -> str:
        return (f"{len(self.cars)} cars: {len(self.vanilla)} vanilla, "
                f"{len(self.mods)} mod, {len(self.unknown)} unknown")


# --------------------------------------------------------------- path helpers
def find_install(start: str = "") -> str:
    """Return the ``files`` folder for a path the user picked.

    Accepts the ``files`` folder itself, the depot, the extracted package root
    (which holds ``files/``), or anything above them.
    """
    if not start:
        return ""
    p = os.path.abspath(start)
    for _ in range(6):
        for cand in (p, os.path.join(p, "files")):
            if os.path.isdir(os.path.join(cand, ".depot")) and \
                    os.path.isdir(os.path.join(cand, "apk")):
                return cand
        if os.path.basename(p) == ".depot" and os.path.isdir(p):
            parent = os.path.dirname(p)
            if os.path.isdir(os.path.join(parent, "apk")):
                return parent
        parent = os.path.dirname(p)
        if parent == p:
            break
        p = parent
    return ""


def default_install() -> str:
    """Guess the install the tools in this workspace already use."""
    import glob
    for pat in (r"E:\DXT*Build*", r"E:\*Real*Racing*", r"D:\*Real*Racing*"):
        for hit in sorted(glob.glob(pat)):
            got = find_install(hit)
            if got:
                return got
    return ""


#: The four GPU families the game ships a texture set for, as the suffix a page
#: carries.  PVRTC is listed because an install can *hold* it; it is not in
#: :data:`WRITABLE_FAMILIES` because a block encoder cannot produce it.
FAMILY_SUFFIX = {
    "dxt": ".dxt.dds.z",
    "etc": ".etc.dds.z",
    "atc": ".atc.dds.z",
    "ptc": ".ptc.pvr.z",
    "rgb": ".rgb.pvr.z",
}
#: What a picture can be encoded into, which is what the setting offers.
WRITABLE_FAMILIES = ("dxt", "etc", "atc")


def detect_texture_family(root: str) -> str:
    """Which family this install's own pages are, by counting what is on disk.

    ``vehicles/common`` is the cheapest place to ask: it holds every shared page
    and the game ships exactly one family of it.  Returns ``""`` when the folder
    is missing or the answer is a tie - a user who set the format by hand should
    not have their answer replaced by a guess.
    """
    folder = os.path.join(root, ".depot", "vehicles", "common")
    if not os.path.isdir(folder):
        return ""
    counts: dict = {}
    try:
        names = os.listdir(folder)
    except OSError:
        return ""
    for leaf in names:
        low = leaf.lower()
        for key, suffix in FAMILY_SUFFIX.items():
            if low.endswith(suffix):
                counts[key] = counts.get(key, 0) + 1
                break
    if not counts:
        return ""
    best = max(counts.items(), key=lambda kv: kv[1])
    if sum(1 for n in counts.values() if n == best[1]) > 1:
        return ""
    return best[0]


# ------------------------------------------------------------- the mods file
#: Where the mods file prefers to live, and where it goes when the install is
#: read-only (an unpacked depot on a drive the user cannot write to, which is
#: the normal case: the game assets are shipped that way and nothing else
#: expects to write there).
STATE_DIRNAME = "RR3ModManager"
#: depot path -> chosen mods file, so scan and save never disagree
_MODS_PATH: dict = {}
#: depot path -> chosen state folder ("" when nothing is writable)
_STATE_DIR: dict = {}


def _state_dirs(depot: str) -> list:
    """Candidate folders for the mods file, best first.

    The install itself is deliberately **not** a candidate.  It used to be first
    in this list, which meant a plain read - opening the program, scanning the
    cars - could create a folder and write a probe file inside the user's
    unpacked game install.  The install is a backup: nothing here may write to
    it, and nothing here may even create a directory in it.

    Every candidate is namespaced by the install's own path, so two installs
    (the DXT one and the ETC one, say) never share one ``rr3mods.json`` and
    never inherit each other's "this car is a mod" flags.
    """
    import hashlib
    import sys
    import tempfile

    tag = hashlib.md5(os.path.abspath(depot).encode("utf-8")).hexdigest()[:10]
    out = []
    appdata = os.environ.get("APPDATA") or ""
    if appdata:
        out.append(os.path.join(appdata, STATE_DIRNAME, "state", tag))
    home = os.path.expanduser("~")
    if home and home != "~":
        out.append(os.path.join(home, "AppData", "Roaming", STATE_DIRNAME,
                                "state", tag))
    if getattr(sys, "frozen", False):
        # portable: the folder the exe sits in, which is writable by definition
        out.append(os.path.join(os.path.dirname(os.path.abspath(sys.executable)),
                                STATE_DIRNAME + "_state", tag))
    out.append(os.path.join(tempfile.gettempdir(), STATE_DIRNAME, "state", tag))
    if not getattr(sys, "frozen", False):
        # running from source: keep the state beside the code, not in temp
        out.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "work", "rrmod_state", tag))
    out.append(os.path.join(os.getcwd(), "work", "rrmod_state", tag))
    return out


def _legacy_paths(depot: str) -> list:
    """Where older versions kept the mods file, newest first.

    Read only: an install that already has one is picked up so existing work is
    not lost, but :func:`mods_path` never writes back to any of these.
    """
    import sys
    import tempfile

    out = [os.path.join(depot, MODS_FILE)]
    appdata = os.environ.get("APPDATA") or ""
    if appdata:
        out.append(os.path.join(appdata, STATE_DIRNAME, "state", MODS_FILE))
    home = os.path.expanduser("~")
    if home and home != "~":
        out.append(os.path.join(home, "AppData", "Roaming", STATE_DIRNAME,
                                "state", MODS_FILE))
    if getattr(sys, "frozen", False):
        out.append(os.path.join(os.path.dirname(os.path.abspath(sys.executable)),
                                STATE_DIRNAME + "_state", MODS_FILE))
    out.append(os.path.join(tempfile.gettempdir(), STATE_DIRNAME, "state",
                            MODS_FILE))
    return out


def _writable_dir(path: str) -> bool:
    """Can this folder be created and written in?  Never raises."""
    try:
        os.makedirs(path, exist_ok=True)
        probe = os.path.join(path, ".write_probe")
        with open(probe, "w", encoding="utf-8") as fh:
            fh.write("1")
        os.remove(probe)
        return True
    except OSError:
        return False


def _usable_dir(path: str) -> bool:
    """Is this folder already there and writable, without creating anything?"""
    try:
        return os.path.isdir(path) and os.access(path, os.W_OK | os.X_OK)
    except OSError:
        return False


def state_dir(depot: str, *, create: bool = True) -> str:
    """The folder this install's state lives in.

    ``create=False`` is for reading: it only reports a folder that is already
    there and writable, so opening the program and looking at the cars cannot
    leave a new directory behind anywhere.  Returns ``""`` when nothing is
    usable, so a caller can say so instead of writing into the install.

    :func:`mods_path` and the pages that keep their own files beside it all go
    through here, which is what makes "one folder per install" true everywhere
    rather than only for the mods file.
    """
    if create:
        cached = _STATE_DIR.get(depot)
        if cached is not None:
            return cached
    found = ""
    for folder in _state_dirs(depot):
        if _writable_dir(folder) if create else _usable_dir(folder):
            found = folder
            break
    if create:
        _STATE_DIR[depot] = found
    return found


def mods_path(depot: str, *, create: bool = True) -> str:
    """The mods file for this install.

    An existing file wins, wherever it is, because losing it would lose every
    "this car is a mod" flag.  Otherwise the first writable folder from
    :func:`state_dir` is used.  The answer is remembered for the process so a
    scan and a save always agree on one path.

    ``create=False`` never makes a directory: it answers with the file that is
    already there, or ``""``.  :func:`load_mods` uses that, which is why a scan
    of a fresh install leaves no trace.
    """
    if create:
        cached = _MODS_PATH.get(depot)
        if cached:
            return cached
    folder = state_dir(depot, create=create)
    if folder:
        own = os.path.join(folder, MODS_FILE)
        if os.path.isfile(own):
            if create:
                _MODS_PATH[depot] = own
            return own
    # An older version may have left one elsewhere; take it if this install has
    # no file of its own yet, so upgrading does not look like a fresh start.
    if not folder or not os.path.isfile(os.path.join(folder, MODS_FILE)):
        for legacy in _legacy_paths(depot):
            if os.path.isfile(legacy):
                if create:
                    _MODS_PATH[depot] = legacy
                return legacy
    if not create:
        return ""
    path = os.path.join(folder, MODS_FILE) if folder else ""
    _MODS_PATH[depot] = path
    return path


def load_mods(depot: str) -> dict:
    """Read this install's mods file.  Never creates one, never makes a folder.

    ``create=False`` is the whole point: scanning 540 cars must not leave a
    state directory behind, because a user who only opened the program to look
    would otherwise find new folders next to their unpacked game.
    """
    path = mods_path(depot, create=False)
    if not path or not os.path.isfile(path):
        return {"version": MODS_VERSION, "reference": "",
                "vanilla": {}, "mods": {}, "series": {}, "brands": {}}
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as exc:
        raise DepotError(f"{path}: {exc}") from exc
    data.setdefault("version", MODS_VERSION)
    data.setdefault("reference", "")
    data.setdefault("vanilla", {})
    data.setdefault("mods", {})
    data.setdefault("series", {})
    data.setdefault("brands", {})
    return data


def _inside_install(depot: str, path: str) -> bool:
    """Is ``path`` inside the install that ``depot`` belongs to?

    Checked by resolved path, so a symlink or a relative path cannot smuggle a
    write into the backup either.
    """
    try:
        target = os.path.abspath(path)
        root = os.path.abspath(os.path.dirname(depot))   # depot is <install>/.depot
        return os.path.commonpath([target, root]) == root
    except (OSError, ValueError):
        return False


def save_mods(depot: str, data: dict) -> None:
    """Write the mods file, refusing to write it inside the install.

    The install is a backup.  Older versions fell back to it when nothing else
    was writable, which turned a read-only drive into a slow corruption of the
    user's only clean copy - so a missing state folder is now an error with a
    name, not a silent write.  The path is also checked, not just trusted: a
    caller that hands in a writable state folder which happens to sit inside the
    install gets refused too.
    """
    path = mods_path(depot)
    if not path:
        raise DepotError(
            "there is nowhere writable to keep this install's state - the "
            "program will not write inside the game install itself. Set "
            "APPDATA, or run it somewhere writable.")
    if _inside_install(depot, path):
        raise DepotError(
            f"{path} is inside the game install, which is a backup - refusing "
            f"to write this install's state there. Set APPDATA, or run the "
            f"program somewhere writable.")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(data, fh, indent=1, sort_keys=True, ensure_ascii=False)
        fh.write("\n")
    os.replace(tmp, path)


def register_mod(depot: str, entry: CarEntry, *, kind: str = "new",
                 donor: str = "") -> dict:
    """Record a car as ours (call after the build or the adoption)."""
    data = load_mods(depot)
    data["mods"][entry.name] = {
        "id": entry.car_id,
        "kind": kind,
        "donor": donor,
        "created": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    data["vanilla"].pop(entry.name, None)
    save_mods(depot, data)
    return data


def unregister_mod(depot: str, name: str) -> dict:
    data = load_mods(depot)
    data["mods"].pop(name, None)
    save_mods(depot, data)
    return data


def register_series(depot: str, series_id: int, *, title: str = "",
                    group: str = "", template: int = 0) -> dict:
    """Record a career series as one we added.

    The career file itself cannot say which series were shipped by the studio
    and which we invented - the ids are just numbers - so the answer lives
    beside the car list.  It is what "only series I made" filters on, and it is
    the list to consult before deleting anything.
    """
    data = load_mods(depot)
    data.setdefault("series", {})[str(series_id)] = {
        "title": title,
        "group": group,
        "template": template,
        "created": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    save_mods(depot, data)
    return data


def unregister_series(depot: str, series_id: int) -> dict:
    data = load_mods(depot)
    data.setdefault("series", {}).pop(str(series_id), None)
    save_mods(depot, data)
    return data


def series_ids(depot: str) -> set:
    """``{series id, ...}`` of every series this program added."""
    data = load_mods(depot)
    out = set()
    for key in (data.get("series") or {}):
        try:
            out.add(int(key))
        except (TypeError, ValueError):
            continue
    return out


def register_brand(depot: str, name: str, *, logo: str = "") -> dict:
    """Record a manufacturer as one this program added.

    A brand is only a string in the spec, so nothing in the game can say whether
    it was shipped or invented.  Keeping the list here is what lets the Brands
    page show a brand with no cars yet, and what tells "only what I made" apart
    from the 53 the studio ships.
    """
    data = load_mods(depot)
    data.setdefault("brands", {})[name] = {
        "logo": logo,
        "created": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    save_mods(depot, data)
    return data


def unregister_brand(depot: str, name: str) -> dict:
    data = load_mods(depot)
    data.setdefault("brands", {}).pop(name, None)
    save_mods(depot, data)
    return data


def brand_names(depot: str) -> set:
    """``{brand name, ...}`` of every brand this program added."""
    data = load_mods(depot)
    return set((data.get("brands") or {}).keys())


def baseline_from_reference(reference_depot: str) -> dict:
    """``{name: {}}`` for every car folder in a pristine depot."""
    veh = os.path.join(reference_depot, "vehicles")
    if not os.path.isdir(veh):
        raise DepotError(f"no vehicles folder in {reference_depot}")
    out = {}
    for name in sorted(os.listdir(veh)):
        if os.path.isdir(os.path.join(veh, name)) and name not in (
                "data", "common", "decals", "shaders", "wheels"):
            out[name] = {}
    return out


# --------------------------------------------------------------------- scan
def _list_car_files(folder: str):
    """``([(lod_letter, size)], file_count, total_bytes)`` for one car folder.

    The file count and the byte total are part of the change signature: adding a
    ``_wing.banim`` or an ``_animations.xml`` to a car does not touch any LOD, so
    without them a car that gained an animation would still look untouched.
    """
    lods = []
    n_files = 0
    total = 0
    try:
        names = os.listdir(folder)
    except OSError:
        return lods, 0, 0
    for f in names:
        p = os.path.join(folder, f)
        try:
            size = os.path.getsize(p)
        except OSError:
            size = 0
        if os.path.isfile(p):
            n_files += 1
            total += size
        m = _LOD_RE.search(f)
        if m:
            lod = m.group(1)
            # Body levels read better as ``A``..``H``; the stand-alone models
            # keep the spelling the game uses (``shared``, ``int_a``).
            lod = lod.upper() if len(lod) == 1 else lod
            lods.append((lod, size))
    return lods, n_files, total


def _count_paints(depot: str, name: str) -> tuple[int, int]:
    """``(paint schemes, livery texture files)`` for one car."""
    paints = 0
    path = os.path.join(depot, *liverylib.LIVERY_DIR.split("/"),
                        f"{name}.liveries.bin.nct")
    if os.path.isfile(path):
        try:
            paints = len(liverylib.load(path).paints)
        except Exception:                        # noqa: BLE001
            paints = 0
    textures = 0
    livery_dir = os.path.join(depot, "vehicles", name, "livery")
    if os.path.isdir(livery_dir):
        try:
            textures = len(os.listdir(livery_dir))
        except OSError:
            textures = 0
    return paints, textures


def _record_name(rec) -> str:
    """``Record.name`` is bytes; the folder name is that text."""
    name = rec.name
    if isinstance(name, bytes):
        return name.decode("utf-8", "replace")
    return str(name)


def _lod_rank(lod: str) -> tuple:
    """Sort LODs A..H first, then the stand-alone models."""
    key = lod.lower()
    if key in _BODY_LOWER:
        return (0, _BODY_LOWER.index(key))
    return (1, STANDALONE.index(key) if key in STANDALONE else 9)


_CAR_NAMES: dict = {}


def car_names(depot: str) -> dict:
    """``{CAR_NAME_KEY: english text}`` for every car name in the game.

    Read from ``gametext.txt`` + ``text_en.txt`` only - the other eleven
    languages are the same keys in the same order, so loading them would cost
    ten times as much for nothing.  Parsing is ~0.9 s, so the result is cached
    per depot and a rescan does not pay for it again.
    """
    if depot in _CAR_NAMES:
        return _CAR_NAMES[depot]
    blobs = {}
    for leaf in (textlib.GAMETEXT, "text_en.txt"):
        path = os.path.join(depot, leaf)
        try:
            with open(path, "rb") as fh:
                blobs[leaf] = fh.read()
        except OSError:
            _CAR_NAMES[depot] = {}
            return {}
    try:
        table = textlib.Texts.from_blobs(blobs)
    except Exception:                            # noqa: BLE001 - names are a nicety
        _CAR_NAMES[depot] = {}
        return {}
    out = {}
    for key in table.keys():
        if key.startswith(textlib.PREFIX):
            key = key[len(textlib.PREFIX):]
        if key.startswith("CAR_NAME_"):
            out[key] = table.get(key)
    _CAR_NAMES[depot] = out
    return out


def forget_names(depot: str) -> None:
    """Drop the cached display names, so a rename shows without a restart.

    Parsing the two text files takes about a second, which is why the answer is
    kept; that also means a car renamed a minute ago still reads under its old
    name until the cache is told.  Every writer of ``gametext.txt`` calls this.
    """
    _CAR_NAMES.pop(depot, None)


#: car name -> spec stem, per install, with the signature it was built from.
_SPEC_STEMS: dict[str, tuple[tuple, dict]] = {}


def _stem_signature(depot: str, spec_dir: str) -> tuple:
    """What :func:`spec_stems` depends on, cheap enough to check every call.

    A build adds or rewrites a spec file and rewrites the appearance table, so
    those three stamps cover everything that can change the answer.  A folder
    under ``vehicles/`` is deliberately *not* part of it: this index never looks
    at car folders.
    """
    stamps = []
    for path in (spec_dir,
                 os.path.join(depot, *appearlib.APPEARANCES.split("/")),
                 os.path.join(depot, *linklib.LINK_TABLE.split("/"))):
        try:
            st = os.stat(path)
            stamps.append((st.st_mtime_ns, st.st_size))
        except OSError:
            stamps.append(None)
    try:
        count = len(os.listdir(spec_dir))
    except OSError:
        count = -1
    return tuple(stamps) + (count,)


def spec_stems(root: str) -> dict:
    """Which spec file belongs to which car, without reading a single car folder.

    ``scan`` answers the same question but also walks all 541 car folders to
    count their files, which costs about two seconds.  That was being paid by
    ``anim.spec_path`` - and ``spec_path`` sits inside ``stats.load``, i.e.
    inside every panel of the Build a car dialog, several times per car picked.
    Choosing a car in that dialog froze for ten seconds or more.

    The answer is cached per install and rebuilt when the spec directory or
    either table changes.  A stem is stable across everything this program
    writes (a build never renumbers a spec), so the cache survives a mod.
    """
    root = find_install(root) or os.path.abspath(root)
    depot = os.path.join(root, ".depot")
    spec_dir = os.path.join(depot, *speclib.SPEC_DIR.split("/"))
    if not os.path.isdir(spec_dir):
        return {}
    signature = _stem_signature(depot, spec_dir)
    hit = _SPEC_STEMS.get(depot)
    if hit and hit[0] == signature:
        return hit[1]

    try:
        _count, recs = appearlib.load(depot)
    except Exception:                            # noqa: BLE001 - no table, no names
        return {}
    by_id = {r.id: _record_name(r) for r in recs}

    out = {}
    for f in sorted(os.listdir(spec_dir)):
        m = _SPEC_RE.match(f)
        if not m:
            continue
        stem = f[: -len(".bin.nct")]
        try:
            aid = speclib.load_spec(depot, stem).appearance_id()
        except Exception:                        # noqa: BLE001
            continue
        name = by_id.get(aid)
        if name:
            out[name] = stem
    _SPEC_STEMS[depot] = (signature, out)
    return out


def forget_spec_stems(root: str) -> None:
    """Drop the cached stem index (called after adding or renaming a spec)."""
    depot = os.path.join(find_install(root) or os.path.abspath(root), ".depot")
    _SPEC_STEMS.pop(depot, None)


def scan(root: str, *, mods: dict | None = None,
         progress=None) -> Inventory:
    """Read the whole install.  Takes well under a second for 540 cars.

    Reading must not write: with no ``mods`` handed in this asks for the mods
    file and treats "there is none" as an empty one, rather than creating a
    folder and a probe file somewhere to find out where it would go.
    """
    t0 = time.time()
    root = find_install(root) or os.path.abspath(root)
    depot = os.path.join(root, ".depot")
    apk = os.path.join(root, "apk")
    if not os.path.isdir(depot):
        raise DepotError(f"no .depot in {root}")

    data = mods if mods is not None else load_mods(depot)
    vanilla_names = set(data.get("vanilla") or ())
    mod_names = set(data.get("mods") or ())

    inv = Inventory(root=root, depot=depot, apk=apk)
    inv.names = car_names(depot)
    refs = carlib.load()
    inv.reference_ok = bool(refs)

    # ---- appearances: id -> record, name -> record
    try:
        _count, recs = appearlib.load(depot)
    except Exception as exc:                     # noqa: BLE001 - reported, not fatal
        inv.warnings.append(f"appearances: {exc}")
        recs = []
    by_id = {}
    by_name = {}
    for r in recs:
        name = _record_name(r)
        by_id[r.id] = r
        by_name[name] = r
        inv.appearances[name] = r

    # ---- specs
    spec_dir = os.path.join(depot, *speclib.SPEC_DIR.split("/"))
    stems = {}
    if os.path.isdir(spec_dir):
        for f in sorted(os.listdir(spec_dir)):
            m = _SPEC_RE.match(f)
            if m:
                stems[f[: -len(".bin.nct")]] = int(m.group(1))
    inv.used_ids = set(stems.values())

    veh = os.path.join(depot, "vehicles")
    folders = set()
    if os.path.isdir(veh):
        folders = {n for n in os.listdir(veh)
                   if os.path.isdir(os.path.join(veh, n))}

    # ---- shared bodies: who borrows whose geometry
    try:
        links = linklib.load(depot)
    except Exception as exc:                     # noqa: BLE001 - reported, not fatal
        inv.warnings.append(f"appearances.link: {exc}")
        links = None

    total = len(stems) or 1
    for i, (stem, car_id) in enumerate(sorted(stems.items(), key=lambda kv: kv[1])):
        if progress and i % 40 == 0:
            progress(i / total)
        try:
            sp = speclib.load_spec(depot, stem)
        except Exception as exc:                 # noqa: BLE001
            inv.warnings.append(f"{stem}: {exc}")
            continue
        aid = 0
        try:
            aid = sp.appearance_id()
        except Exception:                        # noqa: BLE001
            pass
        rec = by_id.get(aid)
        if rec is None:
            inv.warnings.append(f"{stem}: appearance id {aid} is not in the table")
            continue
        name = _record_name(rec)
        e = CarEntry(name=name, car_id=car_id, spec_stem=stem,
                     appearance_id=aid, folder=os.path.join(veh, name))
        try:
            e.year = sp.year()
            e.make = sp.make()
            e.model = sp.model()
            e.display_key = sp.display_name_key()
            flag = sp.aero_flag()
            e.aero_flag = flag.decode("utf-8", "replace") if isinstance(flag, bytes) else str(flag)
        except Exception as exc:                 # noqa: BLE001
            inv.warnings.append(f"{name}: {exc}")
        lods, n_files, total_bytes = _list_car_files(e.folder)
        e.sizes = dict(lods)
        e.file_count = n_files
        e.folder_bytes = total_bytes
        e.lods = sorted({l for l, _s in lods}, key=_lod_rank)
        e.liveries, e.livery_textures = _count_paints(depot, name)
        e.body_bytes = sum(s for l, s in lods if l in BODY_LODS)
        if inv.names and e.display_key:
            e.display_name = inv.names.get(e.display_key, "")
        if refs:
            ref, rule = carlib.match(name, refs, display=e.display_name,
                                     make=e.make)
            e.ref = ref
            e.ref_rule = rule
        # A car without geometry of its own borrows another car's body through
        # appearances.link.nct.  Resolving that here is what lets the list show
        # "63 cars, one body" instead of 63 empty folders.
        model_folder, chain = linklib.resolve(
            depot, name, table=links,
            appearance_of=lambda n: _record_name(rec) if n == name else "")
        if not model_folder:
            model_folder, chain = name, []
        e.model_folder = model_folder
        e.model_chain = chain
        if not e.has_body:
            if e.model_folder != name:
                e.note = f"uses the {e.model_folder} body"
                mlods, _mn, _mb = _list_car_files(
                    os.path.join(veh, e.model_folder))
                e.lods = sorted({l for l, _s in mlods}, key=_lod_rank)
                e.body_bytes = sum(s for l, s in mlods if l in BODY_LODS)
            else:
                e.note = "no body model in the depot"
        # status
        if name in mod_names:
            e.status = "mod"
        elif name in vanilla_names:
            e.status = "vanilla"
        else:
            e.status = "unknown"
        if e.status == "vanilla":
            sig = (data["vanilla"].get(name) or {}).get("sig")
            if sig and sig != e.signature():
                e.modified = True
        inv.cars.append(e)

    inv.cars.sort(key=lambda c: c.name)
    for name in sorted(vanilla_names - {c.name for c in inv.cars}):
        inv.missing.append(name)
    inv.scan_seconds = time.time() - t0
    if progress:
        progress(1.0)
    return inv


def bootstrap(inv: Inventory, *, reference_depot: str = "") -> dict:
    """Create ``rr3mods.json`` from what is on disk right now.

    With a pristine ``reference_depot`` the vanilla list is taken from that
    copy, which is exact.  Without one the current state is snapshotted and
    every car is trusted as vanilla - that is only safe on a clean install.
    """
    data = load_mods(inv.depot)
    if reference_depot:
        data["reference"] = os.path.abspath(reference_depot)
        data["vanilla"] = {name: {} for name in baseline_from_reference(reference_depot)}
        for e in inv.cars:
            if e.name in data["vanilla"]:
                data["vanilla"][e.name] = e.as_dict()
    else:
        data["vanilla"] = {e.name: e.as_dict() for e in inv.cars
                           if e.status != "mod"}
    save_mods(inv.depot, data)
    return data


def car_detail(inv: Inventory, entry: CarEntry) -> dict:
    """Everything the detail pane shows, read lazily."""
    out = {
        "name": entry.name,
        "id": entry.car_id,
        "spec": entry.spec_stem,
        "year": entry.year, "make": entry.make, "model": entry.model,
        "display_key": entry.display_key,
        "appearance_id": entry.appearance_id,
        "aero": entry.aero_flag,
        "lods": list(entry.lods),
        "liveries": entry.liveries,
        "body_bytes": entry.body_bytes,
        "status": entry.status,
        "modified": entry.modified,
        "note": entry.note,
        "model_folder": entry.model_folder,
        "model_chain": list(entry.model_chain),
        "shares_body": entry.shares_body,
    }
    rec = inv.appearances.get(entry.name)
    if rec is not None:
        try:
            out["wheel_sizes"] = tuple(round(v, 4) for v in rec.wheel_sizes())
        except Exception:                        # noqa: BLE001
            pass
        try:
            out["tyre_radius"] = tuple(round(v, 4) for v in rec.tyre_radius())
        except Exception:                        # noqa: BLE001
            pass
        try:
            out["paint"] = rec.paint_colour().hex()
        except Exception:                        # noqa: BLE001
            pass
    try:
        L = liverylib.load_car(inv.depot, entry.name)
        out["paints"] = [p.name() for p in L.paints]
        out["textures"] = len(L.textures)
        out["material_overrides"] = len(L.materials)
        out["paint_details"] = []
        for p in L.paints:
            out["paint_details"].append({
                "name": p.name(),
                "materials": len(p.materials),
                "overrides": len(p.overrides),
                "rgb": p.rgb.hex() if p.rgb else "",
            })
    except Exception as exc:                     # noqa: BLE001
        out["livery_error"] = str(exc)
    try:
        from rr3lib import spec as _s
        sus = _s.load_suspension(inv.depot)
        rec2 = sus.get(entry.car_id)
        if rec2:
            out["tyre_diameter"] = tuple(
                round(v, 4) for v in _s.suspension_tyre_diameter(rec2))
    except Exception:                            # noqa: BLE001
        pass
    return out


def catalogue_summary() -> dict:
    """Static counts for the status bar (no disk access)."""
    return {"parts": len(catlib.part_names()),
            "materials": len(catlib.material_names()),
            "bases": len(catlib.bases()),
            "tags": len(catlib.tags())}
