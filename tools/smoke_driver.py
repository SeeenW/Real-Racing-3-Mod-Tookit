"""Smoke test for the driver import.

Run with::

    & "C:\\Program Files\\Blender Foundation\\Blender 4.5\\blender.exe" \
        -b --factory-startup --python tools\\smoke_driver.py

Checks that ``import_scene.rr3_driver`` brings in the fifteen-part rig, poses it
from ``driver[_<car>].banim``, gives it the ``common/driver`` texture, hangs it
under one root empty and leaves it sitting at the steering wheel - hands on the
rim, head above the feet, chest behind the wheel.  The root is left unrotated:
the pose already faces the way the car does, and turning it put the figure in
backwards.  Finally it exports the pose back out as a ``.banim`` and reads it in
again, so the round trip is covered too.
"""

import glob
import os
import sys

import bpy
from mathutils import Vector

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import rr3_blender_addon as addon  # noqa: E402
from rr3lib import driver as drvlib  # noqa: E402

addon.register()

DEPOT = os.path.join(glob.glob(r"E:\DXT*Build260716")[0], "files", ".depot")
CARS = ("1951_ferrari_f1_f375", "1957_ferrari_500_trc", "1962_ferrari_250_gto",
        "2013_caterham_seven_620r", "2014_mclaren_p1")

ok = 0
fail = 0


def check(name, condition, detail=""):
    global ok, fail
    if condition:
        ok += 1
        print(f"OK   {name}" + (f" -> {detail}" if detail else ""))
    else:
        fail += 1
        print(f"FAIL {name}" + (f" -> {detail}" if detail else ""))


def centre(ob):
    return sum((ob.matrix_world @ v.co for v in ob.data.vertices), Vector()) / len(ob.data.vertices)


def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def mesh_named(fragment):
    found = [o for o in bpy.data.objects if o.type == "MESH" and fragment in o.name]
    return found[0] if found else None


# ------------------------------------------------------------------ the library
print("\n=== the driver library ===")
check("the depot has driver models", drvlib.driver_dir(DEPOT) is not None,
      f"{drvlib.driver_dir(DEPOT)}")
lods = drvlib.available_lods(DEPOT)
check("four LODs are available", lods == ["A", "B", "C", "D"], f"{lods}")
skins = drvlib.skins(DEPOT)
check("the common folder holds the skins", len(skins) >= 9, f"{len(skins)} skin(s)")
check("the default skin comes first",
      os.path.basename(skins[0]) == "driver.dxt.dds.z", f"{os.path.basename(skins[0])}")
model = drvlib.model_for(DEPOT, "a", "2014_mclaren_p1")
check("LOD A falls back to the shared model",
      model and os.path.basename(model) == "driver_lod_a.m3g", f"{model and os.path.basename(model)}")
per_car = drvlib.model_for(DEPOT, "c", "2016_mclaren_mp4x")
check("a car with its own LOD C gets it",
      per_car and os.path.basename(per_car) == "driver_lod_c_mclaren_mp4x.m3g",
      f"{per_car and os.path.basename(per_car)}")
banim, matched = drvlib.banim_for(DEPOT, "2013_caterham_seven_620r")
check("the seating animation is matched by car name",
      matched == "caterham", f"{os.path.basename(banim)} (matched {matched})")
banim, matched = drvlib.banim_for(DEPOT, "2014_mclaren_p1")
check("a car without one falls back to driver.banim",
      os.path.basename(banim) == "driver.banim", f"{os.path.basename(banim)}")

# the car's own data record names the animation - no name guessing
record = drvlib.car_record(DEPOT, "2014_toyota_ts040")
check("a car record is found by folder name",
      record and os.path.basename(record) == "156_2014_toyota_ts040.bin.nct",
      f"{os.path.basename(record) if record else None}")
named = drvlib.banim_in_record(record)
check("the record names the animation", named == "driver_919_lmp1.banim", f"{named}")
banim, matched = drvlib.banim_for(DEPOT, "2014_toyota_ts040")
check("the record beats the name match",
      os.path.basename(banim) == "driver_919_lmp1.banim", f"{os.path.basename(banim)}")
banim, matched = drvlib.banim_for(DEPOT, "1951_ferrari_f1_f375")
check("a car whose name cannot be guessed still gets its own animation",
      os.path.basename(banim) == "driver_f1_1951.banim", f"{os.path.basename(banim)}")

