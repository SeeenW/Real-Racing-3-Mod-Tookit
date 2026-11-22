"""End-to-end test of rr3lib.car.build_car against the real depot (read only)."""
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from rr3lib import appearance, car, livery, nct, spec  # noqa: E402

PKG = r"E:\DXT_480x320+960x640+2048x1536数据包-Build260716\files"
DEPOT = os.path.join(PKG, ".depot")
OUT = os.path.join(tempfile.gettempdir(), "rr3_cartest")
NEWDEPOT = os.path.join(OUT, ".depot")
DATA = os.path.join(NEWDEPOT, "vehicles", "data")
RES = os.path.join(OUT, "apk", "res")

DONOR = "2012_lexus_lfa"
NEW = "2026_test_clone"

fails = []
info = {}


def step(name, fn):
    try:
        out = fn()
        print(f"OK   {name}" + (f"  -> {out}" if out is not None else ""))
    except Exception as exc:
        import traceback
        fails.append(name)
        print(f"FAIL {name}: {exc}")
        traceback.print_exc()


if os.path.isdir(OUT):
    shutil.rmtree(OUT)
os.makedirs(OUT, exist_ok=True)

ids = car.used_ids(DEPOT)
NEW_ID = car.free_car_id(DEPOT)
print(f"depot: {len(ids)} car ids, max {max(ids)}, next free {NEW_ID}")


def _name_check():
    for bad in ("nope", "2026_bad/name"):
        try:
            car.check_name(bad)
        except car.CarError:
            pass
        else:
            raise AssertionError(f"{bad!r} was accepted")
    car.check_name("2026_test_clone")
    return "rejects bad names, accepts 2026_test_clone"


step("name check", _name_check)


def _seed():
    """Seed the shared livery tables so the output depot can be read back."""
    src = os.path.join(DEPOT, "vehicles", "data", "liveries")
    dst = os.path.join(DATA, "liveries")
    os.makedirs(dst, exist_ok=True)
    for f in ("liveryStringTable.bin.nct", "default.liveries.bin.nct"):
        shutil.copyfile(os.path.join(src, f), os.path.join(dst, f))
    return "liveryStringTable + default copied into the output depot"


step("seed", _seed)


def _build():
    info.update(car.build_car(DEPOT, PKG, OUT, new_id=NEW_ID, new_name=NEW,
                              donor_name=DONOR, log=lambda s: None))
    return (f"id {info['new_id']}, appearance {info['appearance_id']}, "
            f"model {info['model_token']}, display {info['display_key']}")


step("build car", _build)


def _spec_ok():
    path = os.path.join(DATA, f"{NEW_ID}_{NEW}.bin.nct")
    assert os.path.exists(path), path
    s = spec.load_spec(NEWDEPOT, NEW_ID)
    assert s.car_id == NEW_ID, s.car_id
    assert s.appearance_id() == info["appearance_id"], s.appearance_id()
    assert s.aero_flag() == spec.AERO_FLAG, s.aero_flag()
    assert s.display_name_key() == info["display_key"]
    assert s.model() == info["model_token"], s.model()
    assert s.to_bytes() == nct.read(path), "spec does not round trip"
    return s.summary()


step("spec", _spec_ok)


def _tables_ok():
    desc = spec.load_cardesc(NEWDEPOT)
    assert f"{NEW_ID}_{NEW}.bin" in [e.decode() for e in desc.entries]
    susp = spec.load_suspension(NEWDEPOT)
    dmg = spec.load_damage(NEWDEPOT)
    assert NEW_ID in susp.ids(), "new id missing from suspension"
    assert NEW_ID in dmg.ids(), "new id missing from damage"
    assert len(nct.read(os.path.join(
        DATA, "suspensionbehaviour.suspensiondata.nct"))) == 75608 + 140
    assert len(nct.read(os.path.join(
        DATA, "cardamagethresholds.damage.nct"))) == 62644 + 116
    return f"{desc.summary()}, {susp.summary()}, {dmg.summary()}"


step("cardesc/susp/damage", _tables_ok)


def _appear_ok():
    count, recs = appearance.load(NEWDEPOT)
    assert count == 541, count
    rec = recs[appearance.find(recs, NEW.encode())]
    assert rec.id == info["appearance_id"], (rec.id, info["appearance_id"])
    _c2, donor_recs = appearance.load(DEPOT)
    d = donor_recs[appearance.find(donor_recs, DONOR.encode())]
    assert rec.block == d.block, "appearance block differs from the donor"
    assert len(rec.block) == len(d.block), (len(rec.block), len(d.block))
    return (f"{count} records, id {rec.id}, "
            f"block {len(rec.block)} B (identical to the donor)")


step("appearances", _appear_ok)


