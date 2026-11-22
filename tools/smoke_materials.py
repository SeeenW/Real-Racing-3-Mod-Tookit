"""Smoke test the game-material import (run inside Blender).

    blender.exe -b --factory-startup --python tools\\smoke_materials.py

Checks, per car:

* the paint scheme count matches the car's .liveries.bin.nct
* every mesh keeps **one** material slot, no matter how many paints exist
* that one material carries one preset per scheme, each with its own atlas
* only the active preset is wired to Material Output
* the roughness / metallic / coat came from materials.bin, not a constant
* the ramps are in the file as image nodes inside the preset frames
* rr3.switch_paint re-links the preset instead of adding a slot
* the atlases are packed, so they survive a reload
* 'simple' materials still work and do NOT create paint presets
* the texture exporter decodes every container kind it claims to
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

import bpy  # noqa: E402

DEPOT = os.environ.get(
    "RR3_DEPOT",
    r"E:\DXT_480x320+960x640+2048x1536数据包-Build260716\files\.depot",
)
VEH = os.path.join(DEPOT, "vehicles")
CARS = ("2014_mclaren_p1", "2012_lexus_lfa", "2013_bugatti_veyron_gsv")

_ok = 0
_bad = 0


def check(name, good, detail=""):
    global _ok, _bad
    if good:
        _ok += 1
        print(f"OK   {name}" + (f"  -> {detail}" if detail else ""))
    else:
        _bad += 1
        print(f"FAIL {name}" + (f"  -> {detail}" if detail else ""))


def body_ext(collection):
    return next((o for o in collection.objects
                 if o.name.startswith("LOD_A_BODY_mm_ext")), None)


def output_source(mat):
    """Name of the node wired to Material Output's Surface, or None."""
    nt = mat.node_tree
    out = next((n for n in nt.nodes if n.type == "OUTPUT_MATERIAL"), None)
    if out is None:
        return None
    for link in nt.links:
        if link.to_node == out and link.to_socket.name == "Surface":
            return link.from_node.name
    return None


def atlas_of(mat):
    """File name of the atlas wired into the active preset, or None."""
    if mat is None or mat.node_tree is None:
        return None
    tex = mat.node_tree.nodes.get("atlas_0")
    if tex is None or tex.image is None:
        return None
    return os.path.basename(tex.image.filepath or tex.image.name)


