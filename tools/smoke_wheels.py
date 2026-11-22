"""Headless check: does the vehicle importer scale the shared wheel template,
and does it mount the wheels where the .points file says?

Run with:
  & "C:\\Program Files\\Blender Foundation\\Blender 4.5\\blender.exe" -b `
      --factory-startup --python tools\\smoke_wheels.py
"""
import os
import sys

import bpy
from mathutils import Vector

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import rr3_blender_addon as addon  # noqa: E402
from rr3lib import parts as partslib  # noqa: E402

DEPOT = r"E:\DXT_480x320+960x640+2048x1536数据包-Build260716\files\.depot"
CARS = ("2012_lexus_lfa", "2018_bugatti_chiron_sport", "2013_caterham_seven_620r",
        "2011_pagani_huayra")

ok = fail = 0


def check(label, cond, detail=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"OK   {label}" + (f" -> {detail}" if detail else ""))
    else:
        fail += 1
        print(f"FAIL {label}" + (f" -> {detail}" if detail else ""))


def run(car, mode="engine", **kw):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    car_dir = os.path.join(DEPOT, "vehicles", car)
    return addon.import_vehicle_file(car_dir, car, lod="A", textures=False,
                                     wheel_size=mode, animate=False, **kw)


for car in CARS:
    print(f"\n=== {car} ===")
    car_dir = os.path.join(DEPOT, "vehicles", car)
    plan = partslib.build_plan(car_dir, car, "A")

    res = run(car)
    fit = res["wheel_fit"]
    check(f"{car}: engine plan", fit is not None,
          f"x{fit.front:.3f}/x{fit.rear:.3f} from {fit.source}" if fit else "none")

    scales = sorted({round(o.get("rr3_wheel_scale", 1.0), 4) for o in res["wheels"]})
    check(f"{car}: wheel objects scaled", all(abs(s - 1.0) > 1e-6 for s in scales),
          f"scales {scales}")

    # radial only: x stays 1, y and z are the factor
    bad = [o.name for o in res["wheels"]
           if abs(o.scale[0] - 1.0) > 1e-6 or abs(o.scale[1] - o.scale[2]) > 1e-6]
    check(f"{car}: radial-only scaling", not bad, f"{len(bad)} wrong: {bad[:3]}")

    tyre = [o for o in res["wheels"] if "TYRE" in o.name]
    if tyre:
        # dimensions are only valid after the depsgraph has seen the new scale
        bpy.context.view_layer.update()
        o = tyre[0]
        dims = o.dimensions
        want = 0.5986 * o.scale[1]
        check(f"{car}: tyre is car-sized",
              abs(max(dims.y, dims.z) - want) < 0.02,
              f"{max(dims.y, dims.z):.3f} m across, template x{o.scale[1]:.3f} "
              f"-> {want:.3f} m")

    # ---------------------------------------------------------- wheel mounting
    # Every wheel pivot must sit exactly on its .points anchor, and the tyre
    # must be outboard of it (x = 0 is the wheel's outer face), not centred.
    for mount in plan.wheel_mounts:
        piv = bpy.data.objects.get(f"WHEEL_{mount.corner}")
        anc = bpy.data.objects.get(f"ANCHOR_{mount.name}")
        if piv is None or anc is None:
            check(f"{car}: pivot+anchor for {mount.corner}", False, "missing")
            continue
        d = (Vector(piv.location) - Vector(anc.location)).length
        check(f"{car}: {mount.corner} pivot on its anchor", d < 1e-5,
              f"off by {d * 1000:.3f} mm")

        parts = [c for c in piv.children]
        xs = []
        for ob in parts:
            xs.extend((ob.matrix_world @ v.co).x for v in ob.data.vertices)
        if not xs:
            continue
        # all geometry of the left side is inboard (+x) of the anchor, the right
        # side outboard (-x): either way the anchor is at one end of the span.
        # A rim lip may stick a few mm past x = 0, so allow 5 % of the width.
        span = max(xs) - min(xs)
        near = min(abs(min(xs) - anc.location.x), abs(max(xs) - anc.location.x))
        check(f"{car}: {mount.corner} wheel hangs off the point",
              near < 0.05 * max(span, 1e-6),
              f"span {span:.3f} m, nearest face {near * 1000:.1f} mm from the point")

    # hub height: a wheel standing on the ground has its centre about one tyre
    # radius up, i.e. 0.28 .. 0.40 m - never ~0
    zs = [bpy.data.objects[f"WHEEL_{m.corner}"].location.z for m in plan.wheel_mounts]
    check(f"{car}: hub height is a wheel radius",
          all(0.25 < z < 0.42 for z in zs), f"z {[round(z, 3) for z in zs]}")

    # ------------------------------------------------------------- wheel normals
    # The right side and the widened rear tyre go through _build_mesh_object's
    # matrix path.  A bug there once dropped the custom normals of exactly those
    # meshes (tuple().normalized()) and the exception was swallowed, so the rear
    # tyre rendered unlit while the front looked fine.
    bpy.context.view_layer.update()
    no_nrm = [o.name for o in res["wheels"]
              if len(o.data.vertices) and not o.data.has_custom_normals]
    check(f"{car}: every wheel keeps its custom normals", not no_nrm,
          f"{len(no_nrm)} lost: {no_nrm[:4]}")
    flipped = []
    for o in res["wheels"]:
        me = o.data
        loops = 0
        bad = 0
        for poly in me.polygons:
            for li in poly.loop_indices:
                loops += 1
                ln = me.loops[li].normal
                if ln.length < 1e-6:
                    bad += 1
                elif poly.normal.length > 1e-6 and ln.dot(poly.normal) < 0.0:
                    bad += 1
        # A few polys are authored inside-out in the source data (the LFA rim
        # has 10 of 3384), so allow a small fraction - but never a whole mesh,
        # which is what a lost normal set looks like.
        if loops and bad > max(4, int(loops * 0.02)):
            flipped.append(f"{o.name} {bad}/{loops}")
    check(f"{car}: wheel normals point outward", not flipped,
          f"{len(flipped)} bad: {flipped[:3]}")

    res2 = run(car, "none")
    flat = sorted({round(o.get("rr3_wheel_scale", 1.0), 4) for o in res2["wheels"]})
    check(f"{car}: 'none' leaves it alone", flat == [1.0], f"scales {flat}")

    res3 = run(car, "ground")
    fit3 = res3["wheel_fit"]
    if fit and fit3:
        # 'ground' is the loaded radius, which is normally a little under the
        # free radius - but a car whose hub sits above its own free radius (the
        # Zenvo case MonkeyTool mentions) legitimately lands slightly above it.
        diff = (fit3.front - fit.front) / fit.front
        check(f"{car}: ground is close to engine", abs(diff) < 0.20,
              f"x{fit3.front:.3f} vs x{fit.front:.3f} ({diff:+.1%})")