def _livery_ok():
    L = livery.load_car(NEWDEPOT, NEW)
    table = livery.load_slot_table(NEWDEPOT)
    assert len(L.paints) == 6, len(L.paints)
    assert L.car.decode() == NEW, L.car
    wing = livery.SLOT_WING_REAR_EXT
    body = livery.SLOT_BODY_EXT
    hits = 0
    for p in L.paints:
        w = p.material_of(wing)
        b = p.material_of(body)
        if w is not None:
            assert w == b, f"{p.name()}: wing {w} != body {b}"
            hits += 1
    assert hits == 5, f"expected 5 schemes with a wing override, got {hits}"
    for _slot, path in L.textures:
        assert DONOR.encode() not in path, path
    return (f"{len(L.paints)} schemes, wing->body on {hits}, "
            f"wing slot {wing} -> {table.name(L.paints[0].material_of(wing))}")


step("liveries", _livery_ok)


def _folder_ok():
    d = os.path.join(NEWDEPOT, "vehicles", NEW)
    files = sorted(os.listdir(d))
    assert len(files) >= 26, f"only {len(files)} files in the car folder"
    assert f"{NEW}_a.m3g" in files, files
    assert f"{DONOR}_a.m3g" in files, "donor alias for the body m3g is missing"
    lv = sorted(os.listdir(os.path.join(d, "livery")))
    renamed = [f for f in lv if f.startswith(NEW)]
    aliases = [f for f in lv if f.startswith(DONOR)]
    assert len(renamed) == 6, renamed
    assert len(aliases) == 6, aliases
    return (f"{len(files)} files, {len(renamed)} livery textures "
            f"+ {len(aliases)} donor aliases")


step("car folder", _folder_ok)


def _manifest_ok():
    path = os.path.join(RES, f"asset_list_vehicle_{NEW}.txt")
    rows = open(path, encoding="utf-8").read().strip().split("\n")
    assert len(rows) == 87, len(rows)
    assert all(NEW in r.split("\t")[0] for r in rows), "row paths not renamed"
    reg = open(os.path.join(NEWDEPOT, "asset_list_base.txtCache.txt"), "rb").read()
    assert reg[:4] == b"\x9d\xf3\xf6\xa4", reg[:4]
    n_reg = reg.count(b"\n")
    assert n_reg >= 47090, n_reg
    dl = open(os.path.join(RES, "asset_list_vehicle_data.txt"), encoding="utf-8").read()
    assert f"{NEW_ID}_{NEW}.bin.nct" in dl
    keys = [r.split("\t")[0] for r in dl.strip().split("\n")]
    assert keys == sorted(keys), "data list is no longer sorted"
    return f"{len(rows)} manifest rows, {n_reg} registry rows, {len(keys)} data rows"


step("manifests", _manifest_ok)


def _reload_all():
    spec.load_cardesc(NEWDEPOT)
    spec.load_suspension(NEWDEPOT)
    spec.load_damage(NEWDEPOT)
    appearance.load(NEWDEPOT)
    livery.load_car(NEWDEPOT, NEW)
    livery.load_default(NEWDEPOT)
    return "all tables re-read cleanly"


step("reload", _reload_all)


def _set_material():
    info2 = car.set_part_material(NEWDEPOT, NEW, "LOD_A_WING_REAR_mm_ext",
                                  "car_paint_matte")
    L = livery.load_car(NEWDEPOT, NEW)
    table = livery.load_slot_table(NEWDEPOT)
    mats = {p.material_of(livery.SLOT_WING_REAR_EXT) for p in L.paints}
    assert len(mats) == 1, mats
    name = table.name(mats.pop())
    assert name == "car_paint_matte", name
    return f"wing is now {name} on all schemes"


step("set_part_material", _set_material)


def _bad_part():
    try:
        car.set_part_material(NEWDEPOT, NEW, "LOD_A_NOT_A_REAL_PART_mm_ext",
                              "car_paint_matte")
    except livery.LiveryError as exc:
        return f"rejects unknown part names ({str(exc)[:40]}...)"
    raise AssertionError("unknown part name was accepted")


step("bad part name", _bad_part)


def _audit():
    meshes = ["LOD_A_BODY_mm_ext", "LOD_A_WING_REAR_mm_ext",
              "LOD_A_TYRE_mm_tyre", "LOD_A_NOT_REAL_mm_ext"]
    rows = car.audit_paint(NEWDEPOT, NEW, meshes, paint_index=0)
    levels = {r[0]: r[3] for r in rows}
    assert levels["LOD_A_BODY_mm_ext"] == "paint", levels
    assert levels["LOD_A_WING_REAR_mm_ext"] == "paint", levels
    assert levels["LOD_A_NOT_REAL_mm_ext"] == "no-slot", levels
    # without a scheme the body falls through to the default table
    plain = {r[0]: r[3] for r in car.audit_paint(NEWDEPOT, NEW, meshes)}
    assert plain["LOD_A_BODY_mm_ext"] == "default", plain
    return (", ".join(f"{m}={l}" for m, l in levels.items())
            + f" | no scheme: body={plain['LOD_A_BODY_mm_ext']}")


step("audit", _audit)


print()
if fails:
    print(f"CARTEST: {len(fails)} FAILURE(S): {fails}")
    sys.exit(1)
print("CARTEST: PASS")
print(f"output kept in {OUT}")
