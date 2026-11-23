"""Self test for the mod manager's data layer, run against a throwaway install.

    python tools\\test_rrmod.py            build a miniature install, then test
    python tools\\test_rrmod.py --keep     leave the miniature install behind

The miniature install is a real subset of the game: one car (the LFA), the tables
in ``vehicles/data``, the two shared livery tables and the manifests.  That is
enough for every code path that writes, and it means the test never touches the
real depot.

Checks, in order:

 1  scan finds the car and calls it unmanaged
 2  bootstrap writes ``rr3mods.json`` and the car becomes vanilla
 3  verify is clean on an untouched install
 4  replace_file rewrites the LOD and both manifests
 5  add_file appends a row to the per car manifest
 6  set_wing_paint fills slot 745 from slot 30 and syncs the livery table
 7  one edit leaves exactly one backup folder, and restoring it works
 8  install_pack builds a new car (spec, appearance, tables, folder, manifests)
 9  the new car verifies clean, and a second install of it is refused
10  remove_car takes the car out again and leaves the install verifying clean
11  the music editor round trips a playlist byte for byte
 12  the music batch helpers plan edits without touching anything
 13  deploy builds the right remote paths and reads a logcat trace
 14  a new file changes a car's fingerprint
 15  the graphics profiles plan, write and round trip
 16  the animation tracks read, swap and rebuild byte for byte
 17  the clip list parses, edits and writes back
 18  copying one car's animation onto another
 19  a stale table that would drop a car is refused before it is pushed
 20  the career file reads, edits and writes back byte for byte
 21  a career file that would drop a device series is refused
 22  no UI code reads a Qt enum member off an instance, and the windows build
 23  the interface speaks two languages and the Chinese table is complete
 24  the car and track pickers read the game's own atlases
 25  a picture becomes a menu card in every screen size
 26  a share zip exports, validates and imports, and refuses what it cannot do
 27  a career read off a device lands where the readers look for it
 28  the worker registry stops background jobs before the window goes away
 29  an existing series can have its event list rebuilt
 30  the data files the frozen build needs are shipped and loadable
 31  adb can be pointed at a device by hand
 32  every editor writes to a working copy, never to the install
 33  every wing behaviour can be read and written
 34  the other GPU texture families decode against the DXT copy of the same art
 35  the manufacturers, their logo art and their display names
 36  the track map pictures the user brings
 37  the paint finishes the game itself offers
 38  painting a car a different finish
 39  the picture beside the name, and the window icon
 40  the build tools never delete a build they cannot move
41  a folder of exported files fills the slots the game has, with no car.json
42  a slot table replaces files in an existing car under the names the game wants
43  the parts' materials resolve, and the library only lists writable ones
44  one paint scheme can have its own finish, and its own atlas
45  the Paints and Parts panes show a car and write through the same helpers
"""

from __future__ import annotations

import dataclasses
import json
import os
import shutil
import sys
import tempfile
import time
import zipfile
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from rr3lib import appearance as appearlib  # noqa: E402
from rr3lib import career as careerlib  # noqa: E402
from rr3lib import ddsdecode as ddslib  # noqa: E402
from rr3lib import driver as drvlib  # noqa: E402
from rr3lib import etcdecode as etclib  # noqa: E402
from rr3lib import livery as liverylib  # noqa: E402
from rr3lib import manifest as manifestlib  # noqa: E402
from rr3lib import nct as nctlib  # noqa: E402
from rr3lib import pvr as pvrlib  # noqa: E402
from rr3lib import spec as speclib  # noqa: E402
from rr3lib import texport as texlib  # noqa: E402
from rr3lib import texture as texturelib  # noqa: E402
from rr3lib import texts as textslib  # noqa: E402
from rrmod import anim as animlib  # noqa: E402
from rrmod import atlas as atlaslib  # noqa: E402
from rrmod import brands as brandlib  # noqa: E402
from rrmod import animcopy as copyllib  # noqa: E402
from rrmod import deps as depslib  # noqa: E402
from rrmod import depot as depotlib  # noqa: E402
from rrmod import deploy as deploylib  # noqa: E402
from rrmod import edit as editlib  # noqa: E402
from rrmod import gfx as gfxlib  # noqa: E402
from rrmod import history as historylib  # noqa: E402
from rrmod import modpack as packlib  # noqa: E402
from rrmod import maps as maplib  # noqa: E402
from rrmod import matmanager as matman  # noqa: E402
from rrmod import materials as matlib  # noqa: E402
from rrmod import paints as paintlib  # noqa: E402
from rrmod import pack as modlib  # noqa: E402
from rrmod import pages as pagelib  # noqa: E402
from rrmod import profile as profilelib  # noqa: E402
from rrmod import project as projlib  # noqa: E402
from rrmod import publish as publishlib  # noqa: E402
from rrmod import slots as slotlib  # noqa: E402
from rrmod import stats as statlib  # noqa: E402
from rrmod import music as musiclib  # noqa: E402
from rrmod import series as serieslib  # noqa: E402
from rrmod import share as sharelib  # noqa: E402
from rrmod import thumbs  # noqa: E402
from rrmod import textures as texpages  # noqa: E402
from rrmod import tracks as tracklib  # noqa: E402
from rr3lib import upgrades as uplib  # noqa: E402

CAR = "2012_lexus_lfa"
#: The appearance id of that car; the sales sheet names its pictures after
#: it, which is how a thumbnail is found without a lookup table.
CAR_ID = 88
SPEC = "88_2012_lexus_lfa.bin.nct"
#: a car with four moving wing parts, used by the animation checks
ANIM_CAR = "2013_bugatti_veyron_gsv"
#: Its spec.  The folder name is the short form of the car; the spec keeps the
#: full one, which is why this is written out rather than built from ANIM_CAR.
ANIM_SPEC = "140_2013_bugatti_veyron_16.4_grand_sport_vitesse.bin.nct"
MINI = os.path.join(ROOT, "work", "rrmod_test_install")

_ok = 0
_bad = []


def _batched_rmtree() -> None:
    """Turn "delete this tree" into "move this tree out of the way".

    A build mirror is a hundred-odd files and the fixture is a thousand, and the
    program deletes both in one ``shutil.rmtree`` - which is right, because they
    are scratch.  Some environments refuse to let a single call remove more than
    fifty files, as a guard against a mistyped ``rm -rf``; that is a good guard
    and a nuisance here, because it stops a *test fixture* being rebuilt.

    So the tests rename instead of deleting.  Everything lands under
    ``work/_trash``, nothing about the program changes, and the same state is
    reached - the only difference is that the files are still on disk, where they
    can be thrown away by hand whenever the disk gets tight.
    """
    real = shutil.rmtree
    real_remove = os.remove
    # A name per run, because the counter restarts with the process: a plain
    # ``_share_0001`` from the previous run is still sitting there, and renaming
    # onto an existing folder fails on Windows and would fall back to deleting.
    import time as _time

    run = f"{os.getpid()}-{_time.strftime('%H%M%S')}"
    trash = os.path.join(ROOT, "work", "_trash", run)
    state = {"n": 0}

    def _stash(path) -> bool:
        try:
            os.makedirs(trash, exist_ok=True)
            state["n"] += 1
            target = os.path.join(trash, f"{os.path.basename(path) or 'tree'}"
                                         f"_{state['n']:04d}")
            os.rename(path, target)
            return True
        except OSError:
            return False

    def moved(path, ignore_errors=False, onerror=None):
        if not os.path.exists(path):
            return None
        if os.path.islink(path) or not os.path.isdir(path):
            return real(path, ignore_errors=ignore_errors, onerror=onerror)
        if _stash(path):
            return None
        return real(path, ignore_errors=ignore_errors, onerror=onerror)

    def moved_file(path, *args, **kwargs):
        if os.path.isfile(path) and _stash(path):
            return None
        return real_remove(path, *args, **kwargs)

    shutil.rmtree = moved
    os.remove = moved_file
    os.unlink = moved_file


_batched_rmtree()


_batched_rmtree()


def check(name: str, cond, detail: str = "") -> None:
    global _ok
    if cond:
        _ok += 1
        print(f"  PASS  {name}")
    else:
        _bad.append(f"{name}  {detail}")
        print(f"  FAIL  {name}  {detail}")


def _raises(exc_type, fn, *args, **kwargs) -> bool:
    """True when ``fn`` raises ``exc_type`` - a short form of assertRaises."""
    try:
        fn(*args, **kwargs)
    except exc_type:
        return True
    except Exception:                            # noqa: BLE001
        return False
    return False


def _png_fixture() -> str:
    """A tiny PNG on disk, for the tests that need a picture to hand in."""
    path = os.path.join(ROOT, "work", "_test_map.png")
    width, height = 48, 24
    pixels = bytes([30, 120, 200, 255]) * (width * height)
    thumbs.write_png_bytes(path, width, height, 4, pixels)
    return path


def find_source() -> str:
    """The real install this workspace uses, or ``""``."""
    env = os.environ.get("RR3_INSTALL", "")
    if env and depotlib.find_install(env):
        return depotlib.find_install(env)
    return depotlib.default_install()


def build_mini(src: str) -> None:
    """Copy one car and the tables it needs into :data:`MINI`.

    The fixture has to start from the same state every run - the groups install
    cars into it, rewrite its manifests and delete things - so an existing copy is
    *moved aside* rather than deleted.  Deleting it would mean removing 281 files,
    which some environments refuse to let a program do in one go, and a stale
    folder in ``work/`` is a smaller problem than a fixture that cannot be rebuilt.
    """
    dep = os.path.join(src, ".depot")
    if os.path.isdir(MINI):
        import time as _time

        stale = os.path.join(ROOT, "work",
                             "_stale_" + _time.strftime("%Y%m%d-%H%M%S"))
        n = 0
        while os.path.exists(stale):
            n += 1
            stale = stale.split("~")[0] + f"~{n}"
        os.makedirs(os.path.dirname(stale), exist_ok=True)
        os.rename(MINI, stale)
        print(f"the previous test install was moved to {stale}")
    out_depot = os.path.join(MINI, ".depot")
    os.makedirs(os.path.join(out_depot, "vehicles", "data", "liveries"))
    os.makedirs(os.path.join(MINI, "apk", "res"))

    def from_depot(rel: str) -> None:
        s = os.path.join(dep, *rel.split("/"))
        d = os.path.join(out_depot, *rel.split("/"))
        os.makedirs(os.path.dirname(d), exist_ok=True)
        shutil.copyfile(s, d)

    def from_pkg(rel: str) -> None:
        s = os.path.join(src, *rel.split("/"))
        d = os.path.join(MINI, *rel.split("/"))
        os.makedirs(os.path.dirname(d), exist_ok=True)
        shutil.copyfile(s, d)

    from_depot("asset_list_base.txtCache.txt")
    from_depot(f"vehicles/data/{SPEC}")
    from_depot(f"vehicles/data/liveries/{CAR}.liveries.bin.nct")
    from_depot("vehicles/data/liveries/liveryStringTable.bin.nct")
    from_depot("vehicles/data/liveries/default.liveries.bin.nct")
    # the material library, so the paint dropdown can tell a real car paint from
    # a name that merely looks like one
    from_depot("materials/materials.bin")
    # the tuning trees, so the upgrade route picker has something to point at
    from_depot("vehicles/data/carupgrade.upgrades.nct")
    data = os.path.join(dep, "vehicles", "data")
    for f in os.listdir(data):
        p = os.path.join(data, f)
        if os.path.isfile(p) and not f.endswith(".bin.nct"):
            from_depot(f"vehicles/data/{f}")
    car_dir = os.path.join(dep, "vehicles", CAR)
    for dirpath, _dirs, files in os.walk(car_dir):
        for f in files:
            p = os.path.join(dirpath, f)
            from_depot(os.path.relpath(p, dep).replace(os.sep, "/"))

    # the pages the car shares with the rest of the grid (glass, carbon, the
    # brake rotor).  A livery names them as ``common/<stem>.ptc.pvr.z``, and the
    # livery file itself is encrypted, so the names are asked of the texture
    # reader rather than scanned for.  Six pages, 0.23 MB, instead of the 13 MB
    # the whole folder would cost.
    try:
        from rrmod import textures as _texpages
        for row in _texpages.car_pages(src, CAR):
            if not (row.get("path") or "").startswith("common/"):
                continue
            found = row.get("onDisk") or ""
            if found and os.path.isfile(os.path.join(dep, *found.split("/"))):
                from_depot(found)
    except Exception:  # noqa: BLE001 - the test still runs without shared pages
        pass

    from_pkg("apk/res/asset_list_vehicle_data.txt")
    from_pkg(f"apk/res/asset_list_vehicle_{CAR}.txt")
    # the list that claims ``materials.bin``.  Cloning a material rewrites that
    # one file, and without the list in the copy the new row had nowhere to go -
    # the working copy held a library the engine had no hash for.
    from_pkg("apk/res/asset_list_startup.txt")

    # the list that claims ``vehicles/common``.  It is the one list whose stems
    # all carry four rows (one per GPU family), so a page added there has to be
    # booked four times - and without the list in the copy there is nothing to
    # book them into.
    from_pkg("apk/res/asset_list_vehicle_common.txt")
    # the list that claims the manufacturer logos.  Adding a brand writes a page
    # into ``gui_assets``, and before this list was carried the new page had no
    # row anywhere - which is what made the game decide the install was
    # incomplete and offer to download the whole thing again.
    from_pkg("apk/res/asset_list_gui_assets_core.txt")

    # the nineteen lists that claim ``Tracks/common``, one per top folder.  A
    # track page needs four rows like a car page does, but which of the nineteen
    # owns it depends on the folder the page sits in, so the page has to be able
    # to ask.  All nineteen together are 1.0 MB, which is cheaper than a test
    # that cannot tell a page with rows from one without.
    res_dir = os.path.join(src, "apk", "res")
    if os.path.isdir(res_dir):
        for leaf in sorted(os.listdir(res_dir)):
            if leaf.startswith("asset_list_track_common") and leaf.endswith(".txt"):
                from_pkg(f"apk/res/{leaf}")

    # three of the game's own track pages, one from each of three top folders, so
    # the track half of the Dependencies page has something to read and the tests
    # can tell a folder that has its own list from one that does not.  They are
    # picked by being the smallest file in their folder rather than by name: the
    # folder holds 195 MB and the test install must not grow by any of it.
    track_common = os.path.join(dep, "Tracks", "common")
    if os.path.isdir(track_common):
        for folder in ("mat", "gnd", "tutorial"):
            sized = []
            base = os.path.join(track_common, folder)
            for dirpath, _dirs, files in os.walk(base):
                for leaf in files:
                    full = os.path.join(dirpath, leaf)
                    if leaf.lower().endswith((".dxt.dds.z", ".etc.dds.z",
                                              ".atc.dds.z", ".ptc.pvr.z")):
                        sized.append((os.path.getsize(full), full))
            if sized:
                from_depot(os.path.relpath(sorted(sized)[0][1], dep)
                           .replace(os.sep, "/"))

    # the driver folder.  A car's seated pose is a field in its data record, and
    # the file it names lives here; without the folder the pose picker has
    # nothing to offer and cannot tell a pose that has a low-poly model from one
    # that does not.  64 files, 3.2 MB.
    driver_src = os.path.join(dep, "driver")
    if os.path.isdir(driver_src):
        for leaf in sorted(os.listdir(driver_src)):
            p = os.path.join(driver_src, leaf)
            if os.path.isfile(p):
                from_depot(f"driver/{leaf}")

    # the vinyl decal list and the font it draws from.  A record names a code
    # point rather than a glyph index, so without the font the page cannot say
    # whether a shape will actually appear - and "cannot tell" is the one answer
    # this page must never give.  Two files, 0.35 MB.
    for rel in ("vehicles/data/custom.decals.nct",
                "vehicles/data/custom.decalpacks.nct",
                "r3_decals.ttf"):
        if os.path.isfile(os.path.join(dep, *rel.split("/"))):
            from_depot(rel)

    # the graphics files, so the Graphics tab has something real to read.  Both
    # the .depot copies (what the engine loads) and the apk/res ones (the source
    # the manager compares against to spot a modified profile) are needed.
    # Every shipped plist comes along too: they are what the editor builds its
    # drop downs from, and they are small.
    for rel in ("eds/AndroidHigh.plist", "feats/AndroidHigh.feats"):
        from_depot(rel)
        from_pkg(f"apk/res/{rel}")
    eds_src = os.path.join(dep, "eds")
    if os.path.isdir(eds_src):
        for leaf in sorted(os.listdir(eds_src)):
            if leaf.endswith(".plist") and leaf != "AndroidHigh.plist":
                from_depot(f"eds/{leaf}")
    feats_src = os.path.join(dep, "feats")
    if os.path.isdir(feats_src):
        for leaf in sorted(os.listdir(feats_src)):
            if leaf.endswith(".feats") and leaf != "AndroidHigh.feats":
                from_depot(f"feats/{leaf}")

    # the career file and the text it indexes, so the Career tab has something
    # real to read.  These are the two biggest files in the install (14 MB and
    # 38k lines apiece) which is why the career tests are the slowest ones here.
    for f in ("data/events.dat.nct", "gametext.txt"):
        p = os.path.join(dep, *f.split("/"))
        if os.path.isfile(p):
            from_depot(f)
    for lang in textslib.LANGUAGES:
        p = os.path.join(dep, f"text_{lang}.txt")
        if os.path.isfile(p):
            from_depot(f"text_{lang}.txt")

    # a couple of playlists, so the music editor has something to read
    tracks = os.path.join(dep, "Tracks", "data")
    if os.path.isdir(tracks):
        for f in sorted(os.listdir(tracks))[:3]:
            from_depot(f"Tracks/data/{f}")

    # the manufacturer logo sheet, so the Brands tab has real art to read.  One
    # screen size is enough: the code walks every size it finds, and the page is
    # 1.6 MB, which is the largest single file in this miniature install.
    logo_dir = os.path.join(dep, "gui_assets", "960x640", "common",
                            "manufacturer_logos")
    if os.path.isdir(logo_dir):
        for f in sorted(os.listdir(logo_dir)):
            if os.path.isfile(os.path.join(logo_dir, f)):
                from_depot(f"gui_assets/960x640/common/manufacturer_logos/{f}")

    # the car sales sheet that holds the LFA's picture, so the preview test has
    # real art.  Only the one batch that contains car 88 is copied (0.27 MB);
    # the whole car_sales folder is 54 MB.
    sales = os.path.join(dep, "gui_assets", "960x640", "car_sales", "cars")
    if os.path.isdir(sales):
        for batch in sorted(os.listdir(sales)):
            atlas = os.path.join(sales, batch, "sprites.android.atlas")
            if not os.path.isfile(atlas):
                continue
            with open(atlas, encoding="utf-8", errors="ignore") as fh:
                if f"car_sales_car_{CAR_ID}.png" not in fh.read():
                    continue
            for f in sorted(os.listdir(os.path.join(sales, batch))):
                from_depot(f"gui_assets/960x640/car_sales/cars/{batch}/{f}")
            break

    # one car with a real active wing, so the Animation tab has something to
    # edit.  Only the three files the animation code touches are copied - the
    # textures and lower LODs would triple the size of the test install for no
    # extra coverage.
    for f in (f"{ANIM_CAR}_a.m3g", f"{ANIM_CAR}_wing.banim",
              f"{ANIM_CAR}_animations.xml"):
        src_f = os.path.join(dep, "vehicles", ANIM_CAR, f)
        if os.path.isfile(src_f):
            from_depot(f"vehicles/{ANIM_CAR}/{f}")


def make_pack() -> str:
    """A ``car.json`` pack folder that claims to add a wing to the LFA."""
    folder = os.path.join(ROOT, "work", "rrmod_test_pack")
    if os.path.isdir(folder):
        shutil.rmtree(folder, ignore_errors=True)
    os.makedirs(folder)
    body = os.path.join(MINI, ".depot", "vehicles", CAR, f"{CAR}_a.m3g")
    shutil.copyfile(body, os.path.join(folder, "LOD_A.m3g"))
    packlib.save(packlib.ModPack(folder, {
        "format": 1,
        "name": "2012_lexus_lfa_wing",
        "kind": "new",
        "donor": CAR,
        "identity": {"year": 2012, "make": "Lexus", "model": "LFA Wing",
                     "display_key": "CAR_NAME_LFA_WING",
                     "model_token": "LFA_WING"},
        "files": {"A": "LOD_A.m3g"},
        "aero": [],
        "liveries": {},
    }))
    return folder


def main() -> int:
    keep = "--keep" in sys.argv
    src = find_source()
    if not src:
        print("no game install found - set RR3_INSTALL or edit depot.default_install")
        return 2
    print(f"source install: {src}")
    install = src          # kept: `src` is reused as a scratch path further down
    build_mini(src)
    root = MINI
    print(f"test install  : {root}\n")

    # The mini install gets its own state folder, and it starts empty.  The
    # state is namespaced by the install path, so without this the run would
    # inherit the mods file from the previous run and the first assertion -
    # "nothing knows this car yet" - would be looking at an install that had
    # already been bootstrapped.
    #
    # Only the files go.  An older version of the program kept a *working copy*
    # under this folder, and a leftover one is a directory of a hundred-odd
    # files that this run has no use for but also no need to delete - and a
    # program is not allowed to remove a hundred files in one go here anyway.
    state = depotlib.state_dir(os.path.join(root, ".depot"))
    if state and os.path.isdir(state):
        for leaf in os.listdir(state):
            target = os.path.join(state, leaf)
            if os.path.isfile(target):
                try:
                    os.remove(target)
                except OSError:
                    pass
    depotlib._MODS_PATH.clear()
    depotlib._STATE_DIR.clear()
    print(f"state folder  : {state or '(nowhere writable)'}\n")

    print("1  scan")
    inv = depotlib.scan(root)
    check("one car", len(inv.cars) == 1, f"got {len(inv.cars)}")
    check("car name", inv.cars[0].name == CAR, inv.cars[0].name)
    check("unmanaged", inv.cars[0].status == "unknown", inv.cars[0].status)

    print("2  bootstrap")
    depotlib.bootstrap(inv)
    inv = depotlib.scan(root)
    check("baseline written", os.path.isfile(depotlib.mods_path(inv.depot)))
    check("vanilla", inv.cars[0].status == "vanilla", inv.cars[0].status)

    print("3  verify")
    check("clean", editlib.verify(root) == [], str(editlib.verify(root)[:2]))

    print("4  replace_file")
    e = inv.get(CAR)
    info = editlib.replace_file(root, CAR, "A",
                                os.path.join(e.folder, f"{CAR}_a.m3g"))
    check("manifest updated", info["manifest"] == "updated", info["manifest"])
    check("registry updated", info["registry"] is True, str(info["registry"]))
    check("still clean", editlib.verify(root) == [], str(editlib.verify(root)[:2]))

    print("5  add_file")
    info = editlib.add_file(root, CAR, os.path.join(e.folder, f"{CAR}_a.m3g"),
                            rename=f"{CAR}_wing.banim")
    check("manifest appended", info["manifest"] == "appended", info["manifest"])
    rows = manifestlib.read_car_manifest(editlib.car_manifest_path(root, CAR))
    check("row present", any(r[0].endswith("_wing.banim") for r in rows),
          f"{len(rows)} rows")

    print("6  set_wing_paint")
    info = editlib.set_wing_paint(root, CAR)
    check("slot 745 filled", len(info["changed"]) > 0, str(info))
    check("clean after paint", editlib.verify(root) == [],
          str(editlib.verify(root)[:2]))

    print("7  backups")
    names = editlib.backups(root)
    check("one folder per edit", len(names) == len(set(names)) and len(names) >= 2,
          str(names))
    # the add_file run is the one that put the wing banim row in the manifest
    stamp = names[1] if len(names) > 1 else names[0]
    rows = manifestlib.read_car_manifest(editlib.car_manifest_path(root, CAR))
    check("wing row present before undo",
          any(r[0].endswith("_wing.banim") for r in rows), f"{len(rows)} rows")
    n = editlib.restore_backup(root, stamp)
    check("restored something", n > 0, str(n))
    rows = manifestlib.read_car_manifest(editlib.car_manifest_path(root, CAR))
    check("wing row gone after undo",
          not any(r[0].endswith("_wing.banim") for r in rows), f"{len(rows)} rows")
    # put the file back so the rest of the test runs against a sane install
    editlib.add_file(root, CAR, os.path.join(e.folder, f"{CAR}_a.m3g"),
                     rename=f"{CAR}_wing.banim")

    print("8  install_pack")
    pack = packlib.load(make_pack())
    check("pack validates", pack.validate() == [], str(pack.validate()))
    inv = depotlib.scan(root)
    _count, _recs = appearlib.load(inv.depot)
    wanted_appearance = appearlib.free_id(_recs)
    out = editlib.install_pack(
        root, pack, new_id=inv.free_id(), appearance_id=wanted_appearance,
        model_token="WINGTEST", aliases=False, paints=[0, 2],
        car_class="Prod", log=lambda m: None)
    check("spec written", os.path.isfile(out["spec"]), out["spec"])
    check("appearance record", out["appearance_id"] > 0, str(out["appearance_id"]))
    check("the appearance id was taken from the caller",
          out["appearance_id"] == wanted_appearance,
          f"{out['appearance_id']} vs {wanted_appearance}")
    check("the model token was taken from the caller",
          out["model_token"] == "WINGTEST", out["model_token"])
    check("no donor aliases were written", out["folder"]["aliases"] == 0,
          str(out["folder"]))
    check("the paints were trimmed to the ones asked for",
          out["wing_material"]["dropped"] == 4,
          str(out["wing_material"]))
    check("the class was written", out["class_changed"] is True,
          str(out["class_changed"]))
    check("folder copied", out["folder"]["files"] > 0, str(out["folder"]))
    check("merged", out["merged"]["copied"] > 0, str(out["merged"]))
    print("9  the new car")
    inv = depotlib.scan(root)
    check("two cars", len(inv.cars) == 2, str([c.name for c in inv.cars]))
    new = inv.get("2012_lexus_lfa_wing")
    check("new car exists", new is not None)
    check("new car verifies", editlib.verify(root, "2012_lexus_lfa_wing") == [],
          str(editlib.verify(root, "2012_lexus_lfa_wing")[:3]))
    _L = liverylib.load_car(inv.depot, "2012_lexus_lfa_wing")
    check("the new car has two paints", len(_L.paints) == 2, str(len(_L.paints)))
    _spec = speclib.load_spec(inv.depot, new.spec_stem)
    check("the new car reads back as Prod",
          _spec.stats().get("car_class") == "Prod",
          str(_spec.stats().get("car_class")))
    try:
        editlib.install_pack(root, pack, new_id=99, log=lambda m: None)
        check("second install refused", False, "no exception")
    except editlib.EditError:
        check("second install refused", True)

    print("10 remove_car")
    n0 = len(appearlib.load(inv.depot)[1])
    editlib.remove_car(root, "2012_lexus_lfa_wing")
    inv = depotlib.scan(root)
    n1 = len(appearlib.load(inv.depot)[1])
    check("car gone", inv.get("2012_lexus_lfa_wing") is None)
    check("appearance gone", n1 == n0 - 1, f"{n0} -> {n1}")
    check("install still verifies", editlib.verify(root) == [],
          str(editlib.verify(root)[:3]))

    print("11 music")
    pls = musiclib.scan(inv.depot)
    if not pls:
        check("playlists found", False, "no Tracks/data in the test install")
    else:
        pl = pls[0]
        raw = pl.to_bytes()
        check("playlist round trips", musiclib.build_records(
            musiclib.parse_records(raw)) == raw, "record stream changed")
        songs = musiclib.available_music(inv.depot)
        check("music files listed", isinstance(songs, list), str(type(songs)))

        # the batch helpers must be pure: build a plan, change nothing on disk
        before = {p.name: p.to_bytes() for p in pls}
        labels = musiclib.LABELS
        check("three slots", len(labels) == 3, str(labels))
        fake = ["a.mp3", "b.mp3", "c.mp3"]
        plan = musiclib.cycle(pls, fake)
        check("cycle covers every playlist", len(plan) == len(pls),
              f"{len(plan)} of {len(pls)}")
        first = [plan[pls[0].name][l] for l in labels]
        second = [plan[pls[1].name][l] for l in labels] if len(pls) > 1 else []
        check("cycle rotates the window",
              first == ["a.mp3", "b.mp3", "c.mp3"]
              and (not second or second == ["b.mp3", "c.mp3", "a.mp3"]),
              f"{first} {second}")
        check("cycle keeps the same song count",
              all(sorted(v.values()) == sorted(fake) for v in plan.values()),
              "a playlist lost or duplicated a song")

        rot = musiclib.rotate(pls, 1)
        check("rotate is a permutation",
              all(sorted(v.values()) == sorted(
                  musiclib.assign(p, {}).values()) for p, v in
                  ((pl, rot[pl.name]) for pl in pls)),
              "rotate changed the set of songs")
        check("rotate one and rotate two differ",
              rot != musiclib.rotate(pls, 2), "1 and 2 slots give the same plan")

        one = musiclib.assign(pls[0], {labels[0]: "x.mp3"})
        check("assign only touches the named slot",
              one[labels[1]] == musiclib.assign(pls[0], {})[labels[1]],
              str(one))
        rep = musiclib.replace_song(pls, "a.mp3", "z.mp3")
        check("replace ignores playlists without the song", rep == {},
              f"{len(rep)} playlists matched a song that is not there")
        clr = musiclib.clear_slot(pls, labels[2])
        check("clear empties the slot",
              all(v[labels[2]] == "" for v in clr.values()), str(clr))
        edits = musiclib.plan_to_edits(clr, pls)
        check("plan converts to pending edits",
              len(edits) == len(clr) and
              all(isinstance(k, tuple) and len(k) == 2 for k in edits),
              f"{len(edits)} edits")
        n_before = musiclib.diff(pls, clr)
        check("pending edits equal the real diff", len(edits) == n_before,
              f"{len(edits)} edits vs {n_before} real changes")
        check("unfiltered edits keep every slot",
              len(musiclib.plan_to_edits(clr)) == len(clr) * len(labels),
              "dropping unchanged values needs the playlist list")
        check("batch helpers wrote nothing",
              {p.name: p.to_bytes() for p in pls} == before,
              "a plan changed a playlist in memory")

    print("12 deploy plans (no device involved)")
    items = deploylib.plan_replace(root, CAR, {
        "A": os.path.join(e.folder, f"{CAR}_a.m3g"),
        "wing_banim": os.path.join(e.folder, f"{CAR}_a.m3g"),
        "animations": os.path.join(e.folder, f"{CAR}_a.m3g"),
        "points": os.path.join(e.folder, f"{CAR}_a.m3g"),
    })
    remotes = [r for _l, r, _k in items]
    check("lod path", remotes[0] == f".depot/vehicles/{CAR}/{CAR}_a.m3g", remotes[0])
    check("banim path", remotes[1].endswith("_wing.banim"), remotes[1])
    check("animations path", remotes[2].endswith("_animations.xml"), remotes[2])
    check("points path", remotes[3].endswith(".points"), remotes[3])
    man = deploylib.plan_manifests(root, CAR)
    check("three manifests", len(man) == 3, str([m[1] for m in man]))
    check("manifests are read only", all(m[2] for m in man if "base.txtCache" not in m[1]),
          str([(m[1], m[2]) for m in man]))
    log = ("I/RR3: StartListDownload\n"
           "E/RR3: ASSET DOWNLOAD ERROR /vehicles/x\n"
           "I/RR3: all files up to date\n"
           "F FATAL EXCEPTION: main\n")
    info = deploylib.check_log(log)
    check("log start list", info["start_list"] == 1, str(info["start_list"]))
    check("log errors", info["download_errors"] == 1, str(info["download_errors"]))
    check("log up to date", info["up_to_date"] == 1, str(info["up_to_date"]))
    check("log fatal", info["fatal"] >= 1, str(info["fatal"]))
    check("log not ok", info["ok"] is False, str(info["ok"]))

    print("13 a new file changes a car's fingerprint")
    # the edits above already touched this car, so take a fresh baseline first -
    # this step is about spotting an addition, not about the earlier ones
    depotlib.bootstrap(depotlib.scan(root))
    before = depotlib.scan(root).get(CAR)
    check("clean car is not modified", before.modified is False, str(before.modified))
    editlib.add_file(root, CAR, os.path.join(e.folder, f"{CAR}_a.m3g"),
                     rename=f"{CAR}_animations.xml")
    after = depotlib.scan(root).get(CAR)
    check("added file noticed", after.modified is True, str(after.modified))
    check("file count grew", after.file_count == before.file_count + 1,
          f"{before.file_count} -> {after.file_count}")

    print("14 the graphics profiles")
    dep = inv.depot
    if not os.path.isfile(os.path.join(dep, "eds", "AndroidHigh.plist")):
        check("graphics files present", False, "no eds/AndroidHigh.plist in the test install")
    else:
        stock = gfxlib.read_pair(dep)
        check("plist parses", stock[0] is not None and len(stock[0]) > 50,
              f"{len(stock[0]) if stock[0] else 0} keys")
        check("feats parses", stock[1] is not None and len(stock[1]) > 50,
              f"{len(stock[1]) if stock[1] else 0} keys")
        check("identifier survives", stock[0].get("PLIST_IDENTIFIER") == "AndroidHigh",
              str(stock[0].get("PLIST_IDENTIFIER")))
        check("stock is stock", gfxlib.match_profile(dep) == "stock",
              gfxlib.match_profile(dep))
        high = gfxlib.plan(dep, "high")
        check("high changes nothing", high["changes"] == 0, str(high["changes"]))
        ultra = gfxlib.plan(dep, "ultra")
        check("ultra changes something", ultra["changes"] > 0, str(ultra["changes"]))
        check("ultra leaves the identifier alone",
              all(k != "PLIST_IDENTIFIER" for k, _b, _a in ultra["plist"]),
              str([k for k, _b, _a in ultra["plist"] if k == "PLIST_IDENTIFIER"]))
        check("plan is a pure function",
              gfxlib.read_pair(dep)[0].text == stock[0].text,
              "planning changed the file in memory")
        keys = [k for k, _b, _a in ultra["plist"]]
        check("no duplicate keys", len(keys) == len(set(keys)), str(len(keys)))
        insane = gfxlib.plan(dep, "insane")
        check("insane is at least ultra", insane["changes"] >= ultra["changes"],
              f"{insane['changes']} vs {ultra['changes']}")
        custom = gfxlib.plan(dep, "high", custom={"AA_LEVEL": 2})
        check("a custom override is honoured",
              [a for k, _b, a in custom["plist"] if k == "AA_LEVEL"] == [2],
              str([(k, a) for k, _b, a in custom["plist"] if k == "AA_LEVEL"]))
        check("an unknown key is a warning",
              gfxlib.plan(dep, "high", custom={"NOT_A_KEY": 1})["warnings"] != [],
              "no warning for an unknown key")

        written = gfxlib.apply(dep, ultra)
        check("both files written", len(written) == 2, str(sorted(written)))
        # apply() writes beside the mods file, not into the install, so read the
        # copies it produced rather than the install again
        again = gfxlib.read(written["plist"]["path"], "plist")
        want = [a for k, _b, a in ultra["plist"] if k == "AA_LEVEL"]
        check("written plist reads back",
              not want or again.get("AA_LEVEL") == want[0],
              f"{again.get('AA_LEVEL')} vs {want}")
        check("written files are not in the install",
              os.path.dirname(written["plist"]["path"]) != os.path.join(dep, "eds"),
              written["plist"]["path"])
        check("written identifier is intact",
              again.get("PLIST_IDENTIFIER") == "AndroidHigh",
              str(again.get("PLIST_IDENTIFIER")))
        check("round trip is byte stable",
              gfxlib.apply(dep, ultra)["plist"]["bytes"] == written["plist"]["bytes"],
              "writing the same plan twice gave different sizes")
        items = deploylib.plan_gfx(written)
        check("gfx deploy paths", [r for _l, r, _k in items] ==
              [".depot/eds/AndroidHigh.plist", ".depot/feats/AndroidHigh.feats"],
              str([r for _l, r, _k in items]))
        check("gfx deploy unlocks the files", all(k is False for _l, _r, k in items),
              str(items))

        # The install ships one plist per device family and they all carry the
        # same keys, so their union is a catalogue of values the engine accepts.
        # The editor turns that into tick boxes and drop downs.
        names = gfxlib.factory_profiles(dep)
        check("the shipped profiles are listed", len(names) > 20, str(len(names)))
        pick = gfxlib.choices(dep, "plist")
        check("some plist keys offer a choice", len(pick) > 20, str(len(pick)))
        check("on/off keys offer both values",
              pick.get("AA_LEVEL") is not None and len(pick["AA_LEVEL"]) > 1,
              str(pick.get("AA_LEVEL")))
        check("keys that never vary are not offered",
              "PLIST_IDENTIFIER" not in pick,
              str(pick.get("PLIST_IDENTIFIER")))
        check("feats keys offer a choice too",
              len(gfxlib.choices(dep, "feats")) > 5,
              str(len(gfxlib.choices(dep, "feats"))))
        borrowed = gfxlib.plan(dep, "high", base="AndroidXtraHigh")
        check("a base profile is reported", borrowed.get("base") == "AndroidXtraHigh",
              str(borrowed.get("base")))
        check("copying another profile changes keys", borrowed["changes"] > 0,
              str(borrowed["changes"]))
        check("the base profile is mentioned in the warnings",
              any("AndroidXtraHigh" in w for w in borrowed["warnings"]),
              str(borrowed["warnings"]))
        check("a base profile leaves the identifier alone",
              [a for k, _b, a in borrowed["plist"]
               if k == "PLIST_IDENTIFIER"] == [],
              str([(k, a) for k, _b, a in borrowed["plist"]
                   if k == "PLIST_IDENTIFIER"]))
        check("an unknown base profile is refused",
              _raises(gfxlib.GfxError, gfxlib.plan, dep, "high",
                      base="NoSuchProfile"),
              "planning from a missing profile did not raise")

        # Borrowing another family's plist must not borrow the keys that
        # describe the *device*.  Pushing HAS_PHOTO_MODE=True onto an Android
        # build kills the game in the car-select scene (bisected on a real
        # device, 2026-11-07), and GUI_LAYOUT_EXTENSION='_1024x768' points at a
        # gui_assets folder the Android package does not ship.
        device_keys = ("HAS_PHOTO_MODE", "GUI_LAYOUT_EXTENSION",
                       "EXPECTED_SCREEN_WIDTH", "EXPECTED_SCREEN_HEIGHT")
        checked = 0
        leaks = []
        for base_name in names:
            one = gfxlib.plan(dep, "ultra", base=base_name)
            after = gfxlib.parse_plist(one["texts"]["plist"])
            for key in device_keys:
                if key not in stock[0].values:
                    continue
                checked += 1
                if after.get(key) != stock[0].values.get(key):
                    leaks.append((base_name, key, after.get(key)))
        check("there were device keys to check", checked > 0,
              "the shipped plists have none of the device keys")
        check("no shipped profile leaks a device key",
              not leaks, f"{len(leaks)} leaks, e.g. {leaks[:3]}")
        check("the photo mode warning fires",
              any("HAS_PHOTO_MODE" in w
                  for w in gfxlib.plan(dep, "high",
                                       custom={"HAS_PHOTO_MODE": True})["warnings"]),
              "turning photo mode on is not warned about")

    print("16 the animation tracks")
    if not animlib.has_animation(root, ANIM_CAR):
        check("animation car present", False, f"{ANIM_CAR} was not copied")
    else:
        info = animlib.read(root, ANIM_CAR)
        check("banim parses", info["duration_ms"] > 0, str(info["duration_ms"]))
        check("four tracks", len(info["tracks"]) == 4, str(len(info["tracks"])))
        check("four parts", len(info["parts"]) == 4, str(info["parts"]))
        check("parts are in name order", info["parts"] == sorted(info["parts"]),
              str(info["parts"]))
        check("every track names a part",
              all(t["part"] for t in info["tracks"]),
              str([t["part"] for t in info["tracks"]]))
        check("frames follow the 33 ms grid",
              info["frames"] == int(round(info["duration_ms"] / 33.0)),
              f"{info['frames']} vs {info['duration_ms']}")
        check("some track rotates",
              max(t["travel"] for t in info["tracks"]) > 1.0,
              str([t["travel"] for t in info["tracks"]]))
        check("reading wrote nothing",
              animlib.read(root, ANIM_CAR)["tracks"] == info["tracks"],
              "read() is not idempotent")

        src = animlib.banim_path(root, ANIM_CAR)
        with open(src, "rb") as fh:
            blob = fh.read()
        identity = animlib.swap_tracks(blob, {0: 0, 1: 1, 2: 2, 3: 3})
        check("the identity mapping rebuilds the file", identity == blob,
              f"{len(identity)} vs {len(blob)} bytes")
        swapped = animlib.swap_tracks(blob, {0: 3, 1: 2, 2: 1, 3: 0})
        check("a swap keeps the size", len(swapped) == len(blob),
              f"{len(swapped)} vs {len(blob)}")
        check("a swap changes the bytes", swapped != blob, "swap produced the original")
        got = animlib.swap_file(root, ANIM_CAR, {0: 1, 1: 0, 2: 2, 3: 3})
        with open(got["path"], "rb") as fh:
            swapped_blob = fh.read()
        reread = animlib.describe_blob(swapped_blob)
        check("the swapped file still parses", len(reread) == 4,
              str(len(reread)))
        check("swapping moved the pivot",
              reread[0]["pivot"] == info["tracks"][1]["pivot"],
              f"{reread[0]['pivot']} vs {info['tracks'][1]['pivot']}")
        try:
            animlib.swap_tracks(blob, {0: 0})
            check("an incomplete mapping is refused", False, "no error raised")
        except animlib.AnimError:
            check("an incomplete mapping is refused", True)
        try:
            animlib.swap_tracks(blob, {0: 0, 1: 1, 2: 2, 3: 3, 4: 0})
            check("an unknown track is refused", False, "no error raised")
        except animlib.AnimError:
            check("an unknown track is refused", True)
        try:
            os.remove(got["path"])
        except OSError:
            pass

    print("17 the clip list")
    clips = info["clips"] if animlib.has_animation(root, ANIM_CAR) else []
    check("clips parse", len(clips) >= 3, str(len(clips)))
    check("clip names are known",
          all(c.name in animlib.animxmllib.CLIP_DOC for c in clips),
          str([c.name for c in clips if c.name not in animlib.animxmllib.CLIP_DOC]))
    check("clip validation is quiet",
          animlib.validate(clips, info["duration_ms"]) == [],
          str(animlib.validate(clips, info["duration_ms"])))
    one = animlib.set_clip(clips, "wing_up", 0, 30)
    check("set_clip replaces in place",
          [c for c in one if c.name == "wing_up"][0].end == 30,
          str([(c.name, c.start, c.end) for c in one]))
    check("set_clip does not duplicate", len(one) == len(clips),
          f"{len(one)} vs {len(clips)}")
    added = animlib.set_clip(clips, "neutral_to_speed", 0, 12)
    check("set_clip appends a new name", len(added) == len(clips) + 1,
          f"{len(added)} vs {len(clips)}")
    gone = animlib.remove_clip(clips, clips[0].name)
    check("remove_clip drops one", len(gone) == len(clips) - 1,
          f"{len(gone)} vs {len(clips)}")
    default = animlib.suggest_clips(info["duration_ms"])
    check("the default set is rest/up/down",
          [c.name for c in default] == ["wing_initial", "wing_up", "wing_down"],
          str([c.name for c in default]))
    check("the default set spans the banim",
          default[1].end == animlib.animxmllib.frames_for(info["duration_ms"]),
          f"{default[1].end} vs {info['duration_ms']}")
    out_xml = os.path.join(ROOT, "work", "_test_anim.xml")
    animlib.write_xml(clips, out_xml)
    check("the xml round trips", animlib.animxmllib.load(out_xml) == clips,
          "reading back the written xml gave different clips")
    os.remove(out_xml)

    print("18 copying an animation between cars")
    cmp = copyllib.compare(root, ANIM_CAR, CAR)
    check("compare reports the track counts",
          cmp["source_tracks"] == 4 and cmp["target_tracks"] == 0,
          f"{cmp['source_tracks']} / {cmp['target_tracks']}")
    check("compare warns about a car with no wing",
          any("no WING meshes" in w for w in cmp["warnings"]),
          str(cmp["warnings"]))
    check("compare can copy", cmp["can_copy"] is True, str(cmp["can_copy"]))
    got = copyllib.copy_animation(root, ANIM_CAR, CAR)
    check("both files landed", os.path.isfile(got["banim"]) and
          os.path.isfile(got["xml"]), str(got))
    check("the copy is named after the target",
          os.path.basename(got["banim"]) == f"{CAR}_wing.banim",
          os.path.basename(got["banim"]))
    check("the copy kept the tracks", got["tracks"] == 4, str(got["tracks"]))
    # the source has its own xml, so the copy inherits its clips rather than
    # getting the default set - the default only kicks in when there is none
    check("the copy kept the source's clips",
          got["clips"] == len(animlib.animxmllib.load(animlib.xml_path(root, ANIM_CAR))),
          f"{got['clips']} clips")

    print("19 refusing to push a stale table")
    # check_table asks the device for its copy; this stand-in hands back whatever
    # blob the test chose, so the guard can be exercised without a real device.
    class FakeDevice:
        def __init__(self, serial, blob):
            self.serial = serial
            self.blob = blob

        def run(self, *args):
            dest = args[-1]
            with open(dest, "wb") as fh:
                fh.write(self.blob)

            class R:
                returncode = 0
            return R()

    tables = os.path.join(root, ".depot", "vehicles", "data")
    cardesc_path = os.path.join(tables, "cardesc.list.nct")
    plain = nctlib.read(cardesc_path)
    entries = speclib.parse_cardesc(plain).entries

    # the device has one more car than we do - exactly what bit us: our copy was
    # a *different* size, so a size test would have let it through
    theirs = speclib.Cardesc(list(entries) + [b"9999_device_only.bin"])
    fake = FakeDevice("tbl-missing", nctlib.crypt(theirs.to_bytes()))
    try:
        deploylib.check_table(cardesc_path, ".depot/vehicles/data/cardesc.list.nct",
                              fake)
        check("a table missing a device row is refused", False,
              "the guard let a shorter cardesc through")
    except deploylib.DeployError as exc:
        check("a table missing a device row is refused",
              "missing 1 id" in str(exc), str(exc)[:120])

    # same rows, so it passes even though the bytes differ
    same = FakeDevice("tbl-same", nctlib.crypt(plain))
    try:
        deploylib.check_table(cardesc_path, ".depot/vehicles/data/cardesc.list.nct",
                              same)
        check("a table with the same rows is allowed", True)
    except deploylib.DeployError as exc:
        check("a table with the same rows is allowed", False, str(exc)[:120])

    # allow_shrink is the escape hatch for a deliberate trim
    try:
        deploylib.check_table(cardesc_path, ".depot/vehicles/data/cardesc.list.nct",
                              fake, allow_shrink=True)
        check("allow_shrink skips the row check", True)
    except deploylib.DeployError as exc:
        check("allow_shrink skips the row check", False, str(exc)[:120])

    # a file that is not a table is never inspected
    other = os.path.join(tables, "appearances.link.nct")
    try:
        deploylib.check_table(other, ".depot/vehicles/data/appearances.link.nct",
                              FakeDevice("tbl-other", b"\x00" * 99999))
        check("files that are not tables are not inspected", True)
    except deploylib.DeployError as exc:
        check("files that are not tables are not inspected", False, str(exc)[:120])

    # a table the device does not have yet cannot lose anything
    empty = FakeDevice("tbl-absent", b"")
    try:
        deploylib.check_table(cardesc_path, ".depot/vehicles/data/cardesc.list.nct",
                              empty)
        check("a table the device lacks is allowed", True)
    except deploylib.DeployError as exc:
        check("a table the device lacks is allowed", False, str(exc)[:120])

    print("20 the career file")
    # events.dat.nct is 14 MB and rebuilt from scratch on every save, so the one
    # thing worth proving is that a parse and a rebuild agree byte for byte: if
    # they do not, an edit would silently corrupt a file the game reads at start.
    career = serieslib.load(root)
    plain = career.to_bytes()
    check("the career file round trips",
          careerlib.parse(plain).to_bytes() == plain,
          f"{len(plain):,} bytes")
    check("it has series, tiers and events",
          len(career.series) > 1000 and len(career.tiers) > 1000,
          f"{len(career.series)} series, {len(career.tiers)} tiers")
    check("it knows the game's track names",
          len(career.track_names()) > 50, f"{len(career.track_names())} tracks")

    texts = serieslib.load_texts(root)
    check("the text files line up with the key file",
          len(texts) > 1000, f"{len(texts)} keys")
    blobs = texts.blobs(only_changed=False)
    check("every text file round trips", len(blobs) == 13, f"{len(blobs)} files")
    reloaded = textslib.Texts.from_blobs(blobs)
    check("re-reading them gives the same keys",
          reloaded.keys() == texts.keys(), "key sets differ")

    rows = serieslib.list_series(career, texts)
    check("every series has a row", len(rows) == len(career.series),
          f"{len(rows)} rows")
    # 493 of the 1602 series sit in a menu: the career and motorsports groups.
    # The rest are the limited-time and daily-race tables, which are addressed by
    # index rather than by menu position and must never be given a page.
    check("the menu holds the career and motorsport series",
          sum(1 for r in rows if r["group"]) > 400,
          f"{sum(1 for r in rows if r['group'])} in a menu")

    templates = serieslib.templates(career)
    check("there are templates to copy", len(templates) > 100,
          f"{len(templates)} templates")
    check("the best template is a career series",
          templates[0]["type"] in (0, 8) and templates[0]["in_menu"],
          str(templates[0]))

    before = len(career.series)
    made = serieslib.build(
        career, texts, template=templates[0]["id"], title="Test Cup",
        description="Written by the test suite.", cars=[88],
        events=["Bathurst:2:2", "Bathurst:1:1"],
        group=serieslib.DEFAULT_GROUP)
    check("a new series gets the next free id",
          made["id"] == max(s.id for s in career.series if s.id != made["id"]) + 1,
          f"id {made['id']}")
    check("the series was added", len(career.series) == before + 1,
          f"{before} -> {len(career.series)}")
    check("its title key is derived from the title",
          made["key"] == f"SERIES_TITLE_TEST_CUP_{made['id']}", made["key"])
    check("it made the tiers and events asked for",
          made["tiers"] == 1 and made["events"] == 2,
          f"{made['tiers']} tier(s), {made['events']} event(s)")
    check("it landed in the group asked for",
          made["group"] == serieslib.DEFAULT_GROUP, made["group"])

    info = serieslib.describe(career, made["id"], texts)
    check("describe finds the title text", info["title"] == "Test Cup",
          info["title"])
    check("describe finds the description",
          info["desc"] == "Written by the test suite.", info["desc"])
    check("describe lists the cars", info["tiers"][0]["cars"] == [88],
          str(info["tiers"][0]["cars"]))
    check("describe lists both events",
          len(info["tiers"][0]["events"]) == 2,
          str([e["track"] for e in info["tiers"][0]["events"]]))
    check("the event types survived",
          [e["type"] for e in info["tiers"][0]["events"]] == [2, 1],
          str([e["type"] for e in info["tiers"][0]["events"]]))

    check("the rebuilt file still parses",
          careerlib.parse(career.to_bytes()).to_bytes() == career.to_bytes(),
          "rebuild after the edit differs")

    # writing is refused unless the file reads back exactly; prove the write and
    # the guard both work by staging a real one
    staging = os.path.join(ROOT, "work", "rrmod_test_career")
    shutil.rmtree(staging, ignore_errors=True)
    written = serieslib.write(career, texts, out_dir=staging, log=lambda m: None)
    check("the career file was written",
          os.path.getsize(written["career"]["path"]) > 14_000_000,
          f"{os.path.getsize(written['career']['path']):,} bytes")
    check("the text files were written", len(written["texts"]) == 13,
          f"{len(written['texts'])} files")
    again = careerlib.parse(nctlib.read(written["career"]["path"]))
    check("the written file reads back identically",
          again.to_bytes() == career.to_bytes(), "bytes differ after a round trip")
    check("the written file still has the new series",
          again.series_by_id(made["id"]) is not None, "the series vanished")
    plan = serieslib.plan(written)
    check("the plan names the career file and the text files", len(plan) == 14,
          f"{len(plan)} item(s)")
    check("the career file goes to .depot/data",
          any(rel == ".depot/data/events.dat.nct" for _l, rel, _k in plan),
          str([rel for _l, rel, _k in plan][:3]))
    # the staging folder is a root like any other, so it has to read back through
    # the same loader - otherwise "save, then edit again" starts from a stale copy
    check("the staging folder reads back like an install",
          serieslib.load(staging).series_by_id(made["id"]) is not None,
          "the written career cannot be loaded back from the staging folder")
    check("the staging folder keeps its text files under .depot",
          os.path.isfile(os.path.join(staging, ".depot", "gametext.txt")),
          "gametext.txt is not where an install would put it")

    # a track name the game does not have must be refused, not written
    try:
        serieslib.build(career, texts, template=templates[0]["id"],
                        title="Bad Cup", events=["Not A Track:2:1"],
                        group=serieslib.DEFAULT_GROUP)
        check("an unknown track is refused", False, "the build accepted it")
    except serieslib.SeriesError as exc:
        check("an unknown track is refused", "not one of the game's track" in str(exc),
              str(exc)[:120])

    # removal takes the tiers, the menu page and the text with it
    tiers_before = len(career.tiers)
    serieslib.remove(career, texts, made["id"])
    check("removing a series drops it", career.series_by_id(made["id"]) is None,
          "still there")
    check("removing a series drops its tiers", len(career.tiers) < tiers_before,
          f"{tiers_before} -> {len(career.tiers)}")
    check("removing a series drops its title text",
          not texts.has(f"SERIES_TITLE_TEST_CUP_{made['id']}"),
          "the key is still there")
    check("the file still parses after a removal",
          careerlib.parse(career.to_bytes()).to_bytes() == career.to_bytes(),
          "rebuild after the removal differs")
    shutil.rmtree(staging, ignore_errors=True)

    print("21 refusing to push a stale career file")
    # The career file cannot be merged row by row, so the guard has to compare the
    # series and event ids.  This is the case that matters in practice: a copy
    # built from the local depot has fewer series than the device, because the
    # device has the ones we added last time.
    older = careerlib.parse(plain)
    extra = careerlib.parse(plain)
    serieslib.build(extra, textslib.Texts.load(os.path.join(MINI, ".depot")),
                    template=templates[0]["id"], title="Device Only",
                    events=["Bathurst:2:1"], group=serieslib.DEFAULT_GROUP)
    newer_blob = nctlib.crypt(extra.to_bytes())
    older_blob = nctlib.crypt(older.to_bytes())
    check("the two career files really differ",
          len(extra.series) == len(older.series) + 1,
          f"{len(older.series)} vs {len(extra.series)}")

    career_path = os.path.join(MINI, ".depot", "data", "events.dat.nct")
    try:
        deploylib.check_career(career_path, deploylib.CAREER_REL,
                               FakeDevice("career-old", newer_blob))
        check("a career file missing a device series is refused", False,
              "the guard let an older career file through")
    except deploylib.DeployError as exc:
        check("a career file missing a device series is refused",
              "missing 1 series" in str(exc), str(exc)[:140])

    # writing the same file back is fine
    with open(career_path, "wb") as fh:
        fh.write(older_blob)
    try:
        deploylib.check_career(career_path, deploylib.CAREER_REL,
                               FakeDevice("career-same", older_blob))
        check("an unchanged career file is allowed", True)
    except deploylib.DeployError as exc:
        check("an unchanged career file is allowed", False, str(exc)[:140])

    # and the escape hatch works
    try:
        deploylib.check_career(career_path, deploylib.CAREER_REL,
                               FakeDevice("career-forced", newer_blob),
                               allow_shrink=True)
        check("allow_shrink skips the career check", True)
    except deploylib.DeployError as exc:
        check("allow_shrink skips the career check", False, str(exc)[:140])

    # a file the device does not have yet cannot lose anything
    try:
        deploylib.check_career(career_path, deploylib.CAREER_REL,
                               FakeDevice("career-absent", b""))
        check("a career file the device lacks is allowed", True)
    except deploylib.DeployError as exc:
        check("a career file the device lacks is allowed", False, str(exc)[:140])

    print("22  the windows start")
    # The exe shipped once with ``dlg.Accepted``: PySide exposes enum members on
    # the class only, so an instance lookup raises AttributeError - and because
    # that line only runs on the first launch, when no install is remembered yet,
    # nothing caught it until a user double clicked a fresh copy.  Scan for the
    # shape rather than trusting a manual test to hit that branch.
    import re

    ENUMS = ("Accepted", "Rejected", "Yes", "No", "Ok", "Cancel", "Save",
             "Discard", "Apply", "Close", "Ignore", "Retry")
    pattern = re.compile(r"\b([a-z_][A-Za-z0-9_]*)\.(" + "|".join(ENUMS) + r")\b")
    offenders = []
    for base in ("rrmod", os.path.join("rrmod", "ui")):
        folder = os.path.join(ROOT, base)
        for name in sorted(os.listdir(folder)):
            if not name.endswith(".py"):
                continue
            path = os.path.join(folder, name)
            with open(path, encoding="utf-8") as fh:
                for lineno, line in enumerate(fh, 1):
                    code = line.split("#", 1)[0]
                    for match in pattern.finditer(code):
                        offenders.append(f"{base}\\{name}:{lineno} {match.group(0)}")
    check("no Qt enum member is read off an instance", not offenders,
          "; ".join(offenders[:4]))

    # and prove the modules still import and the pages still build: a name error
    # in a widget class body only shows up when the class is first touched
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        from PySide6.QtWidgets import QApplication, QDialog

        qapp = QApplication.instance() or QApplication([])
        from rrmod.ui import (animui, app as applayout, buildui, cars, deployui,
                              gfxui, musicbatch, musicui, seriesui, settings as settingslib)

        dlg = applayout.WelcomeDialog()
        check("the first run dialog builds", dlg.windowTitle() != "", "no title")
        # The format is answered here, once, instead of being guessed per file:
        # a page written in a family the GPU cannot decode draws as nothing.
        offered = [dlg.family.itemData(i) for i in range(dlg.family.count())]
        check("the first run dialog asks for the texture format",
              offered == ["auto", "dxt", "etc", "atc"], str(offered))
        check("and every entry it offers has words beside it",
              all(dlg.family.itemText(i) for i in range(dlg.family.count())),
              str([dlg.family.itemText(i) for i in range(dlg.family.count())]))
        check("the folder and the format travel together",
              set(dlg.values()) == {"install", "reference", "family"}
              and dlg.values()["family"] in offered, str(dlg.values()))
        # Choosing the folder again with an answer given for a different install:
        # the dialog has to say the two disagree.  Silently keeping either one is
        # how a page gets written in a family the GPU draws as nothing.
        here = depotlib.detect_texture_family(MINI)
        elsewhere = "etc" if here == "dxt" else "dxt"
        dlg2 = applayout.WelcomeDialog()
        dlg2.picker.set_text(MINI)
        dlg2.family.setCurrentIndex(dlg2.family.findData(elsewhere))
        dlg2._accept()
        told = dlg2.problem.text()
        check("a format that disagrees with the folder is pointed out",
              here.upper() in told and elsewhere.upper() in told, told)
        dlg2.deleteLater()
        # the exact expression that crashed the shipped exe
        check("QDialog.Accepted is reachable from a dialog instance's class",
              applayout.WelcomeDialog.Accepted == QDialog.Accepted,
              "the class lost its enum")
        win = applayout.MainWindow()
        check("the main window builds with no install",
              win.tabs.count() == 11, f"{win.tabs.count()} tab(s)")
        # There is no toolbar any more: every button it held is in a menu, and
        # putting the same command in two places is how one of them goes stale.
        from PySide6.QtWidgets import QToolBar

        check("the window carries no toolbar",
              not win.findChildren(QToolBar),
              str([t.windowTitle() for t in win.findChildren(QToolBar)]))

        def _menu_of(title: str) -> list:
            for act in win.menuBar().actions():
                if act.text() == title and act.menu() is not None:
                    return [a.text() for a in act.menu().actions() if a.text()]
            return []

        tools = _menu_of("&Tools")
        check("the texture converter is in the Tools menu",
              any(t.startswith("Convert textures") for t in tools), str(tools))
        check("Find device is offered once, in that same menu",
              tools.count("Find device") == 1, str(tools))
        files = _menu_of("&File")
        check("the File menu has no project entries left",
              not [t for t in files if "project" in t.lower()], str(files))
        check("and it still opens an install and builds a car",
              any("Open install" in t for t in files)
              and any("Build a car" in t for t in files), str(files))
        # the Brands page is the only one whose data comes from a worker; it has
        # to exist and be named the same as its tab
        check("the brands page is one of them", hasattr(win, "brands"),
              str(type(getattr(win, "brands", None))))
        check("every page has a tab",
              [win.tabs.tabText(i) for i in range(win.tabs.count())]
              == ["Cars", "Music", "Graphics", "Career", "Brands",
                  "Materials", "Dependencies", "Decals", "Publish", "Test",
                  "About"],
              str([win.tabs.tabText(i) for i in range(win.tabs.count())]))
        # The two programs are one build with different pages shown, so the
        # studio must hide the three manager pages and the manager must hide the
        # three studio ones - and the tabs have to come back when it is "both".
        from rrmod import profile as profilelib

        win.set_profile("studio")
        studio = [win.tabs.tabText(i) for i in range(win.tabs.count())
                  if win.tabs.isTabVisible(i)]
        check("the studio hides the manager's pages",
              studio == ["Cars", "Career", "Brands", "Materials",
                         "Dependencies", "Decals", "Publish", "About"],
              str(studio))
        win.set_profile("manager")
        manager = [win.tabs.tabText(i) for i in range(win.tabs.count())
                   if win.tabs.isTabVisible(i)]
        check("the manager hides the studio's pages",
              manager == ["Cars", "Music", "Graphics", "Materials",
                          "Dependencies", "Test", "About"], str(manager))
        check("no page is lost by hiding it",
              win.tabs.count() == len(profilelib.ORDER),
              f"{win.tabs.count()} vs {len(profilelib.ORDER)}")
        win.set_profile("both")
        check("both shows all eleven again",
              all(win.tabs.isTabVisible(i) for i in range(win.tabs.count())),
              "a tab stayed hidden")
        # The tick beside a profile must follow the choice even when the labels
        # are translated: it used to be found by comparing the action's text to
        # the English label, so in Chinese nothing was ever ticked.
        from rrmod import i18n as i18nlib

        win.set_profile("studio")
        ticked = [a.data() for a in win._profile_group.actions() if a.isChecked()]
        check("the profile menu ticks the one in use",
              ticked == ["studio"], str(ticked))
        i18nlib.set_language("zh-Hans")
        win.set_profile("manager")
        ticked = [a.data() for a in win._profile_group.actions() if a.isChecked()]
        check("and still ticks it in another language",
              ticked == ["manager"], str(ticked))
        i18nlib.set_language("en")
        # the panes and pages take no arguments; the three dialogs need data, so
        # they are built from the mini install rather than with no arguments
        for cls in (animui.AnimPane, cars.CarTable, cars.DetailPane,
                    gfxui.GfxPage, musicui.MusicPage, seriesui.SeriesPage,
                    deployui.DeployPage):
            cls()  # noqa: B018 - constructing it is the test
        from rrmod.ui import depsui as depsuilib

        depsuilib.DepsPage()  # noqa: B018 - constructing it is the test
        car_inv = depotlib.scan(MINI)
        buildui.BuildDialog(car_inv)
        musicbatch.BatchDialog(musiclib.scan(car_inv.depot),
                               musiclib.available_music(car_inv.depot))
        career_now = careerlib.load(car_inv.depot)
        seriesui.SeriesDialog(career_now, textslib.Texts.load(car_inv.depot))
        check("every widget class constructs", True)

        # ---- 23 the interface language --------------------------------
        print("23  the interface language")
        from rrmod import i18n
        from rrmod.ui import translate

        langs = i18n.available()
        check("English and Chinese are offered",
              "en" in langs and "zh-Hans" in langs, str(sorted(langs)))
        zh = i18n.table("zh-Hans")
        check("the Chinese table has entries", len(zh) > 150, f"{len(zh)} entries")
        gaps = i18n.missing("zh-Hans")
        check("the Chinese table covers every interface string", not gaps,
              f"{len(gaps)} missing, e.g. {gaps[:2]}")

        # the inventory is what the coverage claim above is measured against, so
        # it has to be there and it has to be current
        inventory = i18n.source()
        check("the string inventory exists", len(inventory) > 150,
              f"{len(inventory)} string(s) in _source.json")

        # switching has to be lossless: English -> Chinese -> English must land
        # back on the exact original text, or the second switch is permanent
        saved_language = settingslib.language()
        before = [win.tabs.tabText(i) for i in range(win.tabs.count())]
        win.set_language("zh-Hans")
        during = [win.tabs.tabText(i) for i in range(win.tabs.count())]
        check("switching to Chinese renames the tabs", during != before, str(during))
        check("the tabs are actually Chinese", during[0] == "车辆", str(during))
        seen = translate.apply(win)
        check("the walker finds strings to translate", seen > 50, f"{seen}")
        win.set_language("en")
        after = [win.tabs.tabText(i) for i in range(win.tabs.count())]
        check("switching back restores the English tabs", after == before, str(after))
        check("the menu bar is translated too",
              [a.text() for a in win.menuBar().actions()][:2] == ["&File", "&View"],
              str([a.text() for a in win.menuBar().actions()]))
        i18n.set_language("en")
        # the switch is remembered, so put the user's own choice back
        settingslib.set_language(saved_language)

        win.deleteLater()
        dlg.deleteLater()
        del qapp
    except ImportError as exc:                   # no Qt on this machine
        print(f"  SKIP  the windows start ({exc})")

    # ---- 24 the pickers -------------------------------------------------
    print("24  picking a car and a track")
    try:
        # the track catalogue works off names alone, so it needs no install
        names = ["Spa", "Spa Sunset", "Bathurst", "Bathurst Night",
                 "Leipzig GroBer Kurs Dawn", "Lime rock South dawn"]
        grouped = tracklib.group(names)
        check("tracks are grouped by circuit", "Spa" in grouped,
              str(sorted(grouped)))
        check("the time of day is read off the end of the name",
              tracklib.time_of_day("Spa Sunset") == "sunset"
              and tracklib.time_of_day("Spa") == "",
              tracklib.time_of_day("Spa Sunset"))
        check("the circuit keeps its own spelling",
              tracklib.circuit_of("Leipzig GroBer Kurs Dawn")
              == "Leipzig GroBer Kurs",
              tracklib.circuit_of("Leipzig GroBer Kurs Dawn"))
        check("a circuit with no art is not given a made up stem",
              tracklib.stem_of("Lime rock South dawn") == "",
              tracklib.stem_of("Lime rock South dawn"))
        check("a known circuit resolves to an art stem",
              tracklib.stem_of("Bathurst Night") == "bathurst",
              tracklib.stem_of("Bathurst Night"))

        # the pictures themselves: the real depot is read only, so this is the
        # one place a test touches it, and only to read
        install = depotlib.default_install()
        depot = os.path.join(install, ".depot") if install else ""
        if depot and os.path.isdir(os.path.join(depot, "gui_assets")):
            info = atlaslib.summary(depot, "events/daily_race/regular")
            check("the track atlas is readable", info["images"] > 20, str(info))
            w, h, channels, pixels = atlaslib.sprite_at(
                depot, "events/daily_race/regular", "bathurst_track_noon.png")
            check("a track card comes out at the size the atlas says",
                  (w, h) == (1024, 361) and len(pixels) == w * h * channels,
                  f"{w}x{h}x{channels}")
            check("a missing picture raises rather than returning nonsense",
                  _raises(atlaslib.AtlasError, atlaslib.sprite_at, depot,
                          "events/daily_race/regular", "no_such_car.png"))

        # the car list and its pictures, again read only
        if install:
            inv = depotlib.scan(install)
            check("the inventory is scannable", len(inv.cars) > 500,
                  f"{len(inv.cars)} cars")
            lfa = inv.get("2012_lexus_lfa")
            check("a car carries its reference data",
                  lfa is not None and lfa.car_class in ("S", "R", "P"),
                  getattr(lfa, "car_class", ""))
            check("most cars have a display name",
                  sum(1 for e in inv.cars if e.display_name) > 450,
                  f"{sum(1 for e in inv.cars if e.display_name)} named")
    except ImportError as exc:                   # no Qt on this machine
        print(f"  SKIP  picking a car and a track ({exc})")

    print("25  a picture becomes a menu card")
    try:
        # The card atlas is the one thing here that needs a real install: the
        # mini copy has no gui_assets.  Reading is all that happens.
        install = depotlib.default_install()
        depot = os.path.join(install, ".depot") if install else ""
        atlases = serieslib.card_atlases(depot) if depot else []
        if not atlases:
            print("  SKIP  a picture becomes a menu card (no gui_assets)")
        else:
            check("every screen size has a career atlas", len(atlases) >= 2,
                  f"{len(atlases)} atlases")
            check("the atlas says it holds pvr pages",
                  atlaslib.texture_format(atlases[0]) == ".rgb.pvr",
                  atlaslib.texture_format(atlases[0]))
            big_w, big_h = atlaslib.card_size(atlases[0])
            check("the shipped cards have a size of their own",
                  big_w > 300 and big_h > 400, f"{big_w}x{big_h}")

            name = serieslib.card_name("LFA Cup")
            check("a card name is made from the title",
                  name == "stream_group_lfa_cup_card.png", name)
            check("an empty title still gives a usable name",
                  serieslib.card_name("!!!") == "stream_group_custom_card.png",
                  serieslib.card_name("!!!"))

            # a flat picture, resized both ways by the atlas code
            source = os.path.join(ROOT, "work", "_test_card.png")
            os.makedirs(os.path.dirname(source), exist_ok=True)
            flat = b"\x20\x40\xc0\xff" * (300 * 420)
            thumbs.write_png_bytes(source, 300, 420, 4, flat)
            check("a picture resizes down without losing its colour",
                  atlaslib.resize(300, 420, 4, flat, 150, 210)[:4]
                  == b"\x20\x40\xc0\xff")
            check("a picture resizes up too",
                  len(atlaslib.resize(30, 42, 4, b"\x01\x02\x03\x04" * 1260,
                                      60, 84)) == 60 * 84 * 4)

            staged = os.path.join(ROOT, "work", "rrmod_test_card")
            shutil.rmtree(staged, ignore_errors=True)
            try:
                result = serieslib.add_card(
                    depot, source, name, out_dir=staged, log=lambda m: None)
                check("a card is written for every screen size",
                      len(result["files"]) == 2 * len(atlases),
                      f"{len(result['files'])} files")
                check("the card is named after its group",
                      result["card"] == "events/career/" + name, result["card"])
                pages = [p for p, _r in result["files"] if p.endswith(".z")]
                xmls = [p for p, _r in result["files"] if p.endswith(".atlas")]
                check("one page per screen size", len(pages) == len(atlases))
                listed = atlaslib.read_atlas(xmls[0])
                check("the new picture is in the atlas",
                      name in listed, str(sorted(listed)[:3]))
                w, h, page = listed[name][3], listed[name][4], listed[name][0]
                check("the new picture sits on a page of its own",
                      page >= 2 and (w, h) == (big_w, big_h), f"page {page}")
                # the page has to decode back to the size it claims
                img = pvrlib.read_bytes(zlib.decompress(
                    open(pages[0], "rb").read()[4:]))
                check("the page decodes at the size the atlas says",
                      (img.width, img.height) == (big_w, big_h),
                      f"{img.width}x{img.height}")
                check("the page is 32 bit rgba", img.channels == 4,
                      f"{img.channels} channels")
                check("the card is deployable",
                      len(serieslib.plan({"career": None, "texts": [],
                                          "files": result["files"]})) ==
                      len(result["files"]))
            finally:
                shutil.rmtree(staged, ignore_errors=True)
                if os.path.exists(source):
                    os.remove(source)
    except ImportError as exc:                   # no Qt on this machine
        print(f"  SKIP  a picture becomes a menu card ({exc})")

    print("26  handing a car to someone else")
    share_zip = os.path.join(ROOT, "work", "rrmod_test_share.zip")
    lod = os.path.join(MINI, ".depot", "vehicles", CAR, f"{CAR}_a.m3g")

    def _md5(path):
        import hashlib

        return hashlib.md5(open(path, "rb").read()).hexdigest()

    try:
        described = sharelib.describe(MINI, CAR)
        check("a car knows what a share of it would hold",
              described["count"] > 10, f"{described['count']} files")
        check("the share carries the spec and the paint table",
              any(r.endswith(".bin.nct") for r, _p in described["files"]) and
              any("/liveries/" in r for r, _p in described["files"]))
        check("the share does not carry the manifests",
              not any("asset_list" in r for r, _p in described["files"]))
        check("the share names the ids it was made against",
              described["car_id"] == 88 and described["appearance_id"] == 25)

        made = sharelib.export_car(MINI, CAR, share_zip, note="test",
                                   log=lambda m: None)
        check("a share is a zip", os.path.isfile(share_zip) and made["bytes"] > 1000)
        import zipfile

        with zipfile.ZipFile(share_zip) as zf:
            names = zf.namelist()
        check("the zip holds one manifest", names.count("mod.json") == 1)
        check("every file sits under files/",
              all(n == "mod.json" or n.startswith("files/") for n in names))
        check("the zip holds every file it promised",
              len(names) == made["files"] + 1, f"{len(names)} members")
        check("the manifest reads back",
              sharelib.read_manifest(share_zip)["name"] == CAR)

        before = _md5(lod)
        with open(lod, "ab") as fh:
            fh.write(b"\x00")
        changed = _md5(lod)
        check("the car really was changed", changed != before)
        insp = sharelib.inspect(MINI, share_zip)
        check("a share made here passes its own checks", not insp["problems"],
              str(insp["problems"])[:60])
        check("every file is listed as a replacement",
              len(insp["changes"]) == made["files"] and not insp["extra"])
        got = sharelib.import_car(MINI, share_zip, log=lambda m: None)
        check("importing writes the files back", got["written"] == made["files"])
        check("importing restores the car", _md5(lod) == before)
        check("the manifests follow the import", editlib.verify(MINI, CAR) == [])
        check("importing leaves an undo point", bool(editlib.backups(MINI)))

        bad = os.path.join(ROOT, "work", "rrmod_test_share_bad.zip")
        import json as _json

        def _pack(manifest, member=True):
            with zipfile.ZipFile(bad, "w") as zf:
                zf.writestr("mod.json", _json.dumps(manifest))
                if member:
                    zf.write(lod, f"files/vehicles/{CAR}/{CAR}_a.m3g")

        _pack({"format": 1, "name": CAR, "kind": "replace",
               "base": "no_such_car", "car_id": 88, "appearance_id": 25,
               "files": [f"vehicles/{CAR}/{CAR}_a.m3g"]})
        r = sharelib.inspect(MINI, bad)
        check("a share for a car that is not installed is refused",
              any("no_such_car" in p for p in r["problems"]),
              str(r["problems"])[:60])
        check("and importing it raises",
              _raises(sharelib.ShareError, sharelib.import_car, MINI, bad))

        _pack({"format": 1, "name": CAR, "kind": "replace", "base": CAR,
               "car_id": 999, "appearance_id": 25,
               "files": [f"vehicles/{CAR}/{CAR}_a.m3g"]})
        r = sharelib.inspect(MINI, bad)
        check("a share whose car id moved is refused",
              any("999" in p for p in r["problems"]), str(r["problems"])[:60])

        _pack({"format": 1, "name": CAR, "kind": "replace", "base": CAR,
               "car_id": 88, "appearance_id": 4242,
               "files": [f"vehicles/{CAR}/{CAR}_a.m3g"]})
        r = sharelib.inspect(MINI, bad)
        check("a share whose appearance id moved is refused",
              any("4242" in p for p in r["problems"]), str(r["problems"])[:60])

        _pack({"format": 1, "name": CAR, "kind": "new", "base": CAR,
               "files": []})
        check("a new-car pack is not a share",
              _raises(sharelib.ShareError, sharelib.read_manifest, bad))

        _pack({"format": 1, "name": CAR, "kind": "replace", "base": CAR,
               "car_id": 88, "appearance_id": 25,
               "files": ["../../escape.txt"]}, member=False)
        r = sharelib.inspect(MINI, bad)
        check("a path that climbs out of the install is refused",
              any("climbs out" in p for p in r["problems"]),
              str(r["problems"])[:60])

        _pack({"format": 1, "name": CAR, "kind": "replace", "base": CAR,
               "car_id": 88, "appearance_id": 25,
               "files": [f"vehicles/{CAR}/{CAR}_a.m3g"]}, member=False)
        check("a zip that lost a file it listed is refused",
              _raises(sharelib.ShareError, sharelib.import_car, MINI, bad))
    finally:
        for p in (share_zip,
                  os.path.join(ROOT, "work", "rrmod_test_share_bad.zip")):
            if os.path.exists(p):
                os.remove(p)

    print("27 reading the career off a device")
    # pull_from_device mirrors the install layout so that load() and load_texts()
    # can read the folder back afterwards - both look under <root>/.depot, which
    # the first version of this forgot.
    class PullDevice:
        def __init__(self, blobs):
            self.serial = "pull-test"
            self.blobs = blobs

        def run(self, *args):
            rel = args[1]
            leaf = rel.rsplit("/", 1)[-1]
            blob = self.blobs.get(leaf, b"")
            if blob:
                with open(args[-1], "wb") as fh:
                    fh.write(blob)

            class R:
                returncode = 0
            return R()

    depot = os.path.join(MINI, ".depot")
    blobs = {}
    for leaf in serieslib.career_leaves():
        p = os.path.join(depot, *leaf.split("/"))
        if os.path.isfile(p):
            blobs[os.path.basename(leaf)] = open(p, "rb").read()
    staged = serieslib.pull_from_device(PullDevice(blobs), MINI, log=lambda m: None)
    check("the pull writes the files it found", len(staged["files"]) == 14,
          f"{len(staged['files'])} file(s)")
    check("nothing is reported missing", not staged["missing"],
          str(staged["missing"])[:60])
    check("the pulled career reads back", len(staged["career"].series) > 1000,
          f"{len(staged['career'].series)} series")
    check("the pulled text reads back", len(staged["texts"]) > 1000,
          f"{len(staged['texts'])} keys")
    check("the pulled copy sits under .depot",
          os.path.isfile(os.path.join(staged["dir"], ".depot", "data",
                                      "events.dat.nct")),
          "the layout does not match an install")
    check("a device with no career file is refused",
          _raises(serieslib.SeriesError, serieslib.pull_from_device,
                  PullDevice({}), MINI, log=lambda m: None))
    shutil.rmtree(staged["dir"], ignore_errors=True)

    print("28 the worker registry")
    # A QThread destroyed while it runs kills the process, and the task a page
    # leaks is the one whose page-level reference was overwritten.  The registry
    # keeps every task reachable so closeEvent can wait for all of them.
    from rrmod.ui import worker as workerlib

    class Holder:
        pass

    holder = Holder()
    seen = []
    holder.task = workerlib.Task(lambda: seen.append(1), parent=None)
    holder.task.start()
    holder.task.wait(5000)
    check("a finished task is not running", not holder.task.isRunning())
    check("the task ran", seen == [1], str(seen))
    check("wait_all returns nothing when everything is idle",
          workerlib.wait_all(1000) == [], "something was still running")

    workerlib.shutdown()
    quiet = Holder()
    quiet.task = workerlib.Task(lambda: seen.append(2), parent=None)
    quiet.task.start()
    quiet.task.wait(5000)
    check("a task started after shutdown does nothing", seen == [1], str(seen))
    workerlib._SHUTDOWN[0] = False

    print("29 rebuilding a series' events")
    # Editing an existing series has to be able to replace its event list, not
    # only its title - and it has to leave the tiers alone when the user did not
    # touch the events, because a rebuild hands out new tier ids.
    dep = os.path.join(MINI, ".depot")
    career = serieslib.load(dep)
    texts = serieslib.load_texts(dep)
    subject = next(s for s in career.series if career.tiers_of(s.id))
    before_tiers = len(career.tiers_of(subject.id))
    before_ids = sorted(t.id for t in career.tiers_of(subject.id))
    quiet = serieslib.retitle(career, texts, subject.id, title="",
                              description="", cars=None, events=None, group="")
    check("a no-op edit changes nothing", quiet["changed"] == [], str(quiet["changed"]))
    check("a no-op edit keeps the tier ids",
          sorted(t.id for t in career.tiers_of(subject.id)) == before_ids,
          "the tier ids moved")

    made = serieslib.set_events(
        career, subject.id,
        ["Bathurst:2:2:0", "Spa:1:1:0", "Laguna Seca:2:1:1"])
    check("the new events replaced the old ones", made["events"] == 3,
          str(made["events"]))
    check("the tier count follows the lines", made["tiers"] == 2,
          str(made["tiers"]))
    tiers = career.tiers_of(subject.id)
    check("the tiers are in index order",
          [t.index for t in tiers] == [0, 1], str([t.index for t in tiers]))
    check("the tracks landed where they were asked",
          sorted(e.track for t in tiers for e in t.events)
          == ["Bathurst", "Laguna Seca", "Spa"],
          str([e.track for t in tiers for e in t.events]))
    check("the tier ids were renewed", all(t.id > 0 for t in tiers),
          str([t.id for t in tiers]))
    written = serieslib.write(career, texts, out_dir=os.path.join(
        ROOT, "work", "rrmod_test_career2"), log=lambda m: None)
    check("a rebuilt series still rebuilds to bytes",
          written["career"]["bytes"] > 14_000_000,
          str(written["career"]["bytes"]))
    check("an unknown track is refused",
          _raises(serieslib.SeriesError, serieslib.set_events, career,
                  subject.id, ["No Such Track:2:2"]))
    check("an empty event list is refused",
          _raises(serieslib.SeriesError, serieslib.set_events, career,
                  subject.id, []))
    shutil.rmtree(os.path.join(ROOT, "work", "rrmod_test_career2"),
                  ignore_errors=True)

    print("30 the shipped data files are where the code looks for them")
    # The first frozen build shipped without rrmod/data at all: the language menu
    # still listed Chinese (the name is hard coded) but picking it changed
    # nothing, and no amount of restarting helped.  Two things came out of that -
    # the spec now lists the folder, and a language is only offered when its
    # table actually loads - so both are checked here.
    from rrmod import cars as carlib
    from rrmod import i18n as i18nlib
    refs = carlib.load()
    check("the car spreadsheet is readable", len(refs) > 400, str(len(refs)))
    check("the Chinese table is readable", len(i18nlib.table("zh-Hans")) > 200,
          str(len(i18nlib.table("zh-Hans"))))
    check("the string inventory is readable", len(i18nlib.source()) > 200,
          str(len(i18nlib.source())))
    check("a language with no table is not offered",
          "zz" not in i18nlib.available(), str(sorted(i18nlib.available())))
    check("the languages with a table are offered",
          set(i18nlib.available()) == {"en", "zh-Hans"},
          str(sorted(i18nlib.available())))
    with open(os.path.join(HERE, "rrmod.spec"), "r", encoding="utf-8") as fh:
        spec_text = fh.read()
    check("the build spec ships the data folder", '"rrmod/data"' in spec_text,
          "rrmod.spec does not mention rrmod/data")

    print("31 adb can be pointed at a device by hand")
    # The serial is not always 127.0.0.1:16384 - this machine's emulator answers
    # as emulator-5554 - and the adb server port is a separate number again.
    check("host:port is taken as a serial",
          deploylib.parse_endpoint("127.0.0.1:16384") == ("127.0.0.1:16384", ""),
          str(deploylib.parse_endpoint("127.0.0.1:16384")))
    check("a plain name is taken as a serial",
          deploylib.parse_endpoint("emulator-5554") == ("emulator-5554", ""),
          str(deploylib.parse_endpoint("emulator-5554")))
    check("the server port can be written in front",
          deploylib.parse_endpoint("5038@127.0.0.1:16384")
          == ("127.0.0.1:16384", "5038"),
          str(deploylib.parse_endpoint("5038@127.0.0.1:16384")))
    check("an empty address means look for one",
          deploylib.parse_endpoint("") == ("", ""),
          str(deploylib.parse_endpoint("")))
    deploylib.set_default_endpoint("emulator-5554", "5038")
    check("the endpoint is remembered for later pushes",
          deploylib.default_endpoint() == ("emulator-5554", "5038"),
          str(deploylib.default_endpoint()))
    deploylib.set_default_endpoint("", "")
    check("the endpoint can be cleared",
          deploylib.default_endpoint() == ("", ""),
          str(deploylib.default_endpoint()))

    print("32 the editor writes straight into the install")
    # There is no working copy any more.  Every edit lands in the folder the game
    # reads, and the two things that make that safe are the undo history (a copy
    # of each file before it is written) and the per-car backup.  This group is
    # about the facade the pages talk to; the history itself is group 58.
    from rrmod.ui import editing as editinglib

    editor = editinglib.Editor(root)
    check("the editor writes into the install itself", editor.root == root,
          editor.root)
    check("it says so", editor.summary()["mode"] == "in place",
          str(editor.summary()))
    check("there is no working copy any more", editor.has_workspace is False,
          str(editor.has_workspace))
    check("nothing is ever staged", editor.pending() == []
          and editor.summary()["files"] == 0, str(editor.summary()))
    check("for_car hands the install back", editor.for_car(CAR) == root,
          editor.for_car(CAR))
    check("the tables come from the install too",
          editor.for_tables(CAR) == root, editor.for_tables(CAR))
    check("the music folder is the install's own",
          editor.for_music() == os.path.join(root, ".depot", "Tracks", "data"),
          editor.for_music())
    check("the career lives in the install", editor.for_career() == root,
          editor.for_career())
    check("it can see a car", editor.has_car(CAR), editor.has_car(CAR))
    check("collecting is a no-op, because the file is already there",
          editor.capture(CAR) == [] and editor.capture_music() == []
          and editor.capture_paths([".depot/anything"]) == [],
          str(editor.capture(CAR)))
    check("there is nothing to discard", editor.discard_car(CAR) == 0)
    check("ensure() reports the install and copies nothing",
          editor.ensure()["root"] == root and not editor.ensure()["created"],
          str(editor.ensure()))
    check("reading a car reads the install", editor.read_root(CAR) == root,
          editor.read_root(CAR))

    # The whole point of the switch: a write reaches the game folder with no
    # second step.  The undo history is what makes that survivable, so the two
    # are checked together - the file changes, the step knows about it, and
    # putting the step back restores the bytes exactly.
    spec_rel = f".depot/vehicles/data/{SPEC}"
    spec_path = os.path.join(root, *spec_rel.split("/"))
    with open(spec_path, "rb") as fh:
        spec_before = fh.read()
    statlib.set_tail(root, CAR, aspiration="Turbo", layout="F", unlock="",
                     cash=402700, gold=130)
    with open(spec_path, "rb") as fh:
        spec_edited = fh.read()
    check("an edit reaches the game folder with no second step",
          spec_edited != spec_before, "the spec was never written")
    steps = editlib.backups(root)
    check("and it leaves an undo step", bool(steps), str(steps[:2]))
    newest = historylib.read(root, steps[0])
    touched = [r[0] for r in newest["files"]]
    check("the step names the file it touched", spec_rel in touched,
          str(touched[:4]))
    editlib.restore_backup(root, steps[0])
    with open(spec_path, "rb") as fh:
        check("undo puts the bytes back exactly", fh.read() == spec_before,
              "the spec did not come back")
    # and back to what the earlier groups left it as
    statlib.set_tail(root, CAR, aspiration="Nat", layout="F", unlock="",
                     cash=402700, gold=130)
    check("the car is where group 31 left it",
          statlib.tail(root, CAR)["aspiration"] == "Nat",
          statlib.tail(root, CAR)["aspiration"])

    print("32b backing a car up and rolling it back")
    # The button the in-place way of working rests on.  A backup has to hold the
    # files *and* the parameters, and a rollback has to be forgiving - the state
    # it is usually asked to rescue is one where the car no longer agrees with
    # the install.
    bak_dir = os.path.join(ROOT, "work", "rrmod_test_backup")
    os.makedirs(bak_dir, exist_ok=True)
    zpath = os.path.join(bak_dir, "lfa backup.zip")
    if os.path.isfile(zpath):
        os.remove(zpath)

    def car_state():
        return {rel: editlib.md5_file(local)
                for rel, local in sharelib.car_files(root, CAR)}

    state = car_state()
    made = sharelib.backup_car(root, CAR, zpath, note="test", log=lambda m: None)
    check("the backup holds every file the car owns",
          made["files"] == len(state) and bool(state),
          f"{made['files']} vs {len(state)}")
    man = sharelib.read_backup(zpath)
    check("it says it is a backup", man["kind"] == "backup", man["kind"])
    check("it names the car", man["name"] == CAR, man["name"])
    check("it carries the parameters", bool(man.get("params")),
          str(man.get("params"))[:80])
    check("the parameters name the ids",
          man["params"].get("car_id") == CAR_ID,
          str(man["params"].get("car_id")))

    insp = sharelib.inspect_backup(root, zpath)
    check("a backup of an installed car has nothing to complain about",
          not insp["problems"], str(insp["problems"]))
    check("every file would be replaced", len(insp["replace"]) == len(state),
          f"{len(insp['replace'])} of {len(state)}")
    check("nothing would be created", insp["add"] == [], str(insp["add"]))

    # break it the way a bad build does: one mesh overwritten, one page gone
    mesh_rel = next(rel for rel in state if rel.endswith(".m3g"))
    mesh = os.path.join(root, ".depot", *mesh_rel.split("/"))
    with open(mesh, "wb") as fh:
        fh.write(b"this is not a mesh")
    gone_rel = next(rel for rel in state if "/livery/" in rel)
    os.remove(os.path.join(root, ".depot", *gone_rel.split("/")))
    check("the damage is real", car_state() != state)

    got = sharelib.rollback(root, zpath, log=lambda m: None)
    check("the rollback wrote every file", got["written"] == len(state),
          str(got["written"]))
    check("no manifest row was left un-booked", not got["failed"],
          str(got["failed"][:2]))
    check("the car is byte identical again", car_state() == state,
          str([k for k in state if state[k] != car_state().get(k)][:3]))
    check("and the manifests agree with it", editlib.verify(root, CAR) == [],
          str(editlib.verify(root, CAR)[:2]))
    check("the rollback is itself undoable",
          bool(editlib.backups(root)) and
          os.path.isdir(os.path.join(historylib.dir_for(root),
                                     editlib.backups(root)[0])),
          str(editlib.backups(root)[:2]))

    # A backup of a car that is not here any more must still be usable - that is
    # the whole reason it exists.
    ghost = os.path.join(bak_dir, "ghost.zip")
    with zipfile.ZipFile(ghost, "w") as zf:
        zf.writestr("mod.json", json.dumps({
            "format": 1, "kind": "backup", "name": "2099_ghost_car",
            "car_id": 999, "files": ["vehicles/2099_ghost_car/readme.txt"]}))
        zf.writestr("files/vehicles/2099_ghost_car/readme.txt", "hello")
    ginsp = sharelib.inspect_backup(root, ghost)
    check("a car that is not installed is not a problem",
          not ginsp["problems"], str(ginsp["problems"]))
    check("it is reported as gone", not ginsp["installed"])
    check("its files would be created",
          ginsp["add"] == ["vehicles/2099_ghost_car/readme.txt"],
          str(ginsp["add"]))
    climbed = os.path.join(bak_dir, "climb.zip")
    with zipfile.ZipFile(climbed, "w") as zf:
        zf.writestr("mod.json", json.dumps({
            "format": 1, "kind": "backup", "name": "x",
            "files": ["../evil.txt"]}))
    check("a path that climbs out of the folder is refused",
          bool(sharelib.inspect_backup(root, climbed)["problems"]))
    check("and rolling it back is refused too",
          _raises(sharelib.ShareError, sharelib.rollback, root, climbed))
    junk = os.path.join(bak_dir, "junk.zip")
    with zipfile.ZipFile(junk, "w") as zf:
        zf.writestr("hello.txt", "no manifest here")
    check("a zip that is not a backup is refused",
          _raises(sharelib.ShareError, sharelib.read_backup, junk))
    for leftover in (ghost, climbed, junk):
        if os.path.isfile(leftover):
            os.remove(leftover)

    print("33 the wing behaviour")
    # Four behaviours ship, and only two of them carry speeds.  Getting this
    # wrong is not cosmetic: the token sits in one slot in front of a
    # "generic_*" string, and writing a longer one there is what makes the
    # difference between an air brake, a drag-reduction flap and both.
    kinds = dict((token, label) for label, token in animlib.AERO_CHOICES)
    check("all four behaviours are offered", len(kinds) == 4, str(sorted(kinds)))
    check("the two speed-dependent ones are known",
          set(animlib.AERO_PARAMETRIC) == {b"DeployAtSpeed",
                                           b"BrakeAndSpeedCombo"},
          str(animlib.AERO_PARAMETRIC))

    sp = speclib.load_spec(os.path.join(root, ".depot"), f"88_{CAR}")
    check("a car with no wing reports no behaviour", sp.aero_kind() == b"",
          str(sp.aero_kind()))
    sp.set_aero(True, kind=b"BrakeAndSpeedCombo", params=(180, 170))
    check("a behaviour can be written into an empty slot",
          sp.aero_kind() == b"BrakeAndSpeedCombo", str(sp.aero_text()))
    check("the speeds come back in order", sp.aero_params() == (180.0, 170.0),
          str(sp.aero_params()))
    again = speclib.parse_spec(sp.to_bytes())
    check("the spec still reads back after the write",
          again.aero_text() == "BrakeAndSpeedCombo, 180, 170",
          again.aero_text())
    again.set_aero(False)
    check("a behaviour can be taken out again", again.aero_kind() == b"",
          str(again.aero_text()))

    # Read straight from the game install: the mini copy carries only the LFA's
    # spec, and this car's spec is the one with a plain DeployWhenBraking.
    wing = speclib.load_spec(os.path.join(install, ".depot"), ANIM_SPEC[:-8])
    check("a car with a wing reports which behaviour",
          wing.aero_kind() == b"DeployWhenBraking", str(wing.aero_text()))
    check("a behaviour with no numbers reports none",
          wing.aero_params() == (), str(wing.aero_params()))
    before_len = len(wing.to_bytes())
    wing.set_aero(True, kind=b"DeployAtSpeed", params=(275, 220))
    check("switching behaviour keeps the file readable",
          speclib.parse_spec(wing.to_bytes()).aero_text()
          == "DeployAtSpeed, 275, 220",
          speclib.parse_spec(wing.to_bytes()).aero_text())
    check("switching behaviour changes the size as expected",
          len(wing.to_bytes()) != before_len,
          f"{before_len} -> {len(wing.to_bytes())}")

    state = animlib.aero_state(install, ANIM_CAR)
    check("the animation tab can read the behaviour", state["kind"]
          == "DeployWhenBraking", str(state))

    print("34 the other GPU families")
    # Real Racing 3 ships the same picture four times - .dxt (which this depot
    # unpacks), .atc, .etc and .ptc - and a depot built for another device holds
    # a different one.  All four have to decode, so the three block decoders are
    # checked against the DXT page of the very same art: ATC and ETC land within
    # a couple of levels, PVRTC only once its gamma curve is accounted for.
    page = os.path.join(install, ".depot", "gui_assets", "960x640", "splash",
                        "loading")
    variants = {}
    for name in ("sprites_0.dxt.dds.z", "sprites_0.atc.dds.z",
                 "sprites_0.etc.dds.z", "sprites_0.ptc.pvr.z"):
        path = os.path.join(page, name)
        if os.path.isfile(path):
            variants[name] = texlib.payloads(path)[0]
    check("this install ships more than one variant of the page",
          len(variants) >= 3, str(sorted(variants)))

    def mean_gap(one, other):
        """Mean absolute difference of two RGBA images, sampled on a grid."""
        aw, ah, ach, apx = one
        bw, bh, bch, bpx = other
        total = count = 0
        for y in range(0, min(ah, bh), 11):
            for x in range(0, min(aw, bw), 11):
                i = (y * aw + x) * ach
                j = (y * bw + x) * bch
                total += (abs(apx[i] - bpx[j]) + abs(apx[i + 1] - bpx[j + 1])
                          + abs(apx[i + 2] - bpx[j + 2]))
                count += 3
        return total / count if count else 0.0

    if "sprites_0.dxt.dds.z" in variants:
        reference = ddslib.decode(variants["sprites_0.dxt.dds.z"])
        if "sprites_0.atc.dds.z" in variants:
            atc = ddslib.decode(variants["sprites_0.atc.dds.z"])
            gap = mean_gap(reference, atc)
            check("ATC decodes to the same picture", gap < 6,
                  f"mean difference {gap:.2f}")
            check("ATC reports its fourcc",
                  ddslib.info(variants["sprites_0.atc.dds.z"])["format"] == "ATC ",
                  ddslib.info(variants["sprites_0.atc.dds.z"])["format"])
        if "sprites_0.etc.dds.z" in variants:
            etc = ddslib.decode(variants["sprites_0.etc.dds.z"])
            gap = mean_gap(reference, etc)
            check("ETC decodes to the same picture", gap < 6,
                  f"mean difference {gap:.2f}")
            body = variants["sprites_0.etc.dds.z"][128:]
            near = mean_gap(reference, etclib.decode_etc(
                body, reference[0], reference[1], transpose=True))
            far = mean_gap(reference, etclib.decode_etc(
                body, reference[0], reference[1], transpose=False))
            check("ETC blocks are walked transposed, as the reference does",
                  near < far, f"transposed {near:.2f}, plain {far:.2f}")
        if "sprites_0.ptc.pvr.z" in variants:
            ptc = pvrlib.read_bytes(variants["sprites_0.ptc.pvr.z"])
            shown = (ptc.width, ptc.height, ptc.channels, ptc.pixels)
            raw = mean_gap(reference, shown)
            through = mean_gap((reference[0], reference[1], reference[2],
                                etclib.to_display(reference[3])), shown)
            check("PVRTC decodes at the size the header states",
                  (ptc.width, ptc.height) == (reference[0], reference[1]),
                  f"{ptc.width}x{ptc.height}")
            # The two families differ by a gamma curve, so the raw gap is large
            # and the corrected one is small; that asymmetry *is* the check.
            check("PVRTC matches DXT once the gamma curve is applied",
                  through < 8 and raw > through * 4,
                  f"raw {raw:.2f}, through the curve {through:.2f}")
            check("the gamma curve leaves alpha alone",
                  etclib.to_display(bytes((10, 10, 10, 7)))[3] == 7)
            check("the gamma curve lifts dark values",
                  etclib.to_display(bytes((10, 10, 10, 255)))[0] > 40,
                  str(etclib.to_display(bytes((10, 10, 10, 255)))[0]))

    check("a fourcc nobody implements is refused",
          _raises(etclib.BlockError, etclib.decode_dds, b"DDS " + b"\0" * 124))
    check("an unknown PVR kind is refused",
          _raises(etclib.BlockError, etclib.decode_pvr, b"\0" * 52))
    atlas_source = open(os.path.join(ROOT, "rrmod", "atlas.py"),
                        encoding="utf-8").read()
    thumbs_source = open(os.path.join(ROOT, "rrmod", "thumbs.py"),
                         encoding="utf-8").read()
    check("both page finders know all four suffixes",
          all(suffix in atlas_source and suffix in thumbs_source
              for suffix in (".dxt.dds.z", ".atc.dds.z", ".etc.dds.z",
                             ".ptc.pvr.z")),
          "a suffix is missing from page_path")

    # A depot built for a Mali device holds the .etc copy where this one holds
    # the .dxt copy, so the two finders that walk a car folder by suffix have to
    # see it.  The car folder is copied and its atlases renamed to prove it; the
    # scratch lives in the writable mini install, not in the read only depot.
    mini_depot = os.path.join(MINI, ".depot")
    car_dir = os.path.join(mini_depot, "vehicles", "2012_lexus_lfa")
    if os.path.isdir(car_dir):
        sample = texturelib.find_atlas(car_dir, "lights")
        if sample:
            scratch = os.path.join(MINI, "_atlas_scratch")
            shutil.rmtree(scratch, ignore_errors=True)
            os.makedirs(scratch)
            try:
                shutil.copyfile(sample, os.path.join(
                    scratch, "2012_lexus_lfa_lights.etc.dds.z"))
                shutil.copyfile(sample, os.path.join(
                    scratch, "2012_lexus_lfa_badges.atc.dds.z"))
                found = texturelib.find_atlas(scratch, "lights")
                check("the atlas finder sees an ETC-only car folder",
                      bool(found) and found.endswith(".etc.dds.z"),
                      os.path.basename(found or "-"))
                found = texturelib.find_atlas(scratch, "badges")
                check("the atlas finder sees an ATC-only car folder",
                      bool(found) and found.endswith(".atc.dds.z"),
                      os.path.basename(found or "-"))
                check("the atlas finder still prefers the DXT copy",
                      os.path.basename(sample).endswith(".dxt.dds.z"),
                      os.path.basename(sample))
            finally:
                shutil.rmtree(scratch, ignore_errors=True)

    # The driver skins follow the same rule: one name, whichever family on disk.
    common = os.path.join(mini_depot, "vehicles", "common")
    real_common = os.path.join(os.path.join(depotlib.default_install() or "",
                                            ".depot"), "vehicles", "common")
    if os.path.isdir(real_common):
        os.makedirs(common, exist_ok=True)
        for name in os.listdir(real_common):
            target = os.path.join(common, name)
            if name.startswith("driver") and name.endswith(".dxt.dds.z") \
                    and not os.path.isfile(target):
                shutil.copyfile(os.path.join(real_common, name), target)
    if os.path.isdir(common):
        skins = drvlib.skins(mini_depot)
        found = drvlib.texture_for(mini_depot)
        check("the driver texture is found whichever family is on disk",
              bool(found) and found.endswith(drvlib.TEXTURE_SUFFIXES),
              os.path.basename(found or "-"))
        check("a driver skin resolves with or without its suffix",
              drvlib.texture_for(mini_depot, "alesi")
              == drvlib.texture_for(mini_depot, "driver_alesi.dxt.dds.z"),
              os.path.basename(drvlib.texture_for(mini_depot, "alesi") or "-"))
        check("every driver skin the depot has is listed once",
              len(skins) == len(set(skins)) and len(skins) > 1,
              str(len(skins)))

    print("35 the brands")
    mini_texts = textslib.Texts.load(inv.depot)
    found = brandlib.brands(inv, mini_texts)
    check("every make the install files a car under is listed",
          len(found) == len({c.make for c in inv.cars if c.make}),
          f"{len(found)} vs {len({c.make for c in inv.cars if c.make})}")
    check("the cars add up to the whole install",
          sum(b["cars"] for b in found) == len(inv.cars),
          f"{sum(b['cars'] for b in found)} vs {len(inv.cars)}")
    check("the list is ordered by how many cars use the brand",
          all(found[i]["cars"] >= found[i + 1]["cars"]
              for i in range(len(found) - 1)))
    have = brandlib.logos(inv.depot)
    check("the logo sheet was found", len(have) > 20, str(len(have)))
    check("every brand has a logo picture",
          all(b["has_logo"] for b in found),
          str([b["name"] for b in found if not b["has_logo"]][:4]))
    check("a brand with no text key falls back to its own name",
          all((b["shown"] and b["has_text"]) or b["shown"] ==
              b["name"].replace("_", " ") for b in found),
          str([b["name"] for b in found if not b["shown"]][:3]))
    check("the brands can be counted", brandlib.summary(inv)["brands"] == len(found),
          str(brandlib.summary(inv)))
    check("a brand nobody ships is not listed", not any(
        b["name"] == "Nonesuch Motors" for b in found))
    check("a brand of our own is listed even with no cars",
          any(b["ours"] and b["cars"] == 0
              for b in brandlib.brands(inv, mini_texts,
                                       ours=("Nonesuch Motors",))),
          "ours did not appear")
    check("stem and key are spelled the way the art and the spec are",
          brandlib.stem_of("Aston Martin") == "aston_martin"
          and brandlib.key_of("Aston Martin") == "ASTON_MARTIN"
          and brandlib.stem_of("Formula_E") == "formula_e",
          f"{brandlib.stem_of('Aston Martin')} {brandlib.key_of('Aston Martin')}")
    check("a logo picture name follows the convention",
          brandlib.picture_of("Aston Martin") == "logo_aston_martin.png",
          brandlib.picture_of("Aston Martin"))
    w, h, ch, px = brandlib.logo(inv.depot, found[0]["name"])
    check("a logo decodes to real pixels", w > 8 and h > 8 and ch in (3, 4)
          and len(px) == w * h * ch, f"{w}x{h} ch{ch} {len(px)}")
    try:
        brandlib.logo(inv.depot, "Nonesuch Motors")
        check("a brand with no art is refused", False, "no exception")
    except brandlib.BrandError:
        check("a brand with no art is refused", True)
    check("fitting keeps the aspect ratio",
          brandlib._fit(600, 200, 350, 107) == (321, 107)
          and brandlib._fit(100, 100, 350, 107) == (107, 107),
          str(brandlib._fit(600, 200, 350, 107)))
    sheets = brandlib.atlases(inv.depot)
    check("the logo sheet has a size to fit into",
          bool(sheets) and min(min(brandlib._logo_box(p)) for p in sheets) > 16,
          str([brandlib._logo_box(p) for p in sheets]))
    check("no logo picture is unreadable", brandlib.selftest(inv.depot) == 0)

    print("36 the track maps")
    career_for_maps = serieslib.load(inv.depot)
    every_track = serieslib.track_names(career_for_maps)
    # the pictures the user brings live next to rr3mods.json, not in the install
    map_depot = inv.depot
    made = maplib.store(map_depot, "Bathurst Night", _png_fixture())
    check("a picture the user brings is stored under its circuit",
          os.path.basename(made["path"]) == "bathurst.png",
          os.path.basename(made["path"]))
    check("the picture is really there", os.path.getsize(made["path"]) > 40,
          f"{made['bytes']} bytes")
    path, source = maplib.picture_for(map_depot, "Bathurst")
    check("the user's picture wins over the game's card",
          source == "mine", source)
    check("every layout of a circuit shares one picture",
          maplib.picture_for(map_depot, "Bathurst Morning")[0] == path,
          maplib.picture_for(map_depot, "Bathurst Morning")[0])
    counts = maplib.summary(map_depot, every_track)
    # one picture covers every time of day the circuit is raced at, so the
    # count is the number of Bathurst layouts, not one
    bathurst = [t for t in every_track
                if tracklib.circuit_of(t).lower() == "bathurst"]
    check("the summary counts every layout that picture now covers",
          counts["mine"] == len(bathurst) and counts["tracks"] == len(every_track),
          f"{counts['mine']} vs {len(bathurst)}")
    check("a picture that is not a picture is refused",
          _raises(maplib.MapError, maplib.store, map_depot, "Spa", __file__),
          "no exception")
    check("the stored pictures all read back", maplib.selftest(map_depot, every_track) == 0)
    check("forgetting it puts the game's card back",
          maplib.forget(map_depot, "Bathurst")
          and maplib.picture_for(map_depot, "Bathurst")[1] == "game",
          str(maplib.picture_for(map_depot, "Bathurst")))
    check("forgetting twice is not an error", maplib.forget(map_depot, "Bathurst") is False)
    left = maplib.missing(map_depot, every_track)
    check("most tracks have the game's own card", len(left) < len(every_track),
          f"{len(left)} without a picture")
    fixture = _png_fixture()
    if os.path.isfile(fixture):
        os.remove(fixture)

    print("37 the paint finishes the game itself offers")
    # ``inv`` was re-pointed at the real install by group 34; the paint tests
    # write, so they need the scratch install back.
    local = depotlib.scan(root)
    finishes = paintlib.load(local.depot)
    check("the game ships a paint table", len(finishes) > 20, f"{len(finishes)}")
    check("every finish uses a car paint material",
          all(f.material.startswith("car_paint_") for f in finishes),
          str(sorted({f.material for f in finishes})[:3]))
    check("no finish points at a map surface",
          all("concrete" not in f.material for f in finishes))
    mats = paintlib.materials(local.depot)
    check("the finishes cover several materials", len(mats) >= 10, f"{len(mats)}")
    offered = paintlib.choices(local.depot)
    check("the dropdown offers each material once",
          len(offered) == len({m for _l, m in offered}),
          f"{len(offered)} rows, {len({m for _l, m in offered})} materials")
    check("the dropdown reaches past the customiser's own menu",
          len(offered) > len(mats),
          f"{len(offered)} offered vs {len(mats)} in the customiser's table")
    check("everything offered can actually be written",
          all(paintlib.table_slot(local.depot, m) is not None
              for _l, m in offered),
          str([m for _l, m in offered
               if paintlib.table_slot(local.depot, m) is None][:3]))
    check("the labels are readable",
          paintlib.label_for("car_paint_matte") == "Matte"
          and paintlib.label_for("car_paint_metallic_white") == "Metallic white",
          paintlib.label_for("car_paint_metallic_white"))
    check("a gloss starts from black", paintlib.starting_colour(local.depot, "car_paint_gloss") == (33, 33, 33),
          str(paintlib.starting_colour(local.depot, "car_paint_gloss")))
    check("a gloss knows all eight of its colours",
          len(paintlib.colours_for(local.depot, "car_paint_gloss")) >= 5,
          f"{len(paintlib.colours_for(local.depot, 'car_paint_gloss'))}")
    swatches = paintlib.colours(local.depot)
    check("the game's own swatches are there", len(swatches) == 42, f"{len(swatches)}")
    check("every swatch is a colour", all(len(c) == 3 and all(0 <= v <= 255 for v in c)
                                          for c in swatches))
    raw = paintlib._plain(paintlib.paints_path(local.depot))
    rows, trailer = paintlib.parse_paints_with_tail(raw)
    check("the paint table reads back byte for byte",
          paintlib.build_paints(rows, trailer) == raw)
    check("the table's trailer is carried through", b"Author:" in trailer,
          f"{len(trailer)} bytes")
    check("the paint tables round trip", paintlib.selftest(local.depot) == 0)

    print("38 painting a car a different finish")
    paint_car = CAR
    _before = liverylib.load_car(local.depot, paint_car)
    _table = liverylib.load_slot_table(local.depot)
    _body = _table.part_slot("LOD_A_BODY_mm_ext")
    _wing = _table.part_slot("LOD_A_WING_REAR_mm_ext")
    painted = editlib.set_paint_finish(root, paint_car,
                                       material="car_paint_matte",
                                       colours={0: (10, 200, 30)})
    check("the body slot was found", painted["body_slot"] == _body, str(painted["body_slot"]))
    check("the wing slot was found", painted["wing_slot"] == _wing, str(painted["wing_slot"]))
    _after = liverylib.load_car(local.depot, paint_car)
    check("every scheme uses the new finish",
          all(p.material_of(_body) == _table.material_slot("car_paint_matte")
              for p in _after.paints),
          str([p.material_of(_body) for p in _after.paints]))
    check("the wing follows the body",
          all(p.material_of(_wing) == p.material_of(_body) for p in _after.paints))
    check("the recoloured scheme took the colour",
          tuple(_after.paints[0].rgb[:3]) == (10, 200, 30),
          str(tuple(_after.paints[0].rgb[:3])))
    check("the schemes left alone kept their colours",
          tuple(_after.paints[1].rgb[:3]) == tuple(_before.paints[1].rgb[:3]),
          f"{tuple(_before.paints[1].rgb[:3])} -> {tuple(_after.paints[1].rgb[:3])}")
    check("the livery still reads back", len(liverylib.parse(_after.to_bytes()).paints) == len(_after.paints))
    check("the manifests agree with the livery", editlib.verify(root, paint_car) == [])
    check("a material that is not in the table is refused",
          _raises(editlib.EditError, editlib.set_paint_finish, root, paint_car,
                  material="car_paint_not_a_thing"),
          "no exception")
    editlib.set_wing_paint(root, paint_car)

    print("39 the picture beside the name, and the window icon")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        from PySide6.QtWidgets import QApplication
    except Exception:                            # noqa: BLE001 - no Qt, no UI
        QApplication = None
    if QApplication is None:
        print("  skip  Qt is not installed")
    else:
        from rrmod.ui import app as appui
        from rrmod.ui import cars as carui
        from rrmod.ui import settings as setlib
        from rrmod.ui import thumbcache
        qapp = QApplication.instance() or QApplication([])
        page = carui.CarsPage()
        page.load(local)
        with_pic = None
        for e in local.cars:
            if thumbcache.thumbs.has(local.depot, e.car_id):
                with_pic = e
                break
        check("the car list found a car with a picture", with_pic is not None)
        page.detail.show_entry(local, with_pic)
        pm = page.detail.picture.pixmap()
        check("the picture is drawn", not pm.isNull(), f"{pm.width()}x{pm.height()}")
        check("the picture fits the pane", pm.width() <= 240 and pm.height() <= 130,
              f"{pm.width()}x{pm.height()}")
        # an id the game never drew, borrowed from the car that has one: the
        # miniature install holds a single car, and that one is pictured
        no_pic = dataclasses.replace(with_pic, car_id=999999)
        page.detail.show_entry(local, no_pic)
        check("a car the game never drew says so",
              page.detail.picture.text() == "no picture",
              repr(page.detail.picture.text()))
        check("and shows nothing", page.detail.picture.pixmap().isNull())
        page.detail.show_entry(None, None)
        check("clearing the selection clears the picture",
              page.detail.picture.text() == "" and page.detail.picture.pixmap().isNull())
        page.close()

        icon_file = os.path.join(ROOT, "work", "_test_icon.png")
        thumbs.write_png_bytes(icon_file, 32, 32, 4, bytes([40, 120, 220, 255] * 1024))
        was = setlib.icon()
        setlib.set_icon(icon_file)
        check("the chosen icon is remembered", setlib.icon() == icon_file)
        win = appui.MainWindow()
        check("the window wears it", not win.windowIcon().isNull())
        check("and so does the application", not qapp.windowIcon().isNull())
        win.close()
        setlib.set_icon(was)
        check("the icon can be put back", setlib.icon() == was)

    print("40 the build tools never delete a build they cannot move")
    # A build that did ``shutil.rmtree(dist/NAME, ignore_errors=True)`` and only
    # then tried to rename it gutted a live install: the running program locks
    # its own image and the folder, so the delete took every unlocked file out
    # of ``_internal`` and the rename then failed.  What was left could not
    # start - "Failed to start embedded python interpreter!" - and the user was
    # looking at a program that building a new one had broken.
    def code_of(name: str) -> str:
        """The file with its comments stripped - the comments explain the bug."""
        with open(os.path.join(HERE, name), encoding="utf-8") as fh:
            return "\n".join(line.split("#", 1)[0] for line in fh)
    build = code_of("build_exe.py")
    swap = code_of("swap_build.py")
    check("the builder does not delete the old build", "rmtree(" not in build,
          "build_exe.py still calls rmtree()")
    check("the swapper does not delete the old build", "rmtree(" not in swap,
          "swap_build.py still calls rmtree()")
    check("the builder moves it aside with a rename", "os.rename(stale" in build,
          "build_exe.py does not rename the old build out of the way")
    check("the swapper moves it aside with a rename", "os.rename(target" in swap,
          "swap_build.py does not rename the old build out of the way")

    print("41 a folder of exported files fills the slots the game has")
    export = os.path.join(ROOT, "work", "_test_export")
    shutil.rmtree(export, ignore_errors=True)
    os.makedirs(export)
    for src_name, out_name in ((f"{CAR}_a.m3g", "LOD_A.m3g"),
                               (f"{CAR}_b.m3g", "LOD_B.m3g"),
                               (f"{CAR}_shared.m3g", "SHARED.m3g"),
                               (f"{CAR}.points", "car.points")):
        source = os.path.join(MINI, ".depot", "vehicles", CAR, src_name)
        if os.path.isfile(source):
            shutil.copyfile(source, os.path.join(export, out_name))
    mapping = slotlib.read_folder(export)
    check("the body LOD was found by its name", "A" in mapping, str(sorted(mapping)))
    check("the second LOD too", "B" in mapping, str(sorted(mapping)))
    check("the shared model too", "shared" in mapping, str(sorted(mapping)))
    check("and the anchors", "points" in mapping, str(sorted(mapping)))
    check("nothing is missing", slotlib.problems(export, mapping) == [],
          str(slotlib.problems(export, mapping)))
    plan = {k: t for k, _s, t in slotlib.plan(mapping, "mymod")}
    check("the game's own file name is worked out", plan.get("A") == "mymod_a.m3g",
          str(plan))
    check("and for the shared model", plan.get("shared") == "mymod_shared.m3g",
          str(plan))
    check("a car-named export is understood too",
          slotlib.slot_of(f"{CAR}_shared.m3g") == "shared",
          slotlib.slot_of(f"{CAR}_shared.m3g"))
    check("an int model is not read as LOD A",
          slotlib.slot_of(f"{CAR}_int_a.m3g") == "int_a",
          slotlib.slot_of(f"{CAR}_int_a.m3g"))
    # A bare INT_A.m3g ends with "_a.m3g", so without its own entry the interior
    # would be filed as body LOD A and the real LOD_A.m3g would come out unused.
    check("nor is a bare int file, which ends like a body LOD",
          slotlib.slot_of("INT_A.m3g") == "int_a", slotlib.slot_of("INT_A.m3g"))
    check("and a bare LOD file still reads as its own LOD",
          slotlib.slot_of("A.m3g") == "A", slotlib.slot_of("A.m3g"))
    check("an unknown file is not guessed at", slotlib.slot_of("notes.txt") == "",
          slotlib.slot_of("notes.txt"))
    check("every slot has a name the game expects",
          all(slotlib.target_name(k, "x") for k in slotlib.KEYS))
    check("there are as many slots as the game has files",
          len(slotlib.KEYS) == len(slotlib.SLOTS) == 17, str(len(slotlib.KEYS)))
    pack_like = slotlib.SlotPack(export, mapping, name="mymod", kind="new",
                                 donor=CAR)
    check("a slot table validates like a pack", pack_like.validate() == [],
          str(pack_like.validate()))
    check("and reports its files", len(pack_like.files()) == len(mapping),
          str(len(pack_like.files())))
    check("and hands back the body LOD", pack_like.body() == mapping["A"])
    shutil.rmtree(export, ignore_errors=True)

    print("42 a slot table replaces files in an existing car")
    # The car that group 8 built is gone by now (group 10 removes it), so this
    # works on the shipped one and puts its body LOD back afterwards.
    slot_car = CAR
    scratch = os.path.join(ROOT, "work", "_test_slots")
    shutil.rmtree(scratch, ignore_errors=True)
    os.makedirs(scratch)
    body = os.path.join(MINI, ".depot", "vehicles", slot_car,
                        f"{slot_car}_a.m3g")
    original = os.path.join(scratch, "original.m3g")
    shutil.copyfile(body, original)
    copy = os.path.join(scratch, "LOD_A.m3g")
    shutil.copyfile(body, copy)
    with open(copy, "ab") as fh:
        fh.write(b"\0" * 8)              # a different file, same shape
    placed = editlib.install_slots(root, slot_car, {"A": copy},
                                   log=lambda m: None)
    check("the file was placed", len(placed["placed"]) == 1, str(placed))
    check("under the game's own name",
          placed["placed"][0]["file"] == f"{slot_car}_a.m3g", str(placed))
    landed = os.path.join(MINI, ".depot", "vehicles", slot_car,
                          f"{slot_car}_a.m3g")
    check("it landed on disk", os.path.isfile(landed))
    check("with the bytes we gave it",
          os.path.getsize(landed) == os.path.getsize(copy),
          f"{os.path.getsize(landed)} vs {os.path.getsize(copy)}")
    check("and the manifests agree", editlib.verify(root, slot_car) == [],
          str(editlib.verify(root, slot_car)[:2]))
    check("an empty table changes nothing",
          editlib.install_slots(root, slot_car, {},
                                log=lambda m: None)["placed"] == [])
    # a file the table does not mention is left alone
    before = os.path.getsize(os.path.join(MINI, ".depot", "vehicles", slot_car,
                                          f"{slot_car}_b.m3g"))
    editlib.install_slots(root, slot_car, {"A": original}, log=lambda m: None)
    after = os.path.getsize(os.path.join(MINI, ".depot", "vehicles", slot_car,
                                         f"{slot_car}_b.m3g"))
    check("the LODs it was not told about are untouched", before == after,
          f"{before} vs {after}")
    check("and it is clean again", editlib.verify(root, slot_car) == [],
          str(editlib.verify(root, slot_car)[:2]))
    shutil.rmtree(scratch, ignore_errors=True)

    print("43 the parts' materials resolve, and only writable ones are listed")
    lib = matlib.library(inv.depot)
    check("the library is not empty", len(lib) > 50, str(len(lib)))
    check("every entry has a livery slot",
          all(liverylib.load_slot_table(inv.depot).material_slot(n) is not None
              for n in lib[:20]))
    check("car paint is in there", "car_paint_gloss" in lib, str(lib[:5]))
    check("the map's concrete is not a car paint",
          matlib.group_of("concrete_floor") == "Other",
          matlib.group_of("concrete_floor"))
    check("paint is grouped as paint", matlib.group_of("car_paint_matte") == "Car paint",
          matlib.group_of("car_paint_matte"))
    paints_only = [n for _l, n in matlib.paint_choices(inv.depot) if n]
    check("the paint list is only paint",
          all(n.startswith("car_paint_") for n in paints_only), str(paints_only[:3]))
    rows = matlib.parts(inv.root, CAR)
    check("every mesh of the car was read", len(rows) > 20, str(len(rows)))
    check("each one resolved a material",
          all(r["material"] for r in rows if r["slot"] is not None),
          str([r for r in rows if r["slot"] is not None and not r["material"]][:2]))
    check("the body panel is painted",
          any(r["mesh"].endswith("_mm_ext") and r["material"].startswith("car_paint")
              for r in rows),
          str([(r["mesh"], r["material"]) for r in rows[:3]]))
    got = matlib.summary(inv.root, CAR)
    check("the summary counts the meshes", got["meshes"] == len(rows), str(got))

    print("43b the shared model has its own parts and page slots")
    models = [key for key, _label, _path in matlib.models(inv.root, CAR)]
    check("the car's model files are listed", "shared" in models, str(models))
    shared = matlib.parts(inv.root, CAR, model="shared")
    check("the shared model was read", len(shared) > 20, str(len(shared)))
    check("the tyres are in there",
          any(r["mesh"].endswith("_mm_tyre") for r in shared),
          str([r["mesh"] for r in shared[:4]]))
    tyre = next(r for r in shared if r["mesh"].endswith("_mm_tyre"))
    check("the tyre resolves a tyre material",
          (tyre["material"] or "").startswith(("car_tires", "car_tire")),
          str(tyre))
    check("the tyre names a page slot", tyre["texture"] == "ext_tyre", str(tyre))
    check("the body itself is not in the shared model",
          not any(r["mesh"] == "LOD_A_BODY_mm_ext" for r in shared),
          str([r["mesh"] for r in shared[:3]]))
    slots = matlib.texture_slots(inv.depot)
    check("the page slots are listed", len(slots) == 33, str(len(slots)))
    names = [name for _slot, name, _label in slots]
    check("the tyre and rotor pages are among them",
          "ext_tyre" in names and "ext_rotor" in names, str(names[:6]))
    pages = matlib.textures(inv.root, CAR)
    check("every page slot is reported", len(pages) == 33, str(len(pages)))
    check("a page knows where it comes from",
          all(p["from"] in ("this car", "common", "none") for p in pages),
          str({p["from"] for p in pages}))
    check("the body page is the car's own",
          next(p for p in pages if p["name"] == "ext_ext")["from"] == "this car",
          str(next(p for p in pages if p["name"] == "ext_ext")))
    check("the rotor page comes from common",
          next(p for p in pages if p["name"] == "ext_rotor")["from"] == "common",
          str(next(p for p in pages if p["name"] == "ext_rotor")))
    check("a page lists the meshes that read it",
          next(p for p in pages if p["name"] == "ext_tyre")["meshes"] != [],
          str(next(p for p in pages if p["name"] == "ext_tyre")))
    check("the shared model lists the same slots",
          matlib.textures_summary(inv.root, CAR)["slots"] == 33,
          str(matlib.textures_summary(inv.root, CAR)))

    print("44 one paint scheme can have its own finish, and its own atlas")
    one = slot_car
    if depotlib.scan(root).get(one) is None:
        print("  FAIL  there is no car to paint")
    else:
        got = editlib.set_paint_finish(root, one,
                                       per_paint={0: "car_paint_matte",
                                                  1: "car_paint_gloss"})
        first_scheme = liverylib.load_car(
            depotlib.scan(root).depot, one).paints[0].name()
        check("one scheme got its own finish",
              got.get("per_paint", {}).get(first_scheme) == "car_paint_matte",
              str(got.get("per_paint")))
        # ``inv`` was repointed at the real install by an earlier group; this
        # car only exists in the miniature one
        local44 = depotlib.scan(root)
        table = liverylib.load_slot_table(local44.depot)
        _L2 = liverylib.load_car(local44.depot, one)
        body_slot = table.part_slot("LOD_A_BODY_mm_ext")
        first = _L2.paints[0].material_of(body_slot)
        second = _L2.paints[1].material_of(body_slot)
        check("and the file agrees",
              table.name(first) == "car_paint_matte", table.name(first))
        check("while the other scheme kept gloss",
              table.name(second) == "car_paint_gloss", table.name(second))
        check("the livery still reads back",
              editlib.verify(root, one) == [], str(editlib.verify(root, one)[:2]))
        check("an unknown finish is refused",
              _raises(editlib.EditError, editlib.set_paint_finish, root, one,
                      per_paint={0: "concrete_floor"}))
        atlas_src = os.path.join(MINI, ".depot", "vehicles", CAR, "livery",
                                 f"{CAR}_ext_passionate_pink.ptc.pvr.z")
        if os.path.isfile(atlas_src):
            got = editlib.set_livery_texture(root, one, source=atlas_src, paint=0)
            check("the atlas was copied in", os.path.isfile(got["file"]), str(got))
            check("under the scheme's own stem",
                  first_scheme.rsplit(".", 1)[0] in got["rel"], got["rel"])
            check("and the scheme points at it",
                  len(got["changed"]) == 1, str(got["changed"]))
            check("the livery still reads back after the swap",
                  editlib.verify(root, one) == [],
                  str(editlib.verify(root, one)[:2]))
            check("a file that is not a texture is refused",
                  _raises(editlib.EditError, editlib.set_livery_texture, root, one,
                          source=os.path.join(MINI, ".depot", "vehicles", CAR,
                                              f"{CAR}.points")))

    print("45 the Paints and Parts panes show a car and write through the same helpers")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        from PySide6.QtWidgets import QApplication
        from rrmod.ui import editing as editingui
        from rrmod.ui import materialui, paintui

        app = QApplication.instance() or QApplication([])
        scan = depotlib.scan(root)
        editor = editingui.Editor(root)
        editor.ensure()
        schemes = paintui.PaintsPane()
        schemes.load(editor, CAR)
        check("the paint pane lists the schemes", len(schemes._schemes) == 6,
              str(len(schemes._schemes)))
        check("each row names its finish",
              all(r["finish"] for r in schemes._schemes),
              str([r["finish"] for r in schemes._schemes][:3]))
        check("each row names its atlas",
              all(r["atlas"] for r in schemes._schemes),
              str([r["atlas"] for r in schemes._schemes][:2]))
        check("the finish list is the game's own",
              schemes.finish.count() > 10, str(schemes.finish.count()))
        schemes.table.selectRow(0)
        schemes._picked()
        check("picking a row shows its finish",
              schemes.finish.currentText() not in ("", paintui.FINISH_NONE),
              schemes.finish.currentText())
        schemes._dirty_finishes["1"] = "car_paint_matte"
        check("a pending finish is remembered",
              schemes.pending()["finishes"] == {"1": "car_paint_matte"},
              str(schemes.pending()))
        schemes._reset()
        check("dropping the edits empties them",
              schemes.pending() == {"colours": {}, "finishes": {},
                                    "pictures": {}}, str(schemes.pending()))

        # the three-dot column, and a picture that is converted on Save
        check("the paint table has a column of three-dot buttons",
              schemes.table.columnCount() == 5, str(schemes.table.columnCount()))
        check("and every row has one",
              all(schemes.table.cellWidget(r, 4) is not None
                  for r in range(schemes.table.rowCount())),
              str([r for r in range(schemes.table.rowCount())
                   if schemes.table.cellWidget(r, 4) is None]))
        check("a scheme's pictures are read off its own table",
              paintui.effective_pictures(depotlib.scan(root).depot, CAR, 0)
              .get("body", "").startswith("livery/"),
              str(paintui.effective_pictures(depotlib.scan(root).depot, CAR, 0)
                  .get("body")))
        schemes._dirty_pictures["1"] = {"body": _png_fixture()}
        check("a pending picture is remembered",
              "1" in schemes.pending()["pictures"], str(schemes.pending()))

        class _Box:
            Yes, No = 1, 2

            @staticmethod
            def question(*a, **k):
                return 1

            @staticmethod
            def information(*a, **k):
                return None

            @staticmethod
            def critical(*a, **k):
                raise AssertionError(a[2] if len(a) > 2 else "critical")

        real_box = paintui.QMessageBox
        paintui.QMessageBox = _Box
        try:
            schemes.save()
        finally:
            paintui.QMessageBox = real_box
        check("saving writes the picture and clears the queue",
              not any(schemes.pending().values()), str(schemes.pending()))
        wrote = [f for f in os.listdir(os.path.join(MINI, ".depot", "vehicles",
                                                    CAR, "livery"))
                 if f.endswith(".dxt.dds.z") and "_ext_" in f]
        check("the scheme's body is in the livery folder", bool(wrote), str(wrote))
        after_save = liverylib.load_car(depotlib.scan(root).depot, CAR)
        named = after_save.paints[1].texture_of(1932) or b""
        check("and the table points at it",
              named.decode("utf-8", "replace").startswith("livery/"),
              str(named))

        parts = materialui.PartsPane()
        parts.load(editor, CAR)
        check("the parts pane lists the meshes", parts.table.rowCount() == 68,
              str(parts.table.rowCount()))
        check("every part resolves a material",
              all(r["material"] for r in parts._rows), "some part had none")
        check("the material list only holds writable ones",
              parts.material.count() > 50, str(parts.material.count()))
        check("no material from the world is offered",
              not any("concrete" in (parts.material.itemText(i) or "").lower()
                      for i in range(parts.material.count())), "concrete offered")
        body = next(r for r in parts._rows if r["mesh"].endswith("_mm_ext"))
        check("the body resolves through the paint", body["material"].startswith(
            "car_paint"), body["material"])
        parts.table.selectRow(0)
        check("a row can be picked",
              (parts._picked_mesh() or {}).get("mesh") is not None, "nothing picked")
        # the model dropdown is how the wheels and tyres are reachable at all
        check("the pane offers every model the car has", parts.lod.count() == 12,
              str([parts.lod.itemData(i) for i in range(parts.lod.count())]))
        index = parts.lod.findData("shared")
        check("the shared model can be chosen", index >= 0, str(index))
        parts.lod.setCurrentIndex(index)
        check("the shared model's parts are listed", parts.table.rowCount() > 20,
              str(parts.table.rowCount()))
        check("the tyre is one of them",
              any(r["mesh"].endswith("_mm_tyre") for r in parts._rows),
              str([r["mesh"] for r in parts._rows[:4]]))
        check("the page table lists every slot", parts.tex_table.rowCount() == 33,
              str(parts.tex_table.rowCount()))
        parts.tex_table.selectRow(0)
        check("a page can be picked",
              (parts._picked_texture() or {}).get("slot") is not None,
              "nothing picked")
        check("a page knows its own picture", parts.tex_btn.isEnabled(),
              "the picture button is off")

        schemes.load(editor, "")
        parts.load(editor, "")
        check("an empty selection clears the paint pane",
              schemes.table.rowCount() == 0, str(schemes.table.rowCount()))
        check("an empty selection clears the parts pane",
              parts.table.rowCount() == 0, str(parts.table.rowCount()))
    except ImportError as exc:
        check("the Qt panes can be imported", False, str(exc))

    print("46 a page of its own can be given to a car")
    paint_car = "2012_lexus_lfa"
    atlas_src = ""
    for folder in ("livery", ""):
        base = os.path.join(MINI, ".depot", "vehicles", paint_car, folder)
        if not os.path.isdir(base):
            continue
        for f in sorted(os.listdir(base)):
            if f.endswith((".dxt.dds.z", ".etc.dds.z", ".atc.dds.z",
                           ".ptc.pvr.z")):
                atlas_src = os.path.join(base, f)
                break
        if atlas_src:
            break
    if not atlas_src:
        print("  FAIL  there is no texture to give a page")
    else:
        before = set(os.listdir(os.path.join(MINI, ".depot", "vehicles",
                                             paint_car)))
        got = editlib.set_texture_slot(root, paint_car, 4, atlas_src)
        check("the page was pointed at a picture", got.get("slot") == 4, str(got))
        check("the page it names is the tyre page",
              got.get("slot_name") == "ext_tyre", str(got.get("slot_name")))
        check("it landed under the page's own name",
              "ext_tyre" in os.path.basename(got["file"]),
              os.path.basename(got["file"]))
        check("the file is there", os.path.isfile(got["file"]), got["file"])
        after = liverylib.load_car(depotlib.scan(root).depot, paint_car)
        check("the car now names that page", after.texture_of(4) is not None,
              str(after.texture_of(4)))
        check("the manifest was updated", editlib.verify(root, paint_car) == [],
              str(editlib.verify(root, paint_car)[:2]))
        now = set(os.listdir(os.path.join(MINI, ".depot", "vehicles",
                                          paint_car)))
        check("the car's other files are untouched", before <= now,
              str(sorted(before - now)[:3]))
        try:
            editlib.set_texture_slot(root, paint_car, 4, __file__)
            check("a file that is not a texture is refused", False, "accepted")
        except editlib.EditError as exc:
            check("a file that is not a texture is refused",
                  "not a game texture" in str(exc), str(exc))

    print("47 the build dialog can write the aero clips")
    try:
        from PySide6.QtWidgets import QApplication
        from rrmod.ui import buildui

        app = QApplication.instance() or QApplication([])
        # the animated cars are not in the mini install, so read the real one
        real = depotlib.scan(install)
        dlg = buildui.BuildDialog(real)
        dlg.branch_new.setChecked(True)
        dlg._branch_changed()
        index = dlg.donor.findText(ANIM_CAR)
        check("the animated donor is offered", index >= 0, str(index))
        dlg.donor.setCurrentIndex(index)
        check("the donor's clips are shown", dlg.clips_table.rowCount() > 3,
              str(dlg.clips_table.rowCount()))
        check("the clip table names them",
              all(name for name, _s, _e in dlg._clip_rows()),
              str(dlg._clip_rows()[:2]))
        check("the animation's length was read", dlg.clip_end.value() > 100,
              str(dlg.clip_end.value()))
        check("the clips come back as Clip objects",
              len(dlg.clip_list()) == dlg.clips_table.rowCount(),
              str(len(dlg.clip_list())))
        check("an empty table means keep the donor's file",
              buildui.BuildDialog(real).clip_list() == [], "not empty")
        dlg._default_clips()
        rows = dlg._clip_rows()
        check("the default set is rest, up and down",
              [r[0] for r in rows] == ["wing_initial", "wing_up", "wing_down"],
              str([r[0] for r in rows]))
        check("the default set spans the animation",
              rows[1][2] == dlg.clip_end.value() > 0,
              f"{rows[1]} vs {dlg.clip_end.value()}")
        check("the dialog hands the clips to the builder",
              len(dlg.result_info()["clips"]) == 3,
              str(dlg.result_info()["clips"]))
        aero_kinds = [dlg.aero.itemText(i) for i in range(dlg.aero.count())]
        check("every behaviour is offered", len(aero_kinds) == 6, str(aero_kinds))
        dlg.aero.setCurrentIndex(3)
        check("a speed-based behaviour asks for its two speeds",
              dlg.aero_high.isEnabled() and dlg._aero_params() == (180.0, 170.0),
              str(dlg._aero_params()))
        dlg.aero.setCurrentIndex(5)
        check("turning it off asks for nothing",
              dlg._aero_mode() == 2 and dlg._aero_params() == (),
              str(dlg._aero_params()))
        dlg.close()

        print("47b modifying a car can also change its behaviour")
        dlg = buildui.BuildDialog(real)
        dlg.branch_modify.setChecked(True)
        dlg._branch_changed()
        check("the aero behaviour is offered when modifying",
              dlg.aero.isEnabled() and dlg.aero.count() == 6,
              str(dlg.aero.isEnabled()))
        check("the clips are editable when modifying",
              dlg.clips_table.isEnabled() and dlg.add_clip_btn.isEnabled(),
              str(dlg.clips_table.isEnabled()))
        car_index = dlg.car.findText(ANIM_CAR)
        check("the animated car is offered", car_index >= 0, str(car_index))
        dlg.car.setCurrentIndex(car_index)
        check("its clips are shown in the modify branch",
              dlg.clips_table.rowCount() > 3, str(dlg.clips_table.rowCount()))
        check("the figures start switched off",
              not dlg.stats.isEnabled() and dlg.stat_changes() == {},
              str(dlg.stat_changes()))
        check("the figure box is offered", dlg.tune_box.isEnabled(),
              "disabled")
        dlg.tune_box.setChecked(True)
        check("ticking the box makes the figures editable", dlg.stats.isEnabled())
        dlg.stats.setItem(0, 2, buildui.QTableWidgetItem("1234"))
        check("a typed figure is picked up",
              dlg.stat_changes() == {"weight_lb": "1234"},
              str(dlg.stat_changes()))
        dlg.tune_box.setChecked(False)
        check("unticking it drops the figures again",
              dlg.stat_changes() == {}, str(dlg.stat_changes()))
        dlg.branch_new.setChecked(True)
        dlg._branch_changed()
        check("a new car always takes its own figures",
              dlg.stats.isEnabled() and not dlg.tune_box.isEnabled(),
              f"{dlg.stats.isEnabled()} {dlg.tune_box.isEnabled()}")
        dlg.close()
    except ImportError as exc:
        check("the build dialog can be imported", False, str(exc))

    print("48 the starting PR can be set, and only the starting one")
    pr_car = "2012_lexus_lfa"
    got = statlib.read(root, pr_car)["fields"]
    check("the PR is readable", got.get("pr", {}).get("value") is not None,
          str(got.get("pr")))
    check("the PR is offered as writable", got["pr"]["writable"] is True,
          str(got["pr"]))
    check("the fully upgraded PR is offered as an override as well",
          got["pr_max"]["writable"] is True, str(got["pr_max"]))
    before_pr = got["pr"]["value"]
    before_max = got["pr_max"]["value"]
    made = statlib.write(root, pr_car, {"pr": 55.5})
    check("writing the PR reports the change", made["changed"] == ["pr"],
          str(made["changed"]))
    after = statlib.read(root, pr_car)["fields"]
    check("the PR reads back as written",
          abs(after["pr"]["value"] - 55.5) < 1e-3, str(after["pr"]["value"]))
    check("the fully upgraded PR was left alone",
          abs(after["pr_max"]["value"] - before_max) < 1e-4,
          f"{before_max} -> {after['pr_max']['value']}")
    check("the rest of the spec survived",
          after["weight_lb"]["value"] == 3360 and after["car_class"]["value"]
          == "Supercar",
          f"{after['weight_lb']['value']} {after['car_class']['value']}")
    check("an out of range PR is refused",
          bool(statlib.validate({"pr": 500})), str(statlib.validate({"pr": 500})))
    # a car with no display-name key has no PR to find, and must say so rather
    # than write four bytes somewhere arbitrary.  33 shipped specs are like
    # this, so the case is made here by taking the name key away.
    nameless = speclib.load_spec(os.path.join(root, ".depot"),
                                 "88_2012_lexus_lfa")
    for token in nameless.tokens:
        if token[0] == "s" and token[3].startswith(b"CAR_NAME_"):
            token[3] = b"NOT_A_NAME_KEY"
    check("a car with no name key reports no PR",
          nameless.stats().get("pr") is None, str(nameless.stats().get("pr")))
    check("and writing one is refused rather than guessed",
          nameless.set_pr(80.0) is False, "it wrote something")
    statlib.write(root, pr_car, {"pr": before_pr})
    check("putting the old PR back works",
          abs(statlib.read(root, pr_car)["fields"]["pr"]["value"] - before_pr)
          < 1e-3, "")

    print("49 the engine figures are written by byte offset")
    eng_car = "2012_lexus_lfa"
    eng = statlib.read(root, eng_car)["fields"]
    check("the engine block is readable", eng.get("power_hp", {}).get("value"),
          str(eng.get("power_hp")))
    check("the engine figures are offered as writable",
          eng["power_hp"]["writable"] and eng["redline"]["writable"],
          f"{eng['power_hp']['writable']} {eng['redline']['writable']}")
    check("the gear count is writable too", eng["gears"]["writable"] is True,
          str(eng["gears"]))
    old_hp = eng["power_hp"]["value"]
    old_red = eng["redline"]["value"]
    made = statlib.write(root, eng_car, {"power_hp": 610.0, "redline": 9100})
    check("both engine figures were written",
          sorted(made["changed"]) == ["power_hp", "redline"],
          str(made["changed"]))
    after = statlib.read(root, eng_car)["fields"]
    check("the power reads back", abs(after["power_hp"]["value"] - 610.0) < 1e-3,
          str(after["power_hp"]["value"]))
    check("the redline reads back", after["redline"]["value"] == 9100,
          str(after["redline"]["value"]))
    check("the figures around them were not disturbed",
          abs(after["power_rpm"]["value"] - eng["power_rpm"]["value"]) < 1e-3
          and after["gears"]["value"] == eng["gears"]["value"],
          f"{after['power_rpm']['value']} {after['gears']['value']}")
    check("the rest of the spec survived an engine write",
          after["weight_lb"]["value"] == 3360
          and after["car_class"]["value"] == "Supercar",
          f"{after['weight_lb']['value']} {after['car_class']['value']}")
    check("a gear count a gearbox could have is accepted",
          statlib.validate({"gears": 5}) == [],
          str(statlib.validate({"gears": 5})))
    check("one it could not is refused",
          bool(statlib.validate({"gears": 40})),
          str(statlib.validate({"gears": 40})))
    check("and a fractional one is refused in its own words",
          any("whole number" in p for p in statlib.validate({"gears": 3.5})),
          str(statlib.validate({"gears": 3.5})))
    check("an impossible redline is refused",
          bool(statlib.validate({"redline": 40000})),
          str(statlib.validate({"redline": 40000})))
    statlib.write(root, eng_car, {"power_hp": old_hp, "redline": old_red})
    check("the old engine figures go back",
          abs(statlib.read(root, eng_car)["fields"]["power_hp"]["value"] - old_hp)
          < 1e-3, "")

    print("50 the engine sound is three strings, and it can be pointed elsewhere")
    # the families are folders under audio/Vehicles; the mini install carries two
    # empty ones so this group does not depend on the real install
    for family in ("v10_04", "ttv8_01"):
        os.makedirs(os.path.join(root, ".depot", "audio", "Vehicles", family),
                    exist_ok=True)
    snd = statlib.sound(root, eng_car)
    check("the sound is readable", snd["accel"].startswith("audio/Vehicles/"),
          snd["accel"])
    check("the family is picked out of the path", bool(snd["family"]),
          snd["family"])
    check("the families on disk are listed", len(snd["families"]) >= 2,
          str(len(snd["families"])))
    check("the sound is offered as writable", snd["writable"] is True,
          str(snd["writable"]))
    old_family = snd["family"]
    other = [f for f in snd["families"] if f != old_family][0]
    made = statlib.set_sound(root, eng_car, other)
    check("pointing it at another family reports the change",
          made["changed"] is True, str(made["changed"]))
    check("the new family reads back", made["after"]["family"] == other,
          made["after"]["family"])
    check("the idle follows the same family",
          made["after"]["idle"].startswith(other), made["after"]["idle"])
    check("the car keeps its own id in the file names",
          f"id_{statlib.read(root, eng_car)['fields']['id']['value']}"
          if "id" in statlib.read(root, eng_car)["fields"]
          else f"id_88_accel" in made["after"]["accel"],
          made["after"]["accel"])
    check("the rest of the spec survived a sound write",
          statlib.read(root, eng_car)["fields"]["weight_lb"]["value"] == 3360, "")
    statlib.set_sound(root, eng_car, old_family)
    check("the old family goes back",
          statlib.sound(root, eng_car)["family"] == old_family, "")

    # ---- 51. a page of a car's own picture, out and back ------------------
    print("\n--- a texture page, saved out and put back ---")
    page_car = CAR
    pages = texpages.car_pages(root, page_car)
    check("the car names the pages it loads", len(pages) >= 20, str(len(pages)))
    found = [p for p in pages if p.get("onDisk")]
    check("some of them are on disk", len(found) >= 5, str(len(found)))
    check("every page has a slot", all(isinstance(p["slot"], int) for p in pages),
          "")
    check("a page that is missing says so rather than raising",
          any(not p["onDisk"] for p in pages), "")
    can_write = [p for p in found if p["writable"]]
    check("the DXT copies can be written", len(can_write) >= 3, str(len(can_write)))
    check("the writable ones are all DXT",
          all("dxt" in (p["onDisk"] or "").lower() for p in can_write), "")

    page = max(can_write, key=lambda r: len(r.get("meshes") or []))
    info = texpages.describe(root, page["path"], car=page_car)
    check("a page describes itself", info["width"] > 0 and info["height"] > 0,
          f"{info['width']}x{info['height']}")
    check("the size is a power of two",
          info["width"] & (info["width"] - 1) == 0, str(info["width"]))
    check("a page knows how many channels it carries",
          info["channels"] in (3, 4), str(info["channels"]))
    check("the readers are named", len(page.get("meshes") or []) >= 1,
          str(len(page.get("meshes") or [])))
    check("asking which meshes read it gives the same list",
          texpages.meshes_for(root, page_car, page["onDisk"])
          == list(page["meshes"]), "")

    shot = os.path.join(ROOT, "work", "_test_page.png")
    got = texpages.export(root, page["path"], shot, car=page_car)
    check("the page comes out as a picture", os.path.isfile(shot),
          str(os.path.getsize(shot)) if os.path.isfile(shot) else "missing")
    check("the picture is the size the page was",
          (got["width"], got["height"]) == (info["width"], info["height"]),
          f"{got['width']}x{got['height']}")

    before = os.path.getsize(texpages.page_path(root, page["path"], car=page_car))
    back = texpages.replace(root, page["path"], shot, car=page_car)
    check("the picture goes back into the page", back["after"] > 1000,
          str(back["after"]))
    check("the page still decodes afterwards",
          texpages.describe(root, page["path"], car=page_car)["width"]
          == info["width"], "")
    check("what was there was kept", before == back["before"], str(before))

    # a picture of the wrong size is refused rather than rescaled
    wrong = os.path.join(ROOT, "work", "_test_wrong.png")
    thumbs.write_png_bytes(wrong, 8, 8, 4, bytes([200, 40, 90, 255]) * 64)
    try:
        texpages.replace(root, page["path"], wrong, car=page_car)
    except texpages.TextureError as exc:
        check("a picture of the wrong size is refused",
              "resize it first" in str(exc), str(exc)[:60])
    else:
        check("a picture of the wrong size is refused", False, "it was accepted")

    # a family this cannot write says so instead of half doing it
    etc_page = [p for p in pages if (p.get("family") or "") in ("etc", "atc", "pvrtc")]
    if etc_page:
        row = etc_page[0]
        check("a page from another family is not offered as writable",
              row["writable"] is False, row["family"])
    else:
        check("a page from another family is not offered as writable", True,
              "this install unpacks only DXT")

    # The encoder can write ETC now, so what has to be refused is PVRTC: its
    # blocks interpolate their colours across block edges.
    try:
        texpages.build(shot, suffix=".ptc.pvr.z")
    except Exception as exc:                     # noqa: BLE001
        check("the encoder refuses to write a PVRTC page",
              "interpolate" in str(exc), str(exc)[:60])
    else:
        check("the encoder refuses to write a PVRTC page", False, "it accepted one")
    made = texpages.build(shot, suffix=".etc.dds.z")
    check("but it will write an ETC page", made["suffix"] == ".etc.dds.z",
          made["suffix"])
    if os.path.isfile(shot):
        os.remove(shot)
    if os.path.isfile(wrong):
        os.remove(wrong)


    # ---- the materials table, and who wears it --------------------------
    print("\n--- every material, and who wears it ---")
    # the usage counts need every car's livery file, and the scratch install
    # only carries one, so those numbers come from the real install.
    try:
        cat = matman.catalogue(install, with_usage=True)
    except matman.ManagerError as exc:
        check("materials.bin reads", False, str(exc)[:80])
        cat = None
    if cat:
        check("materials.bin reads", cat["total"] > 200, cat["total"])
        check("every row carries an application",
              all(r["application"] for r in cat["materials"]),
              sum(1 for r in cat["materials"] if not r["application"]))
        check("some of them can be pointed at by a car",
              cat["writable"] > 50, cat["writable"])
        check("the rest cannot", cat["writable"] < cat["total"], cat["total"])
        # 26 of the 72 paint rows (the candy colours and gold, plus their
        # bumper twins) have no slot in the string table, so a livery row
        # cannot point at them even though the customiser offers them.
        slotless = [r["name"] for r in cat["materials"]
                    if r["paint"] and not r["writable"]]
        check("some paints cannot be pointed at, and they are named",
              len(slotless) < 40 and all(n.startswith("car_") for n in slotless),
              slotless[:3])
        check("most of the table is in use", cat["used"] > 50, cat["used"])
        check("a name without a slot has no slot",
              all((r["slot"] is None) != bool(r["writable"])
                  for r in cat["materials"]), "mismatch")
        named = [r for r in cat["materials"] if r["writable"]]
        check("every writable row names a slot",
              all(isinstance(r["slot"], int) for r in named), "not all int")
        check("the usage counts are plain numbers",
              all(isinstance(r["cars"], int) and r["cars"] >= 0
                  for r in cat["materials"]), "bad count")

        one = matman.details(install, "car_paint_matte")
        check("a paint says what it is", one["application"] == "appCarPaint",
              one["application"])
        check("a paint has a slot", one["slot"] == 23, one["slot"])
        check("a paint carries the flags that make it matte",
              "SPEC_MASK_TEXTURE" in one["flags"], one["flags"])
        check("a paint knows its shader", bool(one["shader"]), one["shader"])
        check("a paint has a specular power", (one["specularPower"] or 0) > 0,
              one["specularPower"])
        check("a paint has a roughness", 0.0 < (one["roughness"] or 0) <= 1.0,
              one["roughness"])
        check("a paint names the ramps it reads",
              len(one["textures"]) >= 1, one["textures"])
        try:
            matman.details(install, "no_such_material_here")
        except matman.ManagerError as exc:
            check("an unknown material is refused", "no material" in str(exc),
                  str(exc)[:60])
        else:
            check("an unknown material is refused", False, "it was accepted")
        check("the page can list what it has",
              matman.summary(install)["materials"] == cat["total"], "mismatch")
        check("the page's own selftest is quiet",
              matman.selftest(install) == 0, "selftest complained")
    print("53 the upgrade route is one string, and the tree lives elsewhere")
    # The trees are read from the real install: the mini one carries the table
    # too, but only one car, so the "who points where" counts are only true of
    # the full depot.
    try:
        tree = uplib.load(install)
    except Exception as exc:                      # noqa: BLE001
        check("the upgrade table reads", False, str(exc)[:80])
        tree = None
    if tree:
        check("the upgrade table reads", len(tree) > 100, len(tree))
        packs = tree.packs()
        check("ten of the routes are templates", len(packs) == 10,
              str(len(packs)))
        check("the templates are the ten the game ships",
              [r.name for r in packs] == [
                  "PROD_01", "PROD_02", "PROD_03", "PROD_04",
                  "SUPER_01", "SUPER_02", "SUPER_03",
                  "RACE_01", "RACE_02", "RACE_03"],
              [r.name for r in packs])
        check("every route names the areas it upgrades",
              all(len(r.areas) >= 3 and r.areas[0] == "Engine"
                  for r in tree.routes), "some route has no areas")
        check("every route has steps in it",
              all(len(r.steps) > 0 for r in tree.routes), "a route is empty")
        check("the reader's own selftest is quiet", uplib.selftest(install) == 0,
              "selftest complained")

    # the key in a spec is a byte offset away from the gear count, not a token
    # index, because the token stream has no per-car anchors past the engine.
    sp = speclib.load_spec(os.path.join(install, ".depot"),
                           "57_1995_mclaren_f1")
    check("a spec knows which tree it follows",
          sp.upgrade_route() == "SUPER_02", sp.upgrade_route())
    check("that tree really exists in the table",
          bool(tree) and sp.upgrade_route() in tree, "not in the table")

    # writing it needs the table to validate against, so this half runs on the
    # mini install, which now carries the table as well.
    got = statlib.route(root, "2012_lexus_lfa")
    check("the route is readable through the manager",
          got["key"] == "LEXUS_LFA_2012", got["key"])
    check("the routes are offered as a list", len(got["routes"]) > 100,
          str(len(got["routes"])))
    check("the templates come first",
          got["routes"][0]["template"] is True, str(got["routes"][0]))
    check("the route is offered as writable", got["writable"] is True,
          str(got["writable"]))
    check("the tree behind the key comes with it",
          len(got["route"]["steps"]) > 0, str(len(got["route"]["steps"])))
    made = statlib.set_route(root, "2012_lexus_lfa", "PROD_02")
    check("pointing the car at a template reports the change",
          made["changed"] is True, str(made["changed"]))
    check("the new route reads back",
          statlib.route(root, "2012_lexus_lfa")["key"] == "PROD_02",
          statlib.route(root, "2012_lexus_lfa")["key"])
    after = statlib.read(root, "2012_lexus_lfa")["fields"]
    check("the rest of the spec survived a route write",
          after["weight_lb"]["value"] == 3360
          and after["car_class"]["value"] == "Supercar",
          f"{after['weight_lb']['value']} {after['car_class']['value']}")
    check("the route is a name, so it is not one of the number fields",
          "route" not in statlib.LIMITS, "it is a number field")
    try:
        statlib.set_route(root, "2012_lexus_lfa", "NO_SUCH_TREE")
    except statlib.StatsError as exc:
        check("an unknown route is refused", "no upgrade route" in str(exc),
              str(exc)[:60])
    else:
        check("an unknown route is refused", False, "it was accepted")
    statlib.set_route(root, "2012_lexus_lfa", got["key"])
    check("the old route goes back",
          statlib.route(root, "2012_lexus_lfa")["key"] == got["key"], "")

    print("54 a new car can be given a series to race in")
    # The build dialog's last section: a car with no series is a car the game
    # never offers, so placing it is part of building it.  The work happens on a
    # copy of the career so the mini install is left as the earlier groups made
    # it.
    check("a title comes from the folder name",
          serieslib.title_from("2012_lexus_lfa_copy") == "Lexus Lfa Copy Cup",
          serieslib.title_from("2012_lexus_lfa_copy"))
    check("a name with no year still gets a title",
          serieslib.title_from("my_car") == "My Car Cup",
          serieslib.title_from("my_car"))
    check("an empty name still gets a title",
          serieslib.title_from("") == "New Cup", serieslib.title_from(""))

    room = os.path.join(ROOT, "work", "rrmod_test_career")
    shutil.rmtree(room, ignore_errors=True)
    os.makedirs(os.path.join(room, ".depot", "data"), exist_ok=True)
    for leaf in serieslib.career_leaves():
        src = os.path.join(MINI, ".depot", *leaf.split("/"))
        dst = os.path.join(room, ".depot", *leaf.split("/"))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if os.path.isfile(src):
            shutil.copyfile(src, dst)
    before = serieslib.load(room)
    before_ids = {x.id for x in before.series}
    template = serieslib.templates(before)[0]["id"]
    placed = serieslib.place(room, template=template, title="Placed Cup",
                             cars=[611], group=serieslib.DEFAULT_GROUP,
                             log=lambda m: None)
    made = placed["made"]
    check("a series is made for the car", made["id"] not in before_ids,
          f"id {made['id']}")
    check("it is placed in the group that was asked for",
          made["group"].endswith(serieslib.DEFAULT_GROUP), made["group"])
    check("the car id is the one on the grid",
          made["cars"] == [611], str(made["cars"]))
    check("it copied the template's races when given none",
          made["events"] > 0, str(made["events"]))
    check("it writes the career file back where it read it",
          os.path.isfile(os.path.join(room, ".depot", "data",
                                      "events.dat.nct")),
          "no career file")
    after = serieslib.load(room)
    check("the series is in the file that was written",
          after.series_by_id(made["id"]) is not None, "not found")
    check("the rest of the career survived",
          len(after.series) == len(before.series) + 1,
          f"{len(before.series)} -> {len(after.series)}")
    check("its title is readable in the menu",
          serieslib.load_texts(room).get(made["key"]) == "Placed Cup",
          serieslib.load_texts(room).get(made["key"]))
    check("it got a description rather than a blank panel",
          bool(serieslib.load_texts(room).get(after.series_by_id(made["id"])
                                             .desc_key)),
          "no description")
    check("the career file still round trips",
          careerlib.parse(after.to_bytes()).to_bytes() == after.to_bytes(),
          "not byte for byte")
    # An empty event list is not an error - it means "copy the template's races",
    # which is what the dialog leaves alone by default.
    copied = serieslib.place(room, template=template, title="Copied Cup",
                             cars=[611], group=serieslib.DEFAULT_GROUP,
                             log=lambda m: None)["made"]
    check("an empty event list copies the template instead of failing",
          copied["events"] > 0, str(copied["events"]))
    try:
        serieslib.place(room, template=999999, title="Nowhere Cup", cars=[611],
                        log=lambda m: None)
    except serieslib.SeriesError as exc:
        check("a template that does not exist is refused", "no series" in str(exc),
              str(exc)[:80])
    else:
        check("a template that does not exist is refused", False,
              "it was accepted")
    shutil.rmtree(room, ignore_errors=True)

    print("55 the spec ends with two words, a rule and two prices")
    # The tail sits after the engine block and the two variable-length strings
    # that follow it, so it is reached by walking the run rather than by token
    # index.  The whole structure was checked against all 540 shipped cars when
    # it was found; what is checked here is that the reader and the writers agree
    # with it and with each other.
    sp = speclib.load_spec(os.path.join(install, ".depot"),
                           "88_2012_lexus_lfa")
    got = sp.tail()
    check("a spec says what its aspiration is", got["aspiration"] == "Nat",
          got["aspiration"])
    check("a spec says what its layout is", got["layout"] == "F", got["layout"])
    check("a spec carries an unlock rule, empty for a car with none",
          got["unlock"] == "", repr(got["unlock"]))
    check("a spec carries both prices", got["cash"] == 402700
          and got["gold"] == 130, f"{got['cash']} {got['gold']}")
    check("the aspiration and the layout are on the stats sheet too",
          sp.stats().get("aspiration") == "Nat"
          and sp.stats().get("layout") == "F", str(sp.stats().get("layout")))
    # The eight R3 specials carry a file name where every other car carries an
    # empty string; assuming the field away puts their money 20 bytes late.
    r3 = speclib.load_spec(os.path.join(install, ".depot"),
                           "252_2017_jaguar_cx75_r3").tail()
    check("a car with an extra string has it read out",
          r3["extra"] == "r3_spec_logo.xml", r3["extra"])
    check("and its money is still found past it",
          r3["cash"] == 2500000 and r3["gold"] == 900,
          f"{r3['cash']} {r3['gold']}")
    # The two words are found by the engine reader, so an unknown one would hide
    # the engine from everything in the file - hence the closed lists.
    check("the aspirations offered are the ones the game knows",
          statlib.aspirations() == ("Nat", "Turbo", "Super", "None", "Electric",
                                    "Hybrid"), str(statlib.aspirations()))
    check("the layouts offered are the ones the game knows",
          statlib.layouts() == ("F", "M", "R", "FM"), str(statlib.layouts()))

    tail = statlib.tail(root, CAR)
    check("the manager reads the tail of a car", tail["cash"] == 402700,
          str(tail["cash"]))
    check("the tail is offered as writable", tail["writable"] is True,
          str(tail["writable"]))
    check("the reader carries the lists the dialog needs",
          "Turbo" in tail["aspirations"] and "FM" in tail["layouts"],
          str(len(tail["aspirations"])))

    # writing all five at once, then reading each one back
    made = statlib.set_tail(root, CAR, aspiration="Turbo", layout="M",
                            unlock="NOTLOCKED", cash=500, gold=200)
    check("writing the tail reports every field that moved",
          set(made["changed"]) == {"aspiration", "layout", "unlock", "price"},
          str(made["changed"]))
    back = statlib.tail(root, CAR)
    check("the aspiration reads back", back["aspiration"] == "Turbo",
          back["aspiration"])
    check("the layout reads back", back["layout"] == "M", back["layout"])
    check("the unlock rule reads back", back["unlock"] == "NOTLOCKED",
          back["unlock"])
    check("both prices read back", (back["cash"], back["gold"]) == (500, 200),
          f"{back['cash']} {back['gold']}")
    check("the rest of the spec survived the tail write",
          statlib.read(root, CAR)["fields"]["weight_lb"]["value"] == 3360,
          str(statlib.read(root, CAR)["fields"]["weight_lb"]["value"]))
    check("the engine block survived the tail write",
          statlib.read(root, CAR)["fields"]["power_hp"]["value"] == 552,
          str(statlib.read(root, CAR)["fields"]["power_hp"]["value"]))
    check("the upgrade route survived the tail write",
          statlib.route(root, CAR)["key"] == "LEXUS_LFA_2012",
          statlib.route(root, CAR)["key"])

    # writing the same values again changes nothing, which is what lets the
    # dialog hand back every control it shows rather than only the edited ones
    same = statlib.set_tail(root, CAR, aspiration="Turbo", layout="M",
                            unlock="NOTLOCKED", cash=500, gold=200)
    check("writing the values that are already there changes nothing",
          same["changed"] == [], str(same["changed"]))

    # None means "leave it alone", which is how the dialog says "untouched"
    half = statlib.set_tail(root, CAR, cash=750)
    check("one field at a time leaves the others alone",
          half["changed"] == ["price"]
          and statlib.tail(root, CAR)["aspiration"] == "Turbo"
          and statlib.tail(root, CAR)["cash"] == 750,
          str(half["changed"]))

    # and the file still parses, byte for byte, after all of that
    plain = speclib.load_spec(os.path.join(root, ".depot"),
                              os.path.basename(statlib.spec_path(root, CAR))[:-8])
    check("the spec still round trips after a tail write",
          speclib.parse_spec(plain.to_bytes()).to_bytes() == plain.to_bytes(),
          "not byte for byte")

    # bad input is refused rather than written
    for name, call, needle in (
            ("an aspiration the game does not know",
             lambda: speclib.load_spec(os.path.join(root, ".depot"),
                                       os.path.basename(
                                           statlib.spec_path(root, CAR))[:-8]
                                       ).set_aspiration("Bogus"),
             "not an aspiration"),
            ("a layout the game does not know",
             lambda: speclib.load_spec(os.path.join(root, ".depot"),
                                       os.path.basename(
                                           statlib.spec_path(root, CAR))[:-8]
                                       ).set_layout("X"),
             "not a layout"),
            ("a price that is not a number",
             lambda: speclib.load_spec(os.path.join(root, ".depot"),
                                       os.path.basename(
                                           statlib.spec_path(root, CAR))[:-8]
                                       ).set_price("abc"),
             "is not a price")):
        try:
            call()
        except speclib.SpecError as exc:
            check(f"{name} is refused", needle in str(exc), str(exc)[:60])
        else:
            check(f"{name} is refused", False, "it was accepted")

    print("56 the test area can send the differences one file at a time")
    # Pushing used to be all or nothing, which is wrong for the ordinary case:
    # a user who edited three cars and only trusts one of them had to throw the
    # other two away.  Every row is ticked when the list is built, so "push
    # everything" is still one press.
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        from PySide6.QtWidgets import QApplication
        from PySide6.QtCore import Qt as QtConst
        from rrmod.ui import deployui

        app = QApplication.instance() or QApplication([])
        body = os.path.join(root, ".depot", "vehicles", CAR, f"{CAR}_a.m3g")
        page = deployui.DeployPage()
        page.inv = depotlib.scan(root)
        page.device = object()               # enough for the button state
        # The compare itself needs adb, so the rows are handed to the table the
        # way the scan would: one file that differs, one the device has not got,
        # and one that already matches and must not appear.
        page._scanned([
            {"local": body, "rel": f".depot/vehicles/{CAR}/{CAR}_a.m3g",
             "state": "differs", "size": os.path.getsize(body)},
            {"local": body, "rel": f".depot/vehicles/{CAR}/{CAR}_b.m3g",
             "state": "missing", "size": 4096},
            {"local": body, "rel": f".depot/vehicles/{CAR}/{CAR}_c.m3g",
             "state": "same", "size": 4096},
        ])
        check("only the differences are listed", page.table.rowCount() == 2,
              str(page.table.rowCount()))
        check("the status column says what will happen",
              page.table.item(0, 3).text() == "differs"
              and page.table.item(1, 3).text() == "missing",
              f"{page.table.item(0, 3).text()} / {page.table.item(1, 3).text()}")
        check("every row starts ticked",
              page.table.item(0, 0).checkState() == QtConst.Checked,
              str(page.table.item(0, 0).checkState()))
        check("a ticked row counts as chosen", len(page._checked_rows()) == 2,
              str(page._checked_rows()))
        check("push is offered", page.push_btn.isEnabled())

        page._tick_all(False)
        check("unticking everything leaves nothing chosen",
              page._checked_rows() == [], str(page._checked_rows()))
        check("push is refused with nothing ticked",
              not page.push_btn.isEnabled())
        page._tick_all(True)
        check("ticking everything again brings push back",
              page.push_btn.isEnabled() and len(page._checked_rows()) == 2)

        # the row still names the right remote path now that a column was added
        check("the remote path is still the one the push needs",
              page._checked_rows()[0][1] == f".depot/vehicles/{CAR}/{CAR}_a.m3g",
              str(page._checked_rows()[:1]))

        # A car selected on the Cars page is what the scan looks at, and with
        # none selected it falls back to what the undo history has touched.
        page.set_car(CAR)
        check("the page remembers which car to scan", page.car == CAR, page.car)
        check("and says so", CAR in page.car_label.text(), page.car_label.text())
        page.set_car("")
        check("clearing the selection falls back to the edited files",
              "edited" in page.car_label.text(), page.car_label.text())

        print("56b quitting no longer asks, because nothing is unsaved")
        # There is no staging area to lose any more: every edit is already in the
        # game folder, so the quit prompt that used to nag about staged files is
        # gone rather than left saying something untrue.
        from rrmod.ui import app as applilib
        window = applilib.MainWindow()
        check("quitting does not stop to ask about staged work",
              window._confirmed_quit() is True)
        check("and the old staged-file wording is gone",
              not hasattr(applilib, "staged_quit_text"),
              "staged_quit_text still exists")
        window.close()

        print("56c a port that did not answer is not saved back")
        # 5555 is the emulator's own adbd port, not the adb server's.  Saving it
        # back means every later call pays the timeout again, so the page stores
        # what really answered instead of what was typed.
        from rrmod import deploy as deploymod
        real_effective = deploymod.effective_port
        try:
            deploymod.effective_port = lambda asked="": ""
            page.server_port.setText("5555")
            page._remember_port()
            check("a port that fell back is cleared from the box",
                  page.server_port.text() == "", repr(page.server_port.text()))
            deploymod.effective_port = lambda asked="": "5038"
            page.server_port.setText("5555")
            page._remember_port()
            check("a port that did answer is written as it is",
                  page.server_port.text() == "5038", repr(page.server_port.text()))
            page.server_port.setText("5038")
            page._remember_port()
            check("a port already right is left alone",
                  page.server_port.text() == "5038", repr(page.server_port.text()))
        finally:
            deploymod.effective_port = real_effective

        page.close()
    except ImportError as exc:
        check("the test page can be built", False, str(exc))

    print("57 a tier can be added or dropped, and one event changed in place")
    # Editing a series used to mean set_events: throw the tier list away and
    # build new ones.  That renumbers every tier id, which breaks anything that
    # already refers to a tier (a save file, an unlock rule).  These three
    # functions edit the records the game already reads and leave the ids alone.
    room = os.path.join(ROOT, "work", "rrmod_test_tiers")
    shutil.rmtree(room, ignore_errors=True)
    os.makedirs(os.path.join(room, ".depot", "data"), exist_ok=True)
    for leaf in serieslib.career_leaves():
        src = os.path.join(MINI, ".depot", *leaf.split("/"))
        dst = os.path.join(room, ".depot", *leaf.split("/"))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if os.path.isfile(src):
            shutil.copyfile(src, dst)

    career = serieslib.load(room)
    many = [s for s in career.series if len(career.tiers_of(s.id)) >= 2]
    check("the career has series with more than one tier", bool(many),
          str(len(many)))
    if many:
        target = max(many, key=lambda s: len(career.tiers_of(s.id)))
        before_tiers = [(t.id, t.index) for t in career.tiers_of(target.id)]
        before_count = len(career.tiers)
        made = serieslib.add_tier(career, target.id)
        after_tiers = [(t.id, t.index) for t in career.tiers_of(target.id)]
        check("a tier is added", len(after_tiers) == len(before_tiers) + 1,
              f"{len(before_tiers)} -> {len(after_tiers)}")
        check("the existing tiers keep their ids and their order",
              after_tiers[:len(before_tiers)] == before_tiers,
              str(after_tiers[:len(before_tiers)])[:120])
        check("the new tier goes on the end",
              after_tiers[-1] == (made["tier"], made["index"]),
              f'{after_tiers[-1]} vs {made["tier"]}, {made["index"]}')
        check("it copies the last tier's races when given none",
              made["events"] > 0, str(made["events"]))
        check("nothing else in the career was added",
              len(career.tiers) == before_count + 1,
              f"{before_count} -> {len(career.tiers)}")
        check("the career still round trips after adding a tier",
              careerlib.parse(career.to_bytes()).to_bytes() == career.to_bytes(),
              "not byte for byte")

        dropped = serieslib.remove_tier(career, target.id, made["tier"])
        check("the tier comes back off", dropped["tiers"] == len(before_tiers),
              str(dropped["tiers"]))
        check("removing it restores the original tier list",
              [(t.id, t.index) for t in career.tiers_of(target.id)]
              == before_tiers, "not the same list")
        check("the career round trips after removing it",
              careerlib.parse(career.to_bytes()).to_bytes() == career.to_bytes(),
              "not byte for byte")

        # Dropping a tier from the middle pulls the later indices down by one so
        # they stay 0..n-1; the ids of the survivors must not move.
        middle = career.tiers_of(target.id)[0]
        survivors = [t.id for t in career.tiers_of(target.id)[1:]]
        serieslib.remove_tier(career, target.id, middle.id)
        kept = career.tiers_of(target.id)
        check("a tier can be dropped from the middle",
              [t.id for t in kept] == survivors, str([t.id for t in kept])[:120])
        check("the indices close up to 0..n-1",
              [t.index for t in kept] == list(range(len(kept))),
              str([t.index for t in kept]))

    single = [s for s in career.series if len(career.tiers_of(s.id)) == 1]
    if single:
        only = career.tiers_of(single[0].id)[0]
        try:
            serieslib.remove_tier(career, single[0].id, only.id)
        except serieslib.SeriesError as exc:
            check("the last tier of a series cannot be dropped",
                  "one tier left" in str(exc), str(exc)[:80])
        else:
            check("the last tier of a series cannot be dropped", False,
                  "it was accepted")

    # One event at a time, in place.
    career = serieslib.load(room)
    pick = None
    for s in career.series:
        for tier in career.tiers_of(s.id):
            if tier.events:
                pick = (s.id, tier.events[0])
                break
        if pick:
            break
    check("the career has an event to change", pick is not None, "none found")
    if pick:
        sid, event = pick
        # set_event edits the record in place, so the object handed in is the one
        # that changes - the old value has to be read before the call.
        was_laps = event.laps
        ids_before = [e.id for t in career.tiers_of(sid) for e in t.events]
        quiet = serieslib.set_event(career, sid, event.id)
        check("changing nothing changes nothing", quiet["changed"] == [],
              str(quiet["changed"]))
        moved = serieslib.set_event(career, sid, event.id, laps=was_laps + 4)
        check("one field can be changed on its own",
              moved["changed"] == ["laps"], str(moved["changed"]))
        check("the new value is the one that was asked for",
              moved["laps"] == was_laps + 4, str(moved["laps"]))
        check("the other events keep their ids and their order",
              [e.id for t in career.tiers_of(sid) for e in t.events]
              == ids_before, "the list moved")
        check("the career round trips after changing an event",
              careerlib.parse(career.to_bytes()).to_bytes() == career.to_bytes(),
              "not byte for byte")
        try:
            serieslib.set_event(career, sid, event.id, track="Not A Track")
        except serieslib.SeriesError as exc:
            check("a track the game does not have is refused",
                  "not one of the game" in str(exc), str(exc)[:80])
        else:
            check("a track the game does not have is refused", False,
                  "it was accepted")
        try:
            serieslib.set_event(career, sid, 99999999, laps=2)
        except serieslib.SeriesError as exc:
            check("an event that is not in the series is refused",
                  "has no event" in str(exc), str(exc)[:80])
        else:
            check("an event that is not in the series is refused", False,
                  "it was accepted")

    # and the whole thing is written back where it was read
    serieslib.write(career, serieslib.load_texts(room), out_dir=room)
    again = serieslib.load(room)
    check("the edited career is the one on disk",
          len(again.series) == len(career.series),
          f"{len(again.series)} vs {len(career.series)}")
    shutil.rmtree(room, ignore_errors=True)

    print("58 undo puts the game folder back, manifests and all")
    # The invariant the old workspace had to keep was "the working copy never
    # reaches the install".  The invariant now is the one that replaced it: an
    # edit writes into the game folder *and* books its manifest row, and undoing
    # the step takes both back - the row goes, and a file the edit created is
    # deleted rather than left behind pointing at nothing.  Without this a
    # rollback leaves the engine told about a banim that is no longer there.
    from rrmod.ui import editing as editinglib

    editor = editinglib.Editor(root)
    check("the editor points at the install", editor.root == root, editor.root)
    car_man = os.path.join(root, "apk", "res",
                           f"asset_list_vehicle_{CAR}.txt")

    def man_bytes(path):
        with open(path, "rb") as fh:
            return fh.read()

    man_before = man_bytes(car_man)
    qa = os.path.join(ROOT, "work", "rrmod_test_qa")
    os.makedirs(qa, exist_ok=True)
    made = os.path.join(qa, "wing2.banim")
    with open(made, "wb") as fh:
        fh.write(b"b" * 752)
    landed = os.path.join(root, ".depot", "vehicles", CAR, f"{CAR}_wing.banim")
    # An earlier group may already have put this file there, and then the undo
    # must put the *old* bytes back rather than delete it - so what the check is
    # allowed to expect depends on what was there before.
    existed = os.path.isfile(landed)
    old_bytes = open(landed, "rb").read() if existed else b""
    editlib.install_slots(root, CAR, {"wing_banim": made}, log=lambda m: None)
    check("the file lands in the game folder", os.path.isfile(landed), landed)
    edited = man_bytes(car_man)
    check("adding a banim changes the manifest", edited != man_before,
          "the row was never written")
    check("and the row describes the file that was added",
          any(f"{CAR}_wing.banim" in line and str(752) in line
              for line in edited.decode("utf-8").splitlines()),
          "no row names the new file")
    check("nothing was staged anywhere", editor.summary()["files"] == 0,
          str(editor.summary()))

    steps = editlib.backups(root)
    check("the edit left an undo step", bool(steps), str(steps[:2]))
    done = historylib.restore(root, [steps[0]])
    check("undo touched the two files the edit wrote", len(done["files"]) >= 2,
          str(done["files"]))
    check("undo puts the manifest back byte for byte",
          man_bytes(car_man) == man_before,
          "the edited row survived the undo")
    if existed:
        check("and the file it replaced is back to what it was",
              os.path.isfile(landed) and open(landed, "rb").read() == old_bytes,
              landed)
    else:
        check("and the file the edit created is deleted, not left behind",
              not os.path.isfile(landed), landed)
    check("the manifests still agree with the car",
          editlib.verify(root, CAR) == [], str(editlib.verify(root, CAR)[:2]))
    os.remove(made)

    # The page-level refresh path: an ordinary edit must only refresh the test
    # list, while an undo must also re-read the car page - otherwise the detail
    # pane keeps showing a change that has just been taken back.
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from rrmod.ui import cars as carslib
    from rrmod.ui import app as applilib

    app = QApplication.instance() or QApplication([])
    page = carslib.CarsPage()
    check("the car page can re-read the selected car",
          callable(getattr(page, "refresh_detail", None)),
          "refresh_detail is missing")
    check("and it tells the rest of the window which car is selected",
          hasattr(page, "picked"), "CarsPage.picked is missing")
    page.close()

    window = applilib.MainWindow()
    seen = []
    window.deploy.refresh = lambda: seen.append("deploy")
    window.cars.refresh_detail = lambda: seen.append("cars")
    window._staged_changed()
    check("writing a file only refreshes the test list",
          seen == ["deploy"], str(seen))
    seen.clear()
    window._staged_cleared()
    check("undoing refreshes the car page too",
          seen == ["deploy", "cars"], str(seen))
    seen.clear()
    window.cars.picked.emit(CAR)
    check("selecting a car tells the test page which one",
          window.deploy.car == CAR, window.deploy.car)
    window.close()

    # put the mini install's car back the way the earlier groups left it
    statlib.set_tail(root, CAR, aspiration="Nat", layout="F", unlock="",
                     cash=402700, gold=130)
    check("the mini install's car is back where it started",
          statlib.tail(root, CAR)["aspiration"] == "Nat",
          statlib.tail(root, CAR)["aspiration"])


    print("59 a wing the pack brings gets paint rows of its own")
    # the model decides whether a car has a wing: the LFA has none, so nothing
    # is added for it unless the caller names the parts it brought in
    check("the LFA carries no wing mesh", editlib.wing_parts(root, CAR) == [],
          str(editlib.wing_parts(root, CAR)))
    livery_path = os.path.join(root, ".depot", "vehicles", "data", "liveries",
                               f"{CAR}.liveries.bin.nct")
    before_size = os.path.getsize(livery_path)
    wing = editlib.sync_wing_paint(root, CAR, log=lambda m: None,
                                   parts=["LOD_A_WING_REAR_mm_ext",
                                          "LOD_A_WING_STRUT_mm_misc"])
    check("the named parts are the ones handled",
          wing["parts"] == ["LOD_A_WING_REAR_mm_ext", "LOD_A_WING_STRUT_mm_misc"],
          str(wing["parts"]))
    # group 6 already filled 745 from the body slot, so only the second part is
    # new here - the first one comes back as already covered
    check("the uncovered wing slot got a row",
          wing["added"] == ["LOD_A_WING_STRUT_mm_misc"], str(wing["added"]))
    check("the slot group 6 filled is left alone",
          wing["kept"] == ["LOD_A_WING_REAR_mm_ext"], str(wing["kept"]))
    check("the livery grew", os.path.getsize(livery_path) > before_size,
          f"{before_size} -> {os.path.getsize(livery_path)}")
    check("the rows were synced to the manifest", bool(wing["saved"]),
          wing["saved"])
    check("the install is still clean after adding rows",
          editlib.verify(root) == [], str(editlib.verify(root)[:2]))
    # the wing now wears whatever the body wears, scheme by scheme
    L = liverylib.load_car(os.path.join(root, ".depot"), CAR)
    table = liverylib.load_slot_table(os.path.join(root, ".depot"))
    body_slot = table.part_slot("LOD_A_BODY_mm_ext")
    wing_slot = table.part_slot("LOD_A_WING_REAR_mm_ext")
    same = [p.material_of(wing_slot) == p.material_of(body_slot)
            for p in L.paints]
    check("every scheme paints the wing like the body", all(same), str(same))
    # running it again changes nothing - a car that already covers the slot keeps
    # the paint the studio gave it
    again = editlib.sync_wing_paint(root, CAR, log=lambda m: None,
                                    parts=["LOD_A_WING_REAR_mm_ext"])
    check("a covered slot is left alone", again["added"] == [], str(again))
    check("and it is reported as kept",
          again["kept"] == ["LOD_A_WING_REAR_mm_ext"], str(again["kept"]))
    # a part the slot table does not know is reported, not guessed at
    unknown = editlib.sync_wing_paint(root, CAR, log=lambda m: None,
                                      parts=["LOD_A_WING_NONSENSE_mm_ext"])
    check("a part with no slot is named", unknown["no_slot"] ==
          ["LOD_A_WING_NONSENSE_mm_ext"], str(unknown))

    # the shipped cars prove the rule: the studio's own wings do have rows where
    # they meant them to, and the slot table covers every wing tag we produce
    check("WING_REAR_mm_ext has a slot",
          table.part_slot("LOD_A_WING_REAR_mm_ext") is not None,
          str(table.part_slot("LOD_A_WING_REAR_mm_ext")))
    for part in ("LOD_A_WING_REAR_mm_misc", "LOD_A_WING_STRUT_mm_misc",
                 "LOD_A_WING_STRUT_REAR_mm_misc", "LOD_A_WING_REAR_LEFT_mm_ext",
                 "LOD_A_WING_REAR_RIGHT_mm_ext", "LOD_A_WING_mm_ext"):
        check(f"{part} has a slot", table.part_slot(part) is not None,
              str(table.part_slot(part)))

    # the permission bug: folders must never share a mode with files, because a
    # folder without the search bit makes everything inside it unreadable
    import inspect
    import re as _re
    dep_src = inspect.getsource(deploylib.Device)
    # only the shell commands count: the docstring quotes the old mistake on
    # purpose, to say why it is a mistake
    shells = [ln for ln in dep_src.splitlines() if "self.su(" in ln]
    check("no blanket chmod -R in a deploy command",
          not any("chmod -R" in ln for ln in shells), str(shells[:3]))
    check("folders are given 2770",
          any("chmod 2770" in ln for ln in shells), str(shells[:3]))
    check("files are given 660",
          any("chmod 660" in ln for ln in shells), str(shells[:3]))
    check("the folder mode keeps the search bit",
          "2770" in dep_src and "drwx" not in _re.sub(r"drw-rw----", "", dep_src),
          "")
    # and the fix is reachable, not dead code
    check("fix_permissions exists", hasattr(deploylib.Device, "fix_permissions"),
          "")

    # restore the livery the source install ships, so later runs start clean
    shutil.copyfile(os.path.join(install, ".depot", "vehicles", "data",
                                 "liveries", f"{CAR}.liveries.bin.nct"),
                    livery_path)
    editlib.sync_file(root, name=CAR,
                      rel_path=f"/vehicles/data/liveries/{CAR}.liveries.bin.nct",
                      local=livery_path)

    print("60 a wing banim with no trailer is reported as broken")
    # The trailer is one hash word per track and the engine will not apply a clip
    # without it: the wing loads, nothing moves, and the part stays at its
    # modelled origin - which on a car whose wing was cut out of the body looks
    # exactly like the wing having been deleted.  That is not a cosmetic warning.
    from rr3lib import banim_write as bwlib
    bpath = animlib.banim_path(root, CAR)
    os.makedirs(os.path.dirname(bpath), exist_ok=True)
    doc = bwlib.simple_wing(duration_ms=1000.0, end_pos=(0.0, 0.0, 0.28),
                            end_deg=(45.0, 0.0, 0.0))
    bwlib.save(doc, bpath)
    check("a banim built without a trailer really has none",
          bwlib.load(bpath).tail_raw == b"", str(bwlib.load(bpath).tail_raw))
    stripped = animlib.read(root, CAR)
    check("the animation page notices the missing trailer",
          any("trailer" in w for w in stripped["warnings"]),
          str(stripped["warnings"]))
    check("and says what the player would see",
          any("look as if it is missing" in w for w in stripped["warnings"]),
          str(stripped["warnings"]))
    # with a trailer the warning is gone.  The word table lives in the Blender
    # exporter, so the trailer is built here the same way it builds it rather
    # than reaching into the real install for a shipped file the mini one lacks.
    import struct as _struct
    doc.tail_raw = _struct.pack("<I", 1) + _struct.pack("<I", 0xAD45C13F)
    bwlib.save(doc, bpath)
    with_trailer = animlib.read(root, CAR)
    check("a banim with a trailer raises no warning",
          not any("trailer" in w for w in with_trailer["warnings"]),
          str(with_trailer["warnings"]))
    check("the trailer survived the round trip",
          bwlib.load(bpath).tail_raw == doc.tail_raw,
          str(bwlib.load(bpath).tail_raw))
    os.remove(bpath)

    print("61 a file outside a car's folder is claimed by the right list")
    # Adding a brand used to make the game offer a download.  The logo page is
    # written under gui_assets, which no car edit walks, and it is claimed by
    # ``asset_list_gui_assets_core.txt`` - a list sync_file never touched.  The
    # engine then saw a file on disk that no list mentioned and decided the
    # install was incomplete.  These checks pin the lookup that fixes it.
    from rrmod.ui import brandsui as brandsuilib

    index = manifestlib.asset_index(root)
    logo_dir = "/gui_assets/960x640/common/manufacturer_logos"
    check("the index knows which list claims a logo page",
          index.owner_of(f"{logo_dir}/sprites_0.rgb.pvr.z")
          == "asset_list_gui_assets_core.txt",
          index.owner_of(f"{logo_dir}/sprites_0.rgb.pvr.z"))
    check("a page that does not exist yet is filed with its neighbours",
          index.list_for(f"{logo_dir}/sprites_9.rgb.pvr.z")
          == "asset_list_gui_assets_core.txt",
          index.list_for(f"{logo_dir}/sprites_9.rgb.pvr.z"))
    check("the install's own lists agree with the game's",
          index.owner_of(f"/vehicles/{CAR}/{CAR}_a.m3g")
          == f"asset_list_vehicle_{CAR}.txt",
          index.owner_of(f"/vehicles/{CAR}/{CAR}_a.m3g"))

    # A logo is written under gui_assets, which no car edit walks.  The list that
    # claims it has to be found from the install itself now that there is no
    # working copy holding a mirror of every list.
    editor = editinglib.Editor(root)
    install_lists = [f for f in os.listdir(os.path.join(root, "apk", "res"))
                     if f.startswith("asset_list") and f.endswith(".txt")]
    check("the install has the asset lists to work with",
          len(install_lists) > 3, str(install_lists[:4]))
    check("the core gui list is one of them",
          "asset_list_gui_assets_core.txt" in install_lists,
          str(sorted(install_lists)[:4]))

    # a logo really does go through sync_file and land in that list
    picture = _png_fixture()
    sheets = brandlib.atlases(editor.depot)
    check("the mini install ships a logo sheet", bool(sheets), str(sheets))
    out_dir = editor.for_gfx()
    # The backup callback is the whole point: the helper writes the atlas and the
    # page itself, and an edit is written straight into the game folder now, so
    # recording the previous state *after* the write would record the new bytes
    # and the undo would restore the edit instead of removing it.
    editlib.begin()
    logo = brandlib.add_logo(editor.depot, "Nonesuch Motors", picture,
                             out_dir=out_dir,
                             backup=lambda path: editlib.backup_before_write(
                                 editor.root, path),
                             log=lambda _m: None)
    check("the logo wrote an atlas and a page", len(logo["files"]) == 2,
          str(logo["files"]))
    for local, rel in logo["files"]:
        game_path = ("/" + rel[len(".depot/"):] if rel.startswith(".depot/")
                     else "/" + rel)
        editlib.sync_file(editor.root, name="", rel_path=game_path,
                          local=local, create=True)
    core = manifestlib.load_asset_list(editor.root,
                                       "asset_list_gui_assets_core.txt")
    page = [r[1] for r in logo["files"] if r[1].endswith(".rgb.pvr.z")][0]
    page_path = "/" + page[len(".depot/"):]
    check("the new page is claimed by the core gui list",
          core.get(page_path) is not None, page_path)
    check("and its row carries the hash of what was written",
          core.get(page_path)[1] == manifestlib.md5_file(
              os.path.join(editor.root, *page.split("/"))),
          str(core.get(page_path)))
    check("the atlas row was rewritten, not appended",
          core.get("/" + [r[1] for r in logo["files"]
                          if r[1].endswith(".android.atlas")][0][len(".depot/"):])
          is not None, "the atlas has no row")

    # undo takes the page away again, and it does so as one step: the atlas goes
    # back to what it was and the page that never existed is deleted
    done = historylib.restore(root, [editlib.backups(root)[0]])
    check("undo restores the logo step", len(done["files"]) >= 2, str(done))
    check("the new page is gone from disk",
          not os.path.isfile(os.path.join(editor.root, *page.split("/"))),
          page)
    check("the atlas is the install's copy again",
          editlib.md5_file(os.path.join(
              editor.root, *[r[1] for r in logo["files"]
                             if r[1].endswith(".android.atlas")][0].split("/")))
          == editlib.md5_file(os.path.join(
              root, *[r[1] for r in logo["files"]
                      if r[1].endswith(".android.atlas")][0].split("/"))),
          "the atlas still differs")

    # the page itself must survive: an undo of an edit that *replaced* a file
    # puts the old bytes back, it does not delete the file
    check("the manifest row for the page went with it",
          manifestlib.load_asset_list(
              editor.root, "asset_list_gui_assets_core.txt").get(page_path)
          is None, page_path)

    # the brand page reads its logos from the working copy, and the cache it
    # keeps has to be dropped when a picture is added or the new one never shows
    check("the brands page reads the working copy",
          hasattr(brandsuilib.BrandsPage, "_read_depot"), "no _read_depot")
    check("the brands page can remove a brand it added",
          hasattr(brandsuilib.BrandsPage, "remove_brand"), "no remove_brand")
    check("atlas.forget drops both caches",
          atlaslib._INDEX is atlaslib._INDEX
          and hasattr(atlaslib, "forget"), "no forget")

    def _copy_into_step(root, stamp, rel):
        """Write the current bytes of ``rel`` into a step, the way edit does."""
        import shutil as _sh

        dst = os.path.join(histlib.dir_for(root), stamp, *rel.split("/"))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        _sh.copyfile(os.path.join(root, *rel.split("/")), dst)

    print("62 undo steps carry a name, a limit and a folder of their own")
    from rrmod import history as histlib

    hist_root = os.path.join(ROOT, "work", "rrmod_test_history")
    outside = os.path.join(ROOT, "work", "rrmod_test_history_out")
    for folder in (hist_root, outside):
        shutil.rmtree(folder, ignore_errors=True)
    os.makedirs(os.path.join(hist_root, ".depot"), exist_ok=True)

    # a step knows what it did, and says so in the panel
    histlib.set_dir("")
    check("history starts inside the working copy",
          histlib.dir_for(hist_root) == os.path.join(hist_root, "_rrmod_backup"),
          histlib.dir_for(hist_root))
    target = os.path.join(hist_root, ".depot", "a.txt")
    with open(target, "w", encoding="utf-8") as fh:
        fh.write("zero")
    s1 = histlib.begin(hist_root, "Build the body")
    _copy_into_step(hist_root, s1, ".depot/a.txt")
    with open(target, "w", encoding="utf-8") as fh:
        fh.write("one")
    histlib.note(hist_root, s1, ".depot/a.txt", size=3)
    steps = histlib.steps(hist_root)
    check("one step is listed", len(steps) == 1, str(len(steps)))
    check("the step kept its name", steps[0]["title"] == "Build the body",
          str(steps[0]))
    check("and the file it touched", steps[0]["files"] == [[".depot/a.txt", 3]],
          str(steps[0]["files"]))
    check("a named step reads as its name",
          histlib.label(steps[0]) == "Build the body", histlib.label(steps[0]))
    check("the note sits beside the folder, not inside it",
          os.path.isfile(os.path.join(histlib.dir_for(hist_root),
                                      s1 + histlib.STEP_SUFFIX))
          and not os.path.isfile(os.path.join(histlib.dir_for(hist_root), s1,
                                              "_step.json")),
          "the sidecar is in the wrong place")

    # two steps, newest first, and the oldest copy wins when both touched a file
    s2 = histlib.begin(hist_root, "Repaint it")
    _copy_into_step(hist_root, s2, ".depot/a.txt")
    with open(target, "w", encoding="utf-8") as fh:
        fh.write("two")
    histlib.note(hist_root, s2, ".depot/a.txt", size=3)
    check("the newest step is listed first",
          histlib.stamps(hist_root)[0] == s2, str(histlib.stamps(hist_root)))
    histlib.restore(hist_root, [s1, s2])
    with open(target, encoding="utf-8") as fh:
        got = fh.read()
    check("restoring two steps leaves the state before both",
          got == "zero", got)
    histlib.restore(hist_root, [s2])
    with open(target, encoding="utf-8") as fh:
        got = fh.read()
    check("restoring one step leaves the state before just that one",
          got == "one", got)

    # pinning keeps a step out of the limit's way
    histlib.pin(hist_root, s1, True)
    check("a pinned step says so",
          histlib.read(hist_root, s1)["pinned"] is True, str(s1))
    for i in range(histlib.DEFAULT_KEEP + 3):
        histlib.begin(hist_root, f"step {i}")
    left = histlib.stamps(hist_root)
    check("the limit drops the oldest steps",
          len(left) <= histlib.DEFAULT_KEEP + 1, str(len(left)))
    check("but never the pinned one", s1 in left, str(s1))
    check("the pinned step still counts towards the limit",
          len(left) <= histlib.DEFAULT_KEEP + 1, str(len(left)))
    # A step is dropped on purpose.  It has to be one that survived the limit
    # above: the twenty-three steps made there push everything older out, which
    # is the limit doing its job, not a bug in drop().
    doomed = histlib.stamps(hist_root)[0]
    gone = histlib.drop(hist_root, [doomed])
    check("a step can be forgotten on purpose", gone == 1, str(gone))
    check("and it is gone from the list", doomed not in histlib.stamps(hist_root),
          str(histlib.stamps(hist_root)))
    check("and the limit did drop the old ones",
          s2 not in histlib.stamps(hist_root), str(histlib.stamps(hist_root)))

    # an unnamed step still reads as something
    bare = histlib.begin(hist_root)
    check("an unnamed step still has a line",
          histlib.label(histlib.read(hist_root, bare)).startswith("An unnamed"),
          histlib.label(histlib.read(hist_root, bare)))
    check("a step without a sidecar still shows",
          os.path.isfile(os.path.join(histlib.dir_for(hist_root),
                                      bare + histlib.STEP_SUFFIX)),
          "the sidecar was not written")

    # a folder of its own, so the history can live on another disk
    histlib.set_dir(outside)
    where = histlib.dir_for(hist_root)
    check("a chosen folder is used", where.startswith(outside), where)
    check("and is tagged per working copy", where != outside, where)
    histlib.set_dir("")
    check("clearing the setting goes back inside",
          histlib.dir_for(hist_root) == os.path.join(hist_root, "_rrmod_backup"),
          histlib.dir_for(hist_root))

    # the editor writes the same sidecar, so the panel is never guessing
    histlib.set_dir("")
    step = editlib.begin("Change one file")
    editlib.backup_for_undo(editor.root, os.path.join(
        editor.root, ".depot", "vehicles", CAR, f"{CAR}_a.m3g"))
    rows = histlib.steps(editor.root)
    check("an edit made through the editor is a named step",
          bool(rows) and rows[0]["title"] == "Change one file",
          str(rows[:1]))
    check("and lists the file it copied",
          any(r[0].endswith(f"{CAR}_a.m3g") for r in rows[0]["files"]),
          str(rows[:1]))
    check("the step is the one the editor opened",
          rows[0]["stamp"] == step, f"{rows[0]['stamp']} vs {step}")

    # Undo puts the files back but keeps the step: the copy that makes the undo
    # possible is also the only record of what the edit was, and throwing it away
    # on the first press makes "undo the undo" impossible.  Forgetting is a
    # separate, deliberate action.
    before = len(histlib.stamps(editor.root))
    done2 = histlib.restore(editor.root, [step])
    check("undoing one step reports the files", len(done2["files"]) >= 1,
          str(done2))
    check("undoing keeps the step, so it can be undone again",
          len(histlib.stamps(editor.root)) == before,
          f"{before} -> {len(histlib.stamps(editor.root))}")
    check("forgetting it is what removes it",
          histlib.drop(editor.root, [step]) == 1
          and len(histlib.stamps(editor.root)) == before - 1,
          str(len(histlib.stamps(editor.root))))

    # the setting round-trips, because the panel reads it on every refresh
    settingslib.set_history_dir(outside)
    check("the chosen history folder is remembered",
          settingslib.history_dir() == outside, settingslib.history_dir())
    settingslib.set_history_dir("")
    settingslib.set_history_keep(12)
    check("so is the limit", settingslib.history_keep() == 12,
          str(settingslib.history_keep()))
    settingslib.set_history_keep(0)
    histlib.set_dir("")
    shutil.rmtree(hist_root, ignore_errors=True)
    shutil.rmtree(outside, ignore_errors=True)

    print()
    print("62c converting a texture to a picture and back")
    # The toolbar button's whole job.  Three families - an ordinary picture, a
    # plain DDS, and the game's own container - and the point of the checks is
    # that a page survives the round trip with its size, its format and its
    # orientation intact.
    from rrmod import texconv as convlib

    conv_dir = os.path.join(ROOT, "work", "rrmod_test_conv")
    shutil.rmtree(conv_dir, ignore_errors=True)
    os.makedirs(conv_dir, exist_ok=True)
    page = os.path.join(MINI, ".depot", "vehicles", CAR, "livery",
                        f"{CAR}_ext_yellow.dxt.dds.z")
    if not os.path.isfile(page):
        page = os.path.join(MINI, ".depot", "vehicles", CAR,
                            f"{CAR}_misc.dxt.dds.z")
    check("there is a page to convert", os.path.isfile(page), page)
    if os.path.isfile(page):
        info = convlib.describe(page)
        check("the page is recognised as a game texture",
              info["kind"] == "game", info["kind"])
        check("and its size is read from the header",
              info["width"] > 0 and info["height"] > 0, str(info)[:100])
        check("a picture is a picture",
              convlib.kind_of(_png_fixture()) == "picture")
        check("a plain dds is a dds",
              convlib.kind_of(os.path.join(conv_dir, "x.dds")) == "dds")
        check("and a text file is neither",
              convlib.kind_of(os.path.join(conv_dir, "x.txt")) == "",
              convlib.kind_of(os.path.join(conv_dir, "x.txt")))

        w, h, ch, pixels = convlib.read(page)
        check("it decodes", w > 0 and h > 0 and len(pixels) == w * h * ch,
              f"{w}x{h} {ch}")

        for fmt in ("png", "dds", "game-dxt", "game-etc"):
            got = convlib.convert(page, conv_dir, fmt)
            check(f"it converts to {fmt}", os.path.isfile(got["path"]), got["path"])
            check(f"the {fmt} keeps its size",
                  (got["width"], got["height"]) == (w, h),
                  f"{got['width']}x{got['height']} vs {w}x{h}")
            back = convlib.read(got["path"])
            check(f"the {fmt} reads back at the same size",
                  (back[0], back[1]) == (w, h), f"{back[0]}x{back[1]}")

        # The one that matters: a page written back must land on the same format.
        # A DXT1 page decodes to four channels, so "four channels means alpha"
        # would silently turn an opaque page into a DXT5 one of twice the size.
        check("an opaque page is not quietly given an alpha channel",
              convlib.source_alpha(page) is False,
              str(convlib.source_alpha(page)))
        again = convlib.convert(page, conv_dir, "game-dxt")
        check("re-encoding keeps it colour-only",
              again["alpha"] is False, str(again["alpha"]))
        check("and the result is about the size of the original",
              abs(again["bytes"] - os.path.getsize(page)) < os.path.getsize(page) * 0.2,
              f"{again['bytes']} vs {os.path.getsize(page)}")

        # A PNG carries no such history, so the channel count decides there.
        png = convlib.convert(page, conv_dir, "png")["path"]
        check("a PNG of it keeps its size",
              convlib.read(png)[:2] == (w, h), str(convlib.read(png)[:2]))
        check("and converting that PNG back gives a game texture again",
              convlib.kind_of(convlib.convert(png, conv_dir, "game-dxt")["path"])
              == "game")

        # A batch keeps going when one file cannot be read.
        bad = os.path.join(conv_dir, "not-a-texture.dxt.dds.z")
        with open(bad, "wb") as fh:
            fh.write(b"nonsense")
        many = convlib.convert_many([page, bad], conv_dir, "png",
                                    log=lambda _m: None)
        check("a batch converts what it can", len(many["done"]) == 1,
              str(len(many["done"])))
        check("and reports what it could not", len(many["failed"]) == 1,
              str(many["failed"]))
        os.remove(bad)

        # Writing over the source is refused rather than half done.
        check("a conversion is not allowed to overwrite its own source",
              _raises(convlib.ConvertError, convlib.convert, page,
                      os.path.dirname(page), "game-dxt",
                      out_path=page), "it wrote over the source")
        check("a folder of textures is found in one go",
              bool(convlib.files_in(os.path.dirname(page), recursive=False)),
              "nothing found next to the page")
    shutil.rmtree(conv_dir, ignore_errors=True)

    print("63 a project is a file that remembers the answers as well as the bytes")
    proj_root = os.path.join(ROOT, "work", "rrmod_test_project")
    shutil.rmtree(proj_root, ignore_errors=True)
    os.makedirs(proj_root, exist_ok=True)

    fp = projlib.fingerprint(MINI)
    check("the install has a fingerprint",
          len(fp["md5"]) == 32 and fp["cars"] >= 1, str(fp))

    # a staged edit is what a project is for
    from rrmod.ui import editing as editinglib
    editor = editinglib.Editor(MINI)
    root = editor.for_car(CAR)
    target = os.path.join(root, ".depot", "vehicles", CAR, f"{CAR}_a.m3g")

    # nothing edited and no car named: there is nothing to hold
    bare = os.path.join(proj_root, "bare")
    os.makedirs(bare, exist_ok=True)
    try:
        projlib.save(bare, os.path.join(proj_root, "empty.rr3proj"),
                     log=lambda m: None)
        check("an empty project is refused", False, "no error")
    except projlib.ProjectError as exc:
        check("an empty project is refused", "nothing" in str(exc), str(exc))

    editlib.begin("Widen the arch")
    editlib.backup_for_undo(root, target)
    with open(target, "ab") as fh:
        fh.write(b"\0\0\0\0")
    saved = open(target, "rb").read()
    check("the edit is in the undo history",
          any(rel.endswith(f"{CAR}_a.m3g")
              for stamp in historylib.stamps(root)
              for rel in historylib.files(root, stamp)),
          "the history does not know the file was touched")

    out = os.path.join(proj_root, "one.rr3proj")
    done = projlib.save(root, out, name="Arch test",
                        params={"new": False, "car": CAR, "aero": 1},
                        include_history=True, log=lambda m: None)
    check("a project is written", os.path.isfile(out), out)
    # The zip is smaller than what went into it.  The history it carries is not
    # part of ``raw``, so the comparison is made against a copy saved without it.
    plain = projlib.save(root, os.path.join(proj_root, "plain.rr3proj"),
                         name="Arch test, no history",
                         params={"new": False, "car": CAR},
                         include_history=False, log=lambda m: None)
    check("and the payload compresses", plain["bytes"] < plain["raw"],
          f"{plain['bytes']} vs {plain['raw']}")
    check("it holds the staged file", done["files"] >= 1, str(done["files"]))
    check("it carries the undo steps", done["steps"] >= 1, str(done["steps"]))

    about = projlib.describe(out, install=MINI)
    check("the project names the car", about["cars"] == [CAR], str(about["cars"]))
    check("it says it was made against this install",
          about["same_install"] is True, str(about))
    check("it lists its files", about["count"] == done["files"], str(about["count"]))
    check("it remembers the answers",
          about["params"].get("car") == CAR, str(about["params"]))

    # the manifest is readable on its own, and refuses a foreign format
    man = projlib.read(out)
    check("the manifest names its format", man.get("format") == projlib.FORMAT,
          str(man.get("format")))
    bad = os.path.join(proj_root, "bad.rr3proj")
    with zipfile.ZipFile(bad, "w") as zf:
        zf.writestr(projlib.MANIFEST, json.dumps({"format": 99, "files": []}))
    try:
        projlib.read(bad)
        check("a foreign format is refused", False, "no error")
    except projlib.ProjectError as exc:
        check("a foreign format is refused", "format 99" in str(exc), str(exc))
    try:
        projlib.read(os.path.join(proj_root, "nothere.rr3proj"))
        check("a missing project is refused", False, "no error")
    except projlib.ProjectError:
        check("a missing project is refused", True, "")

    # disturb the file, then open the project and get the bytes back
    with open(target, "wb") as fh:
        fh.write(b"ruined")
    before_steps = {s["stamp"] for s in histlib.steps(root)}
    back = projlib.open_project(root, out, log=lambda m: None)
    check("opening a project puts the files back", back["files"] >= 1,
          str(back["files"]))
    check("the bytes are the ones that were saved",
          open(target, "rb").read() == saved,
          f"{os.path.getsize(target)} vs {len(saved)}")
    check("and every file it wrote is in the undo step", back["written"] >= 1,
          str(back["written"]))
    check("the answers come back with it",
          back["params"].get("car") == CAR, str(back["params"]))
    check("the undo steps came along", back["steps"] >= 1, str(back["steps"]))
    added = {s["stamp"] for s in histlib.steps(root)} - before_steps
    # Two kinds of step arrive: the project's own, carried in the file, and the
    # one this session opened to hold what it replaced.  Only the first kind is
    # imported, so only the first kind carries the suffix.
    local = {s for s in added
             if "Open the project" in (histlib.read(root, s).get("title") or "")}
    imported = added - local
    check("the steps that came out of the project are marked as such",
          bool(imported) and all(
              projlib.FROM_PROJECT in (histlib.read(root, s).get("title") or "")
              for s in imported),
          str([histlib.read(root, s).get("title") for s in sorted(imported)][:3]))
    check("and the step this session opened is not",
          all(projlib.FROM_PROJECT not in
              (histlib.read(root, s).get("title") or "") for s in local),
          str([histlib.read(root, s).get("title") for s in sorted(local)]))
    check("and opening twice does not chain the suffix",
          all("-p1-p" not in s for s in added), str(sorted(added)[:2]))

    # The step opening the project made has to hold the *ruined* bytes.  Taking
    # the backup after the write would copy the project's own bytes into the
    # history, and Ctrl+Z would then put the project back instead of taking it
    # off again - the one action it exists for.
    open_step = [s for s in added if "Open the project" in
                 (histlib.read(root, s).get("title") or "")]
    check("opening a project is one named undo step", len(open_step) == 1,
          str([histlib.read(root, s).get("title") for s in added][:3]))
    if open_step:
        undone = histlib.restore(root, open_step)
        check("undoing it puts the ruined file back",
              open(target, "rb").read() == b"ruined",
              f"{os.path.getsize(target)} bytes, {len(undone['files'])} file(s)")
        # put the good copy back, so the rest of the group sees what it expects
        projlib.open_project(root, out, log=lambda m: None)
        check("reopening it works a second time",
              open(target, "rb").read() == saved,
              f"{os.path.getsize(target)} vs {len(saved)}")

    # a project with nothing staged and no car has nothing to hold
    # (already checked above, before the edit was made)

    # a project can hold a whole car even with nothing staged
    whole = os.path.join(proj_root, "whole.rr3proj")
    done2 = projlib.save(root, whole, car=CAR, log=lambda m: None)
    check("a whole car can be taken", done2["files"] > done["files"],
          f"{done2['files']} vs {done['files']}")
    check("and it holds the spec too",
          any("/vehicles/data/" in f[0] or f[0].endswith(".points")
              for f in projlib.read(whole)["files"]),
          str(projlib.read(whole)["files"][:3]))

    # the build dialog's answers survive being written down
    plain = projlib.params_from({"new": True, "aero_kind": b"DeployAtSpeed",
                                 "aero_params": (230, 200), "pack": r"C:\x.zip",
                                 "slots": {"A": "a.m3g"}, "car": CAR})
    check("a project drops the paths", "pack" not in plain and
          "slots" not in plain, str(sorted(plain)))
    check("and turns bytes into text", plain["aero_kind"] == "DeployAtSpeed",
          str(plain.get("aero_kind")))
    check("and tuples into lists", plain["aero_params"] == [230, 200],
          str(plain.get("aero_params")))

    # The folder the last project lived in is no longer remembered: there is no
    # Save/Open project in the interface any more, and a setting nothing reads
    # is a setting that goes stale.  ``projlib`` stays as the file format - a
    # .rr3proj is still a portable way to hand a build to somebody.
    check("the project settings the interface no longer uses are gone",
          not hasattr(settingslib, "project_dir")
          and not hasattr(settingslib, "set_last_project"),
          str([n for n in ("project_dir", "set_last_project")
               if hasattr(settingslib, n)]))
    shutil.rmtree(proj_root, ignore_errors=True)

    print("64 a shared page is four rows in one list, and one dependency")
    # ``vehicles/common`` is the one place a page can live that several cars
    # read.  Adding one has to book four rows (one per GPU family, each inside
    # its own run of the list) and record who asked for it, because that record
    # is the only way a later removal knows the page is not the game's own.
    editor = editinglib.Editor(MINI)
    ws_root = editor.root
    depot_ws = os.path.join(ws_root, ".depot")
    depslib.forget()

    common = depslib.shipped(os.path.join(MINI, ".depot"))
    check("the install's shared pages are known",
          len(common) >= 10 and "common/car_windows_04" in common,
          f"{len(common)} stems")
    check("a stem covers all four families",
          depslib.stem_of("vehicles/common/car_windows_04.dxt.dds.z")
          == depslib.stem_of("vehicles/common/car_windows_04.etc.dds.z"),
          depslib.stem_of("vehicles/common/car_windows_04.etc.dds.z"))
    check("and a fifth suffix the tables use",
          depslib.stem_of("common/car_tyre_slick_pirelli_f1_2019.rgb.pvr.z")
          == "common/car_tyre_slick_pirelli_f1_2019",
          depslib.stem_of("common/car_tyre_slick_pirelli_f1_2019.rgb.pvr.z"))
    check("the pages the game ships are not dependencies",
          depslib.orphans(os.path.join(MINI, ".depot")) == [],
          str(depslib.orphans(os.path.join(MINI, ".depot"))[:2]))

    # the four-row rule on the real list
    leaf = editlib.COMMON_LIST
    before = manifestlib.load_asset_list(ws_root, leaf)
    runs_before = manifestlib.runs(before.rows)
    check("the common list has four runs",
          len(runs_before) == 4 and [r[0] for r in runs_before] == [1, 2, 3, 4],
          str(runs_before))

    page_src = os.path.join(ROOT, "work", "rrmod_page.dxt.dds.z")
    with open(page_src, "wb") as fh:
        fh.write(b"RR3 page" * 8)
    made = editlib.add_common_page(ws_root, page_src, stem="rrmod_test_page",
                                   log=lambda _m: None)
    check("a shared page is copied in", os.path.isfile(made["target"]),
          made.get("target", ""))
    check("and its four rows go in together", len(made["list_rows"]) == 4,
          str(made.get("list_rows")))
    after = manifestlib.load_asset_list(ws_root, leaf)
    check("the list grew by four rows", len(after) == len(before) + 4,
          f"{len(before)} -> {len(after)}")
    check("the four runs are still four runs",
          [r[0] for r in manifestlib.runs(after.rows)] == [1, 2, 3, 4],
          str(manifestlib.runs(after.rows)))
    check("each row sits in its own family's run",
          all(manifestlib.family_of(p) == i + 1
              for i, p in enumerate(made["list_rows"])),
          str([manifestlib.family_of(p) for p in made["list_rows"]]))
    reg = manifestlib.load_registry(depot_ws)
    check("the registry gets the dxt row",
          reg.get("/vehicles/common/rrmod_test_page.dxt.dds.z") is not None,
          "/vehicles/common/rrmod_test_page.dxt.dds.z")

    # and it is recorded as ours, not as the game's
    state = depslib.status(depot_ws, "common/rrmod_test_page")
    check("the new page is recorded", state["brought_by"] == ["<this mod>"],
          str(state["brought_by"]))
    check("and it is not called shipped", state["shipped"] is False,
          str(state["shipped"]))
    check("a page nothing names is an orphan",
          any(o["stem"] == "common/rrmod_test_page"
              for o in depslib.orphans(depot_ws)),
          str(depslib.orphans(depot_ws)))
    check("the game's own pages never become orphans",
          all(o["stem"] != "common/car_windows_04"
              for o in depslib.orphans(depot_ws)), "car_windows_04 listed")

    # adding it twice is not an error and does not double the rows
    again = editlib.add_common_page(ws_root, page_src, stem="rrmod_test_page",
                                    log=lambda _m: None)
    check("adding the same page twice adds no rows",
          again.get("list_rows") is None, str(again.get("list_rows")))
    check("and the list did not grow",
          len(manifestlib.load_asset_list(ws_root, leaf)) == len(after),
          str(len(manifestlib.load_asset_list(ws_root, leaf))))

    # the game's own pages are refused, whatever names them
    try:
        editlib.remove_common_page(ws_root, "common/car_windows_04")
        check("a shipped page cannot be removed", False, "no error")
    except editlib.EditError as exc:
        check("a shipped page cannot be removed",
              "game's own" in str(exc), str(exc))
    # a page somebody still names is refused without force.  Point the mini
    # car's window slot at the test page so it really is in use - the mini
    # install has no livery table naming a shared page on its own.
    lv = liverylib.load_car(depot_ws, CAR)
    lv.set_texture(3, b"common/rrmod_test_page.dxt.dds.z")
    liverylib.save(lv, os.path.join(depot_ws, "vehicles", "data", "liveries",
                                    f"{CAR}.liveries.bin.nct"))
    depslib.forget()
    check("the test page is now in use",
          depslib.live_owners(depot_ws, "common/rrmod_test_page") == [CAR],
          str(depslib.live_owners(depot_ws, "common/rrmod_test_page")))
    try:
        editlib.remove_common_page(ws_root, "common/rrmod_test_page")
        check("a page still named is refused", False, "no error")
    except editlib.EditError as exc:
        check("a page still named is refused",
              "still named by" in str(exc), str(exc))
    gone = editlib.remove_common_page(ws_root, "common/rrmod_test_page",
                                      force=True)
    check("force removes it anyway", gone["files"], str(gone["files"]))
    check("and its four rows go with it", len(gone["rows"]) == 4,
          str(len(gone["rows"])))
    check("the list is back to its old length",
          len(manifestlib.load_asset_list(ws_root, leaf)) == len(before),
          str(len(manifestlib.load_asset_list(ws_root, leaf))))
    check("and the registry row is gone too",
          manifestlib.load_registry(depot_ws).get(
              "/vehicles/common/rrmod_test_page.dxt.dds.z") is None,
          "registry still lists it")
    check("the record is dropped",
          "common/rrmod_test_page" not in depslib.load(depot_ws)["pages"],
          str(sorted(depslib.load(depot_ws)["pages"])))
    os.remove(page_src)

    print("65 a name the game has never heard of can be added to the slot table")
    # A hand made wing has a mesh name the string table has no slot for, and the
    # engine looks the *whole* mesh name up: no slot, no material.  Slots are
    # positions, so the only safe change is appending.
    table_path = liverylib.slot_table_path(depot_ws)
    plain_before = nctlib.read(table_path)
    # The whole file, not just its plain payload: edits go straight into the
    # install now, so "put the install's copy back" has to be a write of the
    # bytes this group found, not a copy from somewhere else - there is no
    # somewhere else any more.
    with open(table_path, "rb") as fh:
        table_bytes = fh.read()
    table = liverylib.load_slot_table(depot_ws)
    check("the slot table reads", len(table) > 2000, str(len(table)))
    check("and it round trips byte for byte",
          liverylib.serialize_slot_table(table) == plain_before,
          f"{len(liverylib.serialize_slot_table(table))} vs {len(plain_before)}")
    was = len(table)
    # names the game has never heard of: a hand made wing the exporter gave a
    # mesh name of its own.  The two the game already knows must be reported as
    # known, not appended a second time.
    made_up = ["LOD_A_RRMOD_WING_mm_ext", "LOD_A_RRMOD_FLAP_mm_misc"]
    check("a name the game knows is not appended again",
          table.part_slot("LOD_A_WING_REAR_mm_ext") == 745,
          str(table.part_slot("LOD_A_WING_REAR_mm_ext")))
    out = editlib.add_slot_names(ws_root, made_up, log=lambda _m: None)
    check("two names were appended", len(out["added"]) == 2, str(out["added"]))
    check("they land at the end", out["slots"][made_up[0]] == was,
          str(out["slots"]))
    check("the table grew by two", out["after"] == was + 2, str(out["after"]))
    reread = liverylib.load_slot_table(depot_ws)
    check("the new names can be looked up",
          reread.part_slot(made_up[1]) == was + 1,
          str(reread.part_slot(made_up[1])))
    check("and the old slots did not move",
          reread[0] == table[0] and reread[was - 1] == table[was - 1],
          f"{reread[0]} / {reread[was - 1]}")
    twice = editlib.add_slot_names(ws_root, [made_up[0]], log=lambda _m: None)
    check("adding a name twice changes nothing",
          twice["added"] == [] and twice["saved"] is False, str(twice))
    check("the table is still one name longer than before",
          len(liverylib.load_slot_table(depot_ws)) == was + 2,
          str(len(liverylib.load_slot_table(depot_ws))))
    # put the real table back so later groups see the install's own slots
    with open(table_path, "wb") as fh:
        fh.write(table_bytes)
    check("the table is the install's again",
          nctlib.read(table_path) == plain_before,
          f"{len(nctlib.read(table_path))} vs {len(plain_before)}")

    print("66 a push can be taken back, and only what it overwrote is kept")
    # A full copy of an install is 10.43 GB; a car mod is a few dozen files.  So
    # the device's own bytes are kept for exactly the files a push overwrites -
    # and the asset lists count, because a car that was put back but still had
    # its rows in the lists would stay in the menus pointing at nothing.
    from rrmod import backup as backuplib

    # a device that keeps its files in a dict: enough for pull, push, exists
    class FakeDevice:
        def __init__(self):
            self.files = {}

        def run(self, *args):
            cmd = args[0]
            if cmd == "pull":
                src, dest = args[1], args[2]
                leaf = src.rsplit("/files/", 1)[-1]
                os.makedirs(os.path.dirname(os.path.abspath(dest)), exist_ok=True)
                data = self.files.get(leaf)
                if data is None:
                    return type("R", (), {"returncode": 1, "stdout": "",
                                          "stderr": "not there"})()
                with open(dest, "wb") as fh:
                    fh.write(data)
                return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
            if cmd == "push":
                local, remote = args[1], args[2]
                leaf = remote.rsplit("/files/", 1)[-1]
                with open(local, "rb") as fh:
                    self.files[leaf] = fh.read()
                return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
            return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

        def push(self, local, remote_rel, *, lock=False):
            with open(local, "rb") as fh:
                self.files[remote_rel] = fh.read()
            return {"local": local, "remote": remote_rel,
                    "size": os.path.getsize(local), "locked": lock}

        def exists(self, remote_rel):
            return remote_rel in self.files

        def remove(self, remote_rel, *, tree=False):
            self.files.pop(remote_rel, None)

        def stop(self):
            return None

    dev = FakeDevice()
    # the install's copy of a car file, and a file only the device has
    car_rel = f".depot/vehicles/{CAR}/{CAR}_a.m3g"
    dev.files[car_rel] = b"the device's own body"
    dev.files[".depot/vehicles/data/liveries/liveryStringTable.bin.nct"] = \
        b"the device's own slot table"
    plan = [(os.path.join(MINI, "x"), car_rel, False),
            (os.path.join(MINI, "y"),
             ".depot/vehicles/data/liveries/liveryStringTable.bin.nct", True),
            (os.path.join(MINI, "z"), f".depot/vehicles/{CAR}/{CAR}_wing.banim",
             False)]

    taken = backuplib.take(dev, MINI, plan, title="Wing test", log=lambda _m: None)
    check("a push is remembered under a name", bool(taken["id"]), str(taken))
    check("and it names what it touched", len(taken["files"]) == 3,
          str(taken["files"]))
    check("a file the device has is copied", any(
        not row[3] for row in taken["files"]), str(taken["files"]))
    check("a file the device lacks is marked absent", any(
        row[3] for row in taken["files"] if row[0].endswith(".banim")),
        str(taken["files"]))
    check("the copy on disk is the device's own bytes",
          open(os.path.join(taken["folder"], *car_rel.split("/")), "rb"
               ).read() == b"the device's own body", "not the device's bytes")
    check("the stack has one push",
          backuplib.summary(MINI)["pushes"] == 1,
          str(backuplib.summary(MINI)))

    # the push lands, then the button takes it back
    dev.files[car_rel] = b"a modded body"
    dev.files[f".depot/vehicles/{CAR}/{CAR}_wing.banim"] = b"a new wing clip"
    dev.files[".depot/vehicles/data/liveries/liveryStringTable.bin.nct"] = \
        b"a modded slot table"
    back = backuplib.restore(dev, MINI, log=lambda _m: None)
    check("restoring puts the device's files back",
          dev.files[car_rel] == b"the device's own body", str(dev.files[car_rel]))
    check("and the list it overwrote too",
          dev.files[".depot/vehicles/data/liveries/liveryStringTable.bin.nct"]
          == b"the device's own slot table",
          str(dev.files[".depot/vehicles/data/liveries/liveryStringTable.bin.nct"]))
    check("a file the push created is deleted",
          f".depot/vehicles/{CAR}/{CAR}_wing.banim" not in dev.files,
          str(sorted(dev.files)))
    check("two files went back and one went away",
          (back["restored"], back["removed"]) == (2, 1), str(back))
    check("the stack is empty again", back["left"] == 0, str(back["left"]))

    # last in, first out: a second push over the same file must come off first
    dev.files[car_rel] = b"the device's own body"
    first = backuplib.take(dev, MINI, [(os.path.join(MINI, "x"), car_rel, False)],
                           title="first", log=lambda _m: None)
    dev.files[car_rel] = b"after the first mod"
    second = backuplib.take(dev, MINI, [(os.path.join(MINI, "x"), car_rel, False)],
                            title="second", log=lambda _m: None)
    dev.files[car_rel] = b"after the second mod"
    try:
        backuplib.restore(dev, MINI, first["id"], log=lambda _m: None)
        check("an older push cannot come off first", False, "no error")
    except backuplib.BackupError as exc:
        check("an older push cannot come off first",
              "went on before" in str(exc), str(exc))
    out2 = backuplib.restore(dev, MINI, log=lambda _m: None)
    check("the newer one comes off first and gets the middle version",
          dev.files[car_rel] == b"after the first mod", str(dev.files[car_rel]))
    out1 = backuplib.restore(dev, MINI, log=lambda _m: None)
    check("then the older one gets the original back",
          dev.files[car_rel] == b"the device's own body", str(dev.files[car_rel]))
    check("and the stack is empty", (out2["left"], out1["left"]) == (1, 0),
          f"{out2['left']} / {out1['left']}")

    # a push that was forgotten frees its copies and leaves the stack alone
    dev.files[car_rel] = b"the device's own body"
    keep1 = backuplib.take(dev, MINI, [(os.path.join(MINI, "x"), car_rel, False)],
                           log=lambda _m: None)
    keep2 = backuplib.take(dev, MINI, [(os.path.join(MINI, "x"), car_rel, False)],
                           log=lambda _m: None)
    got = backuplib.forget(MINI, keep1["id"])
    check("forgetting drops one entry", got["left"] == 1, str(got))
    check("and frees the bytes it held", got["freed"] > 0, str(got["freed"]))
    check("its folder is gone",
          not os.path.isdir(os.path.join(backuplib.backup_root(MINI),
                                         keep1["id"])), keep1["id"])
    check("the newer one is still there",
          backuplib.top(MINI)["id"] == keep2["id"], str(backuplib.top(MINI)))
    backuplib.forget(MINI, keep2["id"])
    check("an empty stack refuses to restore",
          not backuplib.pushes(MINI), str(backuplib.pushes(MINI)))
    try:
        backuplib.restore(dev, MINI, log=lambda _m: None)
        check("nothing to take back is an error", False, "no error")
    except backuplib.BackupError as exc:
        check("nothing to take back is an error",
              "nothing has been pushed" in str(exc), str(exc))
    try:
        backuplib.take(dev, MINI, [], log=lambda _m: None)
        check("an empty plan is refused", False, "no error")
    except backuplib.BackupError as exc:
        check("an empty plan is refused", "plan is empty" in str(exc), str(exc))

    print("67 a slot can be pointed at a page the game already ships")
    # A different tyre, disc or interior weave needs no new bytes at all: the
    # pages are already in vehicles/common, so only the livery row changes.  The
    # picker narrows the list to the same *kind* of page, because a tyre page in
    # a window slot is not a cosmetic mistake - it draws the wrong material.
    pages = texpages.shipped_pages(ws_root, "common/car_windows_04.ptc.pvr.z")
    check("the windows slot is offered the windows pages",
          pages and all(r["kind"] == "windows" for r in pages),
          str(sorted({r["kind"] for r in pages})))
    check("and not the tyre pages",
          not any("tyre" in r["stem"] for r in pages), str(len(pages)))
    interior = texpages.shipped_pages(ws_root,
                                    "common/carbon_fibre_black_mat00.ptc.pvr.z")
    check("an interior slot only gets its own slot's pages",
          interior and all(r["kind"] == "mat00" for r in interior),
          str(sorted({r["kind"] for r in interior})))
    check("a slot that names nothing gets everything",
          len(texpages.shipped_pages(MINI, "")) >= 10,
          str(len(texpages.shipped_pages(MINI, ""))))
    check("the page the car already names is marked as its kind",
          all(r["now"] for r in pages), str(len(pages)))

    before = liverylib.load_car(depot_ws, CAR).texture_of(13)
    # the bytes as this group found them: edits land in the install, so putting
    # the car's own table back means writing these, not copying from the depot
    # the install was built from.
    with open(os.path.join(depot_ws, "vehicles", "data", "liveries",
                           f"{CAR}.liveries.bin.nct"), "rb") as fh:
        livery_bytes = fh.read()
    got = editlib.set_texture_slot_page(ws_root, CAR, 13,
                                        "common/stitching_red_mat02")
    # The livery this car came with names ``.ptc.pvr.z`` - it was authored for
    # the PTC build - but this depot's shared folder holds the DXT set.  Writing
    # the family the row inherited would point the slot at a file nobody has, so
    # the file that is really on disk decides it.
    check("the slot now names the other page",
          got["page"] == "common/stitching_red_mat02.dxt.dds.z", str(got["page"]))
    check("and the family follows the file on disk, not the name it inherited",
          got["page"].endswith(".dxt.dds.z"), got["page"])
    check("the file on disk is named too", got["on_disk"].startswith(
        "vehicles/common/"), got["on_disk"])
    check("the row changed", got["changed"] == ["(every scheme)"],
          str(got["changed"]))
    again = liverylib.load_car(depot_ws, CAR).texture_of(13)
    check("the table really holds it",
          again == b"common/stitching_red_mat02.dxt.dds.z", str(again))
    check("and it is not what it was", again != before, str(before))
    table_rel = f"/vehicles/data/liveries/{CAR}.liveries.bin.nct"
    reg = manifestlib.parse_registry(nctlib.read(os.path.join(
        depot_ws, "asset_list_base.txtCache.txt")))
    check("the registry holds the table's new hash",
          reg.get(table_rel) == manifestlib.md5_file(os.path.join(
              depot_ws, "vehicles", "data", "liveries",
              f"{CAR}.liveries.bin.nct")),
          f"{reg.get(table_rel)}")
    check("nothing new was copied into the car's folder",
          not any("stitching" in f for f in os.listdir(
              os.path.join(depot_ws, "vehicles", CAR, "livery"))),
          str(sorted(os.listdir(os.path.join(depot_ws, "vehicles", CAR,
                                             "livery")))[:4]))
    twice = editlib.set_texture_slot_page(ws_root, CAR, 13,
                                          "common/stitching_red_mat02")
    check("pointing it at the same page again changes nothing",
          twice["changed"] == [] and "saved" not in twice, str(twice))
    for bad, why in (("common/no_such_page", "holds no page"),
                     ("livery/some_page", "not a page of vehicles/common")):
        try:
            editlib.set_texture_slot_page(ws_root, CAR, 13, bad)
            check(f"{bad} is refused", False, "no error")
        except editlib.EditError as exc:
            check(f"{bad} is refused", why in str(exc), str(exc))
    try:
        editlib.set_texture_slot_page(ws_root, CAR, 99999,
                                      "common/car_windows_04")
        check("a slot the table does not have is refused", False, "no error")
    except editlib.EditError as exc:
        check("a slot the table does not have is refused",
              "not in the livery string table" in str(exc), str(exc))
    # one scheme only: the car-wide row stays where it was
    per = editlib.set_texture_slot_page(ws_root, CAR, 13,
                                        "common/carbon_fibre_black_mat00",
                                        paint=0)
    check("one scheme can be pointed on its own",
          len(per["changed"]) == 1, str(per["changed"]))
    L = liverylib.load_car(depot_ws, CAR)
    check("the other schemes keep the car-wide page",
          L.texture_of(13) == b"common/stitching_red_mat02.dxt.dds.z",
          str(L.texture_of(13)))
    check("and that one scheme reads the new page",
          L.paints[0].texture_of(13) ==
          b"common/carbon_fibre_black_mat00.dxt.dds.z",
          str(L.paints[0].texture_of(13)))
    # put the table back so later groups see the install's own rows
    with open(os.path.join(depot_ws, "vehicles", "data", "liveries",
                           f"{CAR}.liveries.bin.nct"), "wb") as fh:
        fh.write(livery_bytes)
    check("the car is back to the install's own table",
          liverylib.load_car(depot_ws, CAR).texture_of(13) == before,
          str(liverylib.load_car(depot_ws, CAR).texture_of(13)))

    print("68 the dependencies page shows what needs each shared page")
    # Two questions kept apart: who names a page *now* (a live scan of all 540
    # livery tables, never cached) and who *brought* it (deps.json, because
    # nothing on disk records that).  Only a page this program added that nothing
    # names any more may be deleted - a shipped page never, however unused.
    try:
        from rrmod.ui import depsui as depsuilib

        page = depsuilib.DepsPage()
        check("the page builds", page.table.columnCount() == 5,
              str(page.table.columnCount()))
        check("it has no depot to read yet", page.depot == "", page.depot)
        page.load("", "")
        check("loading nothing leaves it empty", page.rows == [], str(page.rows))
        # the real thing, against the mini install.  The page does its reading on
        # a worker thread, so the test drives the two halves itself rather than
        # waiting on a thread the event loop has to schedule.
        page.load(depot_ws, ws_root)
        page._loaded(page._gather())
        check("it read the livery tables", len(page.rows) > 10,
              str(len(page.rows)))
        check("the summary counts the pages", "page(s) named" in page.summary.text(),
              page.summary.text()[:60])
        check("it knows which pages are the game's own",
              any(r["shipped"] for r in page.rows),
              str(sum(1 for r in page.rows if r["shipped"])))
        check("the shipped pages come from vehicles/common",
              all(r["stem"].startswith("common/")
                  for r in page.rows if r["shipped"]),
              str([r["stem"] for r in page.rows if r["shipped"]][:3]))
        check("a page in use says how many cars name it",
              any(r["count"] for r in page.rows),
              str([r["count"] for r in page.rows][:5]))
        check("nothing is an orphan yet", page.orphan_rows == [],
              str(page.orphan_rows))
        # add a page of our own to the working copy, then let the last car stop
        # naming it.  The working copy is the one that knows which install it
        # belongs to, so "is this the game's own page?" gets the right answer
        # there; asking about the install folder itself would say yes to
        # everything, because a minute ago it was not there and now it is.
        src = os.path.join(MINI, ".depot", "vehicles", "common",
                           "car_windows_04.dxt.dds.z")
        added = editlib.add_common_page(ws_root, src, stem="rrmod_test_page",
                                        log=lambda _m: None)
        check("the page was added", added["stem"] == "common/rrmod_test_page",
              str(added))
        lv = liverylib.load_car(depot_ws, CAR)
        lv.set_texture(3, b"common/rrmod_test_page.ptc.pvr.z")
        liverylib.save(lv, os.path.join(depot_ws, "vehicles", "data", "liveries",
                                        f"{CAR}.liveries.bin.nct"))
        depslib.forget()
        check("while a car names it, it is not an orphan",
              not any(r["stem"] == "common/rrmod_test_page"
                      for r in depslib.orphans(depot_ws)),
              str([r["stem"] for r in depslib.orphans(depot_ws)]))
        check("and it is recorded as this program's",
              depslib.status(depot_ws, "common/rrmod_test_page")["brought_by"]
              == ["<this mod>"],
              str(depslib.status(depot_ws, "common/rrmod_test_page")))
        lv = liverylib.load_car(depot_ws, CAR)
        lv.set_texture(3, b"common/car_windows_04.ptc.pvr.z")
        liverylib.save(lv, os.path.join(depot_ws, "vehicles", "data", "liveries",
                                        f"{CAR}.liveries.bin.nct"))
        depslib.forget()
        orphan = depslib.orphans(depot_ws)
        check("once nothing names it, it is an orphan",
              any(r["stem"] == "common/rrmod_test_page" for r in orphan),
              str([r["stem"] for r in orphan]))
        # the page the panel offers to delete is the one it may delete
        page.load(depot_ws, ws_root)
        page._loaded(page._gather())
        check("the panel lists it", any(r["stem"] == "common/rrmod_test_page"
                                        for r in page.orphan_rows),
              str([r["stem"] for r in page.orphan_rows]))
        page.orphans.selectRow(0)
        check("and the delete button turns on", page.forget_btn.isEnabled(),
              "the button stayed off")
        gone = editlib.remove_common_page(ws_root, "common/rrmod_test_page")
        check("deleting it takes the file and its rows",
              len(gone["files"]) == 1 and len(gone["rows"]) == 4, str(gone))
        check("and the registry row too", gone["registry"] >= 0, str(gone))
        check("it is gone from the disk",
              not os.path.isfile(os.path.join(depot_ws, "vehicles",
                                              "common",
                                              "rrmod_test_page.dxt.dds.z")),
              "still there")
        try:
            editlib.remove_common_page(ws_root, "common/car_windows_04")
            check("a page the game ships is never deleted", False, "no error")
        except editlib.EditError as exc:
            check("a page the game ships is never deleted",
                  "game's own" in str(exc), str(exc))
        check("the missing pages are named, not repaired",
              all("common/" in s for s in depslib.missing(depot_ws)),
              str(depslib.missing(depot_ws)))
    except ImportError as exc:
        check("the dependencies page can be imported", False, str(exc))

    # ---- 69 a pack remembers what it needs ------------------------------
    print("69  a pack is one file and a list of what it needs")
    try:
        pack_dir = os.path.join(ROOT, "work", "rrmod_test_pack")
        shutil.rmtree(pack_dir, ignore_errors=True)
        os.makedirs(pack_dir, exist_ok=True)
        inv = depotlib.scan(MINI)
        car = CAR

        # The manifest is built from named parts, and every part is validated:
        # a pack that names a kind nobody knows is refused rather than written.
        made = modlib.make(kind="car", name=car, files=[("vehicles/x", "x")],
                           requires=["base_car"])
        check("a bare requirement becomes a car", 
              made["requires"] == [{"kind": "car", "name": "base_car"}],
              str(made["requires"]))
        check("the format is written down", made["format"] == modlib.FORMAT,
              str(made.get("format")))
        for bad, why in ((dict(kind="nonsense", name=car), "kind"),
                         (dict(kind="car", name=""), "name"),
                         (dict(kind="car", name=car,
                               requires=[{"kind": "nonsense", "name": "x"}]),
                          "requirement")):
            try:
                modlib.make(files=[], **bad)
                check(f"a pack with a bad {why} is refused", False, "no error")
            except modlib.PackError:
                check(f"a pack with a bad {why} is refused", True)

        # A format 1 share - what this program wrote before packs existed - is
        # read as a car pack, so old files keep working.
        old = {"format": 1, "kind": "replace", "name": car, "base": car,
               "files": ["vehicles/x"]}
        got = modlib.upgrade(old, "old.rr3mod")
        check("a share from before packs is read as a car pack",
              got["kind"] == "car" and got["format"] == 2, str(got["kind"]))
        check("and its base becomes a requirement",
              got["requires"] == [{"kind": "car", "name": car}],
              str(got["requires"]))
        try:
            modlib.upgrade({"format": 9, "kind": "car", "name": car}, "new")
            check("a newer format is refused by name", False, "no error")
        except modlib.PackError as exc:
            check("a newer format is refused by name", "format 9" in str(exc),
                  str(exc))

        # Publishing a car: the folder, its spec, its livery table, and any
        # shared page it names that the game does not ship.
        out = os.path.join(pack_dir, f"{car}.rr3mod")
        plan = publishlib.car_plan(MINI, car)
        check("a car plan finds the car's files", plan["count"] > 3,
              f"{plan['count']} file(s)")
        check("and it needs the car it was built from",
              any(r["kind"] == "car" and r["name"] == car
                  for r in plan["requires"]), str(plan["requires"]))
        made = publishlib.car(MINI, car, out, note="a test", log=lambda m: None)
        check("the pack is written", os.path.isfile(out), "no file")
        check("and it is a zip", zipfile.is_zipfile(out), "not a zip")
        with zipfile.ZipFile(out) as zf:
            names = zf.namelist()
            manifest = json.loads(zf.read(modlib.MANIFEST))
        check("the manifest travels inside it", modlib.MANIFEST in names,
              str(names[:3]))
        check("the files keep their game paths",
              any(n.startswith(modlib.PREFIX + "vehicles/") for n in names),
              str(names[:3]))
        check("the note is kept", manifest["note"] == "a test",
              str(manifest.get("note")))

        info = modlib.check(MINI, out)
        check("reading it back names the car", info["name"] == car, info["name"])
        check("a pack whose car is here is ready", info["state"] == "ready",
              f"{info['state']}: {info['problems']}")
        check("nothing it needs is missing", not info["unsatisfied"],
              str(info["unsatisfied"]))

        # A requirement nothing can satisfy is reported, not silently ignored.
        # The pack has to carry a file that is really here, because "missing"
        # means "installed but cannot work" - a pack with nothing in it is
        # merely absent.
        real = os.path.join(MINI, ".depot", "vehicles", car, f"{car}_a.m3g")
        missing = modlib.make(kind="car", name=car,
                              files=[(f"vehicles/{car}/{car}_a.m3g", real)],
                              requires=[{"kind": "driver", "name": "nope.banim"}])
        lonely = os.path.join(pack_dir, "lonely.rr3mod")
        modlib.write(lonely, missing,
                     [(f"vehicles/{car}/{car}_a.m3g", real)],
                     log=lambda m: None)
        bad = modlib.check(MINI, lonely)
        check("a pack that needs something absent says so",
              bad["state"] == "missing" and len(bad["unsatisfied"]) == 1,
              f"{bad['state']} {bad['unsatisfied']}")
        check("and it names the thing", 
              bad["unsatisfied"][0]["name"] == "nope.banim",
              str(bad["unsatisfied"]))

        # Installing writes the files into the game folder and records the step.
        from rrmod.ui import editing as editinglib

        ws_root = editinglib.Editor(MINI).root
        done = publishlib.install(ws_root, out, log=lambda m: None)
        check("installing writes the files", done["written"] > 3,
              str(done["written"]))
        check("and the car's body is there",
              os.path.isfile(os.path.join(
                  ws_root, ".depot", "vehicles", car, f"{car}_a.m3g")),
              "no body")
        touched = {rel for stamp in historylib.stamps(ws_root)
                   for rel in historylib.files(ws_root, stamp)}
        check("and the files are in the undo history",
              any(rel.endswith(f"{car}_a.m3g") for rel in touched),
              str(sorted(touched)[:3]))
        after = modlib.check(ws_root, out)
        check("a pack that is installed says so", after["installed"],
              str(after["state"]))
        # Installing the same pack twice has to land the same bytes: a pack is a
        # snapshot, so a second install must not drift.
        body = os.path.join(ws_root, ".depot", "vehicles", car, f"{car}_a.m3g")
        first = open(body, "rb").read()
        publishlib.install(ws_root, out, log=lambda m: None)
        check("installing it again writes the same bytes",
              open(body, "rb").read() == first, "the bytes changed")

        # The scan counts what is in a folder.
        scan = modlib.scan(MINI, pack_dir)
        check("a folder of packs is counted", scan["counts"]["ready"] >= 1,
              str(scan["counts"]))
        check("and the ones that cannot work are counted apart",
              scan["counts"]["missing"] >= 1, str(scan["counts"]))
    except ImportError as exc:
        check("packs can be imported", False, str(exc))

    # ---- 70 which pages each program shows -----------------------------
    print("70  the studio and the manager are one build")
    try:
        check("there are three profiles",
              set(profilelib.PROFILES) == {"studio", "manager", "both"},
              str(profilelib.PROFILES))
        studio = set(profilelib.pages("studio"))
        manager = set(profilelib.pages("manager"))
        both = set(profilelib.pages("both"))
        check("the studio does not show the manager's pages",
              not (studio & {"music", "gfx", "deploy"}), str(sorted(studio)))
        check("the manager does not show the studio's pages",
              not (manager & {"career", "brands", "publish"}),
              str(sorted(manager)))
        check("both shows everything", both == set(profilelib.ORDER),
              str(sorted(both - set(profilelib.ORDER))))
        check("they share the pages that describe a car",
              {"cars", "materials", "deps", "about"} <= studio & manager,
              str(sorted(studio & manager)))
        check("nothing is in one profile and not in both",
              studio <= both and manager <= both, "a page is only in one")
        check("the studio is titled differently",
              profilelib.title("studio") != profilelib.title("manager"),
              profilelib.title("studio"))
        try:
            profilelib.check("nonsense")
            check("a profile nobody knows is refused", False, "no error")
        except profilelib.ProfileError:
            check("a profile nobody knows is refused", True)
    except ImportError as exc:
        check("profiles can be imported", False, str(exc))

    # ---- 71 a material can be copied and only a copy deleted -------------
    print("71  a material is a block, and a copy is appended not edited")
    # A material is a run of records with no length prefix of its own, so a field
    # cannot be edited in place - one byte out of step and every block after it is
    # read wrong.  Appending a whole block at the end of the material table is the
    # only edit that cannot move an offset, and deleting one only ever removes a
    # block this program put there.
    try:
        from rr3lib import gamematerial as gamelib
        from rrmod.ui import matui as matuilib

        editor = editinglib.Editor(MINI)
        mat_root = editor.for_materials()
        ws_root = editor.root
        mat_depot = os.path.join(ws_root, ".depot")
        mat_path = os.path.join(mat_depot, *gamelib.MATERIALS_BIN.split("/"))
        check("the library is mirrored into the working copy",
              os.path.isfile(mat_path), mat_path)
        raw = open(mat_path, "rb").read()
        recs = gamelib.load_records(mat_path)
        check("the record stream round trips",
              gamelib.encode_records(recs) == raw, "reassembly differs")
        spans = gamelib.block_spans(recs)
        named = [n for _a, _b, n in spans if n]
        check("every block is found, named or not",
              len(spans) == len(named) + 1, f"{len(spans)} spans")
        check("the game's own paint is one of them",
              "car_paint_matte" in named, str(named[:3]))

        added = editlib.add_material(ws_root, "car_paint_matte",
                                     "rrmod_test_paint", log=lambda _m: None)
        check("the copy is appended, not spliced",
              added["added"] > 0 and os.path.getsize(mat_path) > len(raw),
              str(added.get("added")))
        check("and it gets a livery slot of its own",
              added["slot"] is not None, str(added.get("slot_error") or added))
        check("the slot is in the table",
              liverylib.load_slot_table(mat_depot).slot("rrmod_test_paint")
              == added["slot"], "the table disagrees")
        check("the copy reads back as a material",
              "rrmod_test_paint"
              in {n for _a, _b, n in gamelib.block_spans(gamelib.load_records(mat_path))},
              "not in the table")
        lib = gamelib.load(mat_depot)
        check("and it draws through the shader it was copied from",
              lib.shader_for("rrmod_test_paint") is not None,
              "no shader binding")
        check("the original is still there",
              lib.material("car_paint_matte") is not None, "gone")

        try:
            editlib.add_material(ws_root, "car_paint_matte", "rrmod_test_paint")
            check("a name already taken is refused", False, "no error")
        except editlib.EditError as exc:
            check("a name already taken is refused",
                  "already a material" in str(exc), str(exc))
        try:
            editlib.add_material(ws_root, "no_such_material", "rrmod_test_other")
            check("a source nobody has is refused", False, "no error")
        except editlib.EditError as exc:
            check("a source nobody has is refused",
                  "there is no material called" in str(exc), str(exc))
        try:
            editlib.add_material(ws_root, "car_paint_matte", "  ")
            check("a copy needs a name", False, "no error")
        except editlib.EditError as exc:
            check("a copy needs a name", "needs a name" in str(exc), str(exc))
        try:
            editlib.remove_material(ws_root, "car_paint_matte")
            check("the game's own material is never removed", False, "no error")
        except editlib.EditError as exc:
            check("the game's own material is never removed",
                  "game's own" in str(exc), str(exc))

        # a pack carries only the copies, and installing it merges rather than
        # replacing, so two people who each cloned one end up with both.
        clones = publishlib.cloned_materials(ws_root)
        check("the copy is the only one this working copy added",
              clones == ["rrmod_test_paint"], str(clones))
        pack_root = os.path.join(ROOT, "work", "rrmod_test_material")
        os.makedirs(pack_root, exist_ok=True)
        mat_pack = os.path.join(pack_root, "one_material.rr3mod")
        made = publishlib.materials(ws_root, ["rrmod_test_paint"], mat_pack,
                                    note="one material", log=lambda _m: None)
        check("the pack is one file", len(made["manifest"]["files"]) == 1,
              str(made["manifest"]["files"]))
        info = modlib.check(ws_root, mat_pack)
        check("and it says it is ready", info["state"] == "ready", str(info["state"]))
        check("a material the game shipped is not publishable",
              _raises(publishlib.PublishError, publishlib.materials, ws_root,
                      ["car_paint_matte"], os.path.join(pack_root, "no.rr3mod")),
              "no error")

        gone = editlib.remove_material(ws_root, "rrmod_test_paint")
        check("a copy can be deleted", gone["material"] == "rrmod_test_paint",
              str(gone.get("material")))
        check("and the library is back to its own size",
              os.path.getsize(mat_path) == len(raw),
              f"{os.path.getsize(mat_path)} vs {len(raw)}")
        check("with the name gone from the table",
              "rrmod_test_paint" not in publishlib.cloned_materials(ws_root),
              str(publishlib.cloned_materials(ws_root)))
        got = publishlib.install(ws_root, mat_pack, log=lambda _m: None)
        check("installing the pack puts the copy back",
              got["materials"] == ["rrmod_test_paint"], str(got))
        again = publishlib.install(ws_root, mat_pack, log=lambda _m: None)
        check("installing it twice adds nothing the second time",
              again["materials"] == [], str(again))

        # the page: a copy is the only thing it will delete
        page = matuilib.MaterialsPage()
        page.attach(editor)
        page.depot = editor.depot
        page._loaded(page._gather())
        check("the page reads the working copy",
              page._row_of("rrmod_test_paint") is not None,
              "the new row is missing from its own list")
        check("it knows the copy is ours",
              page._is_ours("rrmod_test_paint"), "called it the game's")
        check("and that the game's own is not",
              not page._is_ours("car_paint_matte"), "called it ours")

        from rrmod.ui import publishui as publishuilib

        kinds = [key for key, _label in publishuilib.KIND_LABELS]
        check("the publish page offers materials", "material" in kinds, str(kinds))
        check("and the pack kinds agree with it",
              set(kinds) <= set(publishlib.KINDS), str(sorted(set(kinds)
                                                              - set(publishlib.KINDS))))

        editlib.remove_material(ws_root, "rrmod_test_paint")
        shutil.rmtree(pack_root, ignore_errors=True)
    except ImportError as exc:
        check("materials can be written", False, str(exc))

    print()
    print("72  a car can be given another driver pose, and told what it costs")
    # The seated pose is a field in the car's data record, not in its spec, and
    # the record is a stream of self describing tokens: the field is the
    # thirteenth token after the CAR_NAME_ string, which is why it is walked
    # rather than found by offset.  A pose with no low-poly model of its own
    # still loads, so the editor reports it and never refuses on that ground.
    try:
        from rrmod.ui import animui as animuilib

        drv_editor = editinglib.Editor(MINI)
        drv_root = drv_editor.for_car(CAR)
        drv_depot = os.path.join(drv_root, ".depot")
        record = os.path.join(drv_depot, "vehicles", "data", SPEC)

        poses = drvlib.banims(editlib._driver_dir(drv_root))
        check("the install ships thirty-six poses", len(poses) == 36, str(len(poses)))
        check("the working copy borrows the install's driver folder",
              editlib._driver_dir(drv_root)
              == os.path.join(MINI, ".depot"),
              editlib._driver_dir(drv_root))
        check("and reading them copies nothing",
              not any("/driver/" in rel
                      for s in historylib.stamps(MINI)
                      for rel in historylib.files(MINI, s)),
              "something was written into the driver folder")

        state = animlib.driver_state(drv_root, CAR)
        check("the car names no pose of its own", state["banim"] == "",
              str(state["banim"]))
        check("so the picker offers the generic one too",
              state["choices"] and state["choices"][0] == "driver",
              str(state["choices"][:2]))
        check("and its record is found", state["record"].endswith(SPEC),
              state["record"])

        before = open(record, "rb").read()
        got = editlib.set_driver_pose(drv_root, CAR, "driver_atom")
        check("a pose can be written", got["changed"], str(got))
        check("and reads back", got["after"] == "driver_atom.banim", got["after"])
        check("a pose with no model of its own says so", got["low_poly"] == "",
              got["low_poly"])
        check("writing the same pose again changes nothing",
              not editlib.set_driver_pose(drv_root, CAR, "driver_atom")["changed"],
              "it rewrote the file")

        owned = editlib.set_driver_pose(drv_root, CAR, "driver_919_lmp1")
        check("a pose that has a model of its own says which",
              owned["low_poly"].endswith("driver_lod_c_919_lmp1.m3g"),
              owned["low_poly"])

        check("a pose the game does not ship is refused",
              _raises(editlib.EditError, editlib.set_driver_pose, drv_root, CAR,
                      "driver_nope"), "no error")
        check("a name that is not a banim is refused",
              _raises(editlib.EditError, editlib.set_driver_pose, drv_root, CAR,
                      "not a name"), "no error")
        check("a car that is not installed is refused",
              _raises(editlib.EditError, editlib.set_driver_pose, drv_root,
                      "no_such_car", "driver_atom"), "no error")

        cleared = editlib.set_driver_pose(drv_root, CAR, "")
        check("the pose can be cleared again", cleared["changed"]
              and cleared["after"] == "", str(cleared))
        check("and the record is byte for byte what it was",
              open(record, "rb").read() == before, "the record drifted")

        editlib.set_driver_pose(drv_root, CAR, "driver_countach")
        touched = historylib.files(drv_root, editlib.backups(drv_root)[0])
        check("the record is what the edit touches",
              any(r.endswith(SPEC) for r in touched), str(touched))

        # the picker: the pane reads the pose and disables itself without one
        pane = animuilib.AnimPane()
        pane.load(drv_editor.root, CAR)
        pane._load_driver()
        check("the pane shows the pose the car now has",
              pane.driver_pose.currentData() == "driver_countach.banim",
              str(pane.driver_pose.currentData()))
        check("and offers every pose plus the generic one",
              pane.driver_pose.count() == 36, str(pane.driver_pose.count()))
        check("the generic entry clears the field",
              pane.driver_pose.itemData(0) == "", str(pane.driver_pose.itemData(0)))
        check("the note says which pose it is",
              "driver_countach" in pane.driver_note.text(),
              pane.driver_note.text())

        editlib.set_driver_pose(drv_root, CAR, "")
        drv_editor.capture(CAR)

        # the real install, if there is one: every record has the field, and the
        # ones that name nothing mean "use driver.banim" rather than "unreadable".
        src = find_source()
        if src:
            real = os.path.join(src, ".depot", "vehicles", "data")
            named = empty = unreadable = 0
            for leaf in sorted(os.listdir(real)):
                if not leaf.endswith(".bin.nct"):
                    continue
                got = drvlib.field_in_record(os.path.join(real, leaf))
                if got is None:
                    unreadable += 1
                elif got:
                    named += 1
                else:
                    empty += 1
            # The count is not fixed: a mod that adds a car adds a record, and
            # what this is about is the *field* - every record has one, and the
            # ones that name nothing mean "use driver.banim" rather than
            # "unreadable".
            total = named + empty + unreadable
            check("every record in the real install has the field",
                  unreadable == 0 and total > 500,
                  f"{named} named, {empty} empty, {unreadable} unreadable")
            check("and most of them name a pose",
                  named > 200, str(named))
    except ImportError as exc:
        check("a driver pose can be chosen", False, str(exc))

    print("73  reading an install never writes into it")
    try:
        # A fake install holding nothing but the two folders a scan needs.
        probe = os.path.join(ROOT, "work", "rrmod_test_readonly")
        shutil.rmtree(probe, ignore_errors=True)
        os.makedirs(os.path.join(probe, ".depot", "vehicles"))
        os.makedirs(os.path.join(probe, "apk"))
        probe_depot = os.path.join(probe, ".depot")

        def tree(path: str) -> list:
            out = []
            for base, dirs, files in os.walk(path):
                for leaf in list(dirs) + list(files):
                    out.append(os.path.relpath(os.path.join(base, leaf), path))
            return sorted(out)

        before = tree(probe)
        depotlib._MODS_PATH.clear()
        depotlib._STATE_DIR.clear()
        # The state folder is namespaced by the install path, and this probe
        # install always sits in the same place, so a leftover mods file from
        # the previous run would make the read-only lookup look like it found
        # one.  Start from nothing.
        stale = depotlib.state_dir(probe_depot)
        if stale and os.path.isdir(stale):
            shutil.rmtree(stale, ignore_errors=True)
        depotlib._MODS_PATH.clear()
        depotlib._STATE_DIR.clear()
        depotlib.scan(probe)
        depotlib.load_mods(probe_depot)
        check("a scan leaves the install alone", tree(probe) == before,
              f"added {[p for p in tree(probe) if p not in before]}")
        check("and the read-only lookup finds no mods file",
              depotlib.mods_path(probe_depot, create=False) == "",
              repr(depotlib.mods_path(probe_depot, create=False)))

        # Two installs must not share one mods file, or the DXT copy would
        # inherit "this car is a mod" from the ETC copy.
        other = os.path.join(ROOT, "work", "rrmod_test_readonly2")
        shutil.rmtree(other, ignore_errors=True)
        os.makedirs(os.path.join(other, ".depot", "vehicles"))
        os.makedirs(os.path.join(other, "apk"))
        depotlib._MODS_PATH.clear()
        depotlib._STATE_DIR.clear()
        one = depotlib.mods_path(probe_depot)
        two = depotlib.mods_path(os.path.join(other, ".depot"))
        check("two installs get two state folders",
              os.path.dirname(one) != os.path.dirname(two),
              f"{one} / {two}")
        check("neither of them is inside an install",
              probe not in one and other not in two, one)

        # Saving lands where the state lives, and is refused outright when the
        # only writable place would be the install itself.
        depotlib.save_mods(probe_depot, {"version": 1, "mods": {}})
        check("saving writes where the state lives", os.path.isfile(one), one)
        check("and not into the install",
              not os.path.exists(os.path.join(probe_depot, "rr3mods.json")),
              "a file appeared in .depot")
        real = depotlib._state_dirs
        depotlib._state_dirs = lambda _depot: [probe_depot]
        depotlib._MODS_PATH.clear()
        depotlib._STATE_DIR.clear()
        try:
            depotlib.save_mods(probe_depot, {"version": 1})
            refused = ""
        except depotlib.DepotError as exc:
            refused = str(exc)
        finally:
            depotlib._state_dirs = real
        check("an install is never a place to keep state",
              "inside the game install" in refused, refused[:120])
        check("so nothing was written there either",
              not os.path.exists(os.path.join(probe_depot, "rr3mods.json")),
              "a file appeared in .depot")
        depotlib._MODS_PATH.clear()
        depotlib._STATE_DIR.clear()
        shutil.rmtree(probe, ignore_errors=True)
        shutil.rmtree(other, ignore_errors=True)
    except Exception as exc:                        # noqa: BLE001
        check("reading an install never writes into it", False, str(exc))

    print("74  the decal list and the font behind it")
    try:
        from rrmod import decals as declib
        from rr3lib import decals as declib2

        dec_depot = os.path.join(MINI, ".depot")
        got = declib.summary(dec_depot)
        check("the list reads", got["decals"] > 0, f"{got['decals']} decals")
        check("it is version eleven", got["version"] == 11, str(got["version"]))
        check("every record draws one thing or the other",
              got["glyphs"] + got["pages"] == got["decals"],
              f"{got['glyphs']} glyphs, {got['pages']} pages")
        check("the font reads", got["font_glyphs"] > 0,
              f"{got['font_glyphs']} glyphs")
        check("every code point a record names is in the font",
              got["missing_from_font"] == 0,
              f"{got['missing_from_font']} missing")
        # The two spellings of a code point.  A record writes it as hex or as the
        # character itself, and reading only one of them loses most of the list.
        table = declib2.load(dec_depot)
        hexed = [d for d in table.decals if d.glyph.startswith(b"0x")]
        plain = [d for d in table.decals if d.glyph and not d.glyph.startswith(b"0x")]
        check("both spellings of a code point are understood",
              hexed and plain and all(d.code_point is not None
                                      for d in hexed + plain),
              f"{len(hexed)} hex, {len(plain)} plain")
        check("a hex code point is read as hex",
              hexed[0].code_point == int(hexed[0].glyph[2:], 16),
              f"{hexed[0].glyph} -> {hexed[0].code_point}")
        check("a single character is read as itself",
              plain[0].code_point == plain[0].glyph[0],
              f"{plain[0].glyph} -> {plain[0].code_point}")
        # The list is the one table in this program whose trailer is 162 bytes of
        # somebody's name and a URL, so it has to survive a round trip untouched.
        raw = nctlib.read(os.path.join(dec_depot, "vehicles", "data",
                                       "custom.decals.nct"))
        check("the list round trips byte for byte",
              declib2.serialize(table) == raw, "bytes differ")
        check("the author trailer is kept", got["trailer"] == 162,
              str(got["trailer"]))
        rows = declib.rows(dec_depot)
        check("every record becomes a row", len(rows) == got["decals"],
              f"{len(rows)} rows")
        check("every row has something to show",
              all(r["shown"] for r in rows), "a row with no text")
        check("a page row names a picture under vehicles/decals",
              all(r["page"].startswith("vehicles/decals/")
                  for r in rows if r["kind"] == "page"),
              "a page row pointing elsewhere")
        # Only two of the fourteen categories have a name in gametext.txt, and
        # every record in those shares it.  The other 199 rows are unnamed on
        # purpose and must still show something.
        check("the categories are labelled",
              all(r["category_label"] for r in rows), "an empty label")
        check("most rows have no name in the text table",
              got["unnamed"] > 100, f"{got['unnamed']} unnamed")
        check("a row without a name still shows something",
              all(r["shown"] for r in rows if not r["has_name"]),
              "a blank row")
        # Adding one record, then taking it away again.
        before = len(table)
        made = declib2.add(table, category=b"GAMETEXT_CUSTOMISATION_DECALS_SHAPES_NAME",
                           name=b"GAMETEXT_RRMOD_TEST_DECAL",
                           glyph=b"0x0041")
        check("a record can be added", len(table) == before + 1,
              f"{len(table)} records")
        check("it gets a free id", made.id > 0 and made.id == 13, str(made.id))
        check("the new record survives a round trip",
              declib2.parse(declib2.serialize(table)).by_id(made.id) is not None,
              "lost on the way through")
        check("a record that draws neither is refused",
              _raises(declib2.DecalError, declib2.add, table,
                      category=b"X", name=b"Y"), "it was accepted")
        check("a record that draws both is refused",
              _raises(declib2.DecalError, declib2.add, table,
                      category=b"X", name=b"Y", glyph=b"0x41",
                      page=b"vehicles/decals/x.pvr"), "it was accepted")
        check("a glyph that is not a code point is refused",
              _raises(declib2.DecalError, declib2.add, table,
                      category=b"X", name=b"Y", glyph=b"nonsense"),
              "it was accepted")
        check("a page outside vehicles/decals is refused",
              _raises(declib2.DecalError, declib2.add, table,
                      category=b"X", name=b"Y",
                      page=b"vehicles/common/x.pvr"), "it was accepted")
        declib2.remove(table, made.id)
        check("and it can be taken away again", len(table) == before,
              f"{len(table)} records")
        check("the list is byte for byte what it was",
              declib2.serialize(table) == raw, "bytes differ after the round trip")
        # The page itself, without a window.
        from rrmod.ui import decalui

        page = decalui.DecalsPage()
        check("the page builds", page is not None, "no page")
        check("it has a filter and a table",
              hasattr(page, "search") and hasattr(page, "table"),
              "a missing widget")
    except ImportError as exc:
        check("the decal list can be read", False, str(exc))

    print("75  every event type is the name the game itself gives it")
    try:
        from rrmod import series as serlib3

        want = {0: "Elimination", 1: "Head 2 Head", 2: "Cup", 4: "Endurance",
                7: "Speed Record", 9: "Autocross", 10: "Speedsnap",
                11: "Drag Race", 12: "Hunter", 13: "Time Trial", 14: "Fuel",
                15: "NASCAR", 16: "Speed Gate"}
        check("the table has thirteen named types",
              len(serlib3.EVENT_TYPES) == 13, str(len(serlib3.EVENT_TYPES)))
        wrong = {c: (serlib3.type_name(c), n) for c, n in want.items()
                 if serlib3.type_name(c) != n}
        check("every name matches the game's own table", not wrong, str(wrong))
        # 3, 5, 6 and 8 are gaps in the game's enumeration, not names we missed.
        gaps = {c: serlib3.type_name(c) for c in (3, 5, 6, 8)}
        check("the four gaps say the game has no name for them",
              all("unnamed" in v for v in gaps.values()), str(gaps))
        check("a type nobody mentions still gets its number",
              serlib3.type_name(17) == "Type 17", serlib3.type_name(17))

        # A gap type must survive the dialog untouched, exactly like a named one.
        from rrmod.ui import seriesui as serui3
        from rr3lib import career as careerlib3

        career3 = careerlib3.load(os.path.join(MINI, ".depot"))
        names3 = career3.track_names()
        for code in (3, 5, 16, 17):
            ev = {"id": 1, "track": names3[0], "type": code,
                  "laps": 2, "fame": 100, "reward": 500}
            dlg3 = serui3.EventDialog(ev, names3)
            got3 = dlg3.result_info()
            check(f"a type {code} event opens and closes unchanged",
                  got3 == {}, str(got3))
            check(f"and it still reads as type {code}",
                  dlg3.type.currentData() == code, str(dlg3.type.currentData()))
        # Changing only the laps must not carry a type with it.
        ev = {"id": 1, "track": names3[0], "type": 16,
              "laps": 2, "fame": 100, "reward": 500}
        dlg3 = serui3.EventDialog(ev, names3)
        dlg3.laps.setValue(7)
        got3 = dlg3.result_info()
        check("changing the laps alone changes only the laps",
              got3 == {"laps": 7}, str(got3))
    except ImportError as exc:
        check("the event types can be named", False, str(exc))

    print("76  a decal record can be renamed, added, moved and removed")
    try:
        from rr3lib import decals as declib3
        from rr3lib import nct as nctlib3
        from rrmod import decals as rdeclib3
        from rrmod import edit as editlib3
        from rrmod.ui import decalui as decui3
        from rrmod.ui import editing as editinglib3

        ed3 = editinglib3.Editor(MINI)
        droot = ed3.for_tables()
        dfile = os.path.join(droot, ".depot", *declib3.DECALS.split("/"))
        pristine = nctlib3.read(dfile)
        table = declib3.load(os.path.join(droot, ".depot"))
        check("the working copy holds the decal list", len(table) > 100,
              str(len(table)))

        # A rename has to come back to the same bytes when it is undone.
        first = table.decals[2]
        was = first.name
        got = editlib3.set_decal(droot, first.id, name=b"GAMETEXT_TEST_RENAME")
        check("a record can be renamed", got["changed"] == ["name"],
              str(got["changed"]))
        check("the file is written", got["saved"] is True, str(got.get("saved")))
        editlib3.set_decal(droot, first.id, name=was)
        check("and renaming it back restores the bytes",
              nctlib3.read(dfile) == pristine, "the file changed")

        # The name key is what gametext.txt is looked up by, so the row's shown
        # name follows it.
        row = [r for r in rdeclib3.rows(os.path.join(droot, ".depot"))
               if r["id"] == first.id][0]
        check("the row keeps the record's position",
              row["position"] == 2, str(row["position"]))

        # Adding a shape, then taking it away again.
        made = editlib3.add_decal(
            droot, category=b"GAMETEXT_CUSTOMISATION_DECALS_SHAPES_NAME",
            name=b"GAMETEXT_TEST_NEW", code_point=0x2605)
        check("a record can be added", made["id"] > 0, str(made["id"]))
        check("the new record draws a glyph",
              made["record"]["glyph"] == "0x2605", str(made["record"]["glyph"]))
        check("the list grew by one",
              len(declib3.load(os.path.join(droot, ".depot"))) == len(table) + 1,
              str(len(declib3.load(os.path.join(droot, ".depot")))))
        editlib3.remove_decal(droot, made["id"])
        check("removing it again restores the bytes",
              nctlib3.read(dfile) == pristine, "the file changed")

        # A picture record, which is the other half of the format.
        page = editlib3.add_decal(
            droot, category=b"GAMETEXT_CUSTOMISATION_DECALS_SPONSORS_NAME",
            name=b"GAMETEXT_TEST_PAGE",
            page=b"vehicles/decals/sponsors/decal_cabletop.pvr")
        check("a picture record has no glyph",
              page["record"]["glyph"] == "", str(page["record"]["glyph"]))
        editlib3.remove_decal(droot, page["id"])
        check("and it comes out cleanly too",
              nctlib3.read(dfile) == pristine, "the file changed")

        # Moving a record is what changes the order the editor shows.
        before_ids = [d.id for d in declib3.load(os.path.join(droot, ".depot")).decals]
        moved = editlib3.move_decal(droot, before_ids[5], 0)
        check("a record can be moved to the front",
              moved["now"] == 0 and moved["changed"] is True, str(moved))
        after_ids = [d.id for d in declib3.load(os.path.join(droot, ".depot")).decals]
        check("the order really changed",
              after_ids[0] == before_ids[5], str(after_ids[:3]))
        editlib3.move_decal(droot, before_ids[5], 5)
        check("moving it back restores the bytes",
              nctlib3.read(dfile) == pristine, "the file changed")

        # Nothing the file cannot hold gets in.
        for kwargs, why in (
            ({"category": b"X", "name": b"Y"}, "neither half"),
            ({"category": b"X", "name": b"Y", "glyph": b"0x41",
              "page": b"vehicles/decals/x.pvr"}, "both halves"),
            ({"category": b"X", "name": b"Y",
              "page": b"vehicles/common/x.pvr"}, "the wrong folder"),
            ({"category": b"", "name": b"Y", "glyph": b"0x41"}, "no category"),
        ):
            try:
                editlib3.add_decal(droot, **kwargs)
                check(f"a record with {why} is refused", False, "it was accepted")
            except editlib3.EditError:
                check(f"a record with {why} is refused", True, "")

        # The page itself: it reads the working copy, not the install.
        from PySide6.QtWidgets import QApplication

        app3 = QApplication.instance() or QApplication([])
        panel = decui3.DecalsPage()
        panel.attach_root(droot)
        panel.attach_editor(ed3)
        panel._loaded(panel._gather(panel._read_depot()))
        check("the page lists every record", len(panel.rows) == len(table),
              str(len(panel.rows)))
        check("nothing is editable before a row is picked",
              panel.edit_btn.isEnabled() is False and
              panel.new_btn.isEnabled() is True, "the buttons are wrong")
        panel.table.selectRow(0)
        check("picking a row turns on the editing buttons",
              panel.edit_btn.isEnabled() and panel.del_btn.isEnabled(), "")
        picked = panel._picked()
        check("the picked row is the one under the cursor",
              picked is not None and picked["id"] == panel.rows[0]["id"],
              str(picked and picked["id"]))
        dlg = decui3.DecalDialog(picked,
                                 declib3.load(os.path.join(droot, ".depot")).categories())
        check("the dialog opens showing what the record has",
              dlg.code.text() == picked["glyph"], dlg.code.text())
        check("opening and closing it changes nothing",
              dlg.result_info() == {}, str(dlg.result_info()))
        dlg.name.setText("GAMETEXT_TEST_DIALOG")
        check("only the field that changed is reported",
              list(dlg.result_info()) == ["name"], str(dlg.result_info()))
        check("the page reads the working copy, not the install",
              panel._read_depot() == os.path.join(droot, ".depot"),
              panel._read_depot())
    except ImportError as exc:
        check("a decal record can be edited", False, str(exc))

    print("77  a shape is a glyph in the font and a record that names it")
    try:
        from rr3lib import ttf as ttflib
        from rr3lib import decals as declib4
        from rr3lib import nct as nctlib4
        from rrmod import edit as editlib4
        from rrmod.ui import editing as editinglib4

        ed4 = editinglib4.Editor(MINI)
        sroot = ed4.for_tables()
        tfile = os.path.join(sroot, ".depot", *declib4.DECALS.split("/"))
        ffile = os.path.join(sroot, ".depot", declib4.FONT)
        t_raw = nctlib4.read(tfile)
        f_raw = open(ffile, "rb").read()

        font = ttflib.load(ffile)
        check("the font reads", font.summary()["glyphs"] > 200,
              str(font.summary()))
        check("an untouched font is written back byte for byte",
              ttflib.write(font) == f_raw, "it was rebuilt differently")

        # Every glyph has to survive a rebuild, because adding one rebuilds them
        # all.  A lost glyph is a shape that silently stops drawing.
        square = [[ttflib.Point(100, 0), ttflib.Point(900, 0),
                   ttflib.Point(900, 800), ttflib.Point(100, 800)]]
        font.add_glyph(0x2605, square, advance=1000)
        rebuilt = ttflib.read(ttflib.write(font))
        lost = [c for c in font.cmap if rebuilt.glyph_of(c) is None]
        check("rebuilding keeps every code point", lost == [], str(lost[:5]))
        moved = [c for c in font.cmap
                 if c != 0x2605 and font.contours(c) != rebuilt.contours(c)]
        check("and every glyph's outline", moved == [], str(moved[:5]))
        wrong = [c for c in font.cmap
                 if c != 0x2605 and font.advance(c) != rebuilt.advance(c)]
        check("and every advance width", wrong == [], str(wrong[:5]))
        check("the new glyph reads back",
              rebuilt.contours(0x2605) == square, str(rebuilt.contours(0x2605)))
        check("with the advance it was given",
              rebuilt.advance(0x2605) == 1000, str(rebuilt.advance(0x2605)))

        # Both halves in one step.
        made = editlib4.add_decal_shape(sroot, code_point=0x2605,
                                        contours=square, advance=1000)
        check("a shape can be added", made["id"] > 0, str(made["id"]))
        check("the font grew", made["font_after"] > made["font_before"],
              f"{made['font_before']} -> {made['font_after']}")
        grown = ttflib.load(ffile)
        check("the glyph is in the font", grown.glyph_of(0x2605) is not None, "")
        record = declib4.load(os.path.join(sroot, ".depot")).by_id(made["id"])
        check("and the record names the same code point",
              record.code_point == 0x2605, str(record.code_point))
        check("the record draws a glyph, not a page",
              bool(record.glyph) and not record.page, record.glyph.decode("latin-1"))

        # Taking it out again empties the glyph but keeps every index.
        back = editlib4.remove_decal_shape(sroot, made["id"])
        check("removing the shape clears its glyph",
              back["cleared"] is True, str(back.get("cleared")))
        check("the decal table comes back byte for byte",
              nctlib4.read(tfile) == t_raw, "the table changed")
        after = ttflib.load(ffile)
        check("the code point is gone", after.glyph_of(0x2605) is None, "")
        check("but every other glyph is where it was",
              len(after.glyphs) == len(font.glyphs), str(len(after.glyphs)))
        still = [c for c in after.cmap
                 if after.glyph_of(c) != ttflib.read(f_raw).glyph_of(c)]
        check("and still draws the same", still == [], str(still[:5]))

        # A shape with nothing in it is not a shape.
        try:
            editlib4.add_decal_shape(sroot, code_point=0x2606, contours=[])
            check("an empty shape is refused", False, "it was accepted")
        except editlib4.EditError:
            check("an empty shape is refused", True, "")

        # The code point has to be one a cmap format 4 can hold.
        try:
            editlib4.add_decal_shape(sroot, code_point=0x10000,
                                     contours=square)
            check("a code point past the basic plane is refused", False,
                  "it was accepted")
        except Exception:                        # noqa: BLE001 - any refusal will do
            check("a code point past the basic plane is refused", True, "")

        # The dialog that draws one: presets, the canvas, and what it hands back.
        from rrmod.ui import shapedlg

        square_pts = shapedlg.preset("Square")
        check("a preset is one contour", len(square_pts) == 1, str(len(square_pts)))
        check("with four corners", len(square_pts[0]) == 4, str(len(square_pts[0])))
        check("inside the em square",
              all(0 <= x <= shapedlg.EM and 0 <= y <= shapedlg.EM
                  for x, y in square_pts[0]), str(square_pts[0]))
        check("a circle is round", len(shapedlg.preset("Circle")[0]) > 8,
              str(len(shapedlg.preset("Circle")[0])))
        check("a star has ten points",
              len(shapedlg.preset("Star")[0]) == 10,
              str(len(shapedlg.preset("Star")[0])))
        check("every preset draws something",
              all(shapedlg.preset(name) for name in shapedlg.PRESETS),
              str([n for n in shapedlg.PRESETS if not shapedlg.preset(n)]))

        # A tiny drawing grows to fill the box, and a huge one shrinks into it.
        tiny = [[(1000, 1000), (1040, 1000), (1040, 1040)]]
        grown = shapedlg.fit_contours(tiny)
        span = max(p[0] for p in grown[0]) - min(p[0] for p in grown[0])
        check("a small drawing is grown", span > 1000, str(span))
        huge = [[(-9000, -9000), (9000, -9000), (9000, 9000), (-9000, 9000)]]
        shrunk = shapedlg.fit_contours(huge)
        wide = max(p[0] for p in shrunk[0]) - min(p[0] for p in shrunk[0])
        check("a large one is shrunk", wide <= 1601, str(wide))
        check("and centred",
              abs(sum(p[0] for p in shrunk[0]) / 4.0 - shapedlg.EM / 2.0) < 2,
              str(sum(p[0] for p in shrunk[0]) / 4.0))

        box = shapedlg.ShapeDialog(None, code_point=0xE100,
                                   taken={0xE100, 0x2605})
        check("the dialog starts with a shape",
              box.canvas.usable() is True, str(box.canvas.contours))
        check("it offers the code point it was given",
              box.code.text() == "0xE100", box.code.text())
        # A code point the font already draws is refused, because writing it
        # again would replace a drawing some record may be using.
        box._accept()
        check("a taken code point is refused",
              "already has a glyph" in box.problem.text(), box.problem.text())
        box.code.setText("0xE101")
        box._accept()
        check("a free one is accepted", box.result() == QDialog.Accepted,
              str(box.result()))
        info = box.result_info()
        check("the result names the code point", info["code_point"] == 0xE101,
              str(info["code_point"]))
        check("and carries contours", bool(info["contours"]), str(info["contours"]))
        check("grown to the box",
              max(p[1] for c in info["contours"] for p in c) <= shapedlg.EM,
              str(max(p[1] for c in info["contours"] for p in c)))
        check("with a category to file it under",
              info["category"] == b"GAMETEXT_CUSTOMISATION_DECALS_SHAPES_NAME",
              str(info["category"]))
        check("and an empty name, so one is made",
              info["name"] == b"", str(info["name"]))
        box.canvas.set_contours([])
        box._accept()
        check("an empty canvas is refused",
              "at least three points" in box.problem.text(), box.problem.text())
    except ImportError as exc:
        check("a shape can be added", False, str(exc))

    print("78  a page can be written in the ETC and ATC families too")
    try:
        from rr3lib import blockencode
        from rr3lib import etcdecode as etcdec
        from rr3lib import pvr as pvrlib2

        # A gradient along one axis.  ATC runs one line of four colours through
        # each 4x4 block, so a block that changes in two directions at once is
        # outside what the format can say - real pages are mostly flat or shaded
        # one way, and the page check below measures one of those.
        side = 8
        pic = bytes()
        for y in range(side):
            for x in range(side):
                shade = (x * 31) % 256
                pic += bytes((shade, shade, shade, 255))

        for label, suffix, decode in (
                ("ETC1", ".etc.dds.z", etcdec.decode_etc),
                ("ATC", ".atc.dds.z", etcdec.decode_atc)):
            blob = texlib.build_texture(side, side, 4, pic, suffix=suffix,
                                        flip_v=False)
            plain = pvrlib2.inflate_z(blob)
            check(f"a {label} page is a DDS file",
                  plain[:4] == b"DDS ", plain[:4].hex())
            check(f"and carries the {label} fourcc",
                  plain[84:88] == (b"ETC " if label == "ETC1" else b"ATC "),
                  str(plain[84:88]))
            check(f"and the right body length for {label}",
                  len(plain) - 128 == (side // 4) ** 2 * 8,
                  str(len(plain) - 128))
            got_w, got_h, _c, got = decode(plain[128:], side, side)
            check(f"it decodes back to the same size for {label}",
                  (got_w, got_h) == (side, side), f"{got_w}x{got_h}")
            worst = max(abs(pic[i + c] - got[i + c])
                        for i in range(0, len(pic), 4) for c in range(3))
            check(f"and every pixel is close for {label}", worst <= 40,
                  str(worst))

        # A flat picture has to come back exactly: one block, one colour.
        flat = bytes((40, 90, 200, 255)) * 16
        for label, suffix, decode in (
                ("ETC1", ".etc.dds.z", etcdec.decode_etc),
                ("ATC", ".atc.dds.z", etcdec.decode_atc)):
            plain = pvrlib2.inflate_z(
                texlib.build_texture(4, 4, 4, flat, suffix=suffix, flip_v=False))
            _w, _h, _c, got = decode(plain[128:], 4, 4)
            worst = max(abs(flat[i + c] - got[i + c])
                        for i in range(0, len(flat), 4) for c in range(3))
            # Five bits per channel is the format's own limit: 200 becomes 206.
            check(f"a flat {label} block comes back exactly", worst <= 8,
                  str(worst))

        # PVRTC is refused, and the refusal says why rather than just no.
        try:
            texlib.build_texture(4, 4, 4, flat, suffix=".ptc.pvr.z")
            check("PVRTC is still refused", False, "it was written")
        except texlib.TextureError as exc:
            check("PVRTC is still refused", True, "")
            check("and the refusal explains itself",
                  "interpolate" in str(exc), str(exc)[:80])

        # Alpha has no home in either family, so asking for it has to fail
        # rather than quietly drop the channel.
        for label, suffix in (("ETC1", ".etc.dds.z"), ("ATC", ".atc.dds.z")):
            try:
                texlib.build_texture(4, 4, 4, flat, suffix=suffix, alpha=True)
                check(f"{label} refuses an alpha page", False, "it was written")
            except Exception:                    # noqa: BLE001 - any refusal will do
                check(f"{label} refuses an alpha page", True, "")

        check("the manager will write an ETC page",
              texpages.writable("a/b_sprites_0.etc.dds.z") is True, "")
        check("and an ATC page",
              texpages.writable("a/b_sprites_0.atc.dds.z") is True, "")
        check("but still not a PVRTC page",
              texpages.writable("a/b_sprites_0.ptc.pvr.z") is False, "")
    except ImportError as exc:
        check("a page can be written in the ETC family", False, str(exc))

    print("79  the track side shares its pages the same way, in nineteen lists")
    try:
        from rrmod import deps as depslib2
        from rr3lib import manifest as mf

        track_root = editor.for_tables()
        track_depot = os.path.join(track_root, ".depot")
        small = os.path.join(MINI, ".depot", "Tracks", "common", "tutorial",
                             "tutorial_black.dxt.dds.z")

        # The nineteen lists are what the track side is spread over, and the top
        # folder is what decides which one owns a page.
        index = mf.asset_index(track_root)
        shipped = sorted(depslib2.shipped_tracks(track_depot))
        check("the test install carries some of the game's own track pages",
              len(shipped) >= 3, str(len(shipped)))
        mat_own = [s for s in shipped if s.startswith("tracks/common/mat/")]
        check("one of them is in the mat folder", bool(mat_own), str(shipped[:3]))
        mat_rows_before = len(
            mf.load_asset_list(track_root, "asset_list_track_common_mat.txt").rows)
        a_game_page = mat_own[0] if mat_own else shipped[0]
        check("and the mat folder is filed under the mat list",
              index.owner_of("/Tracks/common/"
                             + a_game_page[len("tracks/common/"):]
                             + ".dxt.dds.z")
              == "asset_list_track_common_mat.txt", a_game_page)

        got = editlib.add_track_page(track_root, small,
                                     rel="mat/metal/rrmod_test_metal")
        check("a new track page lands in its folder's list",
              got["list"].startswith("asset_list_track_common_mat.txt"),
              got["list"])
        check("and books four rows", len(got.get("list_rows") or []) == 4,
              str(len(got.get("list_rows") or [])))
        mat = mf.load_asset_list(track_root, "asset_list_track_common_mat.txt")
        runs = mf.runs(mat.rows)
        check("the list still has four family runs", len(runs) == 4, str(runs))
        first = f"/Tracks/common/mat/metal/rrmod_test_metal.dxt.dds.z"
        check("and the new row sits inside its own run",
              any(mat.rows[i][0] == first for i in range(runs[1][1], runs[1][2])),
              "")
        check("the file is on disk",
              os.path.isfile(os.path.join(
                  track_depot, "Tracks", "common", "mat", "metal",
                  "rrmod_test_metal.dxt.dds.z")), "")
        state = depslib2.track_status(track_depot,
                                      "tracks/common/mat/metal/rrmod_test_metal")
        check("it is recorded as this program's", state["brought_by"] == ["<this mod>"],
              str(state["brought_by"]))
        check("and is not called the game's own", state["shipped"] is False, "")

        # A brand new top folder has no list of its own, so it lands in the root
        # list - the one that already claims Tracks/common/common.bin.
        other = editlib.add_track_page(track_root, small,
                                       rel="brandnewthing/sub/rrmod_test_new")
        check("a page in a folder nothing lists goes in the root list",
              other["list"].startswith("asset_list_track_common.txt"),
              other["list"])

        # A page with no folder at all is refused: the folder is how the game
        # finds the list, so a page at the root of Tracks/common is unfindable.
        try:
            editlib.add_track_page(track_root, small, rel="rrmod_test_rootless")
            check("a track page with no folder is refused", False, "it was added")
        except editlib.EditError as exc:
            check("a track page with no folder is refused", True, "")
            check("and the refusal says the folder is what files it",
                  "folder" in str(exc), str(exc)[:80])

        # The game's own pages are never deleted.
        try:
            editlib.remove_track_page(track_root, a_game_page)
            check("a track page the game ships is never deleted", False,
                  "it was deleted")
        except editlib.EditError as exc:
            check("a track page the game ships is never deleted", True, "")
            check("and the refusal says so", "game's own" in str(exc),
                  str(exc)[:80])

        # Taking our own pages off again leaves nothing behind.
        for stem in ("tracks/common/mat/metal/rrmod_test_metal",
                     other["stem"]):
            gone = editlib.remove_track_page(track_root, stem)
            check(f"{stem} gives its four rows back", len(gone["rows"]) == 4,
                  str(len(gone["rows"])))
        mat = mf.load_asset_list(track_root, "asset_list_track_common_mat.txt")
        check("the mat list is back to its own length",
              len(mat.rows) == mat_rows_before,
              f"{len(mat.rows)} vs {mat_rows_before}")
        check("and nothing is left as an orphan",
              depslib2.track_orphans(track_depot) == [],
              str(depslib2.track_orphans(track_depot)))

        # A stem can be given either way round, because the file system and the
        # record write it differently.
        bare = a_game_page[len("tracks/common/"):]
        check("a stem without the prefix still reads",
              depslib2.track_status(track_depot, bare)["shipped"] is True, bare)
    except ImportError as exc:
        check("the track side shares its pages", False, str(exc))

    print()
    print("80  the dependencies page keeps the two shared folders apart")
    try:
        from rrmod.ui import depsui as depsuilib

        page = depsuilib.DepsPage()
        check("the page has two halves", page.tabs.count() == 2,
              str(page.tabs.count()))
        check("one is the car side", page.tabs.tabText(0) == "Car pages",
              page.tabs.tabText(0))
        check("one is the track side", page.tabs.tabText(1) == "Track pages",
              page.tabs.tabText(1))
        check("the car half reads vehicles/common",
              page.cars.folder == "vehicles/common", page.cars.folder)
        check("the track half reads Tracks/common",
              page.tracks.folder == "Tracks/common", page.tracks.folder)
        # The rest of the program still reaches for these by the old names, so
        # they have to keep pointing at the car half.
        check("the old table name still works",
              page.table is page.cars.table, "it points somewhere else")
        check("the old summary name still works",
              page.summary is page.cars.summary, "it points somewhere else")
        check("the old delete button still works",
              page.forget_btn is page.cars.forget_btn, "it points somewhere else")

        # A page added now is named by nothing at all - no livery table mentions
        # it and no track model does either - so each half has its own idea of
        # what an orphan is.
        track_root = editor.for_tables()
        track_depot = os.path.join(track_root, ".depot")
        small = os.path.join(MINI, ".depot", "Tracks", "common", "tutorial",
                             "tutorial_black.dxt.dds.z")
        added = editlib.add_track_page(track_root, small,
                                       rel="mat/metal/rrmod_test_twotabs")

        page.load(depot_ws, ws_root)
        page.cars._loaded(page.cars._gather())
        page.tracks.load(track_depot, track_root)
        page.tracks._loaded(page.tracks._gather())

        check("the car half never lists a track page",
              not any(r["stem"].startswith("tracks/") for r in page.cars.rows),
              str([r["stem"] for r in page.cars.rows
                   if r["stem"].startswith("tracks/")][:2]))
        check("the track half lists track pages",
              any(r["stem"].startswith("tracks/common/")
                  for r in page.tracks.rows),
              str([r["stem"] for r in page.tracks.rows][:2]))
        check("and never a car page",
              not any(r["stem"].startswith("common/") for r in page.tracks.rows),
              str([r["stem"] for r in page.tracks.rows
                   if r["stem"].startswith("common/")][:2]))
        check("the track summary counts track models",
              "track model" in page.tracks.summary.text(),
              page.tracks.summary.text()[:70])

        stem = "tracks/common/mat/metal/rrmod_test_twotabs"
        check("the new track page is an orphan there",
              any(r["stem"] == stem for r in page.tracks.orphan_rows),
              str([r["stem"] for r in page.tracks.orphan_rows][:3]))
        check("but not an orphan on the car side",
              not any(r["stem"] == stem for r in page.cars.orphan_rows),
              str([r["stem"] for r in page.cars.orphan_rows][:3]))
        check("the car half's records are only car pages",
              all(k.startswith("common/")
                  for k in depslib.load(track_depot)["pages"]
                  if page.cars._mine(k)),
              "")

        # Deleting through the track half is what the button does.
        page.tracks.orphans.setRowCount(1)
        page.tracks.orphans.setItem(0, 0, depsuilib.QTableWidgetItem(stem))
        page.tracks.orphans.selectRow(0)
        check("the track delete button turns on",
              page.tracks.forget_btn.isEnabled(), "the button stayed off")
        gone = page.tracks._delete(stem)
        check("the track half deletes a track page",
              len(gone["files"]) == 1 and len(gone["rows"]) == 4, str(gone))
        check("and the file is gone",
              not os.path.isfile(os.path.join(
                  track_depot, "Tracks", "common", "mat", "metal",
                  "rrmod_test_twotabs.dxt.dds.z")), "")
    except ImportError as exc:
        check("the two shared folders are kept apart", False, str(exc))

    print("81  a pack carries the picture, and the family is chosen on install")
    try:
        from rrmod import pack as packlib2
        from rrmod import textures as texpages2
        from rrmod.ui import editing as editinglib
        from rrmod.ui import settings as setlib2

        # A picture that was never put on a page has no source to carry, so the
        # first thing to prove is that editing a page leaves one behind.
        shot = os.path.join(ROOT, "work", "rrmod_test_pack_shot.png")
        os.makedirs(os.path.dirname(shot), exist_ok=True)
        page_rel = "/vehicles/common/car_windows_04.ptc.pvr.z"
        root_pack = editor.for_tables()
        depot_pack = os.path.join(root_pack, ".depot")
        on_disk = os.path.join(depot_pack, "vehicles", "common",
                               "car_windows_04.dxt.dds.z")
        had_page = os.path.isfile(on_disk)
        # The replacement has to be the size the game allocated, because nothing
        # here rescales: the shipped page is what says how big it must be.
        side = 512
        thumbs.write_png_bytes(shot, side, side, 3,
                               bytes(bytearray([200, 60, 40]) * (side * side)))
        picture = shot

        made_page = texpages2.replace(root_pack, page_rel, picture,
                                      log=lambda m: None)
        check("a page written here remembers its picture",
              bool(made_page.get("source")) and
              os.path.isfile(made_page.get("source") or ""),
              str(made_page.get("source")))
        check("the picture sits beside the working copy",
              texpages2.SOURCE_DIR in (made_page.get("source") or ""),
              str(made_page.get("source")))

        # Publishing the page must carry the PNG, not the encoded page.
        out = os.path.join(ROOT, "work", "rrmod_test_pack_pages.rr3mod")
        made = publishlib.pages(root_pack, ["common/car_windows_04"], out,
                                log=lambda m: None)
        check("the pack is written", os.path.isfile(out), out)
        check("and carries one picture", made["pictures"] == 1, str(made))
        data = packlib2.read_manifest(out)
        check("the picture is named in the manifest",
              packlib2.pictures_of(data) ==
              ["vehicles/common/car_windows_04.dxt.dds.z"],
              str(packlib2.pictures_of(data)))
        with zipfile.ZipFile(out) as zf:
            names = zf.namelist()
        check("the picture travels under pictures/",
              any(n.startswith(packlib2.PICTURES) for n in names), str(names[:4]))
        check("and the encoded page does not travel",
              not any(n.startswith(packlib2.PREFIX) and
                      n.endswith((".dxt.dds.z", ".etc.dds.z"))
                      for n in names), str(names[:4]))

        # A family other than the one on disk has to be encodable.
        check("there are four families to choose from",
              publishlib.TEXTURE_FAMILIES == ("auto", "dxt", "etc", "atc"),
              str(publishlib.TEXTURE_FAMILIES))
        for key in ("dxt", "etc", "atc"):
            check(f"{key} has a suffix of its own",
                  publishlib.FAMILY_SUFFIX[key] == f".{key}.dds.z",
                  publishlib.FAMILY_SUFFIX[key])

        # Install into a second working copy, asking for ETC by name.
        other = editinglib.Editor(MINI).for_tables()
        other_depot = os.path.join(other, ".depot")
        etc_page = os.path.join(other_depot, "vehicles", "common",
                                "car_windows_04.etc.dds.z")
        done = publishlib.install(other, out, family="etc", log=lambda m: None)
        check("the page is written in the family asked for",
              os.path.isfile(etc_page), etc_page)
        check("and reported as such",
              [p["family"] for p in done.get("pages") or []] == ["etc"],
              str(done.get("pages")))
        if os.path.isfile(etc_page):
            from rr3lib import ddsdecode as dd
            blob = pvrlib.inflate_z(open(etc_page, "rb").read())
            check("the page is a real DDS", blob[:4] == b"DDS ", blob[:4])
            check("with the ETC fourcc", blob[84:88] == b"ETC ", blob[84:88])
            got = dd.decode(blob)
            check("and it decodes at the size of the original",
                  (got[0], got[1]) == (side, side),
                  f"{got[0]}x{got[1]}")
            # ETC1 keeps four bits per channel, so the colour comes back within a
            # few units rather than exactly.  Anything further off means the
            # blocks were laid out wrong.
            want = bytes(bytearray([200, 60, 40]))
            off = max(abs(a - b) for a, b in zip(got[3][:3], want))
            check("in the right colour", off <= 16,
                  f"{str(got[3][:3])} is {off} away from {str(want)}")
        # The asset list has to name the new page, or the game would not find it.
        al = manifestlib.load_asset_list(other, "asset_list_vehicle_common.txt")
        check("the asset list names the new page",
              any(r[0].endswith("car_windows_04.etc.dds.z") for r in al.rows),
              str([r[0] for r in al.rows
                   if "car_windows_04" in r[0]])[:2])

        # A page that was never edited has no picture, so it travels as a file
        # and the pack says so.
        plain = publishlib.pages(
            MINI, ["common/car_rotor_05"], os.path.join(
                ROOT, "work", "rrmod_test_pack_plain.rr3mod"),
            log=lambda m: None)
        check("a page with no picture travels as a file",
              plain.get("pictures") == 0 and
              bool(plain.get("without_a_picture")),
              str(plain)[:120])

        # The menu offers all four, and the choice is remembered.
        setlib2.set_texture_family("etc")
        check("the family choice is remembered",
              setlib2.texture_family() == "etc", setlib2.texture_family())
        setlib2.set_texture_family("nonsense")
        check("and a bad one falls back to auto",
              setlib2.texture_family() == "auto", setlib2.texture_family())
        check("the page labels every family",
              all(k in publishuilib.FAMILY_LABELS
                  for k in publishlib.TEXTURE_FAMILIES),
              str(sorted(publishuilib.FAMILY_LABELS)))

        # The install dialog stores a key; a page carries a suffix.  The two have
        # to agree exactly, or the format chosen at the folder is not the format
        # the next page is written in.
        check("every family the folder dialog offers maps to a page suffix",
              [(k, pagelib.suffix_for_family(k)) for k in ("dxt", "etc", "atc")]
              == [("dxt", ".dxt.dds.z"), ("etc", ".etc.dds.z"),
                  ("atc", ".atc.dds.z")],
              str([(k, pagelib.suffix_for_family(k))
                   for k in ("dxt", "etc", "atc")]))
        check("auto has no suffix, so a page keeps the family it has",
              pagelib.suffix_for_family("auto") == ""
              and pagelib.suffix_for_family("") == "",
              pagelib.suffix_for_family("auto"))
        check("the folder dialog offers exactly the writable families",
              sorted(k for k, _l in applayout.FAMILY_LABELS if k != "auto")
              == sorted(depotlib.WRITABLE_FAMILIES),
              str([k for k, _l in applayout.FAMILY_LABELS]))

        # Reading the family off the folder itself: ``vehicles/common`` holds the
        # shared pages and the game ships exactly one family of it, so counting
        # what is there is the whole test.
        fam_root = os.path.join(ROOT, "work", "rrmod_test_family")
        fam_common = os.path.join(fam_root, ".depot", "vehicles", "common")
        shutil.rmtree(fam_root, ignore_errors=True)
        os.makedirs(fam_common, exist_ok=True)
        for name in ("a.dxt.dds.z", "b.dxt.dds.z", "c.etc.dds.z"):
            with open(os.path.join(fam_common, name), "wb"):
                pass
        check("the shared folder says which family this install unpacks",
              depotlib.detect_texture_family(fam_root) == "dxt",
              depotlib.detect_texture_family(fam_root))
        with open(os.path.join(fam_common, "d.etc.dds.z"), "wb"):
            pass
        check("a tie means no opinion, so a hand-picked format survives",
              depotlib.detect_texture_family(fam_root) == "",
              depotlib.detect_texture_family(fam_root))
        check("a folder that is not there has no opinion either",
              depotlib.detect_texture_family(
                  os.path.join(ROOT, "work", "no_such_install_at_all")) == "",
              "it guessed")
        # An iOS unpack holds PVRTC, which cannot be encoded.  The answer is
        # still reported - the dialog says why it cannot be used - but it is not
        # one of the families the setting accepts.
        pvr_root = os.path.join(ROOT, "work", "rrmod_test_family_pvr")
        pvr_common = os.path.join(pvr_root, ".depot", "vehicles", "common")
        shutil.rmtree(pvr_root, ignore_errors=True)
        os.makedirs(pvr_common, exist_ok=True)
        for name in ("a.ptc.pvr.z", "b.ptc.pvr.z"):
            with open(os.path.join(pvr_common, name), "wb"):
                pass
        check("a PVRTC install is recognised and not offered",
              depotlib.detect_texture_family(pvr_root) == "ptc"
              and "ptc" not in depotlib.WRITABLE_FAMILIES,
              depotlib.detect_texture_family(pvr_root))
        shutil.rmtree(fam_root, ignore_errors=True)
        shutil.rmtree(pvr_root, ignore_errors=True)

        # A missing shared page must not stop an install.  The pack has to carry
        # something real, or "no files" would be the complaint instead.
        warn_pack = os.path.join(ROOT, "work", "rrmod_test_pack_warn.rr3mod")
        real = os.path.join(other_depot, "vehicles", "common",
                            "car_windows_04.dxt.dds.z")
        manifest = packlib2.make(
            kind="pages", name="needs a page", title="needs a page",
            files=[("vehicles/common/car_windows_04.dxt.dds.z", real)],
            requires=[{"kind": "page", "name": "common/nowhere_at_all"}],
            provides={"pages": ["common/nowhere_at_all"]})
        packlib2.write(warn_pack, manifest,
                       [("vehicles/common/car_windows_04.dxt.dds.z", real)],
                       log=lambda m: None)
        told = packlib2.check(other, warn_pack)
        check("a missing page is a warning, not a problem",
              told["warnings"] and not told["problems"], str(told)[:200])
        check("and the pack still counts as installable",
              told["state"] in ("ready", "missing"), told["state"])
        check("the warning says what will not draw",
              "without a texture" in (told["warnings"] or [""])[0],
              (told["warnings"] or [""])[0])

        for junk in (out, warn_pack, os.path.join(
                ROOT, "work", "rrmod_test_pack_plain.rr3mod"), shot):
            if os.path.isfile(junk):
                os.remove(junk)
        if not had_page and os.path.isfile(on_disk):
            os.remove(on_disk)
    except (ImportError, NameError) as exc:
        check("a pack carries the picture it was made from", False, str(exc))

    print("82  one list of cars, and an install that asks before it overwrites")
    try:
        from rrmod.ui import cars as carsui

        cars_page = carsui.CarsPage()
        check("there is one car table now",
              cars_page.vanilla is cars_page.cars, "it is still two tables")
        check("and the old name points at it",
              cars_page.vanilla is not None, "no alias")
        check("the mods table is kept but hidden",
              not cars_page.mods.isVisible(), "it is still on screen")
        check("and so is the unmanaged one",
              not cars_page.unknown.isVisible(), "it is still on screen")
        labels = [cars_page.status_box.itemText(i)
                  for i in range(cars_page.status_box.count())]
        check("the filter still offers all four states", len(labels) == 4,
              str(labels))
        check("but it no longer calls anything mine",
              not any("my mods" in text.lower() for text in labels), str(labels))

        # Every car can be deleted now, because the program stopped keeping a
        # list of which ones are the game's own.
        entry = editor.inv.get(CAR) if hasattr(editor, "inv") else None
        if entry is not None:
            cars_page.inv = editor.inv
            cars_page._picked(entry)
            check("a shipped car can be deleted too",
                  cars_page.delete_btn.isEnabled(), "the button stayed off")

        # Installing asks first, and "no copy" really does skip the backup.
        other2 = editinglib.Editor(MINI).for_tables()
        depot2 = os.path.join(other2, ".depot")
        page2 = os.path.join(depot2, "vehicles", "common",
                             "car_rotor_05.dxt.dds.z")
        before = open(page2, "rb").read() if os.path.isfile(page2) else b""
        src2 = os.path.join(ROOT, "work", "rrmod_test_keep.rr3mod")
        blobby = b"DDS " + bytes(124) + b"\x00" * 64
        fake = os.path.join(ROOT, "work", "rrmod_test_keep_page.dxt.dds.z")
        with open(fake, "wb") as fh:
            fh.write(blobby)
        man2 = packlib2.make(
            kind="pages", name="a page", title="a page",
            files=[("vehicles/common/car_rotor_05.dxt.dds.z", fake)])
        packlib2.write(src2, man2,
                       [("vehicles/common/car_rotor_05.dxt.dds.z", fake)],
                       log=lambda m: None)

        from rrmod import history as histlib
        publishlib.install(other2, src2, keep=False, log=lambda m: None)
        check("a no-copy install writes the file",
              open(page2, "rb").read() == blobby, "the file did not change")
        # With no copy asked for, nothing of the old file is written down - so
        # there is no step holding it either.  Saying "there is a step but it is
        # empty" would be worse than saying nothing: the panel would offer an
        # undo that cannot undo.
        kept_any = any("car_rotor_05" in rel
                       for step in histlib.steps(other2)
                       for rel in histlib.files(other2, step["stamp"]))
        check("and nothing of the old file is written down", not kept_any,
              "a backup of it exists after all")

        # With keep=True the old bytes are there and the step can restore them.
        with open(fake, "wb") as fh:
            fh.write(b"DDS " + bytes(124) + b"\x11" * 64)
        man3 = packlib2.make(
            kind="pages", name="a page", title="a page",
            files=[("vehicles/common/car_rotor_05.dxt.dds.z", fake)])
        packlib2.write(src2, man3,
                       [("vehicles/common/car_rotor_05.dxt.dds.z", fake)],
                       log=lambda m: None)
        publishlib.install(other2, src2, keep=True, log=lambda m: None)
        newest = histlib.steps(other2)[0]
        check("a kept install remembers the file it replaced",
              any("car_rotor_05" in rel
                  for rel in histlib.files(other2, newest["stamp"])),
              str(histlib.files(other2, newest["stamp"]))[:80])
        check("and the step can put the old bytes back",
              len(histlib.restore(other2, [newest["stamp"]])["files"]) >= 1, "")

        if before:
            with open(page2, "wb") as fh:
                fh.write(before)
        for junk in (src2, fake):
            if os.path.isfile(junk):
                os.remove(junk)
    except (ImportError, NameError) as exc:
        check("one list of cars and a guarded install", False, str(exc))

    # A profile is a wish list until the engine prints what it resolved.  The
    # dump it writes after "Loaded settings file" is the only honest answer to
    # "did my edit take effect", so it is parsed and diffed here.
    print("83  a boot log says which keys the engine really used")
    try:
        from rrmod import bootlog as bootloglib

        # Shaped like the real thing, including the two traps: a multi line
        # string only carries its ": STRING" on the last physical line, and a
        # key the file does not name is missing from the dump rather than 0.
        log_text = "\n".join([
            'I/libRealRacing3(13799): ======= platform AndroidHigh',
            'I/libRealRacing3(13799): Loaded settings file: AndroidHigh.plist',
            'I/libRealRacing3(13799):   "AA_LEVEL" - ',
            'I/libRealRacing3(13799): 4 : INT',
            'I/libRealRacing3(13799):   "MIPMAP_BIAS" - ',
            'I/libRealRacing3(13799): 0.000000 : FLOAT',
            'I/libRealRacing3(13799):   "HIGH_RES_MENU" - ',
            'I/libRealRacing3(13799): true : BOOL',
            'I/libRealRacing3(13799):   "CAR_LOD_MAPPING_PLAYER" - ',
            'I/libRealRacing3(13799): "Player high',
            'I/libRealRacing3(13799): A, 6" : STRING',
            'I/libRealRacing3(13799):   "NOT_IN_MY_FILE" - ',
            'I/libRealRacing3(13799): 7 : INT',
            'I/libRealRacing3(13799): Supported extensions:',
            'I/libRealRacing3(13799): GL_EXT_shader_texture_lod',
            'I/libRealRacing3(13799): GL_EXT_texture_filter_anisotropic',
            'I/libRealRacing3(13799): GL_OES_vertex_array_object',
            'I/libRealRacing3(13799): Starting the next thing',
        ])
        dump = bootloglib.parse_dump(log_text)
        check("the dump is read", len(dump) == 5, str(sorted(dump)))
        check("an int keeps its type", dump.get("AA_LEVEL") == 4,
              repr(dump.get("AA_LEVEL")))
        check("a float keeps its type", dump.get("MIPMAP_BIAS") == 0.0,
              repr(dump.get("MIPMAP_BIAS")))
        check("a switch is a bool", dump.get("HIGH_RES_MENU") is True,
              repr(dump.get("HIGH_RES_MENU")))
        check("the profile name is picked up",
              bootloglib.loaded_profile(log_text) == "AndroidHigh.plist",
              bootloglib.loaded_profile(log_text))
        check("the platform is picked up",
              bootloglib.loaded_platform(log_text) == "AndroidHigh",
              bootloglib.loaded_platform(log_text))
        exts = bootloglib.parse_extensions(log_text)
        check("the extension list stops at the next line",
              exts == ["GL_EXT_shader_texture_lod",
                       "GL_EXT_texture_filter_anisotropic",
                       "GL_OES_vertex_array_object"], str(exts))

        wanted = {"AA_LEVEL": 4, "MIPMAP_BIAS": -2.0, "HIGH_RES_MENU": True,
                  "CAR_LOD_MAPPING_PLAYER": "Player high\nA, 6",
                  "NEVER_WRITTEN": 1}
        rows = {r["key"]: r for r in bootloglib.compare(wanted, dump)}
        check("a value that took says so", rows["AA_LEVEL"]["state"] == bootloglib.TOOK,
              str(rows["AA_LEVEL"]))
        check("a value the engine resolved itself is flagged",
              rows["MIPMAP_BIAS"]["state"] == bootloglib.DIFFERS,
              str(rows["MIPMAP_BIAS"]))
        check("a multi line value is compared on its tail",
              rows["CAR_LOD_MAPPING_PLAYER"]["state"] == bootloglib.TOOK,
              str(rows["CAR_LOD_MAPPING_PLAYER"]))
        check("a key the dump never mentions is absent, not wrong",
              rows["NEVER_WRITTEN"]["state"] == bootloglib.ABSENT,
              str(rows["NEVER_WRITTEN"]))
        check("the engine's own keys come with a reason",
              "MIPMAP_BIAS" in bootloglib.ENGINE_OWN
              and bool(rows["MIPMAP_BIAS"].get("note")),
              str(rows["MIPMAP_BIAS"].get("note")))
        ordered = [r["key"] for r in bootloglib.compare(wanted, dump)]
        check("what did not take is listed first",
              ordered[0] in ("MIPMAP_BIAS", "NEVER_WRITTEN"), str(ordered))

        rep = bootloglib.report("", log_text, wanted=wanted)
        check("the counts add up to the rows",
              sum(rep["counts"].values()) == len(rep["rows"]),
              str(rep["counts"]))
        check("the summary names the profile",
              "AndroidHigh.plist" in bootloglib.summarise(rep),
              bootloglib.summarise(rep))
        check("a file with no dump in it is refused",
              _raises(bootloglib.BootLogError, bootloglib.report, "",
                      "nothing to see here"), "a plain text file parsed")

        # The real archive, when it is still around: the ultra profile that was
        # pushed on 2026-11-07 matches the engine on all but the two keys the
        # engine owns.  That is the whole reason this module exists, so it is
        # worth locking in - if a future change starts reporting the shipped
        # values as mismatches, this is the check that notices.
        pushed = os.path.join(ROOT, "work", "gfx", "ah_deployed.plist.dec")
        real_log = os.path.join(ROOT, "re", "logs", "final_verify.log")
        if os.path.isfile(pushed) and os.path.isfile(real_log):
            with open(pushed, encoding="utf-8", errors="replace") as fh:
                real_plist = fh.read()
            with open(real_log, encoding="utf-8", errors="replace") as fh:
                real_text = fh.read()
            real = bootloglib.report(real_plist, real_text)
            bad = sorted(r["key"] for r in real["rows"]
                         if r["state"] != bootloglib.TOOK)
            check("the real ultra boot agrees except where the engine decides",
                  bad == ["3D_SCENE_SCALE", "MIPMAP_BIAS"], str(bad))
            check("and it is the profile we pushed that was loaded",
                  real["profile"] == "AndroidHigh.plist", real["profile"])
    except (ImportError, NameError) as exc:
        check("a boot log can be read back", False, str(exc))

    print("66 a car can be given a showroom picture of its own")
    # The showroom and the career lists cut ``car_sales_car_<id>.png`` out of the
    # car_sales sheets, so a car this program built has no tile until one is
    # written.  The fixture is a sheet with one other car's tile in it.
    pic_root = os.path.join(ROOT, "work", "rrmod_test_pics")
    shutil.rmtree(pic_root, ignore_errors=True)
    pic_depot = os.path.join(pic_root, ".depot")
    batch = os.path.join(pic_depot, "gui_assets", "2048x1536", "car_sales",
                         "cars", "cars_01")
    os.makedirs(batch, exist_ok=True)
    from rr3lib import texport as _texport

    with open(os.path.join(batch, "sprites_0.dxt.dds.z"), "wb") as fh:
        fh.write(_texport.build_texture(64, 32, 4, bytes(64 * 32 * 4),
                                        suffix=".dxt.dds.z", flip_v=True))
    with open(os.path.join(batch, "sprites.android.atlas"), "w",
              encoding="utf-8", newline="\n") as fh:
        fh.write('<atlas_images texture_formats=".dxt.dds" hash="00">\n'
                 '  <image name="car_sales_car_1.png" ver="0" width="60" '
                 'height="30">\n'
                 '    <pos id="0" x="0" y="0"/>\n'
                 '  </image>\n'
                 '</atlas_images>\n')
    thumbs.forget()
    check("the sheet's own picture is found",
          thumbs.index(pic_depot, "2048x1536").get(1) is not None,
          str(thumbs.summary(pic_depot)))

    # a picture to draw: 24x12, red, so a tile that was not written stays black
    picture = os.path.join(pic_root, "shot.png")
    thumbs.write_png_bytes(picture, 24, 12, 4,
                              bytes([200, 30, 30, 255]) * (24 * 12))
    made = thumbs.set_picture(pic_root, 4242, picture, log=lambda _m: None)
    check("a car with no tile gets a sheet entry and a page",
          len(made["files"]) == 2, str(made["files"]))
    check("the sheet is one of them",
          any(rel.endswith("sprites.android.atlas") for _l, rel in made["files"]),
          str(made["files"]))
    check("and the page is the other",
          any(rel.endswith(".dxt.dds.z") for _l, rel in made["files"]),
          str(made["files"]))
    thumbs.forget()
    box = thumbs.index(pic_depot, "2048x1536").get(4242)
    check("the new tile is indexed under the name the engine asks for",
          box is not None, str(sorted(thumbs.index(pic_depot, "2048x1536"))))
    if box:
        w, h, _ch, px = thumbs.sprite(pic_depot, 4242)
        check("and it reads back at the sheet's own size", (w, h) == (60, 30),
              f"{w}x{h}")
        check("with the picture in it",
              px[0] > 150 and px[1] < 90, str(px[0:4]))

    # replacing one keeps its place instead of appending a second page
    before_files = sorted(os.listdir(batch))
    thumbs.set_picture(pic_root, 1, picture, log=lambda _m: None)
    check("an existing tile is drawn over, not added",
          sorted(os.listdir(batch)) == before_files, str(os.listdir(batch)))
    check("and no new row went into the sheet",
          len(thumbs.index(pic_depot, "2048x1536")) == 2,
          str(sorted(thumbs.index(pic_depot, "2048x1536"))))
    thumbs.forget()
    check("the replaced tile still reads back",
          thumbs.sprite(pic_depot, 1)[0:2] == (60, 30),
          str(thumbs.sprite(pic_depot, 1)[0:2]))
    shutil.rmtree(pic_root, ignore_errors=True)

    print("60 the words a car is filed under, and the schemes it carries")
    # ---- the two word fields ------------------------------------------
    check("the game ships four drivetrains",
          tuple(statlib.drivetrains()) == ("RWD", "AWD", "FWD", "RLY"),
          str(statlib.drivetrains()))
    check("and three classes",
          tuple(statlib.classes()) == ("Race", "Supercar", "Prod"),
          str(statlib.classes()))
    fields60 = statlib.read(root, CAR)["fields"]
    check("the drivetrain is a field of its own",
          "drivetrain" in fields60, str(sorted(fields60)))
    check("and it can be written",
          bool(fields60.get("drivetrain", {}).get("writable")),
          str(fields60.get("drivetrain")))
    check("so can the class",
          bool(fields60.get("car_class", {}).get("writable")),
          str(fields60.get("car_class")))
    had60 = fields60["drivetrain"]["value"]
    other60 = "AWD" if had60 != "AWD" else "RWD"
    check("a word the game does not know is refused before it is written",
          bool(statlib.validate({"drivetrain": "WD"})),
          str(statlib.validate({"drivetrain": "WD"})))
    check("and the refusal lists what it does know",
          "RWD" in " ".join(statlib.validate({"drivetrain": "WD"})),
          str(statlib.validate({"drivetrain": "WD"})))
    statlib.write(root, CAR, {"drivetrain": other60})
    check("a drivetrain can be written",
          statlib.read(root, CAR)["fields"]["drivetrain"]["value"] == other60,
          statlib.read(root, CAR)["fields"]["drivetrain"]["value"])
    statlib.write(root, CAR, {"drivetrain": had60})
    check("and put back",
          statlib.read(root, CAR)["fields"]["drivetrain"]["value"] == had60,
          statlib.read(root, CAR)["fields"]["drivetrain"]["value"])

    # ---- the name, the make and the model -----------------------------
    depot60 = depotlib.scan(root).depot
    was60 = depotlib.scan(root).get(CAR)
    # An earlier group leaves one stale manifest row behind (a wing banim it
    # removes), so what this section checks is that it adds none of its own.
    before_60 = editlib.verify(root, CAR)
    got60 = editlib.set_identity(root, CAR, display_name="Lexus LFA (mine)")
    check("the showroom name can be changed",
          got60["after"]["name"] == "Lexus LFA (mine)", str(got60))
    check("through the text entry the name key points at",
          "text" in got60.get("how", ""), str(got60.get("how")))
    again60 = editlib.set_identity(root, CAR, display_name="Lexus LFA (mine)")
    check("asking for the same name again writes nothing",
          again60["changed"] == [], str(again60))
    depotlib.forget_names(depot60)
    fresh60 = depotlib.scan(root).get(CAR)
    check("the new name reads back off the install",
          (fresh60.display_name or "") == "Lexus LFA (mine)",
          str(fresh60.display_name))
    # 32 bytes on purpose: the token in front of a CAR_* key is usually
    # ``01 00 00 00``, and a 32-byte string makes the reader see its length byte
    # as a one-byte string - which used to shift every field after it away.
    long60 = "Nonesuch Motors and Coachworks"
    got60 = editlib.set_identity(root, CAR, make=long60, model="LFA-X")
    check("the make can be changed", got60["after"]["make"] == long60, str(got60))
    check("the manufacturer key moves with it",
          got60["after"]["manufacturer"].startswith("CAR_MANUFACTURER_"),
          str(got60["after"]))
    check("and the model too", got60["after"]["model"] == "LFA-X", str(got60))
    depotlib.forget_names(depot60)
    fresh60 = depotlib.scan(root).get(CAR)
    check("a 32-byte make does not lose the rest of the spec",
          (fresh60.display_name or "") == "Lexus LFA (mine)"
          and fresh60.make == long60,
          f"{fresh60.display_name!r} / {fresh60.make!r}")
    check("and the figures still read after it",
          bool(statlib.read(root, CAR)["fields"]["top_speed"]["value"]),
          str(statlib.read(root, CAR)["fields"].get("top_speed")))
    check("the install verifies exactly as well as it did",
          editlib.verify(root, CAR) == before_60,
          str(editlib.verify(root, CAR)[:2]))

    # ---- adding and removing a scheme ---------------------------------
    L60 = liverylib.load_car(depot60, CAR)
    n60 = len(L60.paints)
    check("the car has paint schemes to work from", n60 >= 1, str(n60))
    suggestion60 = L60.next_paint_name()
    check("a new scheme continues the shipped numbering",
          suggestion60.startswith(f"{n60 + 1:02d}_"), suggestion60)
    added60 = editlib.add_paint_scheme(root, CAR)
    check("a scheme can be added", added60["index"] == n60, str(added60))
    check("under the next free name", added60["name"] == suggestion60,
          str(added60))
    check("and the table has one more row",
          len(liverylib.load_car(depot60, CAR).paints) == n60 + 1,
          str(len(liverylib.load_car(depot60, CAR).paints)))
    check("the added scheme carries the colour of the one it copied",
          liverylib.load_car(depot60, CAR).paints[-1].rgb
          == L60.paints[0].rgb,
          str(liverylib.load_car(depot60, CAR).paints[-1].rgb))
    check("the manifests know about it",
          editlib.verify(root, CAR) == before_60,
          str(editlib.verify(root, CAR)[:2]))
    gone60 = editlib.remove_paint_scheme(root, CAR, [added60["index"]])
    check("and it can be taken out again", gone60["left"] == n60, str(gone60))
    check("with the right name reported",
          gone60["removed"] == [suggestion60], str(gone60["removed"]))
    check("removing a scheme that is not there is refused",
          _raises(editlib.EditError, editlib.remove_paint_scheme, root, CAR, [99]))
    check("so is removing nothing",
          _raises(editlib.EditError, editlib.remove_paint_scheme, root, CAR, []))
    check("and so is removing every scheme, because a car needs one",
          _raises(editlib.EditError, editlib.remove_paint_scheme, root, CAR,
                  list(range(n60))))
    check("the car kept all its schemes through the refusal",
          len(liverylib.load_car(depot60, CAR).paints) == n60,
          str(len(liverylib.load_car(depot60, CAR).paints)))

    # a clone survives a write and a read, which is what makes a new preset a
    # preset and not a blank row
    L61 = liverylib.load_car(depot60, CAR)
    L61.clone_paint(0, name="99_test.livery")
    raw61 = liverylib.serialize(L61)
    back61 = liverylib.parse(raw61)
    check("a cloned scheme reads back under its own name",
          back61.paints[-1].name() == "99_test.livery",
          back61.paints[-1].name())
    check("with its materials and its atlas",
          back61.paints[-1].materials == L61.paints[0].materials
          and back61.paints[-1].overrides == L61.paints[0].overrides,
          str(back61.paints[-1].materials))
    check("and the table is byte for byte what was written",
          liverylib.serialize(back61) == raw61)

    print("61 the gear count, the maximum PR, and a folder that is optional")
    # ---- the cheap stem index -----------------------------------------
    t61 = time.time()
    index61 = depotlib.spec_stems(root)
    first61 = time.time() - t61
    scan61 = {c.name: c.spec_stem for c in depotlib.scan(root).cars}
    check("the cheap stem index finds every car a full scan finds",
          index61 == scan61,
          f"{len(index61)} vs {len(scan61)}")
    t61 = time.time()
    depotlib.spec_stems(root)
    again61 = time.time() - t61
    check("and the second call is cached, not rebuilt",
          again61 < 0.05, f"{first61:.3f}s then {again61:.3f}s")
    check("it knows the test car's own spec",
          index61.get(CAR) == SPEC[:-8], str(index61.get(CAR)))

    # ---- the gear count ------------------------------------------------
    spec61 = speclib.load_spec(os.path.join(root, ".depot"), SPEC[:-8])
    start61 = spec61.stats()
    g061 = start61["gears"]
    ratios061 = spec61.gear_ratios()
    key061 = spec61.display_name_key()
    check("the car has a gear list to work from",
          g061 == len(ratios061) and g061 >= 3, f"{g061} / {len(ratios061)}")
    grew61 = statlib.write(root, CAR, {"gears": str(g061 + 2)})
    check("two more gears can be asked for", grew61["changed"] == ["gears"],
          str(grew61["changed"]))
    spec61 = speclib.load_spec(os.path.join(root, ".depot"), SPEC[:-8])
    after61 = spec61.stats()
    check("the count reads back", after61["gears"] == g061 + 2,
          str(after61["gears"]))
    new61 = spec61.gear_ratios()
    check("with two more ratios in the list", len(new61) == g061 + 2,
          str(len(new61)))
    forward61 = new61[:-1]
    check("the forward gears still get shorter every time",
          all(forward61[i] > forward61[i + 1]
              for i in range(len(forward61) - 1)),
          str([round(v, 3) for v in forward61]))
    check("the top gear is where the designer put it",
          abs(new61[-2] - ratios061[-2]) < 1e-4,
          f"{ratios061[-2]} -> {new61[-2]}")
    check("and the trailing ratio is untouched",
          abs(new61[-1] - ratios061[-1]) < 1e-4, f"{ratios061[-1]} {new61[-1]}")
    check("nothing else in the spec moved",
          all(after61.get(k) == start61.get(k) for k in
              ("pr", "pr_max", "power_hp", "power_rpm", "torque", "redline",
               "limiter", "final_drive", "weight_lb", "top_speed", "route",
               "aspiration", "layout", "unlock", "cash", "gold")),
          str({k: (start61.get(k), after61.get(k)) for k in start61
               if start61.get(k) != after61.get(k)}))
    check("and the car is still itself",
          spec61.display_name_key() == key061, str(spec61.display_name_key()))
    back61 = statlib.write(root, CAR, {"gears": str(g061)})
    check("the old count goes back", back61["changed"] == ["gears"],
          str(back61["changed"]))
    spec61 = speclib.load_spec(os.path.join(root, ".depot"), SPEC[:-8])
    check("and the ratios come back with it",
          all(abs(a - b) < 1e-5 for a, b in
              zip(spec61.gear_ratios(), ratios061)),
          str([round(v, 4) for v in spec61.gear_ratios()]))
    check("writing the count it already has does nothing",
          spec61.set_gears(g061) is False)
    check("a count the game cannot read is refused before the file is touched",
          _raises(speclib.SpecError, spec61.set_gears, 40))
    check("one gear is refused too, because there is no forward list to rebuild",
          any("at least two" in p for p in statlib.validate({"gears": 1})),
          str(statlib.validate({"gears": 1})))
    check("cutting every forward gear away is refused",
          _raises(speclib.SpecError, spec61.set_gears, 1))

    # ---- the maximum PR ------------------------------------------------
    got61 = statlib.read(root, CAR)["fields"]
    pr061, max061 = got61["pr"]["value"], got61["pr_max"]["value"]
    made61 = statlib.write(root, CAR, {"pr_max": "61.5"})
    check("the maximum PR can be set", made61["changed"] == ["pr_max"],
          str(made61["changed"]))
    read61 = statlib.read(root, CAR)["fields"]
    check("it reads back as written",
          abs(read61["pr_max"]["value"] - 61.5) < 1e-3,
          str(read61["pr_max"]["value"]))
    check("and the starting PR was left where it was",
          abs(read61["pr"]["value"] - pr061) < 1e-4,
          f"{pr061} -> {read61['pr']['value']}")
    check("an impossible maximum is refused",
          bool(statlib.validate({"pr_max": 900})),
          str(statlib.validate({"pr_max": 900})))
    statlib.write(root, CAR, {"pr_max": str(max061)})
    check("the old maximum goes back",
          abs(statlib.read(root, CAR)["fields"]["pr_max"]["value"] - max061)
          < 1e-3, "")

    # ---- the folder is optional when changing a car --------------------
    check("an empty folder with nothing mapped is fine for an installed car",
          slotlib.problems("", {}, required=False) == [],
          str(slotlib.problems("", {}, required=False)))
    check("a new car still needs its body",
          bool(slotlib.problems("", {})), str(slotlib.problems("", {})))
    check("a slot that is filled is still checked",
          bool(slotlib.problems("", {"A": os.path.join(root, "nope.m3g")},
                                required=False)),
          str(slotlib.problems("", {"A": os.path.join(root, "nope.m3g")},
                               required=False)))
    check("one real file in one slot is a build on its own",
          slotlib.problems("", {"A": os.path.join(root, ".depot")},
                           required=False)[0].endswith("is missing"),
          str(slotlib.problems("", {"A": os.path.join(root, ".depot")},
                               required=False)))

    print("62 the compare that said everything was missing")
    import hashlib

    # The emulator's ``su`` refuses a long argument outright: a 31-file md5sum
    # batch (4.3 KB of quoted paths) came back empty with exit code 255 while a
    # 20-file one answered.  The empty answer used to be read as "the device has
    # none of these files", so a car's whole folder was listed as missing on
    # every compare however often it had just been pushed.  This stand-in
    # refuses the same way, so the batching can be exercised without a device.
    class FakeAdb:
        def __init__(self, limit=0, refuse_multi=False):
            self.limit = limit
            self.refuse_multi = refuse_multi
            self.present = set()
            self.calls = []

        def su(self, cmd, check=False):
            self.calls.append(cmd)
            paths = cmd.split()[1:]

            class R:
                returncode = 0
                stdout = ""
                stderr = ""
            r = R()
            if ((self.limit and len(cmd) > self.limit)
                    or (self.refuse_multi and len(paths) > 1)):
                r.returncode = 255
                return r
            lines = []
            for word in paths:
                path = word.strip("'")
                rel = path[len(deploylib.DEV) + 1:]
                if rel in self.present:
                    lines.append(f"{hashlib.md5(rel.encode()).hexdigest()}  {path}")
            r.stdout = "".join(line + "\n" for line in lines)
            return r

    rels62 = [f".depot/vehicles/{CAR}/file_{i:02d}.m3g" for i in range(30)]
    naive = len("md5sum " + " ".join(f"'{deploylib.DEV}/{r}'" for r in rels62))
    check("one command for all thirty would have been too long to send",
          naive > deploylib.MAX_CMD, f"{naive} chars")
    strict = FakeAdb(limit=deploylib.MAX_CMD)
    strict.present = set(rels62)
    got62 = deploylib.remote_md5(strict, rels62, log=lambda m: None)
    check("every file comes back even when the device refuses a long batch",
          len(got62) == len(rels62), f"{len(got62)} of {len(rels62)}")
    check("and no command went over the limit",
          max(len(c) for c in strict.calls) <= deploylib.MAX_CMD,
          f"longest {max(len(c) for c in strict.calls)}")

    picky = FakeAdb(refuse_multi=True)
    picky.present = set(rels62)
    got62b = deploylib.remote_md5(picky, rels62, log=lambda m: None)
    check("a refused batch is retried one path at a time, and the files come back",
          len(got62b) == len(rels62)
          and any(c.count("'") == 2 for c in picky.calls),
          f"{len(got62b)} of {len(rels62)}, {len(picky.calls)} calls")

    quick = FakeAdb()
    quick.present = set(rels62)
    deploylib.remote_md5(quick, rels62, log=lambda m: None)
    check("a batch that answers is not repeated path by path",
          len(quick.calls) <= 3 and all(c.count("'") > 2 for c in quick.calls),
          f"{len(quick.calls)} calls")

    # ---- the text tables are parallel arrays ---------------------------
    class FakeWc:
        def __init__(self, lines):
            self.lines = lines
            self.asked = []

        def su(self, cmd, check=False):
            self.asked.append(cmd)

            class R:
                returncode = 0
                stderr = ""
            r = R()
            r.stdout = f"{self.lines} {cmd.split()[-1]}\n"
            return r

    local_text = os.path.join(root, ".depot", "text_en.txt")
    with open(local_text, "rb") as fh:
        ours62 = fh.read().count(b"\n")
    try:
        deploylib.check_texts(local_text, ".depot/text_en.txt", FakeWc(ours62))
        check("a text table with the same line count is allowed", True)
    except deploylib.DeployError as exc:
        check("a text table with the same line count is allowed", False,
              str(exc)[:120])
    try:
        deploylib.check_texts(local_text, ".depot/text_en.txt",
                              FakeWc(ours62 + 5))
        check("a text table that would drop device lines is refused", False,
              "a shorter copy was let through")
    except deploylib.DeployError as exc:
        check("a text table that would drop device lines is refused",
              "parallel arrays" in str(exc), str(exc)[:120])
    try:
        deploylib.check_texts(local_text, ".depot/vehicles/data/x.nct", FakeWc(1))
        check("files that are not text tables are not inspected", True)
    except deploylib.DeployError as exc:
        check("files that are not text tables are not inspected", False,
              str(exc)[:120])

    # ---- what a per-car compare actually looks at ----------------------
    seen62 = {}
    real62 = deploylib.compare_files

    def capture(dev, where, rels, log=print):
        seen62["rels"] = [str(x).replace("\\", "/") for x in rels]
        return []

    deploylib.compare_files = capture
    try:
        deploylib.compare_car(None, root, CAR, log=lambda m: None)
    finally:
        deploylib.compare_files = real62
    looked = seen62.get("rels") or []
    check("the compare reads the text tables a rename rewrites",
          ".depot/gametext.txt" in looked
          and all(f".depot/text_{lang}.txt" in looked
                  for lang in textslib.LANGUAGES),
          str(len(looked)))
    check("and the tables a build adds rows to",
          ".depot/vehicles/data/cardesc.list.nct" in looked
          and ".depot/vehicles/data/carappearances.appearances.nct" in looked,
          str([r for r in looked if "data/" in r and not r.endswith(".m3g")][:6]))
    check("and still the car's own folder, its spec and its livery table",
          any(r.startswith(f".depot/vehicles/{CAR}/") for r in looked)
          and any(r.endswith(f"_{CAR}.bin.nct") for r in looked)
          and f".depot/vehicles/data/liveries/{CAR}.liveries.bin.nct" in looked,
          str(len(looked)))

    print("84 the texture slots a car and its schemes have")
    from rrmod import texslots as texslotslib
    from rr3lib import texport

    mini_depot = os.path.join(root, ".depot")
    pages = texslotslib.car_pages(mini_depot, CAR)
    check("every page of the car's folder is listed", len(pages) >= 6,
          f"{len(pages)} page(s): {[p['stem'] for p in pages]}")
    check("each row carries the livery slot it fills",
          all(isinstance(p["slot"], int) for p in pages),
          str([p.get("slot") for p in pages]))
    check("and the file the depot actually holds",
          all(p.get("path") and os.path.isfile(p["path"]) for p in pages),
          str([p["stem"] for p in pages if not p.get("path")]))
    check("no stem is listed twice",
          len({p["stem"] for p in pages}) == len(pages),
          str([p["stem"] for p in pages]))
    check("the body slot is found by name", texslotslib.body_slot(mini_depot) == 1932,
          str(texslotslib.body_slot(mini_depot)))
    check("and the interior copy of it",
          texslotslib.interior_slot(mini_depot) == 1939,
          str(texslotslib.interior_slot(mini_depot)))

    slots = texslotslib.scheme_slots(mini_depot, CAR)
    check("a scheme lists the body first", slots and slots[0]["key"] == "body",
          str([s["key"] for s in slots][:3]))
    check("the body is the one slot a scheme needs",
          slots[0]["required"] is True, str(slots[0]))
    check("and every car page is offered after it",
          {s["key"] for s in slots[1:]} == {p["stem"] for p in pages},
          str(sorted({s["key"] for s in slots[1:]})[:6]))

    check("a page suffix is read off a name",
          texslotslib.page_suffix("x_misc.dxt.dds.z") == ".dxt.dds.z",
          texslotslib.page_suffix("x_misc.dxt.dds.z"))
    check("the longest suffix wins, not the shortest",
          texslotslib.page_suffix("x_misc.dxt.dds.z") != ".dds.z",
          texslotslib.page_suffix("x_misc.dxt.dds.z"))
    check("a picture is not a page",
          texslotslib.is_picture("misc.png")
          and not texslotslib.is_picture("misc.dxt.dds.z"),
          f"{texslotslib.is_picture('misc.png')} "
          f"{texslotslib.is_picture('misc.dxt.dds.z')}")
    check("a stem loses its suffix and its car",
          texslotslib.stem_of(f"{CAR}_misc.dxt.dds.z", CAR) == "misc",
          texslotslib.stem_of(f"{CAR}_misc.dxt.dds.z", CAR))

    check("a colour word is picked by eye, not by plain distance",
          texslotslib.colour_word((200, 24, 24)) == "red",
          texslotslib.colour_word((200, 24, 24)))
    check("a dark red stays dark",
          texslotslib.colour_word((120, 8, 16)) == "dark_red",
          texslotslib.colour_word((120, 8, 16)))
    check("a blue is a blue", texslotslib.colour_word((16, 32, 192)) == "blue",
          texslotslib.colour_word((16, 32, 192)))
    check("a light grey is called silver",
          texslotslib.colour_word((200, 200, 200)) == "silver",
          texslotslib.colour_word((200, 200, 200)))

    check("a car page is named the way the models are",
          texslotslib.target_rel(CAR, "misc", ".dxt.dds.z") ==
          f"{CAR}_misc.dxt.dds.z",
          texslotslib.target_rel(CAR, "misc", ".dxt.dds.z"))
    check("a scheme's body goes in livery/",
          texslotslib.target_rel(CAR, "ext_red", ".dxt.dds.z", place="livery") ==
          f"livery/{CAR}_ext_red.dxt.dds.z",
          texslotslib.target_rel(CAR, "ext_red", ".dxt.dds.z", place="livery"))
    check("a scheme's wheel stays in the car's folder",
          texslotslib.target_rel(CAR, "wheel_red", ".dxt.dds.z") ==
          f"{CAR}_wheel_red.dxt.dds.z",
          texslotslib.target_rel(CAR, "wheel_red", ".dxt.dds.z"))

    # A folder of exported files is matched to the slots by stem, the way the
    # m3g table matches LOD_A - and a picture of a paint scheme is told apart
    # from a page of the car by its name, not by its position.
    shot = os.path.join(ROOT, "work", "rrmod_test_texfolder")
    shutil.rmtree(shot, ignore_errors=True)
    os.makedirs(os.path.join(shot, "livery"))
    source_png = _png_fixture()
    for leaf in ("misc.png", "wheel.png", "ext_blue.png"):
        shutil.copyfile(source_png, os.path.join(shot, leaf))
    shutil.copyfile(source_png, os.path.join(shot, "livery", "ext_green.png"))
    found = texslotslib.folder_pictures(shot, CAR)
    check("the folder's pictures are read", len(found) >= 4,
          str([f["leaf"] for f in found]))
    guessed = texslotslib.guess(shot, CAR, pages)
    check("a picture called misc fills the misc slot", "misc" in guessed,
          str(sorted(guessed)))
    check("and it is the file the folder holds",
          os.path.basename(guessed["misc"]["path"]).startswith("misc"),
          str(guessed.get("misc", {}).get("path")))
    check("a slot with no picture in the folder is left alone",
          "badges" not in guessed, str(sorted(guessed)))
    livery_found = texslotslib.livery_pictures(shot, CAR)
    check("a file called ext_<colour> is a paint picture",
          {f["tag"] for f in livery_found} >= {"blue", "green"},
          str([f["tag"] for f in livery_found]))
    check("and it is offered as the body",
          all(f["slot"] in (1932, 1939) for f in livery_found),
          str([f["slot"] for f in livery_found]))
    shutil.rmtree(shot, ignore_errors=True)

    print("85 a picture fills a slot, and a scheme keeps its own")
    picture = _png_fixture()
    # an earlier group deleted a banim without dropping its manifest row, so the
    # install is not spotless by now - what matters is that this group adds
    # nothing to the list
    problems_before = len(editlib.verify(root))
    made = editlib.install_textures(
        root, CAR,
        [{"slot": p["slot"], "stem": p["stem"], "source": picture}
         for p in pages[:2]], family_key="dxt", log=lambda m: None)
    check("both pages were written", len(made["written"]) == 2,
          str([w["rel"] for w in made["written"]]))
    check("the name is the game's own",
          made["written"][0]["rel"] == f"{CAR}_{pages[0]['stem']}.dxt.dds.z",
          made["written"][0]["rel"])
    written_path = os.path.join(mini_depot, "vehicles", CAR,
                                made["written"][0]["rel"])
    check("the file is on disk", os.path.isfile(written_path),
          made["written"][0]["rel"])
    frame = texport.decode_frame(written_path)
    check("and it decodes back to a real page",
          (frame[0], frame[1]) == (48, 24), f"{frame[0]}x{frame[1]}")
    check("the slot names are reported back",
          sorted(made["slots"]) == sorted(p["name"] for p in pages[:2]),
          str(made["slots"]))
    rewritten = {r["stem"]: r for r in texslotslib.car_pages(mini_depot, CAR)}
    check("the table now names the file that was written",
          rewritten[pages[0]["stem"]].get("rel") == made["written"][0]["rel"],
          f"{rewritten[pages[0]['stem']].get('rel')} vs "
          f"{made['written'][0]['rel']}")
    check("the table was saved", bool(made["saved"]), str(made["saved"]))
    check("the pages are readable again after the write",
          len(rewritten) == len(pages), str(len(rewritten)))

    # A scheme's own pictures: the body in livery/, anything else in the car's
    # own folder - which is where every shipped scheme keeps a wheel of its own.
    scheme = editlib.set_paint_pictures(
        root, CAR, 0, {"body": picture, "wheel": picture},
        tag="red", family_key="dxt", log=lambda m: None)
    rels = [w["rel"] for w in scheme["written"]]
    check("the body goes in livery/ under the colour word",
          f"livery/{CAR}_ext_red.dxt.dds.z" in rels, str(rels))
    check("a wheel goes in the car's own folder",
          f"{CAR}_wheel_red.dxt.dds.z" in rels, str(rels))
    check("the body points both body slots at one file",
          scheme["slots"].count("ext_ext") == 1
          and scheme["slots"].count("int_ext") == 1, str(scheme["slots"]))
    check("and the wheel slot was pointed at its own page",
          "ext_wheel" in scheme["slots"], str(scheme["slots"]))
    table = liverylib.load_car(mini_depot, CAR)
    over = {int(s): p.decode("utf-8", "replace")
            for s, p in table.paints[0].overrides}
    check("the table reads back with the body override",
          over.get(1932) == f"livery/{CAR}_ext_red.dxt.dds.z", str(over))
    check("and the interior copy of it", over.get(1939) == over.get(1932),
          str(over))
    check("the wheel override is the car-folder name",
          over.get(1938) == f"{CAR}_wheel_red.dxt.dds.z", str(over))
    untagged = editlib.set_paint_pictures(root, CAR, 1, {"body": picture},
                                          family_key="dxt",
                                          log=lambda m: None)
    check("a scheme with no tag takes its colour word",
          untagged["written"][0]["rel"].startswith(f"livery/{CAR}_ext_"),
          untagged["written"][0]["rel"])
    check("a slot the car does not have is refused",
          _raises(editlib.EditError, editlib.set_paint_pictures, root, CAR, 0,
                  {"nonsense": picture}, family_key="dxt", log=lambda m: None))
    check("a scheme index that is not there is refused",
          _raises(editlib.EditError, editlib.set_paint_pictures, root, CAR, 99,
                  {"body": picture}, family_key="dxt", log=lambda m: None))

    print("86 a shared page is named after what it is")
    taken = texslotslib.common_taken(mini_depot)
    check("the pages already there are known", len(taken) >= 1,
          f"{len(taken)} stem(s)")
    check("a tyre gets the next free number",
          texslotslib.common_name("tyre", taken).startswith("car_tyre_"),
          texslotslib.common_name("tyre", taken))
    check("and never one that is taken",
          texslotslib.common_name("tyre", taken) not in taken,
          texslotslib.common_name("tyre", taken))
    check("an interior material gets a _matNN tail",
          texslotslib.common_name("leather", taken) == "leather_mat00",
          texslotslib.common_name("leather", taken))
    check("the next one of that material steps up",
          texslotslib.common_name("leather", taken | {"leather_mat00"}) ==
          "leather_mat01",
          texslotslib.common_name("leather", taken | {"leather_mat00"}))
    check("a label can be forced either way",
          texslotslib.common_name("leather", taken, kind="part") == "car_leather_01",
          texslotslib.common_name("leather", taken, kind="part"))
    check("the label list covers the shipped families",
          {"tyre", "windows", "leather", "carbon_fibre"} <=
          {k for k, _h in texslotslib.COMMON_LABELS},
          str([k for k, _h in texslotslib.COMMON_LABELS]))

    added = editlib.add_common_picture(root, picture, label="tyre",
                                       family_key="dxt", log=lambda m: None)
    check("the page is named car_tyre_<nn>",
          added["name"].startswith("car_tyre_"), added["name"])
    check("and it lands in vehicles/common",
          os.path.isfile(os.path.join(mini_depot, "vehicles", "common",
                                      added["name"] + added["suffix"])),
          added["name"] + added["suffix"])
    # ``manifestlib`` is ``rr3lib.manifest``, imported at the top of this file
    rows = manifestlib.load_asset_list(root, editlib.COMMON_LIST)
    listed = [p for p in rows.paths()
              if p.startswith(f"/vehicles/common/{added['name']}.")]
    check("the four asset-list rows came with it", len(listed) == 4, str(listed))
    check("it is recorded so it can be deleted later",
          f"common/{added['name']}" in (depslib.load(mini_depot)["pages"] or {}),
          str(sorted(depslib.load(mini_depot)["pages"])[:4]))
    second = editlib.add_common_picture(root, picture, label="tyre",
                                        family_key="dxt", log=lambda m: None)
    check("a second one under the same label takes the next number",
          second["name"] != added["name"], f"{added['name']} {second['name']}")
    check("adding a page booked every manifest row it needs",
          len(editlib.verify(root)) == problems_before,
          str(editlib.verify(root)[:2]))
    removed = editlib.remove_common_page(root, second["name"])
    check("the page this program added can be taken back out",
          len(removed["files"]) == 1, str(removed.get("files")))

    print("87 a suspension record carries the travel pair")
    # floats 23/24 of the 140 byte record are the front/rear travel in metres.
    # They are the only thing in the shipped tables that says how far a car's
    # suspension moves - there is no min/max pair anywhere - so writing them is
    # how a car is made to sit differently.  See docs/避震行程-调节范围.md.
    table = speclib.load_suspension(mini_depot)
    rid = table.ids()[0]
    rec = table.get(rid)
    front, rear = speclib.suspension_travel(rec)
    check("the pair reads back as two floats",
          isinstance(front, float) and isinstance(rear, float),
          f"{front} {rear}")

    written = speclib.set_suspension_travel(rec, front=0.032, rear=0.031)
    got = speclib.suspension_travel(written)
    check("the front and rear land in floats 23 and 24",
          abs(got[0] - 0.032) < 1e-6 and abs(got[1] - 0.031) < 1e-6, str(got))
    diff = [i for i, (a, b) in enumerate(zip(rec, written)) if a != b]
    check("nothing outside those two floats moves",
          diff and all(4 + 4 * 23 <= i < 4 + 4 * 25 for i in diff), str(diff))
    check("the tyre diameters are left alone",
          speclib.suspension_tyre_diameter(written) ==
          speclib.suspension_tyre_diameter(rec),
          str(speclib.suspension_tyre_diameter(written)))
    only_front = speclib.set_suspension_travel(rec, front=0.05)
    check("either end can be written on its own",
          abs(speclib.suspension_travel(only_front)[1] - rear) < 1e-9,
          str(speclib.suspension_travel(only_front)))
    check("the sane range brackets what the shipped cars use",
          speclib.SUSP_TRAVEL_SANE[0] <= 0.003
          and speclib.SUSP_TRAVEL_SANE[1] >= 0.150,
          str(speclib.SUSP_TRAVEL_SANE))

    print()
    print(f"{_ok} passed, {len(_bad)} failed")
    for b in _bad:
        print("  -", b)
    if not keep:
        shutil.rmtree(MINI, ignore_errors=True)
        shutil.rmtree(os.path.join(ROOT, "work", "rrmod_test_pack"),
                      ignore_errors=True)
    return 0 if not _bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
