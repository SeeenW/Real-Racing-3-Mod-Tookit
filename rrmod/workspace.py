"""A working copy that sits between the install and the device.

Every edit the manager makes lands here first, never in the install.  The
Deploy tab then shows what is waiting and pushes it only when asked.

Why it has to exist rather than being a convenience
---------------------------------------------------
An unpacked install is normally read-only (the reference one on E: answers
``PermissionError`` to every write), so an editor that writes "into the game"
cannot work at all.  The workspace is an install-shaped folder:

    <state>/workspace/<tag>/
        pending.json                          what has been staged
        .depot/asset_list_base.txtCache.txt   registry, seeded then kept current
        apk/res/asset_list_vehicle_data.txt   data list, same
        apk/res/asset_list_vehicle_<car>.txt  per-car list, seeded per car
        .depot/vehicles/<car>/...             the changed files
        .depot/vehicles/data/...              changed tables
        .depot/eds|feats/...                  graphics files

Because it has the same shape as an install, every :mod:`rrmod.edit` function
works on it unchanged - the manager just hands them the workspace root instead
of the install root.

Seeding rules
-------------
* File contents come from the **install** (it is the clean original).
* Manifests come from the **device** when one is attached, because the device
  is where cars the user added earlier live.  A manifest rebuilt from the
  install alone would delete them on the next push.  With no device the
  install's own manifests are used and the deploy step still merges.
"""
from __future__ import annotations

import json
import os
import shutil
import time

from . import depot as depotlib
from . import history as historylib

PENDING = "pending.json"
FORMAT = 1
WORKSPACE_DIR = "workspace"

REGISTRY_REL = ".depot/asset_list_base.txtCache.txt"
DATA_LIST_REL = "apk/res/asset_list_vehicle_data.txt"
MUSIC_DIR = "Tracks/data"
#: The decal font.  ``custom.decals.nct`` names glyphs by code point and the
#: glyphs themselves live in this one file at the root of ``.depot``; a decal
#: edit that adds a shape has to write both, so the font has to be mirrored with
#: the tables rather than left behind in the install.
DECAL_FONT = "r3_decals.ttf"
#: Where ``rrmod.edit`` keeps the files as they were before each edit.  Mirrored
#: here rather than imported from ``rrmod.edit`` to keep the two modules from
#: importing each other; the two strings have to stay equal.
BACKUP_DIR = historylib.BACKUP_DIR
#: Where the tables live: the 540 specs at the top, the per-car livery files
#: under ``liveries/``, the shared wheel sets under ``wheels/``.  Only the shared
#: part is mirrored up front (see ``ensure_data``); a car's own livery table and
#: its pages are copied when that car is opened.
DATA_DIR = ".depot/vehicles/data"
#: The pages many cars share: glass, carbon, stitching, brake rotors.  A livery
#: names them as ``common/car_windows_04.ptc.pvr.z``.  The folder holds 298 files
#: and 13.4 MB, but one car names only a handful of them and those total about
#: 1.3 MB - so the pages are copied per car by ``ensure_car_pages`` rather than
#: mirroring the whole shared folder for every edit.
COMMON_DIR = ".depot/vehicles/common"
#: folders under ``vehicles/`` that hold shared data rather than a car.  A staged
#: change under one of them belongs to no car, and reading it as one would put a
#: "common" row in the staged list.
SHARED_DIRS = ("data", "common", "decals", "shaders", "wheels")
#: Brand logos, career cards and every other sprite sheet.  Small (the logos are
#: a few kilobytes a size) and touched by pages that never open a car, so the
#: capture walk covers it directly instead of asking each page to hand over a
#: list.  It has to be captured: the atlas and the page it points at are two
#: files, and a push that carries only one of them shows the old sheet.
GUI_DIR = ".depot/gui_assets"
#: The game's material library - one 132 KB file that every mesh in every car is
#: shaded through.  It belongs to no car and lives under no page's folder, so it
#: is mirrored by name like the tables and captured by its own walk: cloning a
#: material writes this file and nothing else, and a push that left it behind
#: would install a livery row naming a material the engine has never heard of.
MATERIALS_DIR = ".depot/materials"



class WorkspaceError(Exception):
    """Something about the workspace cannot be done."""


# --------------------------------------------------------------- where it lives
def workspace_root(depot: str) -> str:
    """The folder holding this install's workspace.

    Beside the mods file, so it follows the same rules: never inside the
    install, always namespaced by the install's own path.  ``state_dir`` already
    carries the tag, so the workspace folder is one level down from it.
    """
    import hashlib
    state = depotlib.state_dir(depot)
    if not state:
        # Nothing writable anywhere: a path under temp that simply will not
        # exist.  Reading it is honest ("no workspace"), writing raises there.
        import tempfile
        state = os.path.join(tempfile.gettempdir(), "RR3ModManager", "state")
    tag = hashlib.md5(os.path.abspath(depot).encode("utf-8")).hexdigest()[:10]
    return os.path.join(state, WORKSPACE_DIR, tag)


def _read_json(path: str, default):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def _write_json(path: str, data) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=1, sort_keys=True)
        fh.write("\n")
    os.replace(tmp, path)


def _has_files(path: str) -> bool:
    """True when ``path`` holds at least one file, at any depth.

    Existence of a *directory* proves nothing here.  ``clear`` used to delete
    every file and leave the directory skeleton behind, and an empty
    ``vehicles/data`` is worse than a missing one: the readers took it as a real
    (but empty) install and reported every car as having no livery table.
    """
    if not os.path.isdir(path):
        return False
    for _dirpath, _dirs, files in os.walk(path):
        if files:
            return True
    return False