# ---------------------------------------------------------------- rear tyre
# Pagani Huayra ships a wider WHEEL_REAR but no TYRE_REAR; the rear tyre has to
# be widened to the rim ratio or it sits inside its own rim.
print("\n=== rear tyre width ===")
for car in ("2011_pagani_huayra", "2012_lexus_lfa"):
    res = run(car)
    bpy.context.view_layer.update()
    got = {}
    for ob in res["wheels"]:
        if "TYRE" not in ob.name:
            continue
        rear = "_B" in ob.name.split("_TYRE")[0] or ob.name.startswith("B")
        got.setdefault("rear" if rear else "front", []).append(ob.dimensions.x)
    plan = partslib.build_plan(os.path.join(DEPOT, "vehicles", car), car, "A")
    shared = addon.m3glib.M3G(plan.shared_file)
    by = {md.name: md for md in addon.geometrylib.all_meshes(shared)}
    fw = addon._mesh_width(by.get(plan.wheels.front_wheel))
    rw = addon._mesh_width(by.get(plan.wheels.rear_wheel))
    if got.get("front") and got.get("rear") and fw and rw:
        ratio = (got["rear"][0] / got["front"][0]) if got["front"][0] > 1e-9 else 0
        want = rw / fw
        check(f"{car}: rear tyre matches rear rim", abs(ratio - want) < 0.06,
              f"tyre ratio {ratio:.3f} vs rim ratio {want:.3f} "
              f"(front {got['front'][0]:.3f} m, rear {got['rear'][0]:.3f} m)")