# ------------------------------------------------------------------- the import
print("\n=== the fifteen-part rig ===")
reset()
res = addon.import_driver(DEPOT, lod="a", car="2013_caterham_seven_620r")
meshes = [o for o in bpy.data.objects if o.type == "MESH"]
check("fifteen parts imported", len(meshes) == 15, f"{len(meshes)} mesh(es)")
check("one collection holds them all",
      [c.name for c in bpy.data.collections] == ["2013_caterham_seven_620r_DRIVER"],
      f"{[c.name for c in bpy.data.collections]}")
check("the parts are posed", res["posed"] == res["frames"] and res["posed"] > 150,
      f"{res['posed']} pose(s)")
check("the poses follow the file's own key rate", res["frames"] == 179,
      f"{res['frames']} frame(s)")
check("every part carries an action",
      all(o.animation_data and o.animation_data.action for o in meshes),
      f"{sum(1 for o in meshes if o.animation_data and o.animation_data.action)}/15")

root = res["root"]
check("a root empty carries the driver", root is not None and root.name.endswith("_DRIVER_ROOT"),
      f"{root.name if root else None}")
check("everything hangs off the root",
      all(o.parent == root for o in meshes),
      f"{sum(1 for o in meshes if o.parent == root)}/15")
check("the root is at the origin", root and root.location.length < 1e-6,
      f"{tuple(round(v, 4) for v in root.location)}")
check("the root leaves the figure facing the car's nose",
      root is not None and root.rotation_euler.to_matrix().is_identity,
      f"rot {tuple(round(v, 4) for v in root.rotation_euler)}" if root else "no root")

mats = {o.material_slots[0].material.name for o in meshes if o.material_slots}
check("one driver material", mats == {"driver"}, f"{sorted(mats)}")
img = bpy.data.images.get("driver.png") or bpy.data.images.get("driver.dxt.dds")
check("the common/driver texture is loaded",
      img is not None and tuple(img.size) == (512, 512),
      f"{img.name if img else None} {tuple(img.size) if img else ''}")
check("the texture is packed", bool(img and img.packed_file), "packed")
nodes = [n for n in meshes[0].material_slots[0].material.node_tree.nodes if n.type == "TEX_IMAGE"]
check("the texture is wired to Base Color",
      any(l.to_socket.name == "Base Color" for n in nodes for l in n.outputs["Color"].links),
      f"{[n.image.name for n in nodes if n.image]}")
check("every part shows the skin, not just the first",
      all(any(l.to_socket.name == "Base Color"
              for n in o.material_slots[0].material.node_tree.nodes
              if n.type == "TEX_IMAGE" and n.image is not None
              for l in n.outputs["Color"].links)
          for o in meshes if o.material_slots),
      f"{sum(1 for o in meshes if o.material_slots)} part(s)")
check("the material slot is on the mesh, not the object",
      all(s.link == "DATA" for o in meshes for s in o.material_slots),
      "DATA")
check("every polygon uses that slot",
      all(p.material_index == 0 for o in meshes for p in o.data.polygons), "index 0")

# a leftover "driver" material must be repaired, not trusted
reset()
stale = bpy.data.materials.new("driver")
stale.use_nodes = True
stale_img = bpy.data.images.new("stale_skin", 4, 4)
stale_tex = stale.node_tree.nodes.new("ShaderNodeTexImage")
stale_tex.image = stale_img            # present but never linked
addon.import_driver(DEPOT, lod="a", car="2013_caterham_seven_620r")
fixed = bpy.data.materials["driver"]
fixed_tex = [n for n in fixed.node_tree.nodes if n.type == "TEX_IMAGE"]
check("a leftover driver material is repaired",
      len(fixed_tex) == 1 and fixed_tex[0].image is not None
      and any(l.to_socket.name == "Base Color"
              for l in fixed_tex[0].outputs["Color"].links),
      f"{[getattr(n.image, 'name', None) for n in fixed_tex]}")