#: The four GPU families the depot can hold, longest first so ``.dxt.dds.z``
#: matches before ``.dds.z`` does.
_PAGE_SUFFIXES = (".dxt.dds.z", ".dxt.dds.bin", ".etc.dds.z", ".atc.dds.z",
                  ".ptc.pvr.z", ".rgb.pvr.z", ".dds.z", ".pvr.z", ".dds", ".pvr")


def _resolve_page(depot: str, car: str, rel: str) -> str:
    """Depot-relative path of the file behind a page a livery names, or ``""``.

    A livery names whichever copy the device it was authored for loads
    (``common/car_windows_04.ptc.pvr.z``) and the depot unpacks only one family,
    so the name has to be tried in each family before giving up.  The search
    order matches :func:`rrmod.textures.page_path`: the car's own folder, then
    the shared vehicle folder, then the depot root.
    """
    rel = str(rel or "").replace("\\", "/").lstrip("/")
    if not rel or ".." in rel.split("/"):
        return ""
    stem = rel
    for suffix in _PAGE_SUFFIXES:
        if rel.lower().endswith(suffix):
            stem = rel[: -len(suffix)]
            break
    names = [rel]
    if stem != rel:
        names += [stem + other for other in _PAGE_SUFFIXES]
    bases = [f"vehicles/{car}", "vehicles", ""]
    for base in bases:
        for name in names:
            candidate = (f"{base}/{name}" if base else name)
            if os.path.isfile(os.path.join(depot, *candidate.split("/"))):
                return candidate
    return ""