# ------------------------------------------------------------- frame options
print("\n=== frame options ===")
res_a = run("2012_lexus_lfa")
piv_a = {o.name: Vector(o.location) for o in res_a["empties"] if o.name.startswith("WHEEL_")}
res_b = run("2012_lexus_lfa", facing="-Y")
piv_b = {o.name: Vector(o.location) for o in res_b["empties"] if o.name.startswith("WHEEL_")}
if piv_a and piv_b:
    same = all((piv_a[k] - piv_b[k]).length < 1e-6 for k in piv_a)
    # the root empty carries the turn, so the local locations are unchanged
    root = bpy.data.objects.get("2012_lexus_lfa_ROOT")
    check("facing -Y turns the car via one root empty",
          same and root is not None and abs(root.rotation_euler.z - 3.14159265) < 1e-4,
          f"{len(piv_a)} pivots unchanged, root z={root.rotation_euler.z if root else None}")

res_c = run("2012_lexus_lfa", mirror_x=True)
root_c = bpy.data.objects.get("2012_lexus_lfa_ROOT")
check("mirror_x sets a -1 scale on the root",
      root_c is not None and abs(root_c.scale.x + 1.0) < 1e-6,
      f"root scale {tuple(round(v, 2) for v in root_c.scale) if root_c else None}")

# -------------------------------------------------------------------- brakes
# The engine sizes the disc and the caliper with the tyre's radial factor, and
# mounts them on the same point, but a caliper does not turn with the wheel: all
# four are modelled in their own corner already.
print("\n=== brakes ===")
for car in ("2012_lexus_lfa", "2018_bugatti_chiron_sport"):
    res = run(car)
    plan = res["plan"]
    by_corner = {}
    for ob in res["wheels"]:
        corner = ob.name.split("_", 1)[0]
        by_corner.setdefault(corner, []).append(ob)
    missing = []
    for mount in plan.wheel_mounts:
        names = [o.name for o in by_corner.get(mount.corner, [])]
        has_rotor = any("ROTOR" in n for n in names)
        has_caliper = any("CALIPER" in n for n in names)
        if not (has_rotor and has_caliper):
            missing.append(f"{mount.corner} rotor={has_rotor} caliper={has_caliper}")
    check(f"{car}: disc and caliper on every corner", not missing, f"{missing}")

    # same radial factor as the tyre of the same axle, and never a turn on the
    # caliper
    k_front = k_rear = None
    for ob in res["wheels"]:
        if "TYRE" not in ob.name:
            continue
        if ob.name.startswith("B"):
            k_rear = ob.get("rr3_wheel_scale")
        else:
            k_front = ob.get("rr3_wheel_scale")
    bad_scale = []
    for o in res["wheels"]:
        if "ROTOR" not in o.name and "CALIPER" not in o.name:
            continue
        want = k_rear if o.name.startswith("B") else k_front
        if want is not None and abs(o.get("rr3_wheel_scale", 1.0) - want) > 1e-6:
            bad_scale.append(o.name)
    check(f"{car}: brakes take the tyre's factor", not bad_scale,
          f"{len(bad_scale)} wrong: {bad_scale[:3]}")
    cal = [o for o in res["wheels"] if "CALIPER" in o.name]
    turned = [o.name for o in cal
              if any(abs(a) > 1e-6 for a in o.rotation_euler)]
    check(f"{car}: calipers are not turned", not turned, f"{len(turned)} turned")

    # a right-hand caliper is modelled on -x, so the four must sit on both sides
    bpy.context.view_layer.update()
    cx = {}
    for o in cal:
        xs = [(o.matrix_world @ v.co).x for v in o.data.vertices]
        if xs:
            cx[o.name.split("_", 1)[0]] = (min(xs) + max(xs)) / 2
    left = [c for c, x in cx.items() if x < 0]
    right = [c for c, x in cx.items() if x > 0]
    check(f"{car}: calipers land on both sides", len(left) == 2 and len(right) == 2,
          f"left {sorted(left)} right {sorted(right)}")

res_nb = run("2012_lexus_lfa", brakes=False)
check("brakes=False mounts no disc or caliper",
      not [o for o in res_nb["wheels"] if "ROTOR" in o.name or "CALIPER" in o.name],
      f"{len(res_nb['wheels'])} wheel objects")