# ------------------------------------------------------------------- the seating
print("\n=== the driver sits at the wheel ===")
for car in CARS:
    reset()
    addon.import_driver(DEPOT, lod="a", car=car)
    bpy.context.scene.frame_set(1)
    bpy.context.view_layer.update()
    helmet, foot = mesh_named("helmet"), mesh_named("leftleg_foot")
    check(f"{car}: the head is above the feet",
          helmet is not None and foot is not None and centre(helmet).z > centre(foot).z,
          f"head z {centre(helmet).z:.3f} vs foot z {centre(foot).z:.3f}"
          if helmet and foot else "missing part")

    bpy.ops.import_scene.rr3_vehicle(filepath=os.path.join(DEPOT, "vehicles", car, f"{car}_a.m3g"),
                                     lod="A", materials="simple")
    bpy.context.view_layer.update()
    wheel = mesh_named("STEERING_WHEEL")
    if wheel is None:
        continue
    wc = centre(wheel)
    rim = max((wheel.matrix_world @ v.co - wc).length for v in wheel.data.vertices)
    anchor = bpy.data.objects.get("ANCHOR_POINT_DRIVER")
    if anchor is None:
        continue
    hands = [centre(mesh_named("lefthand")) + anchor.location,
             centre(mesh_named("righthand")) + anchor.location]
    gaps = [(h - wc).length for h in hands]
    check(f"{car}: both hands reach the rim",
          all(g < rim * 1.30 for g in gaps),
          f"rim {rim:.3f} m, hands {gaps[0]:.3f} / {gaps[1]:.3f} m")

    chest = centre(mesh_named("01_body")) + anchor.location
    # The car's forward direction is +Y, so the wheel sits ahead of the chest.
    check(f"{car}: the chest sits behind the wheel", chest.y < wc.y,
          f"chest y {chest.y:.3f} vs wheel y {wc.y:.3f}")

# ------------------------------------------------------------------ the low LODs
print("\n=== the low LODs ===")
reset()
res = addon.import_driver(DEPOT, lod="c", car="2016_mclaren_mp4x")
meshes = [o for o in bpy.data.objects if o.type == "MESH"]
check("LOD C is a single seated mesh", len(meshes) == 1, f"{len(meshes)} mesh(es)")
check("a single mesh is not posed", res["posed"] == 0, f"{res['posed']} part(s)")
check("LOD C uses the car's own model",
      os.path.basename(res["model"]) == "driver_lod_c_mclaren_mp4x.m3g",
      f"{os.path.basename(res['model'])}")

reset()
res = addon.import_driver(DEPOT, lod="a", car="2014_mclaren_p1", with_root=False)
check("the root empty can be left out", res["root"] is None, "no root")

reset()
res = addon.import_driver(DEPOT, lod="a", car="2014_mclaren_p1", skin="driver_raikkonen")
img = bpy.data.images.get("driver_raikkonen.png") or bpy.data.images.get("driver_raikkonen.dxt.dds")
check("another skin can be picked",
      img is not None and bool(img.packed_file) and tuple(img.size) == (512, 512),
      f"{img.name if img else None} {tuple(img.size) if img else ''}")

# ------------------------------------------------------------------ picking one
print("\n=== picking the animation ===")
reset()
picked = os.path.join(drvlib.driver_dir(DEPOT), "driver_countach.banim")
res = addon.import_driver(DEPOT, lod="a", car="2013_caterham_seven_620r",
                          banim_file=picked)
check("a hand-picked .banim wins over the car's own",
      os.path.basename(res["banim"]) == "driver_countach.banim",
      f"{os.path.basename(res['banim'])}")

reset()
record = drvlib.car_record(DEPOT, "2014_toyota_ts040")
res = addon.import_driver(DEPOT, lod="a", car="", car_record=record)
check("a car record alone picks the animation",
      os.path.basename(res["banim"]) == "driver_919_lmp1.banim",
      f"{os.path.basename(res['banim'])} ({res['banim_matched']})")

# --------------------------------------------------------- exporting the pose
print("\n=== exporting the pose back out ===")
reset()
res = addon.import_driver(DEPOT, lod="a", car="2013_caterham_seven_620r", textures=False)
check("the import keyed the file's own key rate",
      res["frames"] > 150, f"{res['frames']} frame(s)")
out_banim = os.path.join(ROOT, "work", "_smoke_driver_out.banim")
exported = bpy.ops.export_scene.rr3_banim(filepath=out_banim, tracks_from="PARTS")
check("the pose exports as a banim", "FINISHED" in exported, f"{exported}")
if os.path.isfile(out_banim):
    from rr3lib import banim as banimlib
    back = banimlib.load(out_banim)
    check("every part became a track", back.num_tracks == 15, f"{back.num_tracks} track(s)")
    check("the keys were written back", len(back.keys) > 15000, f"{len(back.keys)} key(s)")
    check("the duration survived",
          abs(back.duration_ms - 1980.0) < 30.0, f"{back.duration_ms:.0f} ms")
    os.remove(out_banim)

print(f"\nDRIVER SMOKE: {'PASS' if not fail else 'FAIL'}  ({ok} ok, {fail} failed)")