# ------------------------------------------------------------------- the object
class Workspace:
    """The staged changes for one install.

    ``root`` is the workspace folder itself and is what the edit helpers are
    given; ``install`` is the read-only original it shadows.
    """

    def __init__(self, install: str):
        self.install = os.path.abspath(install)
        self.depot = os.path.join(self.install, ".depot")
        self.root = workspace_root(self.depot)
        self.ws_depot = os.path.join(self.root, ".depot")
        self._index_path = os.path.join(self.root, PENDING)
        self._data = None
        self._data_done = False
        self._common_done = False

    # ---------------------------------------------------------------- plumbing
    @property
    def data(self) -> dict:
        if self._data is None:
            data = _read_json(self._index_path, None)
            if not isinstance(data, dict) or data.get("format") != FORMAT:
                data = {"format": FORMAT, "install": self.install,
                        "files": {}, "tables": {}, "cars": {}, "made": ""}
            data.setdefault("files", {})
            data.setdefault("tables", {})
            data.setdefault("cars", {})
            self._data = data
        return self._data

    def save(self) -> None:
        self.data["install"] = self.install
        _write_json(self._index_path, self.data)

    def _abs(self, rel: str) -> str:
        """Workspace path for a game-relative path (``/vehicles/...``)."""
        return os.path.join(self.root, *rel.lstrip("/").split("/"))

    def _install_abs(self, rel: str) -> str:
        return os.path.join(self.install, *rel.lstrip("/").split("/"))

    # ------------------------------------------------------------------ seeding
    def exists(self) -> bool:
        return os.path.isfile(self._index_path)

    def ensure(self, *, device=None, log=print) -> dict:
        """Create the workspace and seed the manifests.  Safe to call twice."""
        made = {"root": self.root, "created": False, "seeded": [],
                "from_device": False, "problems": []}
        if self.exists():
            # A working copy made before the nineteen ``asset_list_track_common_*``
            # lists were mirrored still needs them: adding a track page has to
            # book four rows in whichever of them owns the page's folder, and a
            # list that is not here cannot be written.  Mirroring is by name, so
            # this is a directory listing on the second call.
            lists = self.ensure_lists(log=None)
            if lists:
                made["lists"] = len(lists)
            return made
        os.makedirs(self.root, exist_ok=True)
        made["created"] = True
        made["made"] = time.strftime("%Y-%m-%d %H:%M:%S")
        self.data["made"] = made["made"]

        if device is not None:
            try:
                from . import deploy as deploylib
                for rel in (REGISTRY_REL, DATA_LIST_REL):
                    blob = deploylib._remote_bytes(device, rel)
                    if not blob:
                        made["problems"].append(f"the device has no {rel}")
                        continue
                    target = self._abs(rel)
                    os.makedirs(os.path.dirname(target), exist_ok=True)
                    with open(target, "wb") as fh:
                        fh.write(blob)
                    made["seeded"].append(rel)
                made["from_device"] = bool(made["seeded"])
            except Exception as exc:                    # noqa: BLE001 - report, do not fail
                made["problems"].append(f"could not read the device: {exc}")

        if not made["seeded"]:
            for rel in (REGISTRY_REL, DATA_LIST_REL):
                src = self._install_abs(rel)
                if not os.path.isfile(src):
                    made["problems"].append(f"this install has no {rel}")
                    continue
                target = self._abs(rel)
                os.makedirs(os.path.dirname(target), exist_ok=True)
                shutil.copyfile(src, target)
                made["seeded"].append(rel)
            log("workspace seeded from the install; a push will still merge with "
                "whatever the device holds")

        # Every asset list, not just the two above.  An edit has to rewrite
        # whichever list claims the file it touches - a logo page lives in
        # ``asset_list_gui_assets_core.txt`` - and a list the working copy does
        # not carry used to be a dead end.  They are 4.6 MB in total, which is
        # worth it: without them the index cannot tell "this path is unclaimed"
        # from "this path's list was never mirrored".
        lists = self.ensure_lists(log=None)
        if lists:
            made["lists"] = len(lists)
        # Remember what was seeded, so ``summary`` can say whether this working
        # copy came from the device or from the install.
        if made["seeded"]:
            self.data["seeded"] = sorted(made["seeded"])
        self.save()
        return made

    def ensure_lists(self, *, log=None) -> list:
        """Mirror every ``apk/res/asset_list*.txt`` the install ships.

        Returns the ones that had to be copied.  Cheap after the first call: the
        folder is compared by name, not by content.
        """
        src_dir = os.path.join(self.install, "apk", "res")
        if not os.path.isdir(src_dir):
            return []
        dst_dir = os.path.join(self.root, "apk", "res")
        os.makedirs(dst_dir, exist_ok=True)
        copied = []
        for f in sorted(os.listdir(src_dir)):
            if not (f.startswith("asset_list") and f.endswith(".txt")):
                continue
            src = os.path.join(src_dir, f)
            dst = os.path.join(dst_dir, f)
            if os.path.isfile(dst):
                continue
            shutil.copyfile(src, dst)
            copied.append(f"apk/res/{f}")
        if log is not None and copied:
            log(f"{len(copied)} asset list(s) mirrored")
        return copied

    def _seed_car_manifest(self, name: str) -> str:
        """Make sure the per-car list for ``name`` is present in the workspace."""
        rel = f"apk/res/asset_list_vehicle_{name}.txt"
        target = self._abs(rel)
        if os.path.isfile(target):
            return rel
        src = self._install_abs(rel)
        if os.path.isfile(src):
            os.makedirs(os.path.dirname(target), exist_ok=True)
            shutil.copyfile(src, target)
            self.data["cars"][name] = rel
            self.save()
        return rel

    # --------------------------------------------------------------- mirroring
    def ensure_car(self, name: str, *, log=None) -> str:
        """Copy a car's folder into the workspace so the edit helpers can work.

        :mod:`rrmod.edit` reads the file it is about to replace, so the folder
        has to exist where it is pointed.  Copying one car is a few megabytes
        and happens once per car per session.

        Along with the car folder come the shared tables (``ensure_data``), this
        car's own livery table (``ensure_livery``) and the texture pages it names
        (``ensure_car_pages``).  Those are exactly what the paint, parts and
        texture pages read, and copying them per car is what keeps the working
        copy at a few megabytes instead of the whole 17 MB of shared trees.
        """
        src = os.path.join(self.install, ".depot", "vehicles", name)
        if not os.path.isdir(src):
            raise WorkspaceError(f"this install has no vehicles/{name}")
        dst = os.path.join(self.root, ".depot", "vehicles", name)
        # ``_has_files`` rather than ``isdir``: a car folder left behind empty by
        # a failed copy would otherwise never be filled in again, and every read
        # of that car would fail as if it had no model.
        if not _has_files(dst):
            shutil.copytree(src, dst, dirs_exist_ok=True)
            self.data["cars"][name] = dst
            self.save()
        self.ensure_data(log=log)
        self.ensure_livery(name)
        self.ensure_car_pages(name)
        self._seed_car_manifest(name)
        return dst

    def ensure_table(self, rel_leaf: str) -> str:
        """Copy one of ``.depot/vehicles/data`` into the workspace."""
        rel = f".depot/vehicles/data/{rel_leaf}"
        target = self._abs(rel)
        if os.path.isfile(target):
            return target
        src = self._install_abs(rel)
        if not os.path.isfile(src):
            raise WorkspaceError(f"this install has no {rel}")
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copyfile(src, target)
        return target

    def ensure_data(self, *, log=None) -> list:
        """Mirror the shared tables of ``.depot/vehicles/data``, not the whole tree.

        What an edit actually reads from that folder is small: the 540 specs at
        the top (they are what makes a car exist at all - a scan without them
        finds nothing), the shared tables in :attr:`TABLES`, and the three
        string tables under ``liveries/``.  That is about 1.6 MB.

        The other 542 files there are one livery table per car, 1.6 MB of them,
        and copying all of it for every edit was the "it copies everything"
        complaint: a build that touches one car does not need the other 539
        cars' paint schemes.  They are mirrored per car by :meth:`ensure_livery`.

        Guessing which leaf an edit opens was once a bug in the other direction -
        a paint edit died with ``no such file or directory`` on the livery table.
        The rule now is: everything that is shared is copied here, everything
        that belongs to one car is copied when that car is opened.
        """
        if self._data_done and _has_files(self._abs(DATA_DIR)):
            return []
        src = self._install_abs(DATA_DIR)
        dst = self._abs(DATA_DIR)
        if not os.path.isdir(src):
            return []
        os.makedirs(dst, exist_ok=True)
        os.makedirs(os.path.join(dst, "liveries"), exist_ok=True)
        wanted = []
        for f in sorted(os.listdir(src)):
            if not os.path.isfile(os.path.join(src, f)):
                continue
            # the specs, the shared tables, and the customiser tables
            if f.endswith(".bin.nct") and f.split("_")[0].isdigit():
                wanted.append(f)
            elif f in self.TABLES:
                wanted.append(f)
            elif f.startswith("custom."):
                wanted.append(f)
            elif f in ("car.brakes.nct", "car.gearbox.nct", "consts.stats.nct"):
                wanted.append(f)
        for leaf in ("liveryStringTable.bin.nct", "default.liveries.bin.nct"):
            wanted.append(f"liveries/{leaf}")
        copied = []
        for leaf in wanted:
            rel = leaf.replace("\\", "/")
            source = os.path.join(src, *rel.split("/"))
            if not os.path.isfile(source):
                continue
            target = os.path.join(dst, *rel.split("/"))
            if os.path.exists(target):
                continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            shutil.copyfile(source, target)
            copied.append(rel)
        self._data_done = True
        # The decal font sits at the root of .depot, not under vehicles/data, so
        # the walk above cannot reach it.  It goes with the tables because
        # custom.decals.nct and the font have to agree on which code points have
        # a glyph: a decal added to one without the other is invisible in the
        # menu and the game copes by drawing nothing.
        font_src = self._install_abs(".depot/" + DECAL_FONT)
        font_dst = self._abs(".depot/" + DECAL_FONT)
        if os.path.isfile(font_src) and not os.path.exists(font_dst):
            os.makedirs(os.path.dirname(font_dst), exist_ok=True)
            shutil.copyfile(font_src, font_dst)
            copied.append(".depot/" + DECAL_FONT)
        if log is not None and copied:
            log(f"{len(copied)} table(s) copied into the working copy")
        return copied

    def ensure_livery(self, car: str) -> str:
        """Mirror one car's livery table, which is all a paint edit needs."""
        rel = f"{DATA_DIR}/liveries/{car}.liveries.bin.nct"
        target = self._abs(rel)
        if os.path.isfile(target):
            return target
        src = self._install_abs(rel)
        if not os.path.isfile(src):
            return ""
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copyfile(src, target)
        return target

    def ensure_car_pages(self, car: str) -> list:
        """Mirror the texture pages this car names, and nothing else.

        A car names around sixteen pages and they total roughly 1.3 MB, while
        ``vehicles/common`` holds 13.4 MB of pages shared across the whole grid.
        Copying the whole shared folder so that one car can read six of its files
        is the other half of the "it copies everything" complaint, so the pages
        are resolved through the livery and copied one by one.

        Missing pages are not an error: a livery names whichever GPU family its
        device loads, and the depot unpacks only one, so a page that cannot be
        resolved is simply left out and the page list shows it as unavailable.
        """
        from rr3lib import livery as liverylib

        copied = []
        try:
            L = liverylib.load_car(self._install_abs(".depot"), car)
        except Exception:                            # noqa: BLE001 - a missing table is not fatal
            return copied
        depot_src = self._install_abs(".depot")
        for _slot, raw in getattr(L, "textures", ()) or ():
            rel = raw.decode("ascii", "replace") if isinstance(raw, bytes) else str(raw)
            rel = rel.replace("\\", "/").lstrip("/")
            if not rel:
                continue
            found = _resolve_page(depot_src, car, rel)
            if not found:
                continue
            target = self._abs(f".depot/{found}")
            if os.path.isfile(target):
                continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            shutil.copyfile(os.path.join(depot_src, *found.split("/")), target)
            copied.append(found)
        return copied

    def ensure_specs(self) -> None:
        """Kept for callers that only want the specs; mirrors the whole tree."""
        self.ensure_data()

    def ensure_common(self, *, log=None) -> list:
        """Kept for callers that still ask for the shared tree up front.

        Nothing calls it any more: the pages a car names are copied by
        :meth:`ensure_car_pages`, which is what keeps the working copy small.
        A caller that genuinely needs the whole shared folder (a texture browser
        that lists every page, say) still gets it, and only what is missing.
        """
        if self._common_done and _has_files(self._abs(COMMON_DIR)):
            return []
        src = self._install_abs(COMMON_DIR)
        dst = self._abs(COMMON_DIR)
        if not os.path.isdir(src):
            return []
        os.makedirs(dst, exist_ok=True)
        copied = []
        for dirpath, _dirs, files in os.walk(src):
            rel_dir = os.path.relpath(dirpath, src)
            out_dir = dst if rel_dir == "." else os.path.join(dst, rel_dir)
            os.makedirs(out_dir, exist_ok=True)
            for f in files:
                target = os.path.join(out_dir, f)
                if os.path.exists(target):
                    continue
                shutil.copyfile(os.path.join(dirpath, f), target)
                copied.append(f)
        self._common_done = True
        if log is not None and copied:
            log(f"{len(copied)} shared page(s) copied into the working copy")
        return copied

    def mirrored(self) -> bool:
        """Is the workspace complete enough to read a car through?

        The test is the shared tables under ``vehicles/data``: without the specs
        :func:`rrmod.depot.scan` finds no cars at all, and every page below the
        car list reads through that scan.  A workspace that has the folder but
        no files in it is the state that made every page go blank, so the test is
        "holds files", not "the folder exists".

        ``vehicles/common`` is deliberately not required any more.  The shared
        pages are copied per car by :meth:`ensure_car_pages`, so a workspace
        holding the tables and one car's pages is complete for that car - and
        demanding the whole 13.4 MB folder up front was exactly the "it copies
        everything" cost this avoids.
        """
        if not self.exists():
            return False
        if not _has_files(self._abs(DATA_DIR)):
            self._data_done = False
            return False
        return True

    #: the shared tables a build needs to read.  About 1.7 MB in total, so the
    #: workspace can afford to hold its own copy and never have to reach into a
    #: read-only install while building.
    TABLES = ("cardesc.list.nct", "carappearances.appearances.nct",
              "suspensionbehaviour.suspensiondata.nct",
              "cardamagethresholds.damage.nct", "carupgrade.upgrades.nct",
              "carparts.parts.nct", "carrepairs.repairs.nct",
              "consts.stats.nct", "appearances.link.nct")

    def ensure_tables(self) -> list:
        """Copy the shared tables and every spec into the workspace."""
        self.ensure_specs()
        data = os.path.join(self.root, ".depot", "vehicles", "data")
        os.makedirs(os.path.join(data, "liveries"), exist_ok=True)
        copied = []
        for leaf in self.TABLES:
            target = os.path.join(data, leaf)
            if os.path.isfile(target):
                continue
            src = os.path.join(self.install, ".depot", "vehicles", "data", leaf)
            if os.path.isfile(src):
                shutil.copyfile(src, target)
                copied.append(leaf)
        for leaf in ("liveryStringTable.bin.nct", "default.liveries.bin.nct"):
            target = os.path.join(data, "liveries", leaf)
            if os.path.isfile(target):
                continue
            src = os.path.join(self.install, ".depot", "vehicles", "data",
                               "liveries", leaf)
            if os.path.isfile(src):
                shutil.copyfile(src, target)
                copied.append(leaf)
        return copied

    def ensure_materials(self, *, log=None) -> str:
        """Mirror ``materials.bin``, which a material edit rewrites wholesale.

        The file is 132 KB, so copying it once per working copy costs nothing and
        means the material library a page reads is the one a push would carry -
        the install stays read only, as everywhere else.
        """
        rel = f"{MATERIALS_DIR}/materials.bin"
        target = self._abs(rel)
        if os.path.isfile(target):
            return target
        src = self._install_abs(rel)
        if not os.path.isfile(src):
            return ""
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copyfile(src, target)
        if log is not None:
            log("materials.bin copied into the working copy")
        return target


    def ensure_gfx(self) -> None:
        """Copy the two graphics files so the editor has a base to work from."""
        for rel in (".depot/eds/AndroidHigh.plist", ".depot/feats/AndroidHigh.feats"):
            target = self._abs(rel)
            if os.path.isfile(target):
                continue
            src = self._install_abs(rel)
            if os.path.isfile(src):
                os.makedirs(os.path.dirname(target), exist_ok=True)
                shutil.copyfile(src, target)

    def ensure_rel(self, rel: str) -> str:
        """Copy one game-relative file into the workspace and return its path.

        Used by the editors whose data does not live under ``vehicles/`` - the
        music playlists and the career file - so they all follow the same rule:
        the workspace copy is the one that gets edited and pushed.
        """
        target = self._abs(rel)
        if os.path.isfile(target):
            return target
        src = self._install_abs(rel)
        if not os.path.isfile(src):
            raise WorkspaceError(f"this install has no {rel}")
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copyfile(src, target)
        return target

    def ensure_music(self) -> str:
        """Mirror the playlists so they can be edited without the install.

        ``Tracks/data`` sits under the depot, so the mirrored copy has to keep
        the same ``.depot/`` prefix - the deploy step compares and pushes
        install-relative paths and a file in the wrong place would be staged as
        a brand new one.
        """
        rel_dir = f".depot/{MUSIC_DIR}"
        src = self._install_abs(rel_dir)
        dst = self._abs(rel_dir)
        if os.path.isdir(src):
            os.makedirs(dst, exist_ok=True)
            for f in os.listdir(src):
                if not f.endswith(".bin.nct"):
                    continue
                d = os.path.join(dst, f)
                if not os.path.isfile(d):
                    shutil.copyfile(os.path.join(src, f), d)
        return dst

    # ----------------------------------------------------------------- capturing
    def capture(self, car: str = "", *, log=None) -> list:
        """Record every file in the workspace that differs from the install.

        Called after an edit has run against :attr:`root`.  Comparing against the
        install rather than trusting the edit's return value means every path -
        a replaced LOD, a new banim, a spec flag, a repainted atlas - is picked
        up the same way, and a file the edit wrote but did not mention is not
        silently left behind.
        """
        from . import edit as editlib

        changed = []
        roots = []
        if car:
            roots.append((f".depot/vehicles/{car}",
                          f".depot/vehicles/{car}"))
        else:
            roots.append((".depot/vehicles", ".depot/vehicles"))
        for sub, prefix in roots:
            base = self._abs(sub)
            if not os.path.isdir(base):
                continue
            for dirpath, _dirs, files in os.walk(base):
                rel_dir = os.path.relpath(dirpath, base).replace(os.sep, "/")
                for f in files:
                    if f.startswith("_") or f.endswith(".tmp"):
                        continue
                    local = os.path.join(dirpath, f)
                    rel = (f"{prefix}/{f}" if rel_dir == "."
                           else f"{prefix}/{rel_dir}/{f}")
                    install = self._install_abs(rel)
                    if not os.path.isfile(install):
                        action = "add"
                    elif editlib.md5_file(local) != editlib.md5_file(install):
                        action = "replace"
                    else:
                        continue
                    changed.append(self.stage(rel, local, car=car, action=action))
        # specs and the shared tables live outside the car folder
        for sub, prefix in ((DATA_DIR, DATA_DIR), (COMMON_DIR, COMMON_DIR)):
            base = self._abs(sub)
            if not os.path.isdir(base):
                continue
            for dirpath, _dirs, files in os.walk(base):
                rel_dir = os.path.relpath(dirpath, base).replace(os.sep, "/")
                for f in files:
                    if f.startswith("_"):
                        continue
                    local = os.path.join(dirpath, f)
                    rel = (f"{prefix}/{f}" if rel_dir == "."
                           else f"{prefix}/{rel_dir}/{f}")
                    action = self._diff(rel)
                    if not action:
                        continue
                    changed.append(self.stage(rel, local, car="", action=action))
        # the two graphics files sit beside the depot's other shared data
        for rel in (".depot/eds/AndroidHigh.plist", ".depot/feats/AndroidHigh.feats"):
            local = self._abs(rel)
            if not os.path.isfile(local):
                continue
            install = self._install_abs(rel)
            if not os.path.isfile(install):
                action = "add"
            elif editlib.md5_file(local) != editlib.md5_file(install):
                action = "replace"
            else:
                continue
            changed.append(self.stage(rel, local, car="", action=action))
        # Brand logos and career cards live under gui_assets, which no car edit
        # walks.  Without this a new logo page was staged but its atlas was not,
        # and the menu kept showing the old sheet.
        for rel in self._gui_rels():
            action = self._diff(rel)
            if not action:
                continue
            changed.append(self.stage(rel, self._abs(rel), car="", action=action))
        # materials.bin is written whole when a material is cloned, and it is
        # neither a car's file nor a page: without this walk the new library sat
        # in the working copy and the push carried only the livery row that
        # names it.
        for rel in self._materials_rels():
            action = self._diff(rel)
            if not action:
                continue
            changed.append(self.stage(rel, self._abs(rel), car="", action=action))
        if log is not None and changed:
            log(f"{len(changed)} file(s) staged")
        return changed

    def _materials_rels(self) -> list:
        """Every file under ``.depot/materials`` the working copy holds."""
        base = self._abs(MATERIALS_DIR)
        out = []
        if not os.path.isdir(base):
            return out
        for dirpath, _dirs, files in os.walk(base):
            rel_dir = os.path.relpath(dirpath, base).replace(os.sep, "/")
            for f in files:
                if f.startswith("_") or f.endswith(".tmp"):
                    continue
                rel = (f"{MATERIALS_DIR}/{f}" if rel_dir == "."
                       else f"{MATERIALS_DIR}/{rel_dir}/{f}")
                out.append(rel)
        return sorted(out)

    def _gui_rels(self) -> list:
        """Every file under ``gui_assets`` the working copy has touched.

        The brand page writes an atlas and a page per screen size; the career
        page writes card art.  They are all under ``.depot/gui_assets`` and they
        are all small, so a walk is cheaper than having each caller remember to
        hand its list over.
        """
        base = self._abs(GUI_DIR)
        out = []
        if not os.path.isdir(base):
            return out
        for dirpath, _dirs, files in os.walk(base):
            rel_dir = os.path.relpath(dirpath, base).replace(os.sep, "/")
            for f in files:
                if f.startswith("_"):
                    continue
                rel = (f"{GUI_DIR}/{f}" if rel_dir == "."
                       else f"{GUI_DIR}/{rel_dir}/{f}")
                out.append(rel)
        return sorted(out)

    def _diff(self, rel: str) -> str:
        """``"add"``, ``"replace"`` or ``""`` for one workspace file."""
        from . import edit as editlib

        local = self._abs(rel)
        if not os.path.isfile(local):
            return ""
        install = self._install_abs(rel)
        if not os.path.isfile(install):
            return "add"
        if editlib.md5_file(local) != editlib.md5_file(install):
            return "replace"
        return ""

    def capture_music(self, *, log=None) -> list:
        """Stage every playlist in the workspace that differs from the install."""
        rel_dir = f".depot/{MUSIC_DIR}"
        base = self._abs(rel_dir)
        changed = []
        if not os.path.isdir(base):
            return changed
        for f in sorted(os.listdir(base)):
            if not f.endswith(".bin.nct"):
                continue
            rel = f"{rel_dir}/{f}"
            action = self._diff(rel)
            if not action:
                continue
            changed.append(self.stage(rel, self._abs(rel), action=action))
        if log is not None and changed:
            log(f"{len(changed)} playlist(s) staged")
        return changed

    def capture_paths(self, rels, *, log=None) -> list:
        """Stage the given game-relative paths if they differ from the install.

        The career editor knows exactly which files it wrote, so it hands the
        list over instead of having the workspace walk a folder - the text files
        alone would otherwise cost a full 14 MB comparison.
        """
        changed = []
        for rel in rels:
            action = self._diff(rel)
            if not action:
                continue
            changed.append(self.stage(rel, self._abs(rel), action=action))
        if log is not None and changed:
            log(f"{len(changed)} career file(s) staged")
        return changed



    # ------------------------------------------------------------------ staging
    def stage(self, rel: str, local: str, *, car: str = "", action: str = "",
              note: str = "") -> dict:
        """Copy ``local`` into the workspace as game path ``rel``."""
        if not os.path.isfile(local):
            raise WorkspaceError(f"{local} does not exist")
        target = self._abs(rel)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        if os.path.abspath(local) != os.path.abspath(target):
            shutil.copyfile(local, target)
        size = os.path.getsize(target)
        entry = self.data["files"].get(rel, {})
        entry.update({"rel": rel, "car": car or entry.get("car", ""),
                      "action": action or entry.get("action", "replace"),
                      "note": note or entry.get("note", ""),
                      "bytes": size, "staged": time.strftime("%Y-%m-%d %H:%M:%S")})
        self.data["files"][rel] = entry
        if car:
            self._seed_car_manifest(car)
        self.save()
        return dict(entry, path=target)

    def stage_bytes(self, rel: str, blob: bytes, **kw) -> dict:
        target = self._abs(rel)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "wb") as fh:
            fh.write(blob)
        return self.stage(rel, target, **kw)

    def forget(self, rel: str, *, remove: bool = True) -> bool:
        """Drop a path from the staged list.  Returns whether it was staged.

        ``remove`` also deletes the working copy's file, which is what the
        discard path wants: the copy is disposable and the next edit re-mirrors
        it.  Undo passes ``False``, because there the file has just been put
        back to the install's bytes and deleting it would be wrong - and for
        ``gui_assets`` it would be permanent, since nothing re-mirrors that
        folder (a logo page that vanished from the working copy made the Brands
        page lose the picture it had just undone back to).
        """
        had = rel in self.data["files"]
        self.data["files"].pop(rel, None)
        target = self._abs(rel)
        if remove and os.path.isfile(target):
            os.remove(target)
        if had:
            self.save()
        return had

    def mark_pushed(self, rels) -> int:
        """Remember that these files now match what the device holds.

        A pushed file used to stay in the staged list for ever: the Deploy tab
        kept offering it, the quit prompt kept asking about it, and the next
        push sent it again.  The file itself stays in the workspace, because
        deleting it would make the next edit start from the install's copy and
        silently drop the change that was just pushed - instead the md5 of what
        was sent is recorded, and a row whose file still matches that md5 is not
        offered again.  Touch the file and it comes back as staged.
        """
        from . import edit as editlib

        n = 0
        for rel in rels:
            entry = self.data["files"].get(rel)
            if not entry:
                continue
            local = self._abs(rel)
            if not os.path.isfile(local):
                continue
            entry["pushed"] = editlib.md5_file(local)
            entry["pushed_bytes"] = os.path.getsize(local)
            # Whole seconds are not enough: two writes inside one second that
            # happen to leave the same size would compare equal and the second
            # edit would never be offered for pushing.  Nanoseconds come from
            # st_mtime_ns, which every platform this runs on provides.
            entry["pushed_mtime"] = int(os.path.getmtime(local))
            entry["pushed_ns"] = os.stat(local).st_mtime_ns
            entry["pushed_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            n += 1
        if n:
            self.save()
        return n

    def undo_step(self) -> dict:
        """Put back the files of the newest edit, and only those.

        Undo used to empty the whole working copy, so throwing away a brand that
        had gone wrong also threw away the car that was half rebuilt - two edits
        that had nothing to do with each other.  Every edit already writes its
        previous files into ``_rrmod_backup/<stamp>/`` (see
        :func:`rrmod.edit._begin`), one folder per edit, so the newest of those
        folders *is* the last edit.  Restoring it undoes that edit and leaves the
        rest alone.

        The restored files then go back through the ordinary staging test: a file
        that now matches the install again is no longer staged, and one that
        still differs (because an earlier edit changed it too) stays staged with
        its new hash.  The backup folder is removed afterwards - keeping it would
        make a second Undo repeat the same step instead of going further back.
        """
        from . import edit as editlib

        steps = editlib.backups(self.root)
        if not steps:
            return {"stamp": "", "files": 0, "staged": 0, "unstage": 0}
        return self.undo_steps(steps[:1])

    def undo_steps(self, stamps_) -> dict:
        """Put back the files of the given steps, and only those.

        The panel lets a user tick several steps at once ("take me back to before
        the wing and the paint"), so the restore is done by
        :func:`rrmod.history.restore`: it walks the steps newest first, which
        leaves the bytes the *oldest* ticked step saved - the state before any of
        them.  Doing it newest-first also means a file that only two of the steps
        touched ends up as old as the older of the two, which is what "go back"
        means.
        """
        from . import edit as editlib

        wanted = [s for s in stamps_
                  if os.path.isdir(os.path.join(historylib.dir_for(self.root), s))]
        if not wanted:
            return {"stamp": "", "files": 0, "staged": 0, "unstage": 0}
        rels = []
        for stamp in wanted:
            for rel in historylib.files(self.root, stamp):
                if rel not in rels:
                    rels.append(rel)
        historylib.restore(self.root, wanted)
        n = len(rels)
        staged = unstaged = 0
        for rel in rels:
            action = self._diff(rel)
            if not action:
                if self.forget(rel, remove=False):
                    unstaged += 1
                continue
            entry = self.data["files"].get(rel)
            if entry:
                # Already known: keep its place in the list, refresh the hashes
                # so a push of what is on disk now is not skipped as "already
                # sent" because the old entry's md5 matches the device.
                entry.pop("pushed", None)
                entry.pop("pushed_bytes", None)
                entry.pop("pushed_mtime", None)
                entry["bytes"] = os.path.getsize(self._abs(rel))
                staged += 1
            else:
                self.stage(rel, self._abs(rel), action=action)
                staged += 1
        self.save()
        historylib.drop(self.root, wanted)
        return {"stamp": wanted[0], "files": n, "staged": staged,
                "unstage": unstaged}

    def clear(self, *, keep_manifests: bool = True) -> int:
        """Throw away every staged change.  Returns how many were dropped.

        The ``_data_done`` / ``_common_done`` flags are reset as well, and the
        mirrored trees are emptied out rather than left as empty folders.

        Leaving the flags set was the bug behind "undo breaks the app": the
        first ``ensure_data`` had already run this session, so after ``clear``
        wiped ``vehicles/data`` to zero files the next ``ensure_car`` skipped the
        mirror and the workspace stayed permanently empty.  ``mirrored()`` then
        still said yes (the *directory* was there), so every page pointed at it:
        the car detail kept its half-finished contents, the paint and parts lists
        came back empty, and Deploy could not read the workspace at all.  Only
        deleting the folder by hand recovered, because that made ``exists()``
        false and the next ``ensure`` rebuilt from scratch.

        ``_rrmod_backup`` is skipped for the same reason the manifests are: it is
        not a working copy of anything.  It holds the only copies of the files as
        they were before an edit, so deleting it turned "undo the edit" into
        "lose the edit and the way back".  The working copy is disposable; the
        backups are the one thing in here that is not.
        """
        n = len(self.data["files"])
        self.data["files"] = {}
        self.data["tables"] = {}
        self.save()
        for dirpath, dirnames, filenames in os.walk(self.root, topdown=False):
            for f in filenames:
                if f == PENDING:
                    continue
                path = os.path.join(dirpath, f)
                rel = os.path.relpath(path, self.root).replace(os.sep, "/")
                if keep_manifests and self._is_manifest_rel(rel):
                    continue
                if self._is_backup_rel(rel):
                    continue
                try:
                    os.remove(path)
                except OSError:
                    pass
            # Remove the directories the files came out of, so a mirrored tree
            # that is now empty does not read as a real one.  The workspace root
            # itself stays, and so do the two manifest folders and the backups.
            for d in dirnames:
                full = os.path.join(dirpath, d)
                rel_dir = os.path.relpath(full, self.root).replace(os.sep, "/")
                if self._is_backup_rel(rel_dir):
                    continue
                try:
                    os.rmdir(full)
                except OSError:
                    pass
        if keep_manifests:
            # The manifests are kept, but keeping the *edited* ones is wrong: an
            # edit appends a row for the file it added, and after a discard that
            # row claims a file which is no longer there.  The next push for the
            # same car merges onto the device and appends that stale row, so the
            # device ends up listing a banim or an m3g it does not have.  Putting
            # the install's copies back keeps the workspace usable and drops the
            # edit's bookkeeping with the edit.
            self._reset_manifests()
        # Everything that was mirrored has just been deleted, so the "already
        # done" flags no longer describe reality.  Clear them and the next edit
        # mirrors again.
        self._data_done = False
        self._common_done = False
        return n

    @staticmethod
    def _is_manifest_rel(rel: str) -> bool:
        """True for an asset list a push merges rather than replaces.

        The startup list belongs here for the same reason as the other two: it
        names ``/materials/materials.bin``, so a push that replaces it would
        drop every material row the device knows about and a push that forgot it
        would leave a cloned material unlisted.  ``asset_list_startup.txt`` used
        to be handled as an ordinary file, which meant ``clear()`` threw the
        mirrored copy away and the next edit had to seed it again.
        """
        return (rel in (REGISTRY_REL, DATA_LIST_REL)
                or (rel.startswith("apk/res/asset_list")
                    and rel.endswith(".txt")))

    @staticmethod
    def _is_backup_rel(rel: str) -> bool:
        """True for anything under the undo backups.

        ``rrmod.edit`` writes one folder per edit under ``_rrmod_backup`` and
        ``restore_backup`` is the only way back from a bad one, so a discard that
        swept the backups away would destroy the very thing it is meant to make
        safe.  Compared on the first path segment, so the folder itself and
        everything below it match.
        """
        return rel == BACKUP_DIR or rel.startswith(BACKUP_DIR + "/")
    def _reset_manifests(self) -> None:
        """Put the asset lists back to what the install holds.

        Only the ones this workspace actually carries are touched: a manifest
        that was never copied is left absent, so the next edit seeds it from the
        install or the device the same way it did the first time.
        """
        # Walk the manifest folders rather than the whole tree: these are the
        # only places a manifest can be, and the car lists live in one folder.
        rels = [REGISTRY_REL, DATA_LIST_REL]
        car_dir = os.path.join(self.root, "apk", "res")
        if os.path.isdir(car_dir):
            for f in os.listdir(car_dir):
                if f.startswith("asset_list_vehicle_") and f.endswith(".txt"):
                    rels.append(f"apk/res/{f}")
        for rel in rels:
            target = self._abs(rel)
            if not os.path.isfile(target):
                continue
            src = self._install_abs(rel)
            try:
                if os.path.isfile(src):
                    shutil.copyfile(src, target)
                else:
                    os.remove(target)
            except OSError:
                pass

    # ---------------------------------------------------------------- reporting
    def pending(self) -> list:
        """Staged changes, biggest first, each with the car it belongs to.

        A file whose contents still match what was last pushed is not pending:
        it is already on the device, and offering it again made the Deploy tab
        look like it had forgotten the push.  Editing the file changes its md5
        and it comes back by itself.
        """
        from . import edit as editlib

        out = []
        for rel, entry in self.data["files"].items():
            target = self._abs(rel)
            if not os.path.isfile(target):
                continue
            row = dict(entry)
            row["path"] = target
            row.setdefault("bytes", os.path.getsize(target))
            if not row.get("car"):
                row["car"] = _car_of(rel)
            sent = row.get("pushed") or ""
            if sent:
                # Cheap tests first: hashing every pushed LOD on every summary
                # call costs milliseconds per megabyte, and the summary is drawn
                # whenever a page refreshes.  Size and nanosecond modification
                # time together are enough to skip the hash for the ordinary case
                # of a file that has not been touched since it was sent; anything
                # that matches neither is hashed, so a rewrite that keeps the size
                # is still caught.  Whole seconds were the old test and they were
                # not enough: two writes in one second with the same length
                # compared equal, and the second edit was never offered.
                same_time = (row.get("pushed_ns") == os.stat(target).st_mtime_ns
                             if "pushed_ns" in row
                             else row.get("pushed_mtime") == int(os.path.getmtime(target)))
                if row.get("pushed_bytes") == os.path.getsize(target) and same_time:
                    continue
                if editlib.md5_file(target) == sent:
                    continue
            out.append(row)
        out.sort(key=lambda r: (r.get("car", ""), r["rel"]))
        return out

    def summary(self) -> dict:
        rows = self.pending()
        cars = sorted({r["car"] for r in rows if r.get("car")})
        return {"root": self.root, "install": self.install, "files": len(rows),
                "bytes": sum(r.get("bytes", 0) for r in rows),
                "cars": cars, "made": self.data.get("made", ""),
                # Was this working copy seeded from the device rather than from
                # the install?  The old expression ended in ``and False``, so it
                # always answered no.  The record of which files were seeded is
                # the honest answer.
                "seeded_from_device": bool(self.data.get("seeded"))}

    def cars(self) -> list:
        return sorted({r["car"] for r in self.pending() if r.get("car")})

    # ------------------------------------------------------------------- deploy
    def deploy_items(self) -> list:
        """``[(local, remote, lock)]`` ready for :func:`rrmod.deploy.deploy_files`."""
        items = []
        for row in self.pending():
            items.append((row["path"], row["rel"], False))
        return items


def _car_of(rel: str) -> str:
    """``.depot/vehicles/<name>/...`` -> ``<name>``; a shared folder gives ``""``.

    ``vehicles/common`` is a folder of shared pages, not a car, so it has to read
    as a table rather than as a car named "common" in the staged summary and the
    quit prompt.
    """
    parts = rel.strip("/").split("/")
    if parts and parts[0] == ".depot":
        parts = parts[1:]
    if (len(parts) >= 3 and parts[0] == "vehicles"
            and parts[1] not in SHARED_DIRS):
        return parts[1]
    return ""


def open_workspace(install: str) -> Workspace:
    return Workspace(install)


def selftest(install: str = "") -> dict:
    """Round trip a file through the workspace without touching anything real."""
    install = install or depotlib.default_install()
    ws = Workspace(install)
    out = {"root": ws.root, "install": ws.install}
    out["exists_before"] = ws.exists()
    made = ws.ensure(log=lambda _m: None)
    out["created"] = made["created"]
    out["seeded"] = made["seeded"]
    out["from_device"] = made["from_device"]
    out["problems"] = made["problems"]
    return out