# --------------------------------------------------------------- LOD F (whole car)
# LOD F's wheel mesh is the four wheels already assembled in car space and at the
# real size.  Scaling or moving it would apply the assembly twice.
print("\n=== pre-assembled LOD ===")
for car in ("2012_lexus_lfa", "2011_pagani_huayra"):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    car_dir = os.path.join(DEPOT, "vehicles", car)
    res_f = addon.import_vehicle_file(car_dir, car, lod="F", textures=False,
                                      animate=False)
    check(f"{car}: LOD F knows it is pre-assembled",
          res_f["plan"].wheels.pre_assembled, "pre_assembled")
    check(f"{car}: LOD F fits no wheel size", res_f["wheel_fit"] is None,
          f"{res_f['wheel_fit']}")
    objs = res_f["wheels"]
    check(f"{car}: LOD F imports the assembled mesh", bool(objs), f"{len(objs)} mesh(es)")
    bad = [o.name for o in objs
           if any(abs(v - 1.0) > 1e-6 for v in o.scale)
           or Vector(o.location).length > 1e-6]
    check(f"{car}: LOD F wheels are untouched", not bad, f"{bad}")
    if objs:
        bpy.context.view_layer.update()
        # the assembled mesh spans both sides of the car and stands on y = 0
        xs = [(objs[0].matrix_world @ v.co).x for v in objs[0].data.vertices]
        zs = [(objs[0].matrix_world @ v.co).z for v in objs[0].data.vertices]
        check(f"{car}: LOD F wheels span the whole car",
              xs and min(xs) < -0.5 and max(xs) > 0.5,
              f"x {min(xs):.2f} .. {max(xs):.2f}")
        check(f"{car}: LOD F wheels stand on the ground",
              zs and min(zs) > -0.05 and min(zs) < 0.10,
              f"z {min(zs):.3f} .. {max(zs):.3f}")

# ------------------------------------------------------- LOD G / H and the rest
print("\n=== the low LODs ===")
LFA_DIR = os.path.join(DEPOT, "vehicles", "2012_lexus_lfa")


def import_lod(letter):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    return addon.import_vehicle_file(LFA_DIR, "2012_lexus_lfa", lod=letter,
                                     textures=False, animate=False)


res_g = import_lod("G")
names_g = [o.get("rr3_wheel") for o in res_g["wheels"]]
check("LOD G borrows the assembled LOD F wheels",
      bool(names_g) and all(n.startswith("LOD_F_") for n in names_g), f"{names_g}")
check("LOD G knows the wheels are pre-assembled",
      bool(res_g["plan"].wheels.pre_assembled), "pre_assembled")
check("LOD G does not fit a wheel size", res_g["wheel_fit"] is None, "no fit")
xs = [v[0] for o in res_g["wheels"] for v in (o.matrix_world @ vv.co for vv in o.data.vertices)]
check("LOD G wheels span the whole car",
      bool(xs) and min(xs) < -0.5 and max(xs) > 0.5, f"x {min(xs):.2f} .. {max(xs):.2f}")

res_h = import_lod("H")
check("LOD H has no wheels", res_h["wheels"] == [], f"{len(res_h['wheels'])} object(s)")
check("LOD H plans no wheel meshes",
      res_h["plan"].wheels.front_wheel is None, f"{res_h['plan'].wheels.front_wheel}")
check("LOD H says nothing about missing wheels",
      not any("wheel" in w for w in res_h["plan"].warnings),
      f"{res_h['plan'].warnings}")

res_s = import_lod("shared")
check("shared imports as one collection",
      [c.name for c in bpy.data.collections] == ["2012_lexus_lfa_shared"],
      f"{[c.name for c in bpy.data.collections]}")
check("shared is imported whole",
      len([o for o in res_s["collection"].objects if o.type == "MESH"]) == 43,
      f"{len(res_s['collection'].objects)} object(s)")
check("shared plans no wheels or aero",
      res_s["plan"].wheels.front_wheel is None and not res_s["plan"].aero_parts,
      "no wheels, no aero")
check("shared raises no warning", res_s["plan"].warnings == [],
      f"{res_s['plan'].warnings}")

res_i = import_lod("int_a")
check("int_a imports as one collection",
      [c.name for c in bpy.data.collections] == ["2012_lexus_lfa_int_a"],
      f"{[c.name for c in bpy.data.collections]}")
check("int_a brings the whole interior",
      len([o for o in res_i["collection"].objects if o.type == "MESH"]) == 44,
      f"{len(res_i['collection'].objects)} object(s)")
check("int_a is not treated as a body LOD",
      res_i["plan"].wheels.front_wheel is None, "no wheels")

print(f"\nWHEEL SMOKE: {'PASS' if not fail else 'FAIL'}  ({ok} ok, {fail} failed)")