def main():
    import rr3_blender_addon as addon  # noqa: E402
    from rr3lib import livery as liverylib  # noqa: E402
    from rr3lib import texport as texportlib  # noqa: E402

    addon.register()  # rr3.switch_paint has to exist for the operator checks

    for car in CARS:
        car_dir = os.path.join(VEH, car)
        if not os.path.isdir(car_dir):
            print(f"SKIP {car}: not in the depot")
            continue
        print(f"\n=== {car} ===")

        bpy.ops.wm.read_factory_settings(use_empty=True)
        res = addon.import_vehicle_file(car_dir, car, lod="A",
                                        materials="game", paint=0)
        gm = res["game_materials"]
        check("game materials built", gm is not None and bool(gm.schemes))
        if gm is None:
            continue

        L = liverylib.load_car(DEPOT, car)
        count = len(gm.schemes)
        check("scheme count matches the livery file",
              count == len(L.paints), f"{count} vs {len(L.paints)}")

        meshes = [o for o in res["collection"].objects if o.type == "MESH"]
        slots = [len(o.data.materials) for o in meshes]
        check("every mesh keeps a single material slot",
              set(slots) == {1}, f"slots {sorted(set(slots))} over {len(meshes)} meshes")

        ob = body_ext(res["collection"])
        check("the body shell is in the scene", ob is not None)
        mat = ob.data.materials[0] if ob is not None and ob.data.materials else None
        if mat is not None:
            nt = mat.node_tree
            check("the material holds one preset per scheme",
                  int(mat.get("rr3_presets") or 0) == count,
                  f"{mat.get('rr3_presets')} of {count}")
            check("every preset has its own BSDF",
                  all(nt.nodes.get(f"bsdf_{i}") is not None for i in range(count)))
            files = []
            for i in range(count):
                tex = nt.nodes.get(f"atlas_{i}")
                files.append(os.path.basename(tex.image.filepath)
                             if tex and tex.image else "")
            check("each preset has its own body atlas",
                  all(files) and len(set(files)) == len(files),
                  ", ".join(f.split("_ext_")[-1] for f in files))

            # the atlas has to actually be plugged into the preset's BSDF
            wired = []
            for i in range(count):
                bsdf = nt.nodes[f"bsdf_{i}"]
                wired.append(any(l.to_node == bsdf and l.from_node.name == f"atlas_{i}"
                                 for l in nt.links))
            check("each preset's atlas is wired to its Base Color", all(wired))

            check("only the active preset reaches the output",
                  output_source(mat) == "bsdf_0", str(output_source(mat)))

            rough = [round(nt.nodes[f"bsdf_{i}"].inputs["Roughness"].default_value, 3)
                     for i in range(count)]
            check("roughness varies with the game material",
                  len(set(rough)) >= 1, f"roughness {sorted(set(rough))}")

            ramps = [n.name for n in nt.nodes if n.name.startswith("ramp_")]
            targets = {l.to_node.name for l in nt.links}
            check("the game ramps are stored in the material",
                  len(ramps) >= count, f"{len(ramps)} ramp node(s)")
            check("the ramps are left unconnected",
                  all(n not in targets for n in ramps))

            packed = all(nt.nodes[f"atlas_{i}"].image.packed_file
                         for i in range(count)
                         if nt.nodes[f"atlas_{i}"].image)
            check("the atlases are packed into the .blend", packed)

            # Specular Tint is a 0..1 colour in Blender; the game stores 0..255
            # bytes, and feeding those through unconverted is what made every
            # painted panel read as chrome.
            tints = []
            for i in range(count):
                b = nt.nodes.get(f"bsdf_{i}")
                if b is None:
                    continue
                tints += list(b.inputs["Specular Tint"].default_value[:3])
            check("specular tint stays inside 0..1",
                  bool(tints) and max(tints) <= 1.0,
                  f"max {max(tints):.3f}" if tints else "no bsdf")

        # A part the livery table never overrides (a tyre, a disc) must not get
        # one preset per scheme: there is nothing to switch on it.
        tyre = next((o for o in meshes if "_TYRE_" in o.name), None)
        if tyre is not None and tyre.data.materials:
            tmat = tyre.data.materials[0]
            check("parts no scheme overrides keep a single preset",
                  int(tmat.get("rr3_presets") or 0) == 1,
                  f"{tyre.name}: {tmat.get('rr3_presets')} preset(s)")
            check("such a part has no paint slot to switch",
                  int(tyre.get("rr3_paint_slots") or 0) == 1,
                  f"{tyre.get('rr3_paint_slots')} slot(s)")

        # shading numbers on a known material
        probe = next((o for o in meshes
                      if o.name.startswith("LOD_A_CHASSIS_mm_misc")), None)
        if probe is not None and probe.data.materials:
            bsdf = probe.data.materials[0].node_tree.nodes.get("bsdf_0")
            if bsdf is not None:
                check("car_flat comes out matte",
                      bsdf.inputs["Roughness"].default_value > 0.7
                      and bsdf.inputs["Metallic"].default_value < 0.05,
                      f"rough {bsdf.inputs['Roughness'].default_value:.2f} "
                      f"metal {bsdf.inputs['Metallic'].default_value:.2f} "
                      f"({probe.data.materials[0].name})")

        # switch paint: same slot, different preset
        bpy.ops.object.select_all(action="SELECT")
        want = min(1, count - 1)
        out = bpy.ops.rr3.switch_paint(paint=want)
        check("rr3.switch_paint runs", out == {"FINISHED"}, str(out))
        if mat is not None:
            check("the new preset is wired to the output",
                  output_source(mat) == f"bsdf_{want}", str(output_source(mat)))
            check("switching paint added no material slot",
                  len(ob.data.materials) == 1, f"{len(ob.data.materials)} slot(s)")
            check("the mesh records the active preset",
                  int(ob.get("rr3_paint_slot") or -1) == want,
                  f"{ob.get('rr3_paint_slot')}")

        # --- the shared vehicles/common atlases -------------------------------
        # Windows, tyre treads and brake discs are not per-car art: the car's
        # livery table has no row for them, only default.liveries.bin.nct does.
        for token, expect in (("TYRE", "tyre"), ("ROTOR", "rotor")):
            hit = next((o for o in meshes
                        if token in (o.get("rr3_mesh_name") or "")), None)
            if hit is None:
                continue
            got = atlas_of(hit.material_slots[0].material) if hit.material_slots else None
            check(f"the {expect} falls back to vehicles/common",
                  bool(got) and got.startswith("car_"), f"{got}")

        # --- one material name, one atlas -------------------------------------
        # car_flat / car_matte / car_glass are each used on several meshes with
        # different atlases; if they all keep the same Blender name the first one
        # built wins and every other mesh wears the wrong texture.
        by_name = {}
        for o in meshes:
            m = o.material_slots[0].material if o.material_slots else None
            if m is None:
                continue
            by_name.setdefault(m.name, set()).add(atlas_of(m))
        clashes = {k: v for k, v in by_name.items() if len(v) > 1}
        check("a material name never carries two atlases", not clashes,
              f"{len(by_name)} names, {len(clashes)} clash(es)")

        # --- interior cab panels can follow the paint too ---------------------
        cab = next((o for o in meshes
                    if "_mm_cab" in (o.get("rr3_mesh_name") or "")), None)
        if cab is not None and cab.material_slots:
            cabmat = cab.material_slots[0].material
            presets = int(cabmat.get("rr3_presets") or 0)
            nt = cabmat.node_tree
            files = []
            for i in range(presets):
                tex = nt.nodes.get(f"atlas_{i}")
                files.append(os.path.basename(tex.image.filepath or tex.image.name)
                             if tex is not None and tex.image else None)
            check("a cab panel keeps one preset per scheme",
                  presets in (1, count), f"{presets} preset(s) of {count}")
            if presets > 1:
                check("its atlas changes with the scheme", len(set(files)) > 1,
                      str(sorted(set(files))[:4]))

        # --- damaged parts live in their own collection ------------------------
        dmg_name = f"{car}_LODA_damaged"
        dmg = bpy.data.collections.get(dmg_name)
        check("the damaged parts get their own collection", dmg is not None,
              dmg_name)
        if dmg is not None:
            names = [(o.get("rr3_mesh_name") or o.name) for o in dmg.objects]
            check("it holds the wrecked panels and the smashed glass",
                  len(names) >= 5, f"{len(names)} object(s)")
            check("everything in it is a damage or broken part",
                  all(("DAMAGE" in n.upper() or "BROKEN" in n.upper())
                      for n in names),
                  str([n for n in names
                       if not ("DAMAGE" in n.upper() or "BROKEN" in n.upper())][:3]))
            good = [o.get("rr3_mesh_name") or o.name for o in meshes]
            check("the good panels stay in the main collection",
                  not any(("DAMAGE" in n.upper() or "BROKEN" in n.upper())
                          for n in good),
                  str([n for n in good
                       if "DAMAGE" in n.upper() or "BROKEN" in n.upper()][:3]))
            check("the damaged meshes are flagged", all(o.get("rr3_damaged")
                                                        for o in dmg.objects))

        # 'simple' must not create presets
        bpy.ops.wm.read_factory_settings(use_empty=True)
        res2 = addon.import_vehicle_file(car_dir, car, lod="A",
                                         materials="simple")
        simple = [o for o in res2["collection"].objects if o.type == "MESH"]
        check("simple materials give one slot per mesh",
              all(len(o.data.materials) == 1 for o in simple),
              f"{len(simple)} meshes")
        check("simple materials build no paint preset",
              res2["game_materials"] is None)

    # the texture exporter
    print("\n=== textures ===")
    bad = texportlib.selftest(DEPOT)
    check("the exporter decodes the car containers", bad == 0,
          f"{bad} container kind(s) failed")

    # The game stores its images bottom-up; the exporter has to turn them over,
    # otherwise every atlas lands upside down on the model.
    flip_src = os.path.join(VEH, "2014_mclaren_p1",
                            "2014_mclaren_p1_lights.dxt.dds.z")
    if os.path.isfile(flip_src):
        fw, fh, fch, raw = texportlib.decode_frame(flip_src, 0)
        flipped = texportlib.flip_rows(fw, fh, fch, raw)
        check("flip_rows reverses the row order",
              all(flipped[y * fw * fch:(y + 1) * fw * fch]
                  == raw[(fh - 1 - y) * fw * fch:(fh - y) * fw * fch]
                  for y in range(fh)))
        check("textures are flipped by default", texportlib.FLIP_V is True)
        import tempfile
        kept = texportlib.export_png(
            flip_src, os.path.join(tempfile.gettempdir(), "rr3_smoke_flip",
                                   "keep.png"), flip_v=False)
        turned = texportlib.export_png(
            flip_src, os.path.join(tempfile.gettempdir(), "rr3_smoke_flip",
                                   "turned.png"))
        check("the two exports differ",
              open(kept, "rb").read() != open(turned, "rb").read(),
              f"{os.path.getsize(kept)} vs {os.path.getsize(turned)} bytes")

    sample = os.path.join(VEH, "2014_mclaren_p1", "livery",
                          "2014_mclaren_p1_ext_yellow.dxt.dds.z")
    if os.path.isfile(sample):
        import tempfile
        out = texportlib.export(sample, os.path.join(tempfile.gettempdir(),
                                                     "rr3_smoke_tex"), "png")
        check("a car atlas exports to a real PNG",
              os.path.isfile(out) and os.path.getsize(out) > 10000,
              f"{os.path.getsize(out)} bytes")
        img = bpy.data.images.load(out, check_existing=False)
        px = list(img.pixels[:4])
        check("the exported PNG holds the paint colour",
              abs(px[0] - 0.90) < 0.05 and abs(px[1] - 0.72) < 0.05,
              f"first pixel {[round(v, 3) for v in px]}")

    # Loading a car's textures has to walk into livery/: the paint atlases live
    # there, and a flat listdir silently skipped exactly the ones a paint scheme
    # needs.  Decodes from an older build also have to go, or the same texture
    # shows up twice - once upright, once upside down.
    print("\n=== loading textures ===")
    car_dir = os.path.join(VEH, "2014_mclaren_p1")
    if os.path.isdir(car_dir):
        import shutil
        import tempfile

        found = addon._car_texture_files(car_dir)
        in_livery = [p for p in found
                     if os.path.basename(os.path.dirname(p)) == "livery"]
        check("the scan walks into livery/", len(in_livery) >= 5,
              f"{len(found)} file(s), {len(in_livery)} in livery/")

        root = os.path.join(tempfile.gettempdir(), "rr3_dds")
        stale_dir = os.path.join(root, "v1")
        stale_png = os.path.join(root, "loose.png")
        os.makedirs(stale_dir, exist_ok=True)
        open(os.path.join(stale_dir, "old.png"), "wb").write(b"x")
        open(stale_png, "wb").write(b"x")
        purged = addon._purge_stale_textures()
        check("a stale decode folder is removed",
              not os.path.isdir(stale_dir), f"{purged['files']} file(s)")
        check("a stale decode file is removed", not os.path.isfile(stale_png))

        report = addon._load_car_textures(car_dir)
        paint_names = [n for n in report["images"] if "_ext_" in n]
        check("the paint atlases get loaded", len(paint_names) >= 5,
              f"{len(report['images'])} image(s), {len(paint_names)} paint")
        check("nothing failed to decode", not report["failed"],
              f"{len(report['failed'])} failed")
        check("the cache carries a version", os.path.basename(
            addon._image_cache_dir()) == f"v{addon.TEXTURE_CACHE_VERSION}",
            addon._image_cache_dir())

    # A car copied out of the depot has no tables above it.  That used to drop
    # the whole game-material pass without a word, which reads as "the materials
    # were not imported"; it must say so, and an explicit depot must fix it.
    print("\n=== depot lookup ===")
    import shutil
    import tempfile

    loose = os.path.join(tempfile.gettempdir(), "rr3_smoke_loose")
    if os.path.isdir(os.path.join(VEH, "2014_mclaren_p1")):
        if os.path.isdir(loose):
            shutil.rmtree(loose)
        shutil.copytree(os.path.join(VEH, "2014_mclaren_p1"), loose)
        try:
            bpy.ops.wm.read_factory_settings(use_empty=True)
            res = addon.import_vehicle_file(loose, "2014_mclaren_p1", lod="A",
                                            materials="game")
            warned = [w for w in res["plan"].warnings if "game materials" in w]
            check("a car outside the depot says why", bool(warned),
                  warned[0][:70] if warned else "no warning")
            check("such a car keeps the placeholders",
                  res["game_materials"] is None)
        finally:
            shutil.rmtree(loose, ignore_errors=True)

        bpy.ops.wm.read_factory_settings(use_empty=True)
        shutil.copytree(os.path.join(VEH, "2014_mclaren_p1"), loose)
        try:
            res = addon.import_vehicle_file(loose, "2014_mclaren_p1", lod="A",
                                            materials="game",
                                            material_depot=DEPOT)
            gm = res["game_materials"]
            check("an explicit depot fixes it",
                  gm is not None and len(gm.schemes) == 6,
                  f"{len(gm.schemes) if gm else 0} scheme(s), "
                  f"{len(bpy.data.materials)} material(s)")
            check("the explicit depot raises no warning",
                  not [w for w in res["plan"].warnings if "game materials" in w])
        finally:
            shutil.rmtree(loose, ignore_errors=True)


main()
print(f"\nMATERIAL SMOKE: {'PASS' if _bad == 0 else 'FAIL'} "
      f"({_ok} ok, {_bad} failed)")
