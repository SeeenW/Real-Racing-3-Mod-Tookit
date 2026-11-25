"""Headless smoke test for the RR3 Blender addon (run inside Blender)."""
import os
import sys
import traceback

ADDON = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "rr3_blender_addon")
sys.path.insert(0, os.path.dirname(ADDON))

import bpy

fails = []


def step(name, fn):
    try:
        out = fn()
        print(f"OK   {name}" + (f"  -> {out}" if out is not None else ""))
    except Exception as exc:
        fails.append(name)
        print(f"FAIL {name}: {exc}")
        traceback.print_exc()


import rr3_blender_addon as addon


def _register():
    addon.register()
    return f"{len(addon.classes)} classes"


step("register", _register)


def _ops():
    import bpy
    names = [c.bl_idname for c in addon.classes if hasattr(c, "bl_idname")]
    missing = [n for n in names if not hasattr(bpy.types, n.replace(".", "_").upper())
               and n not in dir(bpy.ops)]
    return f"{len(names)} operators/panels"


step("operators", _ops)


def _catalog():
    from rr3_blender_addon.rr3lib import catalog as c
    mats = c.materials()
    parts = c.parts()
    assert len(mats) == 297, len(mats)
    assert len(parts) == 1869, len(parts)
    assert c.part_slot("LOD_A_WING_REAR_mm_ext") == 745
    assert c.part_slot("LOD_A_BODY_mm_ext") == 30
    return f"{len(mats)} materials, {len(parts)} parts, {len(c.paint_materials())} paints"


step("catalog", _catalog)


def _catalog_op():
    bpy.ops.rr3.catalog(which="all")
    t = bpy.data.texts["rr3_catalog"]
    return f"{len(t.as_string())} chars"


step("catalog operator", _catalog_op)


def _make_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.mesh.primitive_cube_add()
    body = bpy.context.object
    body.name = "LOD_A_BODY_mm_ext"
    me = body.data
    uv = me.uv_layers.new(name="UVMap")
    for i, loop in enumerate(me.loops):
        uv.data[i].uv = ((loop.vertex_index % 2) * 0.25, (loop.vertex_index // 2) * 0.25)
    m = bpy.data.materials.new("LOD_A_BODY_mm_ext")
    me.materials.append(m)

    # an aero pivot with two keys
    bpy.ops.object.empty_add(type="PLAIN_AXES", location=(0, 0, 0))
    aero = bpy.context.object
    aero.name = "AERO_0_WING_REAR"
    aero["rr3_track"] = 0
    aero.rotation_mode = "XYZ"
    for fr, z, ang in ((1, 0.0, 0.0), (31, 0.28, 45.0)):
        bpy.context.scene.frame_set(fr)
        aero.location = (0.0, 0.0, z)
        aero.rotation_euler = (ang * 3.14159265 / 180.0, 0.0, 0.0)
        aero.keyframe_insert("location", frame=fr)
        aero.keyframe_insert("rotation_euler", frame=fr)
    bpy.context.scene.frame_set(1)

    # anchors
    for name, loc in (("POINT_HEADLIGHT_LEFT", (-0.7, 1.9, 0.6)),
                      ("HINGE_DOOR_LEFT", (0.9, 0.4, 0.8))):
        bpy.ops.object.empty_add(type="PLAIN_AXES", location=loc)
        ob = bpy.context.object
        ob.name = name
        ob["rr3_point_type"] = 0 if name.startswith("POINT") else 2
        ob["rr3_point_type_name"] = "point" if name.startswith("POINT") else "hinge"
    return "cube + aero + 2 anchors"


step("build scene", _make_scene)

TMP = os.path.join(os.environ.get("TEMP", "."), "rr3_smoke")
os.makedirs(TMP, exist_ok=True)


def _export_points():
    path = os.path.join(TMP, "test.points")
    n, warn = addon.explib.export_points(path)
    from rr3_blender_addon.rr3lib import points as pl
    pf = pl.load(path)
    names = [r.name for r in pf.records]
    assert "POINT_HEADLIGHT_LEFT" in names, names
    assert "HINGE_DOOR_LEFT" in names, names
    return f"{n} anchors, {os.path.getsize(path)} bytes, warn={warn}"


step("export .points", _export_points)


def _points_roundtrip():
    """Importing what we exported must put the anchors back where they were."""
    path = os.path.join(TMP, "test.points")
    before = {}
    for ob in bpy.context.scene.objects:
        if ob.name.startswith(("POINT_", "HINGE_")):
            before[ob.name] = tuple(ob.location)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    addon._import_points(path, 1.0, True, bpy.context.scene.collection)
    worst = 0.0
    for ob in bpy.context.scene.objects:
        if ob.name in before:
            for a, b in zip(tuple(ob.location), before[ob.name]):
                worst = max(worst, abs(a - b))
    return f"max position error {worst * 1000:.4f} mm"


step("points round trip", _points_roundtrip)


def _rebuild_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.object.empty_add(type="PLAIN_AXES", location=(0, 0, 0))
    aero = bpy.context.object
    aero.name = "AERO_0_WING_REAR"
    aero["rr3_track"] = 0
    aero.rotation_mode = "XYZ"
    for fr, z, ang in ((1, 0.0, 0.0), (31, 0.28, 45.0)):
        bpy.context.scene.frame_set(fr)
        aero.location = (0.0, 0.0, z)
        aero.rotation_euler = (ang * 3.14159265 / 180.0, 0.0, 0.0)
        aero.keyframe_insert("location", frame=fr)
        aero.keyframe_insert("rotation_euler", frame=fr)
    bpy.context.scene.frame_set(1)
    bpy.context.scene.render.fps = 30
    return "aero empty"


step("rebuild aero scene", _rebuild_scene)


def _export_banim():
    path = os.path.join(TMP, "test_wing.banim")
    n, keys, dur = addon.explib.export_banim(path)
    from rr3_blender_addon.rr3lib import banim as bl
    b = bl.load(path)
    assert n == 1, n
    # frame 31 at 30 fps -> (31-1)/30*1000 = 1000 ms; the scene's own end (250)
    # must not be used or the clip would run seven seconds longer than drawn.
    assert abs(b.duration_ms - 1000.0) < 1.0, b.duration_ms
    tr = b.tracks[0]
    # every channel is written twice: slot 0 holds the nodes (one per frame),
    # slot 1 the Bezier control points.  Writing samples into slot 1 makes the
    # engine read them as controls and the part hitches.
    curves = {c.index: c for c in tr.curves if c.num_keys}
    assert set(curves) == set(range(12)), sorted(curves)
    for ch in range(6):
        n0, n1 = curves[2 * ch].num_keys, curves[2 * ch + 1].num_keys
        assert n1 == 2 * (n0 - 1), (ch, n0, n1)
    last_z = b.keys[curves[4].start_key + curves[4].num_keys - 1][1]
    assert abs(last_z - 0.28 * 65536) < 1.0, last_z
    last_rx = b.keys[curves[6].start_key + curves[6].num_keys - 1][1]
    assert abs(last_rx - 45.0 * 32768 / 180.0) < 2.0, last_rx
    # untouched channels stay at zero
    last_x = b.keys[curves[0].start_key + curves[0].num_keys - 1][1]
    assert abs(last_x) < 1e-3, last_x
    return f"{n} track, {keys} keys, {dur:.0f} ms, z={last_z:.0f}, rotx={last_rx:.0f}"


step("export .banim", _export_banim)


def _banim_container():
    """A file built without a donor still writes the shipped magic and trailer.

    A wing file that stops after the key data is silently ignored by the engine:
    the clip loads, nothing moves, and the part stays at its modelled origin - on
    a car whose wing was cut out of the body that looks exactly as if the wing
    had been deleted.  So the trailer is not optional, and it is one word per
    track, taken from the part name.
    """
    from rr3_blender_addon.rr3lib import banim as bl
    path = os.path.join(TMP, "test_wing.banim")
    b = bl.load(path)
    assert b.magic == 0x7F7F7F00, hex(b.magic)
    assert b.variant == 0, b.variant
    assert len(b.trailer_words) == b.num_tracks, (b.trailer_words, b.num_tracks)
    # The empty here is called AERO_0_WING_REAR, so the word is WING_REAR's.
    assert b.trailer_words[0] == 0xAD45C13F, hex(b.trailer_words[0])
    return f"magic {hex(b.magic)}, trailer {[hex(w) for w in b.trailer_words]}"


step("banim magic and trailer without a donor", _banim_container)


def _banim_trailer_table():
    """Every wing part in the table maps to its shipped word, AERO_ included."""
    ex = addon.explib
    assert ex.TRAILER_WORDS["WING_REAR"] == 0xAD45C13F
    assert ex.TRAILER_WORDS["WING_STRUT"] == 0x89CEF5E4
    assert ex.TRAILER_WORDS["WING_STRUT_REAR"] == 0x57529DC8
    assert ex.TRAILER_WORDS["WING_REAR_LEFT"] == 0x4202CB14
    assert ex.TRAILER_WORDS["WING_REAR_RIGHT"] == 0x344991DE
    assert ex.TRAILER_WORDS["WING"] == 0x6C8C2CFD
    got = ex.trailer_words_for(["WING_REAR", "WING_STRUT", "WING_STRUT_REAR"])
    assert got == [0xAD45C13F, 0x89CEF5E4, 0x57529DC8], [hex(w) for w in got]
    # the importer's pivots carry the part name behind an AERO_<n>_ prefix
    assert ex.trailer_words_for(["AERO_0_WING_REAR"]) == [0xAD45C13F]
    assert ex.trailer_words_for(["AERO_12_WING_REAR_LEFT"]) == [0x4202CB14]
    # an unknown part still gets a word rather than nothing
    assert ex.trailer_words_for(["WING_MADE_UP"]) == [ex.TRAILER_DEFAULT]
    return "6 parts, AERO_ prefix stripped, unknown parts defaulted"


step("trailer word table", _banim_trailer_table)


def _banim_roundtrip():
    """Re-load and re-save the exported banim: must be byte identical."""
    from rr3_blender_addon.rr3lib import banim_write as bw
    path = os.path.join(TMP, "test_wing.banim")
    raw = open(path, "rb").read()
    doc = bw.load(path)
    again = bw.build(doc)
    assert again == raw, f"{len(again)} vs {len(raw)}"
    return f"{len(raw)} bytes, exact"


step("banim round trip", _banim_roundtrip)


def _export_xml():
    path = os.path.join(TMP, "test_animations.xml")
    clips = addon.explib.wing_clips(0, 30)
    problems = addon.explib.export_animxml(path, clips)
    txt = open(path, "r", encoding="utf-8").read()
    assert "wing_up" in txt and "wing_initial" in txt, txt
    return f"{len(clips)} clips, problems={problems}"


step("export _animations.xml", _export_xml)


def _m3g():
    from rr3_blender_addon import m3gexport
    parts = m3gexport.collect_parts([o for o in bpy.context.scene.objects
                                     if o.type == "MESH"] or [])
    return "no meshes to test (ok)" if not parts else f"{len(parts)} parts"


step("m3g collect", _m3g)


def _m3g_export():
    """Build a cube and write a real m3g, then read it back."""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.mesh.primitive_cube_add()
    ob = bpy.context.object
    ob.name = "LOD_A_BODY_mm_ext"
    me = ob.data
    uv = me.uv_layers.new(name="UVMap")
    for i, loop in enumerate(me.loops):
        uv.data[i].uv = ((loop.vertex_index % 2) * 0.25, (loop.vertex_index // 2) * 0.25)
    me.materials.append(bpy.data.materials.new("LOD_A_BODY_mm_ext"))
    path = os.path.join(TMP, "test.m3g")
    from rr3_blender_addon import m3gexport
    blob, n, scale = m3gexport.build_from_objects([ob])
    open(path, "wb").write(blob)
    from rr3_blender_addon.rr3lib import m3g as ml
    m = ml.M3G(path)
    meshes = m.of_type(ml.T_MESH)
    assert len(meshes) == 1, len(meshes)
    return f"{n} part, {len(blob)} bytes, scale {scale:.10f}, {len(meshes)} mesh"


step("m3g export + read back", _m3g_export)


def _lod_names():
    """The export names a file after the LOD collection the meshes are in."""
    import rr3_blender_addon as addon

    class _Coll:
        def __init__(self, name):
            self.name = name

    class _Ob:
        def __init__(self, *colls):
            self.users_collection = [_Coll(c) for c in colls]

    got = {
        "A": addon._lod_of(_Ob("2012_lexus_lfa_LODA")),
        "damaged": addon._lod_of(_Ob("2012_lexus_lfa_LODA_damaged")),
        "shared": addon._lod_of(_Ob("2012_lexus_lfa_shared")),
        "int_a": addon._lod_of(_Ob("2012_lexus_lfa_int_a")),
        "untagged": addon._lod_of(_Ob("Collection")),
    }
    assert got == {"A": "A", "damaged": "A", "shared": "shared",
                   "int_a": "int_a", "untagged": ""}, got
    name = addon._lod_filename([_Ob("x_LODB")])
    assert name == "LOD_B.m3g", name
    assert addon._lod_filename([_Ob("x_shared")]) == "SHARED.m3g"
    assert addon._lod_filename([_Ob("x_int_b")]) == "INT_B.m3g"
    # two levels in one selection is refused, not silently merged
    mixed = addon._lod_mixture([_Ob("x_LODA"), _Ob("x_LODB")])
    assert mixed == ["A", "B"], mixed
    assert addon._lod_filename([_Ob("x_LODA"), _Ob("x_LODB")]) == ""
    return "LOD naming ok"


step("LOD file names", _lod_names)


def _part_tracks():
    """A wing split into material tags becomes one track per part, in name order."""
    from rr3_blender_addon import rr3_export as ex

    assert ex.part_base("LOD_A_WING_REAR_mm_ext") == "WING_REAR"
    assert ex.part_base("LOD_A_WING_REAR_LEFT_mm_misc") == "WING_REAR_LEFT"
    assert ex.part_base("WING_REAR") == "WING_REAR"
    assert ex.part_base("LOD_A_BODY_mm_ext") == "BODY"

    class _Ob:
        def __init__(self, name, action=None, parent=None):
            self.name = name
            self.parent = parent
            self.animation_data = type("AD", (), {"action": action})()

    # two material tags on one part: one track, not two
    got = ex._groups_by_part_base([
        _Ob("LOD_A_WING_REAR_mm_ext", action="a"),
        _Ob("LOD_A_WING_REAR_mm_misc", action="a"),
        _Ob("LOD_A_WING_STRUT_mm_misc", action="a"),
        _Ob("LOD_A_WING_STRUT_REAR_mm_misc", action="a"),
        _Ob("LOD_A_BODY_mm_ext", action="a"),
        _Ob("LOD_A_WING_REAR_BRAKES_mm_misc", action="a"),
    ], "WING")
    bases = [base for base, _carrier in got]
    assert bases == ["WING_REAR", "WING_STRUT", "WING_STRUT_REAR"], bases

    # the importer's AERO empties carry the motion; they are not parts
    pivot = _Ob("AERO_0_WING_REAR", action="a")
    rigged = ex._groups_by_part_base([_Ob("LOD_A_WING_REAR_mm_ext", parent=pivot)], "WING")
    assert [b for b, _c in rigged] == ["WING_REAR"], rigged
    assert rigged[0][1] is pivot, rigged[0][1].name
    return "part tracks ok"


step("part tracks", _part_tracks)


def _animated_is_local():
    """An animated part exports its vertices around its own origin."""
    import rr3_blender_addon as addon
    from rr3_blender_addon import m3gexport as mx

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.mesh.primitive_cube_add(size=0.4, location=(0.0, -1.8, 0.9))
    ob = bpy.context.object
    ob.name = "LOD_A_WING_REAR_mm_ext"
    assert not mx._is_animated(ob)
    ob.keyframe_insert("location", frame=1)
    assert mx._is_animated(ob), "a keyed mesh counts as animated"

    blob, _n, _s = mx.build_from_objects([ob], use_world=True)
    path = os.path.join(TMP, "anim_space.m3g")
    with open(path, "wb") as fh:
        fh.write(blob)
    from rr3_blender_addon.rr3lib import geometry, m3g as m3glib
    m = m3glib.M3G(path)
    md = None
    for o in m.of_type(14):
        if o.data.get("name") == "LOD_A_WING_REAR_mm_ext":
            md = geometry.extract_mesh(m, o)
    assert md is not None, "the part did not come back"
    span = max(abs(p[1]) for p in md.positions)
    assert span < 0.5, f"vertices were baked to the world position ({span:.3f} m)"
    return f"animated part stays local ({span:.3f} m)"


step("animated parts stay local", _animated_is_local)


def _panel():
    from rr3_blender_addon import RR3_PT_panel
    assert RR3_PT_panel.bl_category == "RR3"
    return "panel ok"


step("panel", _panel)


def _anchors_from_a_real_car():
    """A shipped car's own anchors must survive import -> export unchanged.

    This is the regression the ``POINTS_E2B`` rotation caused: the exporter used
    to turn every anchor 180 deg about Z, so re-exporting a car that had just
    been imported moved ``POINT_WHEEL_FL`` to the back-right corner.  Nothing
    caught it because the standalone points importer and the exporter shared the
    same (wrong) frame, and they agreed with each other while disagreeing with
    the vehicle importer - which is the one that places the wheels.
    """
    from rr3_blender_addon.rr3lib import points as pl

    depot = os.environ.get(
        "RR3_DEPOT",
        r"E:\DXT_480x320+960x640+2048x1536数据包-Build260716\files\.depot")
    car = "2018_bugatti_chiron_sport"
    src = os.path.join(depot, "vehicles", car, f"{car}_a.m3g")
    pts = os.path.join(depot, "vehicles", car, f"{car}.points")
    if not (os.path.isfile(src) and os.path.isfile(pts)):
        return "skipped (no depot)"

    before = {r.name: r.position for r in pl.load(pts).records}
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.rr3_vehicle(filepath=src, lod="A", textures=False,
                                     animate=False, import_anchors=True)
    out = os.path.join(TMP, "anchors_rt.points")
    addon.explib.export_points(out)
    after = {r.name: r.position for r in pl.load(out).records}
    assert set(before) == set(after), "anchor names changed"
    worst = 0.0
    worst_name = ""
    for name, pos in before.items():
        d = max(abs(a - b) for a, b in zip(pos, after[name]))
        if d > worst:
            worst, worst_name = d, name
    assert worst < 0.01, f"{worst_name} moved {worst:.2f} file units"
    return f"{len(before)} anchors, worst drift {worst:.4f}"


step("anchors survive a vehicle import", _anchors_from_a_real_car)


def _blur_wheels():
    """Each wheel's motion-blur stand-in lands in ``<car>_LOD<X>_blur``, hidden.

    Two meshes per wheel, not one: the silhouette (``..._BLUR_mm_wheel``) and a
    flatter sheet over it (``..._BLUR_mm_wheel_blur``).  Both are modelled in
    the rim's frame, so both hang off the ``WHEEL_<corner>`` pivot; the folder
    starts hidden in the viewport and in the render, because left visible they
    only double the wheel.
    """
    depot = os.environ.get(
        "RR3_DEPOT",
        r"E:\DXT_480x320+960x640+2048x1536数据包-Build260716\files\.depot")
    car = "2018_bugatti_chiron_sport"
    src = os.path.join(depot, "vehicles", car, f"{car}_a.m3g")
    if not os.path.isfile(src):
        return "skipped (no depot)"
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.rr3_vehicle(filepath=src, lod="A", textures=False,
                                     animate=False, import_anchors=False)
    coll = bpy.data.collections.get(f"{car}_LODA_blur")
    assert coll is not None, "no <car>_LODA_blur collection"
    assert coll.hide_viewport, "the blur folder is visible in the viewport"
    assert coll.hide_render, "the blur folder still renders"
    objs = list(coll.objects)
    assert len(objs) == 8, f"{len(objs)} blur meshes, expected 4 corners x 2"
    kinds = {o["rr3_wheel"] for o in objs}
    assert any(k.endswith("_BLUR_mm_wheel") for k in kinds), sorted(kinds)
    assert any(k.endswith("_BLUR_mm_wheel_blur") for k in kinds), sorted(kinds)
    for ob in objs:
        assert ob.parent is not None and ob.parent.name.startswith("WHEEL_"), \
            f"{ob.name} is not on a WHEEL_ pivot"
        assert ob["rr3_wheel_blur"] is True
    assert coll.name in [c.name for c in bpy.data.collections[f"{car}_LODA"].children]
    return f"{len(objs)} meshes, hidden, hanging off the WHEEL_ pivots"


step("the blur stand-in of each wheel lands in a hidden folder", _blur_wheels)


def _normals_are_editable():
    """No custom normals by default, and the opt-in still bakes them.

    Custom normals are frozen data: after a deform they no longer agree with the
    surface, and the shading breaks into sharp triangles along a handful of
    edges while the rest looks fine.  Measured on the Chiron's body shell, one
    0.25 m stroke leaves 4 edges with a 58.9 deg normal discontinuity when they
    are baked, and 0 with none (worst 0.04 deg).
    """
    depot = os.environ.get(
        "RR3_DEPOT",
        r"E:\DXT_480x320+960x640+2048x1536数据包-Build260716\files\.depot")
    car = "2018_bugatti_chiron_sport"
    src = os.path.join(depot, "vehicles", car, f"{car}_a.m3g")
    if not os.path.isfile(src):
        return "skipped (no depot)"

    def imported(**kw):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.ops.import_scene.rr3_vehicle(filepath=src, lod="A", textures=False,
                                         animate=False, import_anchors=False,
                                         blur_wheels=False, **kw)
        return [o for o in bpy.data.objects if o.type == "MESH"]

    meshes = imported()
    baked = [o.name for o in meshes if o.data.has_custom_normals]
    assert not baked, f"{len(baked)} mesh(es) came in with baked normals"
    flat = [o.name for o in meshes
            if o.data.polygons and not all(p.use_smooth for p in o.data.polygons)]
    assert not flat, f"{len(flat)} mesh(es) came in flat shaded"

    meshes = imported(file_normals=True)
    unbaked = [o.name for o in meshes if not o.data.has_custom_normals]
    assert not unbaked, f"{len(unbaked)} mesh(es) ignored 'Normals from the file'"

    # and the repair operator takes them off again
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.rr3.clear_custom_normals(selected_only=True)
    left = [o.name for o in bpy.data.objects
            if o.type == "MESH" and o.data.has_custom_normals]
    assert not left, f"{len(left)} mesh(es) kept their custom normals"
    return f"{len(meshes)} meshes, both ways, and the repair operator"


step("normals are editable by default, and can still be baked", _normals_are_editable)


print()
if fails:
    print(f"SMOKE TEST: {len(fails)} FAILURE(S): {fails}")
    sys.exit(1)
print("SMOKE TEST: PASS")
