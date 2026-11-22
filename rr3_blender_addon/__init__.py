"""Real Racing 3 asset tools for Blender: import, edit and export.

**Import** the JSR-184 ``.m3g`` meshes, the anchor points in the matching
``.points`` file, and the ``.banim`` part animations with their
``_animations.xml`` clip table.  A whole car folder can be imported in one go,
complete with wheel pivots and active-aero pivots.

**Export** the same things back: ``.m3g`` (meshes), ``.points`` (anchor empties),
``.banim`` (animated part empties) and ``_animations.xml`` (clip table).

**Build a car**: clone a shipped car into a new one - spec, the six shared
tables, the livery file and the three asset manifests - then repaint any part
with any material the game ships.

The game files are only written when you explicitly run a build/export
operator; the importers never touch them.
"""

from __future__ import annotations

import math
import os
import re
import shutil
import sys
import tempfile

import bpy
from bpy.props import (BoolProperty, BoolVectorProperty, CollectionProperty,
                       EnumProperty, FloatProperty, IntProperty, StringProperty)
from bpy.types import Operator
from bpy_extras.io_utils import ImportHelper, ExportHelper
import mathutils
from mathutils import Euler, Matrix, Vector

_ADDON_DIR = os.path.dirname(os.path.abspath(__file__))
if _ADDON_DIR not in sys.path:
    sys.path.insert(0, _ADDON_DIR)

from .rr3lib import animxml as animxmllib  # noqa: E402
from .rr3lib import banim as banimlib  # noqa: E402
from .rr3lib import banim_write as banimwlib  # noqa: E402
from .rr3lib import car as carlib  # noqa: E402
from .rr3lib import carmaterial as carmatlib  # noqa: E402
from .rr3lib import catalog as cataloglib  # noqa: E402
from .rr3lib import driver as drvlib  # noqa: E402
from .rr3lib import gamematerial as gamematlib  # noqa: E402
from .rr3lib import geometry as geometrylib  # noqa: E402
from .rr3lib import livery as liverylib  # noqa: E402
from .rr3lib import m3g as m3glib  # noqa: E402
from .rr3lib import points as pointslib  # noqa: E402
from .rr3lib import points_write as pointswlib  # noqa: E402
from .rr3lib import parts as partslib  # noqa: E402
from .rr3lib import pvr as pvrlib  # noqa: E402
from .rr3lib import rig as riglib  # noqa: E402
from .rr3lib import texport as texportlib  # noqa: E402
from .rr3lib import texture as texturelib  # noqa: E402
from .rr3lib import wheelsize as wheelsizelib  # noqa: E402
from . import rr3_export as explib  # noqa: E402

bl_info = {
    "name": "Real Racing 3 (.m3g / .points / .banim)",
    "author": "rr3 tools",
    "version": (2, 0, 0),
    "blender": (4, 2, 0),
    "location": "File > Import / Export > Real Racing 3, and the 3D View 'RR3' panel",
    "description": "Import and export Real Racing 3 models, anchors, part animations "
                   "and animation clips, and build new cars with custom paint materials",
    "category": "Import-Export",
}


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _to_blender(v, convert: bool):
    """RR3 models are Y-up; Blender is Z-up (rotate +90 deg around X)."""
    x, y, z = v
    if convert:
        return (x, -z, y)
    return (x, y, z)


def _anchor_to_blender(v, convert: bool):
    """Anchor points are already Z-up with +Y forward, so map +Y onto -Y."""
    x, y, z = v
    if convert:
        return (x, -y, z)
    return (x, y, z)


def _frame_matrix(facing: str, mirror_x: bool):
    """Rig-level basis change: swap the facing axis and/or mirror across X.

    ``+Y`` keeps the game convention (nose toward Blender +Y, which is what the
    .m3g meshes use).  ``-Y`` rotates the whole rig 180 deg about Z so it points
    the other way, matching FBX meshes authored with the nose on -Y.
    ``mirror_x`` additionally mirrors the rig across X (the engine hands us
    X-right, Blender imports often expect X-left).
    """
    m = Matrix.Identity(3)
    if facing == "-Y":
        m = Matrix.Rotation(math.pi, 3, "Z")
    if mirror_x:
        m = m @ Matrix.Scale(-1.0, 3, (1.0, 0.0, 0.0))
    return m


def _hex_color(name: str):
    h = 0
    for ch in name:
        h = (h * 131 + ord(ch)) & 0xFFFFFFFF
    r = 0.35 + 0.65 * ((h >> 16) & 0xFF) / 255.0
    g = 0.35 + 0.65 * ((h >> 8) & 0xFF) / 255.0
    b = 0.35 + 0.65 * (h & 0xFF) / 255.0
    return (r, g, b, 1.0)


def _get_material(name: str, image=None):
    mat = bpy.data.materials.get(name)
    if mat is None:
        mat = bpy.data.materials.new(name)
        mat.use_nodes = True
        rgba = _hex_color(name)
        mat.diffuse_color = rgba
        bsdf = mat.node_tree.nodes.get("Principled BSDF")
        if bsdf is not None:
            bsdf.inputs["Base Color"].default_value = rgba
            if "Roughness" in bsdf.inputs:
                bsdf.inputs["Roughness"].default_value = 0.55
            if "Metallic" in bsdf.inputs:
                bsdf.inputs["Metallic"].default_value = 0.1
    if image is not None and mat.node_tree is not None:
        bsdf = mat.node_tree.nodes.get("Principled BSDF")
        tex = next((n for n in mat.node_tree.nodes if n.type == "TEX_IMAGE"), None)
        if tex is None and bsdf is not None:
            tex = mat.node_tree.nodes.new("ShaderNodeTexImage")
            tex.extension = "REPEAT"
            mat.node_tree.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
        if tex is not None:
            tex.image = image
            tex.extension = "REPEAT"
    return mat


def _collection(name: str, parent=None):
    coll = bpy.data.collections.new(name)
    (parent or bpy.context.scene.collection).children.link(coll)
    return coll


def _all_objects(coll):
    """Every object in ``coll`` and in the sub-collections under it."""
    seen = []

    def walk(c):
        seen.extend(c.objects)
        for child in c.children:
            walk(child)

    walk(coll)
    return seen


#: ``<car>_LOD<X>`` plus the ``_damaged`` / ``_camera`` sub-collections the
#: importer makes.  ``\b`` keeps ``<car>_LODA_wing`` out of it.
_LOD_COLL_RE = re.compile(r"_LOD([A-H])(?:_|$)")


def _lod_of(ob):
    """The LOD letter an imported object belongs to, or ``""``.

    The vehicle importer puts each level in a collection named ``<car>_LOD<X>``
    and its wrecked / camera parts in ``<car>_LOD<X>_damaged`` and
    ``<car>_LOD<X>_camera``, so the collection an object lives in is the only
    record of which level it is.  ``<car>_shared`` / ``_int_a`` / ``_int_b`` /
    ``_frontend`` are whole models, not levels of a car body.
    """
    for coll in getattr(ob, "users_collection", ()) or ():
        name = (coll.name or "").upper()
        match = _LOD_COLL_RE.search(name)
        if match:
            return match.group(1)
        for key, suffix in (("shared", "_SHARED"), ("int_a", "_INT_A"),
                            ("int_b", "_INT_B"), ("frontend", "_FRONTEND")):
            if name.endswith(suffix):
                return key
    return ""


def _lod_mixture(objects) -> list:
    """The LOD levels the given meshes span, when it is more than one."""
    levels = []
    for ob in objects:
        level = _lod_of(ob)
        if level and level not in levels:
            levels.append(level)
    return levels if len(levels) > 1 else []


#: The name a level's file carries.  These are the names ``rrmod.slots`` reads,
#: so an exported folder needs no manifest to be understood.
_LOD_FILENAMES = {"shared": "SHARED.m3g", "int_a": "INT_A.m3g",
                  "int_b": "INT_B.m3g", "frontend": "FRONTEND.m3g"}


def _lod_filename(objects) -> str:
    """``LOD_A.m3g`` / ``SHARED.m3g`` for a set of meshes, or ``""``.

    One ``.m3g`` holds one level, so the level is the name.  Returns ``""`` when
    the meshes are untagged (a scratch model, a driver, a track prop) or span
    more than one level - the caller then keeps whatever was typed.
    """
    levels = []
    for ob in objects:
        level = _lod_of(ob)
        if level and level not in levels:
            levels.append(level)
    if len(levels) != 1:
        return ""
    level = levels[0]
    return _LOD_FILENAMES.get(level) or f"LOD_{level}.m3g"


def _is_body_lod(lod) -> bool:
    """True for a real body level (``A``..``H``), false for ``shared``/``int_a``.

    The bonnet-cam shell and the two cockpit shells are complete models with a
    level letter of their own inside them, not attachments of a body LOD, so
    they are imported exactly as picked: no wheels, no aero, no sibling LODs.
    """
    return isinstance(lod, str) and len(lod) == 1 and lod.upper() in "ABCDEFGH"


#: Mesh-name tokens that mark a *damaged* variant of a part.  The game keeps
#: both the pristine and the wrecked version of every panel in the same body
#: file and swaps them by damage state, so an import that keeps them all shows
#: the car dented.  ``BROKEN`` covers the glass and the light lenses
#: (``GLASS_BROKEN_REAR``, ``HEADLIGHT_LENS_BROKEN_A_LEFT``); ``DAMAGE`` covers
#: the panels (``DOOR_LEFT_DAMAGE``, ``HOOD_DAMAGE``, ``REARBUMPER_DAMAGE``).
DAMAGED_TOKENS = ("DAMAGE", "BROKEN")


def _is_damaged(mesh_name: str) -> bool:
    """True when the mesh is the wrecked twin of a part."""
    base = (mesh_name or "").split("_mm_")[0].upper()
    return any(token in base for token in DAMAGED_TOKENS)


#: Mesh-name token for the bonnet-camera shell.  ``_shared.m3g`` carries a second
#: body shell the game renders from the nose camera (``LOD_A_BONNETCAM_BODY_*``
#: and ``LOD_A_BONNETCAM_HOOD_*``) - it sits inside the real body, so keeping it
#: in the car's own collection z-fights with the bonnet.  All 463 shared files
#: have it; 430 also have the emissive ``LOD_A_LIT_*_GLOW`` quads.
BONNETCAM_TOKEN = "BONNETCAM"
GLOW_TOKEN = "LIT_"


def _is_camera_mesh(mesh_name: str) -> bool:
    """True for the bonnet-camera shell and the emissive glow quads."""
    base = (mesh_name or "").split("_mm_")[0].upper()
    return BONNETCAM_TOKEN in base or base.startswith("LOD_") and GLOW_TOKEN in base


def _fcurves_of(ob):
    """All F-curves of an object's action, across Blender's two action APIs.

    Blender <= 4.3 keeps them in ``action.fcurves``; 4.4 introduced slotted
    actions and 5.0 **removed** ``Action.fcurves`` entirely, so they have to be
    reached through ``layers[*].strips[*].channelbags[*].fcurves``.  Without
    this the import dies with "'Action' object has no attribute 'fcurves'" and
    only the first object gets keyed.
    """
    ad = getattr(ob, "animation_data", None)
    act = getattr(ad, "action", None) if ad else None
    if act is None:
        return []
    curves = getattr(act, "fcurves", None)
    if curves is not None:
        return list(curves)
    out = []
    for layer in getattr(act, "layers", []) or []:
        for strip in getattr(layer, "strips", []) or []:
            bags = getattr(strip, "channelbags", None)
            if bags is None:
                slot = getattr(ad, "action_slot", None)
                bag = strip.channelbag(slot) if slot is not None else None
                bags = [bag] if bag is not None else []
            for bag in bags:
                out.extend(getattr(bag, "fcurves", []) or [])
    return out


def _make_linear(ob):
    for fc in _fcurves_of(ob):
        for kp in fc.keyframe_points:
            kp.interpolation = "LINEAR"


def _looks_bone_local(meshes) -> bool:
    """Driver parts are stored in bone-local space (``00_helmet_source_LOD_A``...)."""
    if len(meshes) < 4:
        return False
    hits = 0
    for md in meshes:
        name = md.name or ""
        head, sep, tail = name.partition("_")
        if sep and head.isdigit() and "_source" in name:
            hits += 1
    return hits >= max(4, int(len(meshes) * 0.8))


def _build_mesh_object(md, scale: float, convert: bool, coll, offset=(0.0, 0.0, 0.0),
                       images=None, matrix=None):
    """Build one Blender mesh from an m3g mesh.

    ``matrix`` is an optional 4x4 applied in **model space** before the Y-up to
    Z-up turn; it is how a wheel is stretched radially and turned for the right
    side of the car without touching the mesh data.
    """
    nrm_mat = None
    if matrix is not None:
        nrm_mat = matrix.to_3x3().inverted_safe().transposed()

    verts = []
    for p in md.positions:
        q = tuple(matrix @ Vector(p)) if matrix is not None else p
        verts.append(tuple(c * scale for c in _to_blender(q, convert)))
    if offset != (0.0, 0.0, 0.0):
        verts = [(x + offset[0], y + offset[1], z + offset[2]) for x, y, z in verts]
    tris = [t for t in md.triangles if max(t) < len(verts)]

    me = bpy.data.meshes.new(md.name or "rr3_mesh")
    me.from_pydata(verts, [], tris)
    me.validate(verbose=False)
    me.update()

    if md.normals and len(md.normals) == len(verts):
        try:
            if nrm_mat is not None:
                # normalise BEFORE the tuple() - a tuple has no .normalized(),
                # and that AttributeError used to be swallowed by the except
                # below, silently dropping the custom normals of every wheel
                # that had a matrix (right side + widened rear tyre).
                normals = [
                    _to_blender((nrm_mat @ Vector(n)).normalized(), convert)
                    for n in md.normals
                ]
            else:
                normals = [_to_blender(nrm, convert) for nrm in md.normals]
            me.normals_split_custom_set_from_vertices(normals)
        except Exception as exc:  # noqa: BLE001 - normals are a nicety, never fatal
            # never fail the import for this, but never swallow it silently
            # either: a silent failure here is exactly how the wheels lost
            # their normals on 2026-10-28.
            print(f"warning: {md.name}: custom normals dropped ({exc})")

    if md.uvs and len(md.uvs) == len(verts):
        uvs = geometrylib.blender_uvs(md.uvs)
        uvl = me.uv_layers.new(name="UVMap")
        for poly in me.polygons:
            for li in poly.loop_indices:
                vi = me.loops[li].vertex_index
                uvl.data[li].uv = uvs[vi]

    if md.colors and len(md.colors) == len(verts):
        try:
            attr = me.color_attributes.new(name="Col", type="FLOAT_COLOR", domain="POINT")
            for vi, rgba in enumerate(md.colors):
                attr.data[vi].color = rgba
        except Exception as exc:  # noqa: BLE001 - never fatal, but say so
            print(f"warning: {md.name}: vertex colours dropped ({exc})")

    mat_name = md.material_name or "rr3_material"
    tag = (mat_name or "").rpartition("_mm_")[2]
    atlas = texturelib.atlas_for_tag(tag) if images is not None else None
    image = images.get(atlas) if atlas else None
    me.materials.append(_get_material(mat_name, image))

    ob = bpy.data.objects.new(md.name or "rr3_mesh", me)
    coll.objects.link(ob)
    ob["rr3_material"] = mat_name
    ob["rr3_material_id"] = md.material_id
    ob["rr3_mesh_name"] = md.name or ""
    return ob


def _mesh_width(md):
    """Extent of a mesh along its own x axis (the wheel's width axis), or None.

    A shared wheel mesh is modelled with ``x = 0`` on its outer face and ``+x``
    towards the brakes, so the extent is simply ``max(x) - min(x)``.  Used to
    tell a wider ``WHEEL_REAR`` rim from the front one.
    """
    if md is None or not md.positions:
        return None
    xs = [p[0] for p in md.positions]
    if not xs:
        return None
    return max(xs) - min(xs)


def _points_frame(facing: str, mirror_x: bool):
    """Orientation of a .points file.

    The anchors are authored in the FBX space (nose towards -Y), so the
    default is *no* rotation.  ``facing="+Y"`` rotates them 180 deg about Z to
    match the .m3g model, and ``mirror_x`` mirrors them across X (on by
    default - the RR3 rig is mirrored relative to the FBX exports).
    """
    m = Matrix.Rotation(math.pi, 3, "Z") if facing == "+Y" else Matrix.Identity(3)
    if mirror_x:
        m = m @ Matrix.Scale(-1.0, 3, (1.0, 0.0, 0.0))
    return m


def _point_model_location(raw, convert: bool, scale: float = 1.0):
    """One .points raw position -> Blender location, in the .m3g model frame.

    ``raw / 32`` is metres in animation space (x right, y forward, z up); the
    model frame is that turned Y-up (``x, z, -y``), which is the frame every
    ``.m3g`` vertex is already in.  ``_to_blender`` then does the Y-up to Z-up
    turn for Blender.  The two turns compose to the identity on the numbers, so
    an anchor and the body mesh that belongs to it land at the same place.
    """
    x, y, z = (float(c) / pointslib.POINT_SCALE for c in raw)
    return Vector(_to_blender((x, z, -y), convert)) * scale


def _spline_text(splines) -> str:
    """A spline record's geometry as text, in the file's own 1/32 m units.

    ``list ; point ; point | list ; point ...`` - one ``|`` between the point
    lists of a record, one ``;`` between the points of a list, one space between
    the coordinates.  Nine significant digits are enough to pin an ``f32`` down
    exactly, so ``raw -> text -> raw`` is lossless and a round trip stays byte
    identical.
    """
    return "|".join(
        ";".join(f"{p[0]:.9g} {p[1]:.9g} {p[2]:.9g}" for p in lst)
        for lst in splines)


def _spline_centre(splines, convert: bool, scale: float, model_space: bool,
                   facing: str, mirror_x: bool) -> Vector:
    """Where to park the empty that stands for a spline: its centroid."""
    pts = [p for lst in splines for p in lst]
    if not pts:
        return Vector((0.0, 0.0, 0.0))
    acc = Vector((0.0, 0.0, 0.0))
    for p in pts:
        if model_space:
            acc += _point_model_location(p, convert, scale)
        else:
            acc += _points_frame(facing, mirror_x) @ Vector(_anchor_to_blender(p, convert))
    acc /= len(pts)
    if model_space:
        return acc
    return acc * scale / pointslib.POINT_SCALE


def _import_points(path: str, scale: float, convert: bool, coll, parent=None,
                   facing: str = "-Y", mirror_x: bool = True,
                   model_space: bool = True):
    """Create one empty per anchor in a .points file.

    ``model_space=True`` (the default, and what the vehicle importer and the
    exporter both use) places the anchors exactly where the ``.m3g`` model has
    them: ``raw / 32 -> anim_to_model -> Y-up to Z-up``.  That chain composes to
    the identity on the numbers, which is why a hand-built rig can be exported
    with no rotation either - see ``rr3_export._anchor_position``.

    ``model_space=False`` places them in the *FBX* convention instead
    (``facing`` / ``mirror_x``), for lining anchors up against an FBX export.
    Mixing the two conventions is what made the old wheel pivots land on the
    wrong side of the car, so that path is now opt-in rather than the default.
    """
    pf = pointslib.load(path)
    created = []
    by_name = {}
    for rec in pf.records:
        # a transform record has neither a position nor a spline - its matrix
        # carries the translation - so it has to be let through as well, or
        # every TRANSFORM_EXHAUST_* / TRANSFORM_DRAG_RACE_VIEW is dropped
        if not rec.position and not rec.splines and not rec.transform:
            continue
        if rec.position:
            if model_space:
                loc = _point_model_location(rec.position, convert, scale)
            else:
                loc = _points_frame(facing, mirror_x) @ Vector(
                    _anchor_to_blender(rec.position, convert))
        else:
            loc = _spline_centre(rec.splines, convert, scale, model_space,
                                 facing, mirror_x)
        # The file's own name, verbatim.  Prefixing whatever was not POINT_ /
        # HINGE_ (which this used to do) renamed SPLINE_SPECULAR to
        # POINT_SPLINE_SPECULAR and TRANSFORM_EXHAUST_01 to POINT_TRANSFORM_...,
        # and the engine looks those names up literally - a renamed record is a
        # record that stopped working.  The exporter keys off rr3_point_type /
        # rr3_point_name, so nothing here needs a POINT_ prefix.
        label = rec.name or f"anchor_{rec.index}"
        empty = bpy.data.objects.new(label, None)
        empty.empty_display_type = "PLAIN_AXES"
        empty.empty_display_size = 0.25
        if model_space:
            # already metres and already in the model frame
            empty.location = tuple(loc)
        else:
            empty.location = tuple(c * scale / pointslib.POINT_SCALE for c in loc)
        empty["rr3_point_type"] = rec.type
        empty["rr3_point_type_name"] = pointslib.TYPE_NAMES.get(rec.type, str(rec.type))
        empty["rr3_point_name"] = rec.name or ""
        empty["rr3_point_index"] = rec.index
        if rec.position:
            # Nine significant digits, not six decimals: these numbers are
            # f32 in the file and a position of 2.28 m has an ulp of 2.4e-7, so
            # six *decimals* rounds the value away and the round trip stops
            # being byte exact (it also quietly moved every anchor by a fraction
            # of a millimetre on every save).
            empty["rr3_point_raw"] = (
                f"{rec.position[0]:.9g} {rec.position[1]:.9g} {rec.position[2]:.9g}"
            )
        if rec.matrix:
            empty["rr3_orientation"] = " ".join(f"{v:.9g}" for v in rec.matrix)
            # and put it on the empty, so a hinge's swing axis is something you
            # can see and rotate instead of nine numbers in a custom property
            m = Matrix((rec.matrix[0:3], rec.matrix[3:6], rec.matrix[6:9]))
            m = _POINTS_E2B @ m @ _POINTS_E2B.transposed()
            empty.rotation_mode = "XYZ"
            empty.rotation_euler = m.to_euler("XYZ")
        if rec.transform:
            # The file's matrix is in 1/32 m; the empty's basis is in metres, and
            # the exporter multiplies the translation back.  Keeping the two in
            # the same units is what lets _transform_matrix hand the file's own
            # numbers back untouched.  The layout also differs: the file puts
            # the translation in the bottom row, Blender in the last column -
            # see rr3_export._file_to_basis.
            t = list(rec.transform)
            t[12] /= pointslib.POINT_SCALE
            t[13] /= pointslib.POINT_SCALE
            t[14] /= pointslib.POINT_SCALE
            empty["rr3_transform"] = " ".join(f"{v:.9g}" for v in t)
            empty.matrix_basis = explib._file_to_basis(t)
        # Where the empty ended up, so the exporter can tell "untouched" (write
        # the file's own numbers back, byte exact) from "the user dragged it"
        # (write where it is now).  Without this an anchor could be moved and
        # the export would silently ignore it.  Last, because a transform record
        # carries its own translation and has just overwritten the location.
        empty["rr3_point_loc"] = " ".join(f"{c:.9g}" for c in empty.location)
        if rec.splines:
            # A spline has no single position: it is a list of point lists.  It
            # is kept as text in the file's own 1/32 m units (exact on the way
            # back, like rr3_point_raw) and the empty sits at its centroid so
            # you can at least see where it is.
            empty["rr3_splines"] = _spline_text(rec.splines)
            empty["rr3_spline_count"] = len(rec.splines)
            empty["rr3_spline_points"] = sum(len(s) for s in rec.splines)
        coll.objects.link(empty)
        if parent is not None:
            empty.parent = parent
        created.append(empty)
        if rec.name:
            by_name.setdefault(rec.name, []).append(empty)

    # The override table (light scale / colour, 145 of the 960 shipped files
    # have one).  It belongs to the record it names, so it rides on that empty;
    # anything left over - a name with no record - goes on the scene.
    #
    # A name can repeat (four cars ship two POINT_HEADLIGHT_LEFT records and
    # override both), so the empties are queued per name and each override takes
    # the next one, in file order.
    leftover = []
    for ov in pf.overrides:
        queue = by_name.get(ov.name)
        if queue:
            queue.pop(0)["rr3_override"] = ov.value
        else:
            leftover.append((ov.name, ov.value))
    if leftover:
        scene = bpy.context.scene
        scene["rr3_overrides"] = "\n".join(f"{n}\t{v}" for n, v in leftover)
    scene = bpy.context.scene
    scene["rr3_points_version"] = pf.version
    scene["rr3_points_override_field"] = 1 if pf.override_field else 0
    return pf, created


# --------------------------------------------------------------------------
# anchor frame
# --------------------------------------------------------------------------
#: The turn between the file's frame and the rig's, as the exporter uses it.
#: ``rr3_export.POINTS_E2B`` is the same matrix; a hinge's 3x3 is stored in the
#: file's frame and has to be turned to reach the empty's rotation.
_POINTS_E2B = Matrix.Rotation(math.pi, 3, "Z")


# --------------------------------------------------------------------------
# decoded textures: where they go and how a stale decode is thrown away
# --------------------------------------------------------------------------
#: Bump this whenever the decoder output changes.  The decoded PNGs live in a
#: versioned sub-folder, so a build that flipped the rows can never pick up a
#: file an older build wrote - that was the "textures still upside down after the
#: fix" report, the old PNGs sitting in the temp folder.
TEXTURE_CACHE_VERSION = 2


def _image_cache_dir() -> str:
    return os.path.join(tempfile.gettempdir(), "rr3_dds",
                        f"v{TEXTURE_CACHE_VERSION}")


def _purge_stale_textures() -> dict:
    """Delete decoded textures written by an older decoder.

    Two things are thrown away, both of them ours:

    * files under ``<temp>/rr3_dds`` that are not in the current ``v<n>``
      folder - a decode from a build that flipped the rows the other way;
    * the Blender images that were loaded from those files, so a scene does not
      keep showing the old, upside-down pixels next to the new ones.

    Only ever touches our own temp folder and images pointing into it.  Returns
    ``{"files": n, "images": n}`` for the report.
    """
    root = os.path.join(tempfile.gettempdir(), "rr3_dds")
    keep = f"v{TEXTURE_CACHE_VERSION}"
    current = os.path.join(root, keep)
    files = images = 0
    if os.path.isdir(root):
        for name in os.listdir(root):
            path = os.path.join(root, name)
            if path == current:
                continue
            try:
                if os.path.isdir(path):
                    shutil.rmtree(path)
                    files += 1
                elif name.lower().endswith((".png", ".dds")):
                    os.remove(path)
                    files += 1
            except OSError:
                pass  # a locked file is not worth failing the import for
    # Blender caches the pixels, not just the path: drop the images too.
    for img in list(bpy.data.images):
        filepath = bpy.path.abspath(img.filepath) if img.filepath else ""
        if not filepath:
            continue
        try:
            inside = os.path.commonpath([os.path.abspath(filepath),
                                         os.path.abspath(root)]) == os.path.abspath(root)
        except ValueError:
            inside = False
        if not inside:
            continue
        if os.path.dirname(os.path.abspath(filepath)) == os.path.abspath(current):
            continue
        try:
            bpy.data.images.remove(img)
            images += 1
        except Exception:  # noqa: BLE001 - an image in use can stay
            pass
    return {"files": files, "images": images}


def _adopt_image(png: str):
    """Point an older decode of the same texture at ``png`` and refresh it.

    Images are looked up by file name, so an image decoded before the flip is
    found and re-read from the new file.  Without this the materials that
    already reference it keep showing the old, upside-down pixels until the
    whole scene is rebuilt.
    """
    stem = os.path.basename(png)
    for img in bpy.data.images:
        current = bpy.path.abspath(img.filepath) if img.filepath else ""
        if os.path.basename(current) != stem or current == png:
            continue
        img.filepath = png
        try:
            img.reload()
        except Exception:  # noqa: BLE001 - keep the old pixels rather than none
            pass
        return img
    return None


def _image_for_path(path: str, cache: dict):
    """Load any game texture container as a Blender image (cached by path).

    Uses :mod:`rr3lib.texport`, which understands every container in the depot -
    ``.dxt.dds.z``, the chunked ``.dxt.dds.z.bin`` shadow maps, the
    uncompressed ``.dxt.dds.bin`` and ``.rgb.pvr.z`` - and decodes DXT1/DXT3/DXT5
    itself, so Blender's own DDS support is not required.

    The game stores its images bottom-up, so ``texport`` turns the rows over on
    the way out; the UVs are left exactly as the model states them.  Writing a
    PNG (rather than handing Blender the raw DDS) is what makes that flip happen
    for every container, including the plain ``.dds.z`` ones.
    """
    if not path:
        return None
    hit = cache.get(path)
    if hit is not None:
        return hit
    try:
        png = texportlib.export(path, _image_cache_dir(), "png")
        img = _adopt_image(png)
        if img is None:
            img = bpy.data.images.load(png, check_existing=True)
        # The decoded file lives in the temp folder, which is emptied between
        # sessions - without packing, every texture shows up pink after a
        # restart, which reads as "the textures were never imported".
        if not img.packed_file:
            try:
                img.pack()
            except Exception as exc:  # noqa: BLE001 - unpacked is better than none
                print(f"[rr3] could not pack {os.path.basename(path)}: {exc}")
    except Exception as exc:  # noqa: BLE001 - a broken atlas must not abort
        print(f"[rr3] texture {os.path.basename(path)} failed: {exc}")
        return None
    cache[path] = img
    return img


def _load_atlas_images(car_dir: str) -> dict:
    """Decode every atlas a material tag may need into Blender images."""
    images = {}
    cache = {}
    for atlas in sorted({a for a in texturelib.TAG_ATLAS.values() if a}):
        path = texturelib.find_atlas(car_dir, atlas)
        if not path:
            continue
        img = _image_for_path(path, cache)
        if img is not None:
            images[atlas] = img
    return images


def _car_texture_files(car_dir: str) -> list:
    """Every texture file of a car, **including the ones in sub-folders**.

    The paint atlases live in ``<car>/livery/``, not next to the body, so a flat
    ``listdir`` silently skipped exactly the textures a paint scheme needs.
    """
    found = []
    for root, _dirs, files in os.walk(car_dir):
        for name in sorted(files):
            path = os.path.join(root, name)
            if texportlib.is_texture(path):
                found.append(path)
    return found


def _common_texture_files(car_dir: str) -> list:
    """The shared ``vehicles/common`` atlases this car's materials point at.

    Windows, tyre treads, brake discs, the chassis and the interior swatches are
    not per-car art: every car points at the same handful of files in
    ``vehicles/common``.  They are named by ``default.liveries.bin.nct``, so that
    table is what is walked - loading all 298 files in the folder would drag in
    every interior swatch of every car for no reason.
    """
    depot = gamematlib.find_depot(car_dir)
    if not depot:
        return []
    try:
        default = liverylib.load_default(depot)
    except Exception:  # noqa: BLE001 - the fallback table is optional
        return []
    found, seen = [], set()
    for _slot, internal in default.textures:
        internal = internal.decode("utf-8", "replace")
        if not internal.startswith("common/"):
            continue
        path = carmatlib.resolve_texture(depot, "", internal)
        if path and path not in seen:
            seen.add(path)
            found.append(path)
    return found


def _load_car_textures(car_dir: str) -> dict:
    """Decode every atlas and ramp of a car folder into ``bpy.data.images``.

    Returns ``{"images": [names], "failed": [(file, why)], "purged": {...}}``.
    Ramps are tagged ``Non-Color``; atlases keep sRGB.  Decodes from an older
    build are purged first, so a texture never shows up twice - once upright,
    once upside down.  The car's own folder (including ``livery/``) comes first,
    then the shared ``vehicles/common`` set, then the shader ramps.
    """
    purged = _purge_stale_textures()
    images, failed = [], []
    cache = {}
    if not os.path.isdir(car_dir):
        raise RuntimeError(f"not a folder: {car_dir}")
    for path in _car_texture_files(car_dir):
        name = os.path.relpath(path, car_dir)
        img = _image_for_path(path, cache)
        if img is None:
            failed.append((name, "decode failed"))
            continue
        if "shadow" in name.lower():
            img.colorspace_settings.name = "Non-Color"
        images.append(img.name)
    for path in _common_texture_files(car_dir):
        name = os.path.join("common", os.path.basename(path))
        img = _image_for_path(path, cache)
        if img is None:
            failed.append((name, "decode failed"))
            continue
        images.append(img.name)
    # the shader ramps live in the depot, not the car folder
    depot = gamematlib.find_depot(car_dir)
    if depot:
        shaders = os.path.join(depot, "vehicles", "shaders")
        if os.path.isdir(shaders):
            for name in sorted(os.listdir(shaders)):
                if not texportlib.is_texture(name):
                    continue
                img = _image_for_path(os.path.join(shaders, name), cache)
                if img is None:
                    continue
                img.colorspace_settings.name = "Non-Color"
                images.append(img.name)
    return {"images": images, "failed": failed, "purged": purged}


def _ramp_image(depot: str, internal: str, cache: dict):
    """Load a 1024x1 shader ramp as a non-colour Blender image."""
    if not internal:
        return None
    hit = cache.get(internal)
    if hit is not None:
        return hit
    path = gamematlib.resolve_lut(depot, internal)
    if path is None:
        return None
    try:
        png = pvrlib.to_png(path, _image_cache_dir())
        img = _adopt_image(png)
        if img is None:
            img = bpy.data.images.load(png, check_existing=True)
        img.colorspace_settings.name = "Non-Color"
        if not img.packed_file:
            try:
                img.pack()
            except Exception:  # noqa: BLE001 - unpacked is still usable
                pass
    except Exception as exc:  # noqa: BLE001
        print(f"[rr3] ramp {os.path.basename(path)} failed: {exc}")
        return None
    cache[internal] = img
    return img


def _set_input(bsdf, slot: str, value):
    """Set one Principled input if this Blender build has it."""
    if bsdf is not None and slot in bsdf.inputs:
        bsdf.inputs[slot].default_value = value


#: Every material name this session has handed out, across **all** imports.
#:
#: This used to live on :class:`GameMaterials`, which is created once per LOD,
#: so importing ``LOD_B`` did not know that ``LOD_A`` had already built a
#: material called ``<car>_Vehicle Exterior_car_chassis``.  The name lookup in
#: :func:`_build_preset_material` then found that material, decided its presets
#: did not match, and deleted it - while LOD A's meshes were still wearing it.
#: The chassis atlas lives in ``vehicles/common`` and is shared by every LOD, so
#: it was the first thing to break.  One set for the whole session fixes it.
_MATERIAL_NAMES: set = set()


def _free_material_name(name: str) -> str:
    """``name``, or ``name_2`` / ``name_3`` ... while that one is taken."""
    if bpy.data.materials.get(name) is None:
        return name
    n = 2
    while bpy.data.materials.get(f"{name}_{n}") is not None:
        n += 1
    return f"{name}_{n}"


def _build_preset_material(name: str, presets, active: int = 0):
    """One Blender material holding **one shading preset per paint scheme**.

    This is the structure the game itself implies: a mesh has *one* material,
    and a paint scheme changes the numbers inside it, not the slot count.  So
    the material carries

    * one ``Principled BSDF`` per scheme, named ``bsdf_<n>``;
    * one image node per scheme for that scheme's albedo atlas
      (``atlas_<n>``), wired into its BSDF's Base Color;
    * the scheme's two 1024x1 ramps (``ramp_fresnel_<n>`` /
      ``ramp_specular_<n>``) kept as image nodes in the same frame, so the raw
      game data travels with the file;
    * **only the active scheme's BSDF is wired to Material Output**.

    Switching paint is then a single re-link inside one material - see
    :func:`_activate_preset`.  ``presets`` is a list of ``(index, label, rm,
    image, fresnel_img, spec_img)``.

    The numbers are the game's own, converted rather than invented:

    * **Base Color** <- the atlas the livery table points at, wired straight into
      Base Color.  The scheme's paint colour is the *default* underneath it, so a
      part with no atlas of its own still reads as paint instead of grey.
    * **Roughness** <- ``mu_MaterialSpecularPower_Base`` through
      :func:`rr3lib.gamematerial.roughness_from_power`.  Gloss paint has a sharp
      base lobe (1000 -> 0.045), metallic paint a broad one (8 -> 0.45).
    * **Metallic** <- the mean of the fresnel ramp through
      :func:`rr3lib.gamematerial.metallic_from_fresnel`.
    * **Coat** <- the *top* lobe when it is sharp: metallic paint is broad at the
      base and sharp at the top (8 / 1000), which is a base coat under a clear
      coat, so the top lobe becomes Coat Weight 1.  Gloss paint is the other way
      round (1000 / 10) and gets no coat.
    """
    mat = bpy.data.materials.get(name)
    if mat is not None:
        # A material of that name can be left over from an earlier import with a
        # different scheme count (a car repainted, or a second car reusing the
        # name).  Rebuilding beats silently handing back the wrong presets.
        same = (mat.get("rr3_presets") == len(presets)
                and mat.node_tree is not None)
        if same and presets:
            same = mat.get("rr3_textures") == [p[2].texture_file or "" for p in presets]
        if same:
            return mat
        if mat.users:
            # Something is still wearing it - LOD A's meshes, when LOD B asks for
            # a material of the same name.  Deleting it would strip them bare, so
            # the new one gets a free name instead and both live side by side.
            name = _free_material_name(name)
        else:
            bpy.data.materials.remove(mat)
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    out = next((n for n in nt.nodes if n.type == "OUTPUT_MATERIAL"), None)
    default_bsdf = nt.nodes.get("Principled BSDF")
    if default_bsdf is not None:
        nt.nodes.remove(default_bsdf)

    for order, (index, label, rm, image, fresnel_img, spec_img) in enumerate(presets):
        frame = nt.nodes.new("NodeFrame")
        frame.name = f"preset_{index}"
        frame.label = f"paint {index + 1}: {label}"
        frame.location = (0, -520 * order)

        bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
        bsdf.name = f"bsdf_{index}"
        bsdf.label = f"paint {index + 1}"
        bsdf.location = (60, -520 * order)
        bsdf.parent = frame

        # The paint colour only belongs on paint materials; a matte chassis must
        # not inherit the car's body colour just because it has no atlas.
        is_paint = rm.material.startswith(gamematlib.PAINT_PREFIXES)
        colour = (rm.paint_rgb if is_paint else None) or (0.8, 0.8, 0.8)
        _set_input(bsdf, "Base Color", (*colour, 1.0))
        _set_input(bsdf, "Roughness", rm.roughness)
        _set_input(bsdf, "Metallic", rm.metallic)
        if rm.spec_colour is not None:
            # The game stores specular colours as 0..255 bytes
            # (``mu_MaterialSpecularColour_Base`` is read verbatim, e.g.
            # "255,255,255" or "512,512,512").  Blender's Specular Tint is a
            # 0..1 colour, so writing the raw bytes multiplied the highlight by
            # 255 and every painted panel came out looking like chrome.
            _set_input(bsdf, "Specular Tint",
                       (*[min(1.0, max(0.0, c / 255.0)) for c in rm.spec_colour], 1.0))
        if rm.coat is not None:
            _set_input(bsdf, "Coat Weight", 1.0)
            _set_input(bsdf, "Coat Roughness", rm.coat)
        # glass and light housings are transparent in the game
        if rm.application in ("appDepthSort",) or "GLASS" in (rm.flags or ()):
            _set_input(bsdf, "Alpha", 0.35)
        if "GLASS" in (rm.flags or ()):
            _set_input(bsdf, "Transmission Weight", 0.9)

        if image is not None:
            tex = nt.nodes.new("ShaderNodeTexImage")
            tex.name = f"atlas_{index}"
            tex.label = (os.path.basename(image.filepath)
                         if image.filepath else f"atlas {index + 1}")
            tex.image = image
            tex.extension = "REPEAT"
            tex.location = (-560, -520 * order)
            tex.parent = frame
            nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])

        for slot, img, what in ((0, fresnel_img, "fresnel"),
                                (1, spec_img, "specular")):
            if img is None:
                continue
            node = nt.nodes.new("ShaderNodeTexImage")
            node.name = f"ramp_{what}_{index}"
            node.label = what
            node.image = img
            node.location = (-560, -260 - 260 * slot - 520 * order)
            node.parent = frame

        if out is not None and order == 0:
            nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])

    first = presets[0][2] if presets else None
    if first is not None and first.paint_rgb:
        mat.diffuse_color = (*first.paint_rgb, 1.0)
    mat["rr3_presets"] = len(presets)
    mat["rr3_preset_names"] = [p[1] for p in presets]
    mat["rr3_textures"] = [p[2].texture_file or "" for p in presets]
    if presets:
        mat["rr3_material"] = first.material if first else ""
        mat["rr3_application"] = first.application if first else ""
        mat["rr3_fresnel"] = (first.fresnel or "") if first else ""
        mat["rr3_specular"] = (first.specular or "") if first else ""
    _activate_preset(mat, active)
    return mat


def _activate_preset(mat, index: int) -> bool:
    """Wire preset ``index`` of ``mat`` to Material Output; the rest go quiet."""
    nt = getattr(mat, "node_tree", None)
    if nt is None:
        return False
    out = next((n for n in nt.nodes if n.type == "OUTPUT_MATERIAL"), None)
    bsdf = nt.nodes.get(f"bsdf_{index}")
    if out is None or bsdf is None:
        return False
    for link in list(nt.links):
        if link.to_node == out and link.to_socket.name == "Surface":
            nt.links.remove(link)
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    mat["rr3_preset_active"] = index
    return True


class GameMaterials:
    """Every paint scheme's numbers for one car, packed into one material each.

    A mesh keeps the **single** material slot it was imported with; the paint
    schemes live *inside* that material as shading presets (see
    :func:`_build_preset_material`).  Switching paint therefore never changes the
    slot count - it re-links one BSDF - which is both what the game does and what
    keeps a `.blend` tidy.

    Meshes whose game material and atlas are identical under every scheme share
    one Blender material instead of getting a private copy.
    """

    def __init__(self, depot: str, car: str, meshes, paint_indices=None):
        self.depot = depot
        self.car = car
        self.schemes = []
        self.warnings = []
        self._images = {}
        self._ramps = {}
        self._materials = {}     # signature -> bpy material
        self._by_mesh = {}       # mesh -> bpy material
        # Shared across every import in the session: LOD B has to know the names
        # LOD A already took, or it reuses a name and rebuilds a material that is
        # still in use (see _MATERIAL_NAMES).
        self._names = _MATERIAL_NAMES
        self._build(meshes, paint_indices)

    # -- construction ----------------------------------------------------
    def _build(self, meshes, paint_indices):
        try:
            schemes = carmatlib.car_materials(self.depot, self.car, meshes,
                                              paint_indices=paint_indices)
        except Exception as exc:  # noqa: BLE001 - never fail the import for this
            self.warnings.append(f"game materials: {exc}")
            return
        self.schemes = schemes
        if not schemes:
            self.warnings.append("game materials: the car ships no paint scheme")
            return

        # A mesh whose (material, atlas) is the same under every scheme needs no
        # per-scheme preset at all: one preset is the whole story.
        for mesh in meshes:
            resolved = [(s.index, s.name, s.material_for(mesh)) for s in schemes]
            resolved = [(i, n, rm) for i, n, rm in resolved if rm and rm.material]
            if not resolved:
                continue
            sig = tuple(self._signature(rm) for _i, _n, rm in resolved)
            mat = self._materials.get(sig)
            if mat is None:
                first = resolved[0][2]
                distinct = {self._signature(rm) for _i, _n, rm in resolved}
                # The name has to be unique per *signature*, not per material:
                # a car has one `car_flat` but uses it on the chassis atlas, the
                # cab atlas and the badges atlas, and a `cab` part's atlas is
                # exactly what the paint scheme changes on some cars (the Veyron
                # GSV has cab / cab_chrome / cab_orange).  Naming them all
                # `<car>_car_flat` made the first one win and every other part
                # wear its texture.  The tag is what tells them apart, so it
                # goes in the name whenever the plain one is taken.
                stem = f"{self.car}_{first.material}"
                if len(distinct) > 1:
                    stem += "_paint"
                name = self._unique_name(stem, first.tag)
                if len(distinct) == 1:
                    # Nothing about this part changes with the paint scheme - a
                    # tyre, a disc, a chassis.  Give it the one preset and no
                    # paint switching at all, which is exactly what the livery
                    # table says (no paint overrides its material slot).
                    presets = [
                        (resolved[0][0], resolved[0][1], first,
                         _image_for_path(first.texture_file, self._images),
                         _ramp_image(self.depot, first.fresnel, self._ramps),
                         _ramp_image(self.depot, first.specular, self._ramps))
                    ]
                else:
                    presets = [
                        (i, n, rm,
                         _image_for_path(rm.texture_file, self._images),
                         _ramp_image(self.depot, rm.fresnel, self._ramps),
                         _ramp_image(self.depot, rm.specular, self._ramps))
                        for i, n, rm in resolved
                    ]
                mat = _build_preset_material(name, presets)
                self._materials[sig] = mat
                self._names.add(name)
            self._by_mesh[mesh] = mat

    def _unique_name(self, stem: str, tag: str) -> str:
        """``stem``, or ``stem_<tag>`` / ``stem_<tag>_2`` when this session used it.

        Only names *this session handed out* are skipped here.  A name that is
        merely present in ``bpy.data.materials`` is left alone, because
        :func:`_build_preset_material` knows how to reuse it when the presets are
        identical and how to step aside when they are not - which is what lets a
        second import of the same LOD share its materials instead of piling up
        ``_2`` copies.
        """
        if stem not in self._names:
            return stem
        if tag:
            candidate = f"{stem}_{tag}"
            if candidate not in self._names:
                return candidate
            n = 2
            while f"{candidate}_{n}" in self._names:
                n += 1
            return f"{candidate}_{n}"
        n = 2
        while f"{stem}_{n}" in self._names:
            n += 1
        return f"{stem}_{n}"

    @staticmethod
    def _signature(rm) -> tuple:
        # ``paint_rgb`` is the body colour, and only paint materials ever use it
        # (see ``_build_preset_material``) - leaving it out for everything else
        # is what lets a tyre's six schemes collapse into one preset.
        is_paint = (rm.material or "").startswith(gamematlib.PAINT_PREFIXES)
        return (rm.material, rm.texture_file, rm.fresnel, rm.specular,
                round(rm.roughness, 4), round(rm.metallic, 4),
                None if rm.coat is None else round(rm.coat, 4),
                rm.paint_rgb if is_paint else None)

    # -- queries ---------------------------------------------------------
    def material_for(self, mesh: str):
        """The single material a mesh should carry (``None`` when unresolved)."""
        return self._by_mesh.get(mesh)

    @property
    def scheme_names(self) -> list:
        return [s.name or f"paint{i + 1:02d}" for i, s in enumerate(self.schemes)]

    def report(self) -> str:
        lines = [f"{self.car}: {len(self.schemes)} paint scheme(s), "
                 f"{len(self._materials)} material(s)"]
        for i, scheme in enumerate(self.schemes):
            rgb = scheme.rgb
            colour = ("#%02x%02x%02x" % tuple(int(c * 255) for c in rgb)
                      if rgb else "?")
            lines.append(f"  preset {i}: {scheme.name} {colour}")
        return "\n".join(lines)


def _apply_game_materials(objects, car_dir: str, car: str, paint: int = -1,
                          depot: str = None):
    """Give every mesh **one** material that holds a preset per paint scheme.

    ``paint`` is the preset that starts wired to Material Output (``-1`` keeps
    the first).  Returns the :class:`GameMaterials` instance so the caller can
    report on it, or ``None`` when the depot's material tables are unreachable.

    ``depot`` overrides the walk-up search, which matters for a car that was
    built into a folder outside the depot: without it the tables cannot be
    found and the import would quietly keep the placeholder materials.
    """
    meshes = [ob.get("rr3_mesh_name") for ob in objects]
    meshes = [m for m in meshes if m]
    if not meshes:
        return None
    if depot is None:
        depot = gamematlib.find_depot(car_dir)
    if depot is None:
        raise RuntimeError(
            "cannot find the depot's materials/materials.bin above "
            f"{car_dir}; pick the depot folder explicitly in 'Depot' to get the "
            "game's own materials")
    gm = GameMaterials(depot, car, meshes)
    if not gm.schemes:
        return gm
    count = len(gm.schemes)
    want = paint if 0 <= paint < count else 0
    for ob in objects:
        mat = gm.material_for(ob.get("rr3_mesh_name") or "")
        if mat is None:
            continue
        me = ob.data
        me.materials.clear()
        me.materials.append(mat)
        for poly in me.polygons:
            poly.material_index = 0
        # Parts the livery table never overrides (tyres, discs, the chassis)
        # carry a single preset: there is nothing to switch on them.
        names = list(mat["rr3_preset_names"])
        if not _activate_preset(mat, want) and names:
            _activate_preset(mat, int(mat["rr3_preset_active"]))
        ob["rr3_paint_slot"] = int(mat["rr3_preset_active"])
        ob["rr3_paint_slots"] = len(names)
        ob["rr3_paint_presets"] = names
    return gm



def import_m3g_file(
    filepath: str,
    *,
    scale: float = 1.0,
    convert_axes: bool = True,
    import_anchors: bool = True,
    spread_parts: bool = False,
    spread_step: float = 0.6,
    textures: bool = True,
    collection=None,
):
    m = m3glib.M3G(filepath)
    stem = os.path.splitext(os.path.basename(filepath))[0]
    # A caller that already owns a collection (the vehicle assembler does) hands
    # it in, otherwise every import leaves an empty ``<file stem>`` collection
    # behind and the next one with the same name lands in ``.001``.
    coll = collection if collection is not None else _collection(stem)

    images = _load_atlas_images(os.path.dirname(os.path.abspath(filepath))) if textures else None
    objs = []
    meshes = geometrylib.all_meshes(m)
    for i, md in enumerate(meshes):
        off = (i * spread_step, 0.0, 0.0) if spread_parts else (0.0, 0.0, 0.0)
        objs.append(_build_mesh_object(md, scale, convert_axes, coll, off, images))

    anchor_info = None
    if import_anchors:
        anchor_path = os.path.splitext(filepath)[0] + ".points"
        if os.path.exists(anchor_path):
            anchor_info = _import_points(anchor_path, scale, convert_axes, coll)

    return {
        "m3g": m,
        "objects": objs,
        "meshes": meshes,
        "collection": coll,
        "anchors": anchor_info,
    }


# --------------------------------------------------------------------------
# .banim animation
# --------------------------------------------------------------------------
def _axis_matrix(convert: bool):
    """mesh space (Y-up) -> Blender space, matching :func:`_to_blender`."""
    if convert:
        return Matrix(((1.0, 0.0, 0.0), (0.0, 0.0, -1.0), (0.0, 1.0, 0.0)))
    return Matrix.Identity(3)


def _anim_matrix(convert: bool, flip_driver: bool):
    """animation space (x right, y fore, z up) -> Blender axes.

    The animation basis is z-up, and so is Blender, but a part's mesh is stored
    Y-up: anim -> model (``x, z, -y``) -> Blender (``x, -z, y``) composes to the
    identity, which is why the joint translation needs no axis swap - a part's
    authored position is already the Blender one.

    ``flip_driver`` mirrors x and y, i.e. turns the figure 180 deg about Z.  It is
    **not** needed for the driver: the authored pose already faces +Y, which is
    the way the car's nose points (``WHEEL_FL``/``WHEEL_FR`` have positive y), and
    the ``driver.banim`` hip/knee/ankle heights run 0.000 / +0.166 / +0.460 along
    fore, so the figure sits facing forward.  Mirroring it puts the head toward
    the nose and the legs toward the boot - a driver sitting backwards, which is
    what an earlier default did.  The flag is kept for callers that really do want
    a mirrored figure; the driver importer turns the *whole* rig with its root
    empty instead, so the parts keep the game's own transforms.
    """
    if flip_driver:
        return Matrix(((-1.0, 0.0, 0.0), (0.0, -1.0, 0.0), (0.0, 0.0, 1.0)))
    return Matrix.Identity(3)


def _pose_parts(b, objects, mesh_data, coll, *, fps=30.0, max_frames=0,
                placement="BONE", convert_axes=True, flip_driver=True,
                parent=None):
    """Keyframe every part of ``b`` onto its object.

    Split out of :func:`import_banim_file` so the driver importer can pose the
    same fifteen-part rig into a collection of its own and hang it off a root
    empty (``parent``) without duplicating the matrix chain.
    """
    names = riglib.track_names(b, list(objects) if objects else None)
    roles = riglib.roles_for(b)

    for i in range(b.num_tracks):
        nm = names[i] if i < len(names) else f"track{i}"
        ob = objects.get(nm)
        if ob is None:
            ob = bpy.data.objects.new(f"rr3_{nm}", None)
            ob.empty_display_type = "PLAIN_AXES"
            ob.empty_display_size = 0.08
            coll.objects.link(ob)
            objects[nm] = ob
        ob["rr3_track"] = i
        ob["rr3_role"] = roles[i] if i < len(roles) else ""

    cm = _axis_matrix(convert_axes)
    anim = _anim_matrix(convert_axes, flip_driver)
    # constant per-part data: bbox centre, long axis and its extent (imported space)
    local = {}
    for i in range(b.num_tracks):
        nm = names[i]
        md = mesh_data.get(nm)
        if md is None:
            local[nm] = (Vector((0.0, 0.0, 0.0)), Vector((0.0, 0.0, 1.0)), 0.0)
            continue
        bb = md.bbox
        centre = Vector([(bb[0][k] + bb[1][k]) * 0.5 for k in range(3)])
        axis = "Z"
        if b.num_tracks == len(riglib.DRIVER_RIG):
            axis = riglib.DRIVER_RIG[i][2]
        k = "XYZ".index(axis)
        ax = Vector([1.0 if j == k else 0.0 for j in range(3)])
        length = abs(bb[1][k] - bb[0][k])
        local[nm] = (cm @ centre, (cm @ ax).normalized(), length)

    scene = bpy.context.scene
    scene.render.fps = max(1, int(round(fps)))
    frames = riglib.frames(b, fps, max_frames, names)
    for fr in frames:
        frame_no = int(round(fr.time_ms / 1000.0 * fps)) + 1
        for ps in fr.parts:
            ob = objects[ps.name]
            centre, ax, length = local[ps.name]
            joint = anim @ Vector(ps.position)
            if placement == "BONE":
                origin, direction, _is_limb = riglib.bone_axis(b, fr.time_ms, ps.index)
                d_bl = (anim @ Vector(direction)).normalized()
                o_bl = anim @ Vector(origin)
                align = ax.rotation_difference(d_bl).to_matrix()
            else:
                o_bl = joint
                align = Matrix.Identity(3)
            rot = Euler(ps.rotation_rad, "XYZ").to_matrix()
            # the channel angles live in the *animation* basis (x right, y forward,
            # z up), so they must be conjugated by the animation basis - not by the
            # mesh basis, which is Y-up and would swap y and z
            rot_bl = anim @ rot @ anim.transposed()
            if placement == "NODE":
                # the part is modelled round its own joint, so the node matrix
                # applies about the origin: no bounding-box centre to undo
                ob.matrix_world = (
                    Matrix.Translation(anim @ Vector(ps.position))
                    @ rot_bl.to_4x4()
                )
                ob.keyframe_insert("location", frame=frame_no)
                ob.keyframe_insert("rotation_euler", frame=frame_no)
                continue
            m = rot_bl @ align
            ob.matrix_world = (
                Matrix.Translation(o_bl)
                @ m.to_4x4()
                @ Matrix.Translation(-centre)
            )
            ob.keyframe_insert("location", frame=frame_no)
            ob.keyframe_insert("rotation_euler", frame=frame_no)

    for ob in objects.values():
        _make_linear(ob)

    scene.frame_start = 1
    scene.frame_end = max(1, int(round(b.duration_ms / 1000.0 * fps)))
    return len(frames)


def import_banim_file(
    filepath: str,
    *,
    model_path: str | None = None,
    fps: float = 30.0,
    max_frames: int = 0,
    placement: str = "BONE",
    convert_axes: bool = True,
    flip_driver: bool = True,
):
    """Import a ``.banim`` as keyframed part animations.

    ``placement="BONE"`` orients every part along its bone and keeps the mesh
    centred on the bone; ``placement="JOINT"`` just puts the mesh centre on the
    joint; ``placement="NODE"`` applies the node's own rotation and translation to
    the part around its **origin**, which is what the game does - each driver part
    is modelled round its own joint, so rotating it about its bounding-box centre
    (what the other two modes do, since the assets do not store a skeleton) makes
    the figure 25% too tall.
    """
    b = banimlib.load(filepath)
    model = model_path or riglib.find_model(filepath, b.num_tracks)
    coll = _collection(os.path.splitext(os.path.basename(filepath))[0])

    objects: dict[str, object] = {}
    mesh_data = {}
    if model and os.path.exists(model):
        res = import_m3g_file(model, convert_axes=convert_axes, import_anchors=False)
        for md, ob in zip(res["meshes"], res["objects"]):
            objects[md.name] = ob
            mesh_data[md.name] = md

    frames = _pose_parts(b, objects, mesh_data, coll, fps=fps,
                         max_frames=max_frames, placement=placement,
                         convert_axes=convert_axes, flip_driver=flip_driver)
    return {
        "banim": b,
        "model": model,
        "objects": objects,
        "frames": frames,
        "collection": coll,
    }


# --------------------------------------------------------------------------
# whole-vehicle assembly (wheels + active aero)
# --------------------------------------------------------------------------
_CAR_SUFFIXES = ("_shared", "_int_a", "_int_b") + tuple(f"_{c}" for c in "abcdefgh")


def car_from_path(filepath: str):
    """Derive ``(car_dir, car, lod)`` from any file that belongs to a car.

    ``lod`` is the level the *file itself* holds, so ``<car>_shared.m3g`` gives
    ``"shared"`` and ``<car>_int_a.m3g`` gives ``"int_a"``.  Both are models in
    their own right (the bonnet-cam and cockpit shells are complete, not
    attachments of a body LOD), so the vehicle importer imports exactly what was
    picked instead of adding the body LODs around it.
    """
    path = os.path.abspath(filepath)
    folder = os.path.dirname(path)
    stem = os.path.basename(path)
    for ext in (".m3g", ".points", ".banim", ".xml", ".dashplanes"):
        if stem.lower().endswith(ext):
            stem = stem[: -len(ext)]
    if stem.endswith("_wing"):
        stem = stem[: -len("_wing")]
    lod = None
    for suf in _CAR_SUFFIXES:
        if stem.endswith(suf):
            stem = stem[: -len(suf)]
            if suf.startswith("_") and len(suf) == 2:
                lod = suf[1].upper()
            elif suf in ("_shared", "_int_a", "_int_b"):
                # a model of its own, not a body LOD: keep the name so the
                # caller can import that file and nothing else
                lod = suf[1:]
            break
    return folder, stem, lod


def import_vehicle_file(car_dir: str, car: str, *, lod: str = "A",
                        convert_axes: bool = True, textures: bool = True,
                        animate: bool = True, fps: float = 30.0,
                        import_anchors: bool = True,
                        height_adjust: float = 0.0,
                        rot_mode: str = "DELTA",
                        wheel_scale: float = 1.0,
                        wheel_uniform: bool = False,
                        wheel_size: str = "engine",
                        pos_scale: float = 1.0,
                        hinge: bool = False,
                        facing: str = "+Y",
                        mirror_x: bool = False,
                        delta_axes: tuple = (False, False, False),
                        pos_factor: float = 1.0,
                        rear_tyre_width: bool = True,
                        brakes: bool = True,
                        materials: str = "simple",
                        paint: int = -1,
                        material_depot: str = "",
                        separate_damage: bool = True,
                        separate_camera: bool = True,
                        parent_collection=None):
    """Import one car with its wheels mounted and its active-aero parts rigged.

    The body LOD is imported as-is (static panels are already in car space),
    the wheel meshes from ``_shared.m3g`` are instanced onto the
    ``POINT_WHEEL_*`` anchors as child objects of ``WHEEL_<corner>`` empties, and
    every ``*WING*`` part is parented to a pivot empty placed from the wing
    banim, with the banim rotation keyframed.

    **Order of assembly.**  The ``.points`` file is the authority on where
    things go, so the anchors are imported first and the wheels are then built
    *on* the anchor positions - a wheel pivot is never derived from anything
    else.  The ``.points`` file, the ``.m3g`` meshes and the wing ``.banim`` all
    share one datum (the model origin is on the ground; the hub heights are
    exactly a tyre radius above it), so nothing is re-based along Y.

    **Frame options.**  ``facing``/``mirror_x`` turn and/or mirror the whole
    assembly as one unit, exactly like the standalone .points/.banim importers:
    ``"+Y"`` keeps the game convention, ``"-Y"`` turns it 180 deg about Z for
    FBX-style models, ``mirror_x`` mirrors across X.  They act on a single root
    empty so the body, the wheels, the aero pivots and the anchors can never
    drift apart.  ``pos_factor`` scales the anchor/pivot positions only (the
    meshes keep their own size), which is the escape hatch for a car whose
    ``.points`` are in different units.  ``delta_axes`` makes the aero rotation
    channels relative to the first frame, per axis.

    ``wheel_size`` picks how the shared tyre template is scaled, which the game
    always does at load time: ``"engine"`` uses the car's tyre diameter from
    ``suspensionbehaviour`` (the factor the game itself computes), ``"ground"``
    puts the tyre exactly on the ground, and ``"none"`` leaves the template
    alone.  ``wheel_scale`` is a manual multiplier on top of that.

    ``wheel_uniform`` makes that scale apply to the wheel's width as well.  It is
    off by default because the shipped cars only grow the tyre taller: the
    template radius is the same on all 463 cars (spread 0.8 %) while the width is
    modelled per car, so stretching x would push the tyre into the suspension.
    Turn it on when fitting a *replacement* rim that has to stay round in every
    direction, which is the case for a custom wheel.

    ``rear_tyre_width`` widens the rear tyre to match the rear rim on the 62
    cars that ship a wider ``WHEEL_REAR`` but no ``TYRE_REAR`` of their own
    (the Pagani Huayra is the obvious one: its rear tyre would otherwise be
    23 % narrower than its rear rim).

    ``brakes`` mounts the brake disc and caliper as well.  The engine treats them
    exactly like the tyre and the rim - same radial ``scale``, same position from
    the ``POINT_WHEEL_*`` anchor - except that a caliper does **not** turn with
    the wheel: all four are modelled in their own corner already (the front-left
    caliper has ``+x``, the front-right one ``-x``), so turning them would put
    the caliper on the wrong side of the disc.

    ``parent_collection`` is where the per-LOD collection goes; the all-LODs
    importer uses it to keep one folder per LOD.

    ``separate_damage`` moves the wrecked twins of the body panels into a
    sub-collection ``<car>_LOD<X>_damaged``.  A body file ships both the
    pristine and the damaged version of every panel (``DOOR_LEFT`` and
    ``DOOR_LEFT_DAMAGE``) plus the smashed glass and lenses
    (``GLASS_BROKEN_REAR``, ``HEADLIGHT_LENS_BROKEN_A_LEFT``); kept together they
    z-fight and the car reads as dented.  They are imported, just filed away.

    ``separate_camera`` does the same for the bonnet-camera shell
    (``*_BONNETCAM_*``) and the emissive glow quads (``*_LIT_*``) that
    ``_shared.m3g`` carries: they are what the game renders from the nose
    camera, and inside the real body they only z-fight.  They land in
    ``<car>_LOD<X>_camera``.

    ``materials`` picks how the meshes are shaded.  ``"simple"`` is the old
    behaviour: a colour hashed from the material name plus the tag's atlas.
    ``"game"`` reads the game's own data instead - the livery table says which
    material each mesh has under each paint scheme, ``materials.bin`` says what
    that material's shader is, and the shader's specular power and fresnel ramp
    become the Principled roughness and metallic.  Every mesh keeps **one**
    material slot holding one shading preset per paint scheme, so switching
    paint is a re-link inside that material (``rr3.switch_paint``) and never a
    change of slot count.  ``paint`` is the preset that starts active
    (``-1`` = the first).
    """
    plan = partslib.build_plan(car_dir, car, lod)
    if not plan.body_file:
        raise RuntimeError(f"no LOD {lod} body found for {car} in {car_dir}")

    # ``_shared.m3g``, ``_int_a.m3g`` and ``_int_b.m3g`` are complete models in
    # their own right (the bonnet-cam shell and the two cockpit shells), each
    # carrying its own level letters inside.  Imported on their own they get the
    # file as it is: no wheels (the shared file's wheels are what a body LOD
    # mounts), no aero rigging, no .points anchors - adding those would assemble
    # a car around a model that is not a car.
    standalone = not _is_body_lod(lod)
    if standalone:
        plan.wheels = partslib.WheelSet()
        plan.wheel_mounts = []
        plan.aero_parts = []
        plan.steering = None
        # a cockpit has anchors of its own (``<car>_int.points``); the car's own
        # ``<car>.points`` describes the outside of the car and means nothing here
        plan.points_file = None
        if lod.startswith("int"):
            int_pts = os.path.join(car_dir, f"{car}_int.points")
            if os.path.exists(int_pts):
                plan.points_file = int_pts

    coll = _collection(f"{car}_LOD{lod}" if not standalone else f"{car}_{lod}",
                       parent_collection)
    images = _load_atlas_images(car_dir) if textures else None
    cm = _axis_matrix(convert_axes)
    # vertical trim: model +Y, compensates the .points datum (about 1 cm)
    dy_bl = cm @ Vector((0.0, height_adjust, 0.0))

    # The shared tyre mesh is one template for the whole game; the engine
    # stretches it radially from the car's data, so a car imported without it
    # looks like every other car.  See rr3lib/wheelsize.py.  A pre-assembled LOD
    # (LOD F) is already at the real size, so there is nothing to fit there.
    wheel_fit = None
    if (not standalone and wheel_size != "none" and plan.shared_file
            and not plan.wheels.pre_assembled):
        try:
            wheel_fit = wheelsizelib.plan(car_dir, car, lod=lod, mode=wheel_size,
                                          depot=wheelsizelib.depot_for(car_dir))
        except Exception as exc:  # noqa: BLE001 - never fail the import for this
            plan.warnings.append(f"wheel size: {exc}")

    body = import_m3g_file(plan.body_file, convert_axes=convert_axes,
                           import_anchors=False, textures=textures,
                           collection=coll)
    body_objs = {md.name: ob for md, ob in zip(body["meshes"], body["objects"])}

    # Wrecked panels (``*_DAMAGE``) and smashed glass / lenses (``*_BROKEN``)
    # ship in the same body file as the pristine ones.  They go into a
    # sub-collection of their own, so the car reads as intact out of the box and
    # the damaged twins are still there to switch on when they are wanted.
    # ``shared``/``int_a``/``int_b`` are whole models, not car bodies, so the
    # split makes no sense there and would only add empty folders.
    damage_coll = None
    if separate_damage and not standalone:
        damage_coll = _collection(f"{car}_LOD{lod}_damaged", coll)

    # The bonnet-camera shell and the emissive glow quads from ``_shared.m3g``
    # are not part of the car the player sees from outside: the camera shell is a
    # second body inside the first (it z-fights with the bonnet) and the glow
    # quads are camera-facing sprites.  Both go into a folder of their own.
    # Importing ``shared`` on its own is a different case: that file *is* the
    # bonnet-cam shell, so it is imported whole and split no further.
    camera_coll = None
    if separate_camera and not standalone:
        camera_coll = _collection(f"{car}_LOD{lod}_camera", coll)

    for ob in body["objects"]:
        for c in list(ob.users_collection):
            c.objects.unlink(ob)
        mesh_name = ob.get("rr3_mesh_name") or ""
        target = coll
        if damage_coll is not None and _is_damaged(mesh_name):
            target = damage_coll
            ob["rr3_damaged"] = True
        elif camera_coll is not None and _is_camera_mesh(mesh_name):
            target = camera_coll
            ob["rr3_camera"] = True
        target.objects.link(ob)

    # One root empty carries facing/mirror for the whole assembly.  Applying it
    # per object would turn every part about its own origin instead of turning
    # the car, and the wheels would leave their arches.
    root = None
    if facing != "+Y" or mirror_x:
        root = bpy.data.objects.new(f"{car}_ROOT", None)
        root.empty_display_type = "PLAIN_AXES"
        root.empty_display_size = 0.5
        root.rotation_mode = "XYZ"
        if facing == "-Y":
            root.rotation_euler = (0.0, 0.0, math.pi)
        if mirror_x:
            root.scale = (-1.0, 1.0, 1.0)
        root["rr3_facing"] = facing
        root["rr3_mirror_x"] = bool(mirror_x)
        coll.objects.link(root)

    def attach(ob):
        """Parent to the frame root, if there is one."""
        if root is not None:
            ob.parent = root
            ob.matrix_parent_inverse = Matrix.Identity(4)
        return ob

    created = []
    wheel_objects = []

    for ob in body["objects"]:
        attach(ob)

    # ---------------------------------------------------------------- anchors
    # Imported BEFORE the wheels, because the wheel pivots are taken from these
    # very positions - that is the whole point of doing it in this order.  The
    # anchors go in model space (where the body mesh already is), not in the
    # FBX convention of the standalone importer; facing/mirror is carried by the
    # root empty for the whole assembly, so applying it here too would mirror
    # the anchors away from the body.
    anchors = None
    if import_anchors and plan.points_file:
        pf, anchor_objs = _import_points(plan.points_file, 1.0, convert_axes, coll,
                                         model_space=True)
        for ob in anchor_objs:
            ob.name = "ANCHOR_" + ob.name
            ob.location = (ob.location * (pos_scale * pos_factor)) + dy_bl
            attach(ob)
        anchors = (pf, anchor_objs)

    if plan.shared_file and plan.wheels.front_wheel and plan.wheels.pre_assembled:
        # This LOD's "wheel" mesh is the whole car's four wheels, already
        # assembled in car space and already at the real size (LOD F on every
        # car).  Scaling it, turning it or moving it onto a .points anchor would
        # apply the assembly a second time, so it goes in at the world origin
        # with the identity transform - which is exactly what the game does.
        shared = m3glib.M3G(plan.shared_file)
        by_name = {md.name: md for md in geometrylib.all_meshes(shared)}
        wheel_root = bpy.data.objects.new(f"WHEEL_LOD{lod}_ASSEMBLED", None)
        wheel_root.empty_display_type = "PLAIN_AXES"
        wheel_root.empty_display_size = 0.3
        wheel_root.location = (0.0, 0.0, 0.0)
        wheel_root["rr3_pre_assembled"] = True
        attach(wheel_root)
        coll.objects.link(wheel_root)
        created.append(wheel_root)
        for mesh_name in (plan.wheels.front_wheel, plan.wheels.front_tyre):
            md = by_name.get(mesh_name)
            if md is None:
                continue
            ob = _build_mesh_object(md, 1.0, convert_axes, coll,
                                    (0.0, 0.0, 0.0), images)
            ob.parent = wheel_root
            ob.matrix_parent_inverse = Matrix.Identity(4)
            ob["rr3_wheel"] = mesh_name
            ob["rr3_pre_assembled"] = True
            wheel_objects.append(ob)
        print(f"{car} LOD {lod}: wheels are pre-assembled in the shared file "
              f"({len(wheel_objects)} mesh(es) at the origin, not rescaled)")
    elif plan.shared_file and plan.wheels.front_wheel:
        shared = m3glib.M3G(plan.shared_file)
        by_name = {md.name: md for md in geometrylib.all_meshes(shared)}
        anchor_loc = {}
        if anchors is not None:
            for ob in anchors[1]:
                anchor_loc[ob.name] = Vector(ob.location)
        # Rear tyre that is really the front one, on a car whose rear rim is
        # wider (Pagani Huayra and 61 others): widen the tyre to the rim ratio,
        # otherwise the tyre sits inside its own rim.  Measured over the 87 cars
        # that do ship a TYRE_REAR, TYRE_REAR/TYRE tracks WHEEL_REAR/WHEEL to
        # within 0.6 % (median), so the rim ratio is the right proxy.
        front_w = _mesh_width(by_name.get(plan.wheels.front_wheel))
        rear_w = _mesh_width(by_name.get(plan.wheels.rear_wheel))

        for mount in plan.wheel_mounts:
            pivot = bpy.data.objects.new(f"WHEEL_{mount.corner}", None)
            pivot.empty_display_type = "ARROWS"
            pivot.empty_display_size = 0.15
            # The pivot comes from the anchor that was imported a few lines up,
            # so it inherits facing/mirror/pos_scale for free and can never
            # drift away from the .points file.
            loc = anchor_loc.get("ANCHOR_" + mount.name)
            if loc is None:
                # no anchors imported: rebuild the same position from the raw
                # record, through the same model-space chain
                loc = _point_model_location(mount.raw, convert_axes,
                                            pos_scale * pos_factor) + dy_bl
            pivot.location = loc
            pivot["rr3_corner"] = mount.corner
            pivot["rr3_steers"] = bool(mount.steer)
            pivot["rr3_point"] = mount.name
            attach(pivot)
            coll.objects.link(pivot)
            created.append(pivot)

            rear = not mount.steer
            wheel_name = plan.wheels.rear_wheel if rear else plan.wheels.front_wheel
            tyre_name = plan.wheels.rear_tyre if rear else plan.wheels.front_tyre
            k = wheel_fit.factor(rear) if wheel_fit is not None else 1.0
            k *= wheel_scale
            # Only stretch the tyre when the car has no rear tyre mesh of its
            # own; when it does, that mesh is already the right width.
            widen = 1.0
            if (rear and rear_tyre_width and not plan.wheels.rear_tyre_own
                    and front_w > 1e-6 and rear_w is not None and rear_w > 1e-6):
                widen = rear_w / front_w
                if not (0.6 <= widen <= 1.6):
                    widen = 1.0
            # (mesh name, is the tyre, does it turn with the wheel)
            # The disc turns with the wheel; the caliper does not - all four are
            # modelled in their own corner (front-left caliper on +x, front-right
            # on -x), so turning them would put them behind the wrong face of
            # the disc.  Everything gets the same radial scale, because the
            # engine sizes the whole corner from the tyre.
            parts = [(wheel_name, False, True), (tyre_name, True, True)]
            if brakes:
                parts.append((plan.wheels.rotor_rear if rear else plan.wheels.rotor,
                              False, True))
                parts.append((plan.wheels.calipers.get(mount.corner), False, False))
            for mesh_name, is_tyre, turns in parts:
                md = by_name.get(mesh_name)
                if md is None:
                    continue
                mat = None
                w = widen if is_tyre else 1.0
                turn = turns and mount.corner.endswith("R")
                if w != 1.0 or turn:
                    mat = Matrix.Identity(4)
                    if w != 1.0:
                        mat = Matrix.Scale(w, 4, (1.0, 0.0, 0.0)) @ mat
                    if turn:
                        # Half a turn about the wheel's own vertical axis, not a
                        # mirror: a mirrored rim reads its lettering backwards.
                        # In model space that is (x, y, z) -> (-x, y, -z).
                        mat = Matrix.Rotation(math.pi, 4, "Y") @ mat
                # No offset: the shared mesh is already modelled in the wheel's
                # own frame, with x = 0 on its outer face and y/z centred, and
                # that outer face is exactly where the point sits.
                ob = _build_mesh_object(md, 1.0, convert_axes, coll,
                                        (0.0, 0.0, 0.0), images, matrix=mat)
                ob.name = f"{mount.corner}_{mesh_name}"
                ob.parent = pivot
                ob.matrix_parent_inverse = Matrix.Identity(4)
                if abs(k - 1.0) > 1e-6:
                    # Radial stretch by default: the tyre grows taller, never
                    # wider - the width is already modelled per car, and widening
                    # it would push the tyre into the suspension.  Blender's local
                    # y/z are the wheel's round plane (model y/z).
                    ob.scale = (k, k, k) if wheel_uniform else (1.0, k, k)
                ob["rr3_wheel"] = mesh_name
                ob["rr3_wheel_scale"] = k
                if not turns:
                    ob["rr3_brake_fixed"] = True
                if w != 1.0:
                    ob["rr3_tyre_widen"] = w
                wheel_objects.append(ob)

    if plan.steering is not None:
        steer_piv = bpy.data.objects.new("STEERING_WHEEL", None)
        steer_piv.empty_display_type = "SINGLE_ARROW"
        steer_piv.empty_display_size = 0.12
        steer_piv.location = cm @ (Vector(plan.steering) * (pos_scale * pos_factor)) + dy_bl
        steer_piv["rr3_point"] = partslib.STEERING_ANCHOR
        attach(steer_piv)
        coll.objects.link(steer_piv)
        created.append(steer_piv)
        steer_bits = []
        for mesh_name, ob in body_objs.items():
            if "STEERING_WHEEL" in mesh_name.upper():
                ob.parent = steer_piv
                ob.matrix_parent_inverse = Matrix.Identity(4)
                steer_bits.append(mesh_name)
        if steer_bits:
            print("steering wheel at %s m -> %d mesh(es)" % (
                tuple(round(v, 3) for v in plan.steering), len(steer_bits)))

    aero_objects = []
    # a KD-tree over the body shell lets each flap find the edge that touches the
    # body; that edge is the hinge it really rotates about (rotating about the
    # part's own origin makes the flap swing off the body).
    body_kd = None
    if hinge:
        wing_names = {n for p in plan.aero_parts for n in p.mesh_names}
        pts = []
        for mesh_name, ob in body_objs.items():
            if mesh_name in wing_names:
                continue
            for v in ob.data.vertices:
                pts.append(cm @ v.co)
        if pts:
            body_kd = mathutils.kdtree.KDTree(len(pts))
            for i, p in enumerate(pts):
                body_kd.insert(p, i)
            body_kd.balance()

    for part in plan.aero_parts:
        piv = bpy.data.objects.new(f"AERO_{part.index}_{_short_part(part)}", None)
        piv.empty_display_type = "CUBE"
        piv.empty_display_size = 0.1
        piv.location = cm @ (Vector(part.pivot) * (pos_scale * pos_factor)) + dy_bl
        piv["rr3_track"] = part.track
        piv["rr3_part"] = part.part_name or ""
        attach(piv)
        coll.objects.link(piv)
        created.append(piv)
        for mesh_name in part.mesh_names:
            ob = body_objs.get(mesh_name)
            if ob is None:
                continue
            ob.parent = piv
            ob.matrix_parent_inverse = Matrix.Identity(4)
            aero_objects.append(ob)

        # hinge point in the mesh's own coordinates: the centroid of the 10% of
        # vertices that sit closest to the body shell at the rest pose
        hinge_bl = None
        rest_bl = None
        if body_kd is not None and part.mesh_names:
            _r = partslib.matmul(
                partslib.matmul(partslib.ANIM_TO_MODEL,
                                partslib.euler_xyz(*part.rest_rotation)),
                partslib.transpose(partslib.ANIM_TO_MODEL))
            rest_bl = cm @ Matrix(_r) @ cm.transposed()
            p_bl = cm @ Vector(part.pivot) + dy_bl
            vs = []
            for mesh_name in part.mesh_names:
                ob = body_objs.get(mesh_name)
                if ob is None:
                    continue
                vs.extend(Vector(v.co) for v in ob.data.vertices)
            if vs:
                scored = []
                for k, co in enumerate(vs):
                    w = p_bl + rest_bl @ (cm @ co)
                    _hit, _idx, d = body_kd.find(w)
                    scored.append((d, k))
                scored.sort()
                take = max(8, len(scored) // 10)
                acc = Vector((0.0, 0.0, 0.0))
                for _d, k in scored[:take]:
                    acc += vs[k]
                hinge_bl = cm @ (acc / take)

        def apply_pose(pos_model, rot_mat_anim, frame_no=None):
            r_model = partslib.matmul(
                partslib.matmul(partslib.ANIM_TO_MODEL, rot_mat_anim),
                partslib.transpose(partslib.ANIM_TO_MODEL))
            rot_bl = cm @ Matrix(r_model) @ cm.transposed()
            # the animation is authored in the same space as the .points file,
            # so it takes the same position scale
            loc_bl = cm @ (Vector(pos_model) * (pos_scale * pos_factor)) + dy_bl
            if hinge_bl is not None:
                # keep the hinge edge fixed: L = P + R0*h - R*h
                loc_bl = loc_bl + rest_bl @ hinge_bl - rot_bl @ hinge_bl
            piv.location = loc_bl
            piv.rotation_euler = rot_bl.to_euler("XYZ")
            if frame_no is not None:
                piv.keyframe_insert("location", frame=frame_no)
                piv.keyframe_insert("rotation_euler", frame=frame_no)

        # every channel of a wing track has its own key times, so parts.frames()
        # returns the union of them, with the pivot position and the rotation
        # already sampled at every one of those times
        samples = part.frames() or [(0.0, part.pivot, part.rest_rotation)]
        r_first = partslib.euler_xyz(*samples[0][2])
        if any(delta_axes):
            # per-axis delta: subtract the first frame on the axes the user
            # ticked, leave the others as stored.  This is the fine control the
            # standalone .banim importer offers; 'Rotation reading' is all-or-
            # nothing, this is per channel.
            base = samples[0][2]
            samples = [
                (t, p, tuple((r[i] - base[i]) if delta_axes[i] else r[i]
                             for i in range(3)))
                for t, p, r in samples
            ]
            samples = [(t, p, partslib.euler_xyz(*r)) for t, p, r in samples]
            rest_bl = Matrix.Identity(3)
        elif rot_mode == "DELTA":
            # interpret the stored angles as a delta from the rest pose: the
            # first frame becomes zero rotation, only the change is animated
            r_inv = partslib.transpose(r_first)
            samples = [(t, p, partslib.matmul(r_inv, partslib.euler_xyz(*r)))
                       for t, p, r in samples]
            rest_bl = Matrix.Identity(3)
        else:
            samples = [(t, p, partslib.euler_xyz(*r)) for t, p, r in samples]
        if animate:
            for t_ms, pos, rot in samples:
                apply_pose(pos, rot, 1 + int(round(t_ms / 1000.0 * fps)))
            _make_linear(piv)
        else:
            apply_pose(samples[0][1], samples[0][2])

    scene = bpy.context.scene
    if animate:
        scene.render.fps = max(1, int(round(fps)))
        scene.frame_start = 1
        dur = max((p.duration_ms for p in plan.aero_parts), default=0.0)
        scene.frame_end = max(2, 1 + int(round(dur / 1000.0 * fps)))

    # Game materials last, so every object (body, wheels, brakes) is already in
    # the collection and can take its per-paint slots in one pass.
    game_materials = None
    if materials == "game":
        every = [ob for ob in _all_objects(coll) if ob.type == "MESH"]
        try:
            game_materials = _apply_game_materials(every, car_dir, car, paint,
                                                   depot=material_depot or None)
        except Exception as exc:  # noqa: BLE001 - never fail the import for this
            msg = f"game materials: {exc}"
            plan.warnings.append(msg)
            print(f"[rr3] {car}: {msg}")
        if game_materials is None and not any(
                "game materials" in w for w in plan.warnings):
            msg = ("game materials: the depot's materials/materials.bin was not "
                   f"found above {car_dir}, so the placeholder materials were "
                   "kept - set 'Depot' to the .depot folder to use the game's own")
            plan.warnings.append(msg)
            print(f"[rr3] {car}: {msg}")
        if game_materials is not None:
            plan.warnings.extend(game_materials.warnings)

    return {
        "plan": plan,
        "body": body,
        "collection": coll,
        "wheels": wheel_objects,
        "empties": created,
        "aero": aero_objects,
        "anchors": anchors,
        "wheel_fit": wheel_fit,
        "game_materials": game_materials,
    }


# --------------------------------------------------------------------------
# the driver
# --------------------------------------------------------------------------
#: The fifteen parts carry the material name ``driver`` straight from the .m3g's
#: own material list - ``materials.bin`` has no material of that name and the
#: livery table has no ``driver`` slot - so the texture is wired by name here.
DRIVER_MATERIAL = "driver"


def _driver_material(image):
    """Material for the driver: the skin atlas wired to Base Color.

    The ``.m3g``'s own material list names the fifteen parts' material ``driver``,
    so :func:`_build_mesh_object` has already created a material of that name (a
    hashed colour, no texture) by the time this runs.  That is why the function
    cannot assume it is building a fresh material: it has to *repair* whatever is
    already there.  A leftover ``driver`` material may have no texture node at
    all, a texture node with an image that was never linked, or a BSDF under a
    different name - every one of those looks like "the texture is not connected"
    in the node editor.

    So the check is on the finished state: if a texture node already holds the
    right image *and* is linked to a Principled BSDF's Base Color, keep the tree
    (a second import is a no-op, and any tweak the user made survives).  Anything
    else rebuilds the tree from scratch, which guarantees the skin is wired.
    """
    mat = bpy.data.materials.get(DRIVER_MATERIAL)
    if mat is None:
        mat = bpy.data.materials.new(DRIVER_MATERIAL)
    if not mat.use_nodes or mat.node_tree is None:
        mat.use_nodes = True
    nt = mat.node_tree

    def wired_ok():
        for tex in (n for n in nt.nodes if n.type == "TEX_IMAGE"):
            if image is not None and tex.image != image:
                continue
            for link in tex.outputs["Color"].links:
                if (link.to_node.type == "BSDF_PRINCIPLED"
                        and link.to_socket.name == "Base Color"):
                    return True
        return False

    if not wired_ok():
        nt.nodes.clear()
        out = nt.nodes.new("ShaderNodeOutputMaterial")
        out.location = (320.0, 0.0)
        bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
        bsdf.location = (0.0, 0.0)
        nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
        tex = nt.nodes.new("ShaderNodeTexImage")
        tex.name = "driver_skin"
        tex.label = "driver skin"
        tex.location = (-340.0, 0.0)
        tex.extension = "REPEAT"
        if image is not None:
            tex.image = image
            nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
        else:
            bsdf.inputs["Base Color"].default_value = (0.55, 0.42, 0.36, 1.0)
        _set_input(bsdf, "Roughness", 0.6)
        _set_input(bsdf, "Metallic", 0.0)
        _set_input(bsdf, "Specular IOR Level", 0.35)

    mat.diffuse_color = (0.62, 0.45, 0.38, 1.0)
    mat["rr3_material"] = DRIVER_MATERIAL
    mat["rr3_texture"] = image.name if image is not None else ""
    return mat


def import_driver(depot: str, *, lod: str = "a", car: str = "", skin: str = "",
                  fps: float = 90.0, max_frames: int = 0, placement: str = "NODE",
                  convert_axes: bool = True, flip_driver: bool = False,
                  with_root: bool = True,
                  banim_file: str = "", car_record: str = "",
                  textures: bool = True, parent_collection=None):
    """Import the game's driver, posed and animated, under one root empty.

    The parts are modelled round their own origins and the ``.banim`` has one
    node per part in name order (``00_helmet`` first), so the animation is bound
    by index, not by a keyframe table.  ``driver_lod_c`` and ``_d`` are a single
    mesh already sitting in the seat: they are imported as they are, without a
    pose.

    The rig is left facing the way the file authored it, which is the car's own
    forward direction - the parts keep the transforms the file gave them and the
    root empty is added unrotated.  An earlier version turned that root 180 deg
    about Z to "face the car's nose", which put the figure in backwards: the pose
    already faces that way.  The root stays because it is what the driver is
    moved and rotated into place with.

    Which animation is used, most specific first:

    * ``banim_file`` - a ``.banim`` the caller picked by hand;
    * ``car_record`` - the car's ``.bin.nct`` data record, whose own field names
      the animation (this is the game's answer, not a guess);
    * otherwise the car folder name is matched against ``driver_<x>.banim``, and
      ``driver.banim`` is the fallback.

    ``with_root`` adds ``<car>_DRIVER_ROOT`` and parents every part to it, so the
    whole figure can be moved into a car with one transform.

    ``fps`` is how many poses a second are keyframed, and it defaults to 90 rather
    than 30 because that is what the shipped animations actually carry: the keys
    land on 11, 10 and 12 ms in a repeating cycle, about 91 a second.  Sampling at
    30 keeps one in three, which the export then writes back out, so the motion
    comes out coarser than the game's.  At 90 the same driver exports 16,110 keys
    against the source's 16,290.
    """
    matched = None
    if banim_file:
        banim_path = banim_file if os.path.isfile(banim_file) else None
        if banim_path is None:
            raise RuntimeError(f"no such .banim file: {banim_file}")
    elif car_record:
        named = drvlib.banim_in_record(car_record)
        if named:
            candidate = os.path.join(drvlib.driver_dir(depot) or "", named)
            banim_path = candidate if os.path.isfile(candidate) else None
            matched = named[len(drvlib.SKIN_PREFIX):-len(drvlib.BANIM_SUFFIX)]
        else:
            banim_path = None
        if banim_path is None:
            # the record said nothing usable: fall back to the name match
            banim_path, matched = drvlib.banim_for(depot, car or None)
    else:
        banim_path, matched = drvlib.banim_for(depot, car or None)

    # The animation is settled first because it names the mesh: a car with a
    # special pose ships its own driver_lod_c_<x>.m3g under the same <x>.
    model = drvlib.model_for(depot, lod, car or None, banim_stem=matched or "")
    if model is None:
        raise RuntimeError(
            f"no driver model for LOD {lod} in {depot}; the depot's 'driver' "
            "folder holds driver_lod_a..d.m3g")

    coll = _collection(f"{car}_DRIVER" if car else "DRIVER", parent_collection)

    res = import_m3g_file(model, convert_axes=convert_axes, import_anchors=False,
                          textures=textures, collection=coll)
    objects = {}
    mesh_data = {}
    for md, ob in zip(res["meshes"], res["objects"]):
        objects[md.name] = ob
        mesh_data[md.name] = md
    inner = res["collection"]
    for ob in list(inner.objects):
        inner.objects.unlink(ob)
        coll.objects.link(ob)
    if inner is not coll:
        bpy.data.collections.remove(inner)

    posed = 0
    b = None
    if banim_path and os.path.isfile(banim_path):
        b = banimlib.load(banim_path)
        # only the fifteen-part rig is posed; _c/_d is one mesh already seated
        parts = sum(1 for n in objects if n[:2].isdigit() and n[2:3] == "_")
        if parts * 2 >= b.num_tracks:
            posed = _pose_parts(b, objects, mesh_data, coll, fps=fps,
                                max_frames=max_frames, placement=placement,
                                convert_axes=convert_axes,
                                flip_driver=flip_driver)

    # the driver's own atlas: vehicles/common/driver.dxt.dds.z (nine skins ship)
    image = None
    if textures:
        path = drvlib.texture_for(depot, skin)
        if path:
            try:
                image = _image_for_path(path, {})
            except Exception as exc:  # noqa: BLE001 - a missing skin is not fatal
                print(f"[rr3] driver: {os.path.basename(path)}: {exc}")
    mat = _driver_material(image)
    for ob in objects.values():
        if ob.type != "MESH":
            continue
        me = ob.data
        me.materials.clear()
        me.materials.append(mat)
        # a slot linked to the object instead of the mesh shows whatever the
        # object overrides with - which is nothing - so the skin would be there
        # in the node tree but invisible on the figure
        for slot in ob.material_slots:
            slot.link = "DATA"
        for poly in me.polygons:
            poly.material_index = 0
        ob["rr3_material"] = DRIVER_MATERIAL
        ob["rr3_texture"] = image.name if image is not None else ""

    root = None
    if with_root:
        root = bpy.data.objects.new(f"{car}_DRIVER_ROOT" if car else "DRIVER_ROOT",
                                    None)
        root.empty_display_type = "PLAIN_AXES"
        root.empty_display_size = 0.3
        root.rotation_mode = "XYZ"
        root["rr3_driver_root"] = True
        coll.objects.link(root)
        for ob in objects.values():
            if ob.parent is None:
                ob.parent = root
                ob.matrix_parent_inverse = Matrix.Identity(4)

    return {
        "model": model,
        "banim": banim_path,
        "banim_matched": matched,
        "objects": objects,
        "root": root,
        "collection": coll,
        "posed": posed,
        "frames": len(riglib.frames(b, fps, max_frames, None)) if b is not None else 0,
    }


def _short_part(part) -> str:
    name = part.part_name or f"part{part.index}"
    for prefix in ("LOD_A_", "LOD_B_", "LOD_C_", "LOD_D_"):
        if name.startswith(prefix):
            name = name[len(prefix):]
    return name


# --------------------------------------------------------------------------
# operators
# --------------------------------------------------------------------------
class IMPORT_OT_rr3_m3g(Operator, ImportHelper):
    """Import a Real Racing 3 .m3g model"""

    bl_idname = "import_scene.rr3_m3g"
    bl_label = "Import RR3 Model (.m3g)"
    bl_options = {"REGISTER", "UNDO"}

    filename_ext = ".m3g"
    filter_glob: StringProperty(default="*.m3g", options={"HIDDEN"})

    scale: FloatProperty(
        name="Scale", description="Uniform scale applied to the model", default=1.0, min=0.0001
    )
    convert_axes: BoolProperty(
        name="Convert Y-up to Z-up", description="Rotate the RR3 Y-up model into Blender Z-up", default=True
    )
    import_anchors: BoolProperty(
        name="Import .points anchors", description="Import the sibling .points file as empty objects", default=True
    )
    spread_parts: BoolProperty(
        name="Spread bone-local parts", description="Lay parts out on a row (needed for the driver, whose parts are rig-local)", default=False
    )
    spread_step: FloatProperty(name="Spacing", default=0.6, min=0.01)
    textures: BoolProperty(
        name="Load .dxt.dds.z atlases",
        description="Decode the <car>_<tag>.dxt.dds.z atlases next to the model and bind them to the _mm_<tag> materials",
        default=True,
    )

    def execute(self, context):
        try:
            result = import_m3g_file(
                self.filepath,
                scale=self.scale,
                convert_axes=self.convert_axes,
                import_anchors=self.import_anchors,
                spread_parts=self.spread_parts,
                spread_step=self.spread_step,
                textures=self.textures,
            )
        except Exception as exc:  # noqa: BLE001
            self.report({"ERROR"}, f"RR3 import failed: {exc}")
            return {"CANCELLED"}

        verts = sum(len(md.positions) for md in result["meshes"])
        tris = sum(len(md.triangles) for md in result["meshes"])
        msg = f"Imported {len(result['objects'])} meshes, {verts} verts, {tris} tris"
        if result["anchors"]:
            msg += f", {len(result['anchors'][1])} anchors"
        self.report({"INFO"}, msg)
        if not self.spread_parts and _looks_bone_local(result["meshes"]):
            self.report(
                {"WARNING"},
                "This model looks like a rig-local (driver) mesh set: parts overlap at the "
                "origin. Re-import with 'Spread bone-local parts' to inspect them.",
            )
        return {"FINISHED"}


class IMPORT_OT_rr3_m3g_raw(Operator, ImportHelper):
    """Import any Real Racing 3 .m3g and nothing else

    No car context, no anchors, no atlas guessing: just the meshes with their
    game material names.  It also reports the bounding box of every mesh, which
    is what makes it useful for checking the wheel scaling by hand - import a
    shipped ``_shared.m3g`` and a candidate model side by side and compare the
    printed tyre radius and width instead of trusting the assembler.
    """

    bl_idname = "import_scene.rr3_m3g_raw"
    bl_label = "Import Generic Model (.m3g)"
    bl_options = {"REGISTER", "UNDO"}

    filename_ext = ".m3g"
    filter_glob: StringProperty(default="*.m3g", options={"HIDDEN"})

    scale: FloatProperty(
        name="Scale", description="Uniform scale applied to the model", default=1.0, min=0.0001
    )
    convert_axes: BoolProperty(
        name="Convert Y-up to Z-up",
        description="Rotate the RR3 Y-up model into Blender Z-up.  Turn it off to "
                    "see the raw file coordinates, which is what the game's own "
                    "numbers are in.",
        default=True,
    )
    report_sizes: BoolProperty(
        name="Print mesh sizes",
        description="Write the bounding box of every mesh to the System Console, "
                    "in metres.  A tyre should come out at a radius of about "
                    "0.299 m.",
        default=True,
    )

    def execute(self, context):
        try:
            result = import_m3g_file(
                self.filepath,
                scale=self.scale,
                convert_axes=self.convert_axes,
                import_anchors=False,
                spread_parts=False,
                textures=False,
            )
        except Exception as exc:  # noqa: BLE001
            self.report({"ERROR"}, f"RR3 import failed: {exc}")
            return {"CANCELLED"}

        meshes = result["meshes"]
        verts = sum(len(md.positions) for md in meshes)
        tris = sum(len(md.triangles) for md in meshes)
        self.report({"INFO"},
                    f"Imported {len(result['objects'])} meshes, {verts} verts, {tris} tris")
        if self.report_sizes:
            print(f"[rr3] {os.path.basename(self.filepath)}: "
                  f"{len(meshes)} meshes, scale {self.scale}")
            for line in _mesh_size_lines(meshes, self.scale):
                print(line)
        return {"FINISHED"}


def _mesh_size_lines(meshes, scale: float = 1.0) -> list:
    """One line per mesh: its extent in metres, and the radius of a wheel-ish one.

    The extents are the model-space ones the game stores, so they are directly
    comparable with the numbers in the depot: a shipped tyre is 0.299 m in
    radius and about 0.25 m wide, whatever its car.
    """
    lines = []
    for md in meshes:
        if not md.positions:
            continue
        xs = [p[0] for p in md.positions]
        ys = [p[1] for p in md.positions]
        zs = [p[2] for p in md.positions]
        dx, dy, dz = (max(xs) - min(xs)) * scale, (max(ys) - min(ys)) * scale, (max(zs) - min(zs)) * scale
        # A wheel's round plane is model y/z and its width is model x, so the
        # radius is half the larger of the two round extents.
        radius = max(dy, dz) / 2.0
        lines.append(f"    {md.name:44s} x {dx:7.4f}  y {dy:7.4f}  z {dz:7.4f}"
                     f"   radius {radius:7.4f}")
    return lines


# --------------------------------------------------------------------------
# .banim -> empty objects (animation only, no meshes)
# --------------------------------------------------------------------------
def banim_series(filepath, *, fps: float = 30.0, max_frames: int = 0,
                 delta_axes: tuple = (False, False, False),
                 pos_factor: float = 1.0):
    """Read a ``.banim`` into plain, engine-space series.

    Returns ``(banim, [(label, [(t_ms, pos_model_m, rot_model_rad), ...]), ...])``
    where ``pos_model_m`` is already in **model space metres** (x right, y up,
    z forward, i.e. the space the meshes live in) and the rotation is the Euler
    angle in the same basis.

    The position unit is the same for every file kind: 1/65536 m.  MonkeyTool
    divides every banim's translation channels by 65536 in ``nodeMatrix``, and
    the driver's own geometry confirms it (at 1/65536 the fifteen parts assemble
    into a 1.09 m seated figure whose hands land on the steering wheel's rim).
    ``driver.banim`` was long believed to use 1/32768; that was wrong.

    ``rot_mode="DELTA"`` subtracts the first frame, which is what the game does:
    the t=0 angle is an authoring offset, the mesh is modelled at rest.
    """
    b = banimlib.load(filepath)
    # every .banim stores its translation in 1/65536 m (MonkeyTool divides every
    # file's channels by 65536 in nodeMatrix; the driver's own geometry confirms
    # it - at 1/65536 he is 1.09 m tall with his hands on the wheel rim).
    pos_scale = riglib.POS_SCALE * pos_factor
    times = riglib.frame_times(b, fps, max_frames)

    anim_to_model = Matrix(partslib.ANIM_TO_MODEL)
    out = []
    # driver names are nicer than track00/track01
    names = riglib.track_names(b, None)
    for ti in range(b.num_tracks):
        rows = []
        tr = b.tracks[ti]
        for t in times:
            raw = riglib.sample_track(b, tr, t)
            p_anim = tuple(float(raw[c]) * pos_scale for c in range(3))
            p_model = anim_to_model @ Vector(p_anim)
            rot = tuple(float(raw[3 + c]) * riglib.ROT_SCALE for c in range(3))
            rows.append((t, p_model, rot))
        if not rows:
            rows = [(0.0, Vector((0.0, 0.0, 0.0)), (0.0, 0.0, 0.0))]
        r0 = rows[0][2]
        if any(delta_axes):
            rows = [(t, p, tuple(r[k] - (r0[k] if delta_axes[k] else 0.0)
                                 for k in range(3)))
                    for t, p, r in rows]
        label = names[ti] if ti < len(names) else f"track{ti:02d}"
        out.append((label, rows))
    return b, out


def import_banim_clips(filepath: str, *, xml_path: str = "",
                       fps: float = 30.0, frame_ms: float = animxmllib.FRAME_MS,
                       delta_axes: tuple = (False, False, False),
                       convert_axes: bool = True, empty_size: float = 0.08,
                       pos_factor: float = 1.0, facing: str = "+Y",
                       mirror_x: bool = False, flip_mode: str = "ROOT",
                       nla: bool = True):
    """Import a ``.banim`` and split it into the named clips of its XML.

    One Action **per clip and per track**, plus one NLA track named after the
    clip on every empty, so the glTF exporter (Animation mode ``NLA Tracks``)
    writes one animation per clip instead of one long timeline.

    Frame numbers follow the banim's own 33 ms grid (``1 + t / 33``), which is
    also the XML's frame numbering, so ``wing_up 0 -> 45`` lands on frames
    1 -> 46 exactly as the game plays it.
    """
    # the empties are built by the plain importer, then re-keyed per clip
    info = import_banim_empties(
        filepath, fps=fps, max_frames=0, delta_axes=(False, False, False),
        convert_axes=convert_axes, empty_size=empty_size, pos_factor=pos_factor,
        facing=facing, mirror_x=mirror_x, flip_mode=flip_mode)
    b, series = banim_series(filepath, fps=fps, delta_axes=(False, False, False),
                             pos_factor=pos_factor)
    objects = info["objects"]
    cm = _axis_matrix(convert_axes)
    anim_to_model = Matrix(partslib.ANIM_TO_MODEL)
    stem = os.path.splitext(os.path.basename(filepath))[0]

    xml = xml_path or animxmllib.find_xml(filepath) or ""
    clips = animxmllib.load(xml) if xml else []
    if not clips:
        total = int(round(b.duration_ms / frame_ms))
        clips = [animxmllib.Clip("all", 0, total)]

    for ob in objects:
        ob.animation_data_clear()

    scene = bpy.context.scene
    # 1 frame == 33 ms, so frames line up with the banim / XML numbering
    scene.render.fps = 1000
    scene.render.fps_base = float(frame_ms)

    built = []
    last_frame = 1
    for clip in clips:
        t_lo, t_hi = sorted((clip.start_ms, clip.end_ms))
        f_lo, f_hi = 1 + int(round(t_lo / frame_ms)), 1 + int(round(t_hi / frame_ms))
        for ob, (label, rows) in zip(objects, series):
            inside = [r for r in rows if t_lo - 1e-6 <= r[0] <= t_hi + 1e-6]
            if not inside:
                continue
            r0 = inside[0][2]
            ad = ob.animation_data_create()
            act = bpy.data.actions.new(f"{stem}_{clip.name}_{ob.name}")
            ad.action = act
            for t, p_model, rot in inside:
                frame_no = 1 + int(round(t / frame_ms))
                ob.location = cm @ p_model
                rr = (rot[0] - (r0[0] if delta_axes[0] else 0.0),
                      rot[1] - (r0[1] if delta_axes[1] else 0.0),
                      rot[2] - (r0[2] if delta_axes[2] else 0.0))
                rot_model = (anim_to_model @ Euler(rr, "XYZ").to_matrix()
                             @ anim_to_model.transposed())
                ob.rotation_mode = "XYZ"
                ob.rotation_euler = (cm @ rot_model @ cm.transposed()).to_euler("XYZ")
                ob.keyframe_insert("location", frame=frame_no)
                ob.keyframe_insert("rotation_euler", frame=frame_no)
            _make_linear(ob)
            ad.action = None
            if nla:
                track = ad.nla_tracks.new()
                track.name = clip.name
                strip = track.strips.new(clip.name, max(1, f_lo), act)
                strip.name = clip.name
                # a strip must not hold its last pose past its own range, or the
                # stacked tracks of the later clips override the earlier ones
                strip.extrapolation = "NOTHING"
                strip.blend_type = "REPLACE"
                if clip.reversed:
                    try:
                        strip.use_reverse = True
                    except AttributeError:
                        strip.action_frame_start, strip.action_frame_end = (
                            f_hi, f_lo)
            built.append((clip.name, ob.name, act.name))
        last_frame = max(last_frame, f_hi)

    # only the first clip is left audible, so the viewport shows its motion
    for ob in objects:
        ad = ob.animation_data
        if ad:
            for i, track in enumerate(ad.nla_tracks):
                track.mute = i != 0
    scene.frame_start = 1
    scene.frame_end = max(1, last_frame)
    return {
        "banim": b,
        "xml": xml,
        "clips": clips,
        "objects": objects,
        "root": info.get("root"),
        "actions": built,
        "collection": info["collection"],
    }


class IMPORT_OT_rr3_banim_clips(Operator, ImportHelper):
    """Import a .banim as one NLA clip per named transition in its XML"""

    bl_idname = "import_scene.rr3_banim_clips"
    bl_label = "Import RR3 Animation Clips (.banim + XML)"
    bl_options = {"REGISTER", "UNDO"}

    filename_ext = ".banim"
    filter_glob: StringProperty(default="*.banim", options={"HIDDEN"})

    xml_path: StringProperty(
        name="Animations XML (empty = auto)", default="", subtype="FILE_PATH")
    delta_x: BoolProperty(name="Difference X", default=False,
                          description="Make X rotation relative to the clip start")
    delta_y: BoolProperty(name="Difference Y", default=False,
                          description="Make Y rotation relative to the clip start")
    delta_z: BoolProperty(name="Difference Z", default=False,
                          description="Make Z rotation relative to the clip start")
    convert_axes: BoolProperty(name="Convert axes (Z-up)", default=True)
    pos_scale: FloatProperty(name="Position scale", default=1.0,
                             min=0.01, max=100.0)
    facing: EnumProperty(
        name="Facing",
        items=(("+Y", "+Y forward (.m3g, no rotation)", ""),
               ("-Y", "-Y forward (FBX, rotated 180)", "")),
        default="+Y")
    mirror_x: BoolProperty(name="Mirror X", default=False)
    flip_mode: EnumProperty(
        name="Apply to",
        items=(("ROOT", "Parent root", ""), ("BAKE", "Track empties", "")),
        default="ROOT")
    nla: BoolProperty(name="Build NLA tracks", default=True,
                      description="One NLA track per clip (for glTF export)")

    def execute(self, context):
        try:
            info = import_banim_clips(
                self.filepath, xml_path=self.xml_path, fps=30.0,
                delta_axes=(bool(self.delta_x), bool(self.delta_y),
                            bool(self.delta_z)),
                convert_axes=bool(self.convert_axes),
                pos_factor=float(self.pos_scale), facing=self.facing,
                mirror_x=bool(self.mirror_x), flip_mode=self.flip_mode,
                nla=bool(self.nla))
        except Exception as exc:  # noqa: BLE001 - reported to the user
            import traceback
            traceback.print_exc()
            self.report({"ERROR"}, f"RR3 clip import failed: {exc}")
            return {"CANCELLED"}
        clips = info["clips"]
        names = ", ".join(c.name for c in clips[:6])
        more = "" if len(clips) <= 6 else f" (+{len(clips) - 6})"
        self.report({"INFO"}, f"{len(clips)} clip(s): {names}{more}")
        for c in clips:
            if c.reversed:
                self.report({"INFO"},
                            f"clip {c.name} plays backwards ({c.start} -> {c.end})")
        return {"FINISHED"}


def import_banim_empties(filepath: str, *, fps: float = 30.0, max_frames: int = 0,
                         delta_axes: tuple = (False, False, False),
                         convert_axes: bool = True,
                         empty_size: float = 0.08, pos_factor: float = 1.0,
                         facing: str = "+Y", mirror_x: bool = False,
                         flip_mode: str = "ROOT"):
    """Import a ``.banim`` as one animated **empty per track** (no meshes).

    Every empty carries ``rr3_track``/``rr3_role`` custom properties, so you can
    parent your own mesh to it (or use a Child Of / Copy Transforms constraint)
    and get the motion without the reconstructed part placement.
    """
    b, series = banim_series(filepath, fps=fps, max_frames=max_frames,
                             delta_axes=delta_axes, pos_factor=pos_factor)
    coll = _collection(os.path.splitext(os.path.basename(filepath))[0])

    cm = _axis_matrix(convert_axes)
    anim_to_model = Matrix(partslib.ANIM_TO_MODEL)
    roles = riglib.roles_for(b)
    stem = os.path.splitext(os.path.basename(filepath))[0]

    # Facing / mirror is applied by ONE parent empty, never per object: the
    # track empties keep the exact game convention, so meshes already assembled
    # in car space (FBX) rotate with the rig instead of spinning about their own
    # origin.
    root = None
    if flip_mode == "ROOT" and (facing != "+Y" or mirror_x):
        root = bpy.data.objects.new(f"{stem}_ROOT", None)
        root.empty_display_type = "PLAIN_AXES"
        root.empty_display_size = empty_size * 1.6
        root.rotation_mode = "XYZ"
        if facing == "-Y":
            root.rotation_euler = (0.0, 0.0, math.pi)
        if mirror_x:
            root.scale = (-1.0, 1.0, 1.0)
        root["rr3_facing"] = facing
        root["rr3_mirror_x"] = bool(mirror_x)
        coll.objects.link(root)

    objects = []
    for ti, (label, rows) in enumerate(series):
        ob = bpy.data.objects.new(f"{os.path.splitext(os.path.basename(filepath))[0]}_{label}", None)
        ob.empty_display_type = "PLAIN_AXES"
        ob.empty_display_size = empty_size
        coll.objects.link(ob)
        ob["rr3_track"] = ti
        ob["rr3_role"] = roles[ti] if ti < len(roles) else label
        ob["rr3_facing"] = facing
        ob["rr3_mirror_x"] = bool(mirror_x)
        if root is not None:
            ob.parent = root
            ob.matrix_parent_inverse = Matrix.Identity(4)
        if flip_mode == "BAKE":
            ob.scale = (-1.0, 1.0, 1.0) if mirror_x else (1.0, 1.0, 1.0)
        for t, p_model, rot in rows:
            frame_no = int(round(t / 1000.0 * fps)) + 1
            rot_model = anim_to_model @ Euler(rot, "XYZ").to_matrix() @ anim_to_model.transposed()
            rot_bl = cm @ rot_model @ cm.transposed()
            if flip_mode == "BAKE":
                fm = _frame_matrix(facing, mirror_x)
                sgn = Matrix.Diagonal((-1.0, 1.0, 1.0)) if mirror_x else Matrix.Identity(3)
                ob.location = fm @ (cm @ p_model)
                ob.rotation_euler = (fm @ rot_bl @ sgn).to_euler("XYZ")
            else:
                ob.location = cm @ p_model
                ob.rotation_euler = rot_bl.to_euler("XYZ")
            ob.rotation_mode = "XYZ"
            ob.keyframe_insert("location", frame=frame_no)
            ob.keyframe_insert("rotation_euler", frame=frame_no)
        _make_linear(ob)
        objects.append(ob)

    scene = bpy.context.scene
    scene.render.fps = max(1, int(round(fps)))
    scene.frame_start = 1
    scene.frame_end = max(1, int(round(b.duration_ms / 1000.0 * fps)))
    return {
        "banim": b,
        "root": root,
        "objects": objects,
        "tracks": len(series),
        "frames": len(series[0][1]) if series else 0,
        "collection": coll,
    }


class IMPORT_OT_rr3_banim_empties(Operator, ImportHelper):
    """Import a Real Racing 3 .banim as animated empties (no meshes)"""

    bl_idname = "import_scene.rr3_banim_empties"
    bl_label = "Import RR3 Animation as Empties (.banim)"
    bl_options = {"REGISTER", "UNDO"}

    filename_ext = ".banim"
    filter_glob: StringProperty(default="*.banim", options={"HIDDEN"})

    fps: FloatProperty(name="FPS", default=30.0, min=1.0, max=240.0)
    max_frames: FloatProperty(name="Max frames (0 = all)", default=0.0, min=0.0)
    delta_x: BoolProperty(
        name="Difference X", default=False,
        description="Subtract the t=0 angle on the X axis only",
    )
    delta_y: BoolProperty(
        name="Difference Y", default=False,
        description="Subtract the t=0 angle on the Y axis only",
    )
    delta_z: BoolProperty(
        name="Difference Z", default=False,
        description="Subtract the t=0 angle on the Z axis only",
    )
    convert_axes: BoolProperty(name="Convert Y-up to Z-up", default=True)
    facing: EnumProperty(
        name="Facing",
        items=[("+Y", "+Y forward (.m3g model)", "Orientation of the mesh after "
                                                  "importing it with this add-on"),
               ("-Y", "-Y forward (FBX)", "Orientation of an already converted FBX "
                                          "car, i.e. rotated 180 deg about Z")],
        default="+Y",
        description="Orientation of the car you will apply the animation to. "
                    "The .points import is not affected by this switch.",
    )
    mirror_x: BoolProperty(
        name="Mirror X",
        default=False,
        description="Mirror the rig across X",
    )
    flip_mode: EnumProperty(
        name="Apply to",
        items=[("ROOT", "Parent root", "One parent empty carries the flip; the "
                                      "track empties keep the game values"),
               ("BAKE", "Track empties", "Bake the flip into every track empty "
                                         "(use this with a Copy Transforms "
                                         "constraint)")],
        default="ROOT",
        description="Where the facing/mirror transform is applied",
    )
    pos_scale: FloatProperty(
        name="Position scale",
        description="Multiplier on the decoded track positions (1.0 = built-in "
                    "scale: wing /65536, driver /32768)",
        default=1.0, min=0.01, max=100.0,
    )

    def execute(self, context):
        try:
            res = import_banim_empties(
                self.filepath,
                fps=self.fps,
                max_frames=int(self.max_frames),
                delta_axes=(bool(self.delta_x), bool(self.delta_y), bool(self.delta_z)),
                convert_axes=self.convert_axes,
                pos_factor=self.pos_scale,
                facing=self.facing,
                mirror_x=self.mirror_x,
                flip_mode=self.flip_mode,
            )
        except Exception as exc:  # noqa: BLE001
            self.report({"ERROR"}, f"RR3 animation import failed: {exc}")
            return {"CANCELLED"}

        b = res["banim"]
        self.report(
            {"INFO"},
            f"{res['tracks']} empty track(s), {res['frames']} frames @ {self.fps:g} fps"
            f" ({b.duration_ms:g} ms, {b.total_keys} keys)",
        )
        return {"FINISHED"}


class IMPORT_OT_rr3_banim(Operator, ImportHelper):
    """Import a Real Racing 3 .banim animation as keyframed parts"""

    bl_idname = "import_scene.rr3_banim"
    bl_label = "Import RR3 Animation (.banim)"
    bl_options = {"REGISTER", "UNDO"}

    filename_ext = ".banim"
    filter_glob: StringProperty(default="*.banim", options={"HIDDEN"})

    model: StringProperty(
        name="Model (.m3g)",
        description="Model whose parts are animated; leave empty to auto-detect",
        default="",
        subtype="FILE_PATH",
    )
    fps: FloatProperty(name="FPS", default=30.0, min=1.0, max=240.0)
    max_frames: FloatProperty(name="Max frames (0 = all)", default=0.0, min=0.0)
    placement: EnumProperty(
        name="Placement",
        items=(
            ("BONE", "Bone (aligned)", "Centre the mesh on its bone and align its long axis"),
            ("JOINT", "Joint only", "Put the mesh centre on the joint, no alignment"),
        ),
        default="BONE",
    )
    convert_axes: BoolProperty(name="Convert Y-up to Z-up", default=True)
    flip_driver: BoolProperty(
        name="Face like the car", description="Turn the figure 180 deg so it faces the car nose", default=True
    )

    def execute(self, context):
        try:
            res = import_banim_file(
                self.filepath,
                model_path=self.model or None,
                fps=self.fps,
                max_frames=int(self.max_frames),
                placement=self.placement,
                convert_axes=self.convert_axes,
                flip_driver=self.flip_driver,
            )
        except Exception as exc:  # noqa: BLE001
            self.report({"ERROR"}, f"RR3 animation import failed: {exc}")
            return {"CANCELLED"}

        b = res["banim"]
        msg = (
            f"{b.num_tracks} part(s), {res['frames']} frames @ {self.fps:g} fps"
            f" ({b.duration_ms:g} ms)"
        )
        if res["model"]:
            msg += f", model {os.path.basename(res['model'])}"
        self.report({"INFO"}, msg)
        self.report(
            {"WARNING"},
            "Placement is reconstructed from the joint positions: the assets hold no "
            "skeleton, so the part orientation is an inference, not stored data.",
        )
        return {"FINISHED"}


class IMPORT_OT_rr3_vehicle(Operator, ImportHelper):
    """Import a complete car: body LOD, mounted wheels and rigged active aero

    Pick any file of the car (for example <car>_a.m3g or <car>.points); the
    add-on finds the matching _shared.m3g, .points and _wing.banim itself.
    """

    bl_idname = "import_scene.rr3_vehicle"
    bl_label = "Import RR3 Vehicle (wheels + aero)"
    bl_options = {"REGISTER", "UNDO"}

    filename_ext = ".m3g"
    filter_glob: StringProperty(default="*.m3g;*.points;*.banim", options={"HIDDEN"})

    lod: EnumProperty(
        name="Body LOD",
        items=[(c, f"LOD {c}", "") for c in "ABCDEFGH"] + [
            ("shared", "shared (bonnet-cam shell, whole file)", ""),
            ("int_a", "int_a (cockpit, first person)", ""),
            ("int_b", "int_b (cockpit, first person)", ""),
        ],
        default="A",
    )
    convert_axes: BoolProperty(name="Convert Y-up to Z-up", default=True)
    textures: BoolProperty(name="Load .dxt.dds.z atlases", default=True)
    animate: BoolProperty(name="Keyframe the active aero", default=True)
    fps: FloatProperty(name="Animation fps", default=30.0, min=1.0, max=240.0)
    import_anchors: BoolProperty(name="Import .points anchors", default=True)
    height_adjust: FloatProperty(
        name="Vertical adjust (m)", default=0.0, min=-0.3, max=0.3,
        description="Shift wheels, aero pivots and anchors along model +Y; "
                    "compensates the .points datum (about +0.01 m fixes the "
                    "1 cm sag)")
    rot_mode: EnumProperty(
        name="Rotation reading",
        items=[("DELTA", "Delta from rest",
                "Subtract the first frame so the rest pose becomes 0° (default: "
                "the meshes are already modelled in their rest orientation)"),
               ("ABS", "Absolute (as stored)",
                "Use the stored angles directly - the rest pose carries a bias, "
                "which double-counts the rest orientation and clips the body")],
        default="DELTA",
        description="How to read the stored rotation channels",
    )
    hinge_pivot: BoolProperty(
        name="Rotate flaps about their hinge (experimental)",
        description="Pivot each aero flap about the edge that touches the body "
                    "instead of its own origin. Off by default: in-game tests "
                    "show the wing banim pivot already is the part origin",
        default=False,
    )
    pos_scale: FloatProperty(
        name="Position scale", default=1.0, min=0.05, max=100.0,
        description="Multiplier on wheel mounts and aero pivots (set 0.5 if the "
                    "whole rig came in twice as large as the body)",
    )
    pos_factor: FloatProperty(
        name="Anchor position scale", default=1.0, min=0.05, max=100.0,
        description="Multiplier on the .points anchor positions only; the meshes "
                    "keep their own size. Leave at 1.0 - the .points file is in "
                    "the same metres as the mesh",
    )
    facing: EnumProperty(
        name="Facing",
        items=[("+Y", "+Y forward (matches the .m3g)",
                "Keep the game orientation: the nose points along Blender +Y "
                "after the Y-up conversion, which is where the body mesh is"),
               ("-Y", "-Y forward (FBX, turned 180)",
                "Turn the whole car 180 deg about Z, to line it up with an FBX "
                "export whose nose is on -Y")],
        default="+Y",
        description="Turns the body, the wheels, the aero pivots and the anchors "
                    "together, so nothing can drift apart",
    )
    mirror_x: BoolProperty(
        name="Mirror X", default=False,
        description="Mirror the whole car across X (only when matching an FBX "
                    "that was exported mirrored)",
    )
    rear_tyre_width: BoolProperty(
        name="Widen rear tyre to the rear rim", default=True,
        description="On the 62 cars that have a wider WHEEL_REAR but no TYRE_REAR "
                    "of their own (Pagani Huayra and others), widen the rear tyre "
                    "to the rim ratio so it does not sit inside its own rim",
    )
    delta_axes: BoolVectorProperty(
        name="Delta axes",
        size=3, default=(False, False, False),
        subtype="XYZ",
        description="Make the aero rotation channels relative to the first frame, "
                    "per axis. Overrides 'Rotation reading' when any axis is set",
    )
    wheel_scale: FloatProperty(
        name="Wheel scale", default=1.0, min=0.2, max=4.0,
        description="Extra multiplier on top of 'Wheel size'; leave at 1.0 "
                    "unless a car still looks wrong",
    )
    wheel_uniform: BoolProperty(
        name="Scale the width too", default=False,
        description="Stretch the wheel along every axis instead of only round its "
                    "face. Off matches the game, which grows the tyre taller and "
                    "leaves the width as modelled; on is what a replacement rim "
                    "needs to stay round",
    )
    wheel_size: EnumProperty(
        name="Wheel size",
        items=[
            ("engine", "Match the game",
             "Stretch the shared tyre to the car's own tyre diameter from "
             "suspensionbehaviour - the factor the game computes at load time"),
            ("ground", "Sit on the ground",
             "Stretch it so the tyre just touches the ground under a static car "
             "(about 5% smaller than 'Match the game', which sags into the "
             "ground)"),
            ("none", "Leave the template alone",
             "Import the shared wheel unscaled - every car then has the same "
             "0.60 m tyre"),
        ],
        default="engine",
        description="The shared tyre mesh is one template for all 463 cars; the "
                    "game always stretches it radially. This picks the factor",
    )
    brakes: BoolProperty(
        name="Brake disc and caliper", default=True,
        description="Mount the brake disc and the caliper too. The engine sizes "
                    "them with the same radial factor as the tyre, but a caliper "
                    "does not turn with the wheel - all four are modelled in "
                    "their own corner. Only LOD A and B ship them",
    )
    materials: EnumProperty(
        name="Materials",
        items=[
            ("simple", "Name colours + tag atlas",
             "The old behaviour: a colour hashed from the material name, plus "
             "the atlas the mesh tag points at. One material per mesh"),
            ("game", "Game materials, one shader per paint",
             "Read the game's own data: the livery table gives each mesh its "
             "material per paint scheme and materials.bin gives that material's "
             "specular power and fresnel ramp. Every mesh gets one material "
             "holding one preset per paint scheme"),
        ],
        default="simple",
        description="Where the shading comes from",
    )
    paint: IntProperty(
        name="Paint scheme", default=-1, min=-1, max=63,
        description="Which paint scheme starts active (-1 = the first). Only "
                    "used with 'Game materials'; the others stay in the same "
                    "material as further presets",
    )
    separate_damage: BoolProperty(
        name="Damaged parts in their own folder", default=True,
        description="A body file ships the pristine and the wrecked version of "
                    "every panel (DOOR_LEFT and DOOR_LEFT_DAMAGE) plus the "
                    "smashed glass and lenses (*_BROKEN_*). Put the wrecked ones "
                    "in a '<car>_LOD<X>_damaged' sub-collection instead of on "
                    "top of the good ones",
    )
    separate_camera: BoolProperty(
        name="Bonnet-cam shell in its own folder", default=True,
        description="_shared.m3g carries a second body shell the game renders "
                    "from the nose camera (BONNETCAM_BODY / BONNETCAM_HOOD) plus "
                    "the emissive LIT_* glow quads. Inside the real body they "
                    "only z-fight, so they go into '<car>_LOD<X>_camera'",
    )
    material_depot: StringProperty(
        name="Depot", default="", subtype="DIR_PATH",
        description="Folder holding materials/materials.bin. Leave empty to look "
                    "for it above the car folder; set it when importing a car "
                    "that was copied out of the depot",
    )

    def execute(self, context):
        car_dir, car, lod = car_from_path(self.filepath)
        common = dict(
            convert_axes=self.convert_axes,
            textures=self.textures,
            animate=self.animate,
            fps=self.fps,
            import_anchors=self.import_anchors,
            height_adjust=self.height_adjust,
            rot_mode=self.rot_mode,
            wheel_scale=self.wheel_scale,
        wheel_uniform=self.wheel_uniform,
            wheel_size=self.wheel_size,
            pos_scale=self.pos_scale,
            hinge=self.hinge_pivot,
            facing=self.facing,
            mirror_x=self.mirror_x,
            delta_axes=tuple(bool(v) for v in self.delta_axes),
            pos_factor=self.pos_factor,
            rear_tyre_width=self.rear_tyre_width,
            brakes=self.brakes,
            materials=self.materials,
            paint=self.paint,
            material_depot=bpy.path.abspath(self.material_depot)
            if self.material_depot else "",
            separate_damage=self.separate_damage,
            separate_camera=self.separate_camera,
        )

        try:
            res = import_vehicle_file(car_dir, car, lod=lod or self.lod, **common)
        except Exception as exc:  # noqa: BLE001
            self.report({"ERROR"}, f"RR3 vehicle import failed: {exc}")
            return {"CANCELLED"}

        plan = res["plan"]
        msg = (f"{car}: {len(plan.body_meshes)} body meshes, "
               f"{len(plan.wheel_mounts)} wheels, {len(plan.aero_parts)} aero parts")
        if res["wheels"]:
            msg += f", {len(res['wheels'])} wheel objects"
        if plan.aero_parts:
            msg += f", {len(plan.aero_parts)} pivots keyframed"
        fit = res.get("wheel_fit")
        if fit is not None:
            msg += f", tyres x{fit.front:.3f}/x{fit.rear:.3f} ({fit.source})"
        if plan.wheels.pre_assembled:
            msg += ", wheels already assembled in the shared file"
        self.report({"INFO"}, msg)
        for w in plan.warnings:
            self.report({"WARNING"}, w)
        if not plan.aero_parts:
            self.report({"WARNING"}, "No active-aero parts found for this car.")
        return {"FINISHED"}


class IMPORT_OT_rr3_driver(Operator):
    """Import the game's driver, posed from his .banim"""

    bl_idname = "import_scene.rr3_driver"
    bl_label = "Import RR3 Driver"
    bl_options = {"REGISTER", "UNDO"}

    depot: StringProperty(
        name="Depot", default="", subtype="DIR_PATH",
        description="The .depot folder holding 'driver/'. Leave empty to use the "
                    "one above the current file's folder",
    )
    car: StringProperty(
        name="Car", default="",
        description="Car folder name (2013_caterham_seven_620r). Picks the car's "
                    "own driver_<car>.banim and its driver_lod_c_<car> variant; "
                    "leave empty for the generic seated pose",
    )
    car_record: StringProperty(
        name="Car data (.bin.nct)", default="", subtype="FILE_PATH",
        description="The car's vehicles/data/<id>_<car>.bin.nct record. Its own "
                    "field names the animation the game uses for this car, so this "
                    "is more reliable than typing the folder name. Leave empty to "
                    "look it up from the Car name",
    )
    banim_file: StringProperty(
        name="Animation (.banim)", default="", subtype="FILE_PATH",
        description="Pick the animation by hand; overrides both the car record and "
                    "the name match",
    )
    lod: EnumProperty(
        name="Driver LOD",
        items=[("a", "A (15 parts, full)", ""),
               ("b", "B (15 parts, lower)", ""),
               ("c", "C (legs only, in the seat)", ""),
               ("d", "D (legs only, lowest)", "")],
        default="a",
    )
    skin: StringProperty(
        name="Skin", default="",
        description="Texture name from vehicles/common (alesi, alonso, ferrari, "
                    "raikkonen...). Leave empty for the default driver.dxt.dds.z",
    )
    fps: FloatProperty(
        name="FPS", default=90.0, min=1.0, max=240.0,
        description="How many poses per second to keyframe. The shipped driver "
                    "animations carry a key every 11 ms (about 90 a second), so "
                    "sampling at 30 throws two thirds of them away and the export "
                    "cannot reproduce the motion",
    )
    max_frames: IntProperty(name="Max frames", default=0, min=0)
    placement: EnumProperty(
        name="Placement",
        items=[("NODE", "Node matrix (each part round its own joint)", ""),
               ("BONE", "Along the bone", ""),
               ("JOINT", "Centre on the joint", "")],
        default="NODE",
    )
    flip_driver: BoolProperty(
        name="Mirror the figure", default=False,
        description="Mirror x and y, i.e. turn every part 180 deg on its own. Off by "
                    "default: it also swaps the hands and reverses the rotations, so "
                    "use 'Turn the root' instead",
    )
    with_root: BoolProperty(
        name="Parent to a root empty", default=True,
        description="Add <car>_DRIVER_ROOT and parent every part to it, so the whole "
                    "figure can be moved with one transform",
    )
    textures: BoolProperty(name="Load the driver skin", default=True)

    def invoke(self, context, event):
        if not self.depot:
            self.depot = gamematlib.find_depot(bpy.path.abspath("//")) or ""
        if not self.car_record and self.car:
            rec = drvlib.car_record(self.depot, self.car) if self.depot else None
            if rec:
                self.car_record = rec
        return context.window_manager.invoke_props_dialog(self, width=460)

    def execute(self, context):
        depot = bpy.path.abspath(self.depot) if self.depot else ""
        if not depot:
            depot = gamematlib.find_depot(bpy.path.abspath("//")) or ""
        if not depot:
            self.report({"ERROR"}, "Set 'Depot' to the .depot folder (it holds 'driver/')")
            return {"CANCELLED"}
        record = bpy.path.abspath(self.car_record) if self.car_record else ""
        if not record and self.car:
            record = drvlib.car_record(depot, self.car) or ""
        try:
            res = import_driver(depot, lod=self.lod, car=self.car, skin=self.skin,
                                fps=self.fps, max_frames=self.max_frames,
                                placement=self.placement,
                                flip_driver=self.flip_driver,
                                banim_file=(bpy.path.abspath(self.banim_file)
                                            if self.banim_file else ""),
                                car_record=record,
                                with_root=self.with_root,
                                textures=self.textures)
        except Exception as exc:  # noqa: BLE001
            self.report({"ERROR"}, f"RR3 driver import failed: {exc}")
            return {"CANCELLED"}
        meshes = sum(1 for ob in res["objects"].values() if ob.type == "MESH")
        msg = (f"Driver: {meshes} part(s), {res['frames']} frame(s)"
               f" from {os.path.basename(res['banim'] or 'no animation')}")
        if res["banim_matched"]:
            msg += f" ({res['banim_matched']})"
        if not res["posed"]:
            msg += ", not posed (a single seated mesh)"
        self.report({"INFO"}, msg)
        return {"FINISHED"}


class IMPORT_OT_rr3_points(Operator, ImportHelper):
    """Import a Real Racing 3 .points anchor file"""

    bl_idname = "import_scene.rr3_points"
    bl_label = "Import RR3 Anchors (.points)"
    bl_options = {"REGISTER", "UNDO"}

    filename_ext = ".points"
    filter_glob: StringProperty(default="*.points", options={"HIDDEN"})
    scale: FloatProperty(name="Scale", default=1.0, min=0.0001)
    convert_axes: BoolProperty(name="Convert axes", default=True)
    facing: EnumProperty(
        name="Facing",
        items=[("-Y", "-Y forward (FBX, no rotation)",
                "Import the anchors as they are - this is the FBX space"),
               ("+Y", "+Y forward (.m3g, rotated 180)",
                "Rotate the anchors 180 deg about Z to match the .m3g model")],
        default="-Y",
        description="Anchors are authored in the FBX space; pick +Y only if you "
                    "are matching them to a .m3g import",
    )
    mirror_x: BoolProperty(
        name="Mirror X",
        default=True,
        description="Mirror the anchors across X (the RR3 rig is mirrored "
                    "relative to the FBX exports) - only used with Model space off",
    )
    model_space: BoolProperty(
        name="Model space",
        default=True,
        description="Place the anchors where the .m3g model has them, which is "
                    "the frame the exporter writes back. Turn this off to line "
                    "them up against an FBX export instead",
    )

    def execute(self, context):
        path = self.filepath
        coll = _collection(os.path.splitext(os.path.basename(path))[0])
        try:
            pf, created = _import_points(path, self.scale, self.convert_axes, coll,
                                         facing=self.facing, mirror_x=self.mirror_x,
                                         model_space=self.model_space)
        except Exception as exc:  # noqa: BLE001
            self.report({"ERROR"}, f"RR3 points import failed: {exc}")
            return {"CANCELLED"}
        self.report({"INFO"}, f"Imported {len(created)} anchors from {pf.path.name}")
        return {"FINISHED"}


class RR3_OT_report_to_text(Operator, ImportHelper):
    """Load the readable report of a .banim / .points / .m3g file into a Text datablock"""

    bl_idname = "rr3.report_to_text"
    bl_label = "RR3 Report to Text Editor"
    bl_options = {"REGISTER"}

    filename_ext = ""
    filter_glob: StringProperty(default="*.banim;*.points;*.m3g", options={"HIDDEN"})
    max_keys: FloatProperty(name="Max keys per file (0 = all)", default=0.0, min=0.0)

    def execute(self, context):
        path = self.filepath
        ext = os.path.splitext(path)[1].lower()
        try:
            if ext == ".banim":
                text = banimlib.format_report(banimlib.load(path), max_keys=int(self.max_keys))
            elif ext == ".points":
                text = pointslib.format_report(pointslib.load(path))
            elif ext == ".m3g":
                text = geometrylib.format_report(m3glib.M3G(path))
            else:
                self.report({"ERROR"}, f"unsupported file: {ext}")
                return {"CANCELLED"}
        except Exception as exc:  # noqa: BLE001
            self.report({"ERROR"}, f"RR3 report failed: {exc}")
            return {"CANCELLED"}

        name = os.path.basename(path)
        block = bpy.data.texts.get(name) or bpy.data.texts.new(name)
        block.clear()
        block.write(text)
        self.report({"INFO"}, f"Report for {name} is in the Text Editor")
        return {"FINISHED"}


# --------------------------------------------------------------------------
# export operators (.points / .banim / _animations.xml)
# --------------------------------------------------------------------------
class EXPORT_OT_rr3_points(bpy.types.Operator, ExportHelper):
    bl_idname = "export_scene.rr3_points"
    bl_label = "Export RR3 Anchors (.points)"
    bl_description = ("Write the anchor empties (POINT_* / HINGE_* / TRANSFORM_*, or "
                      "anything tagged rr3_point_type) as a Real Racing 3 .points file")
    bl_options = {"REGISTER"}

    filename_ext = ".points"
    filter_glob: StringProperty(default="*.points", options={"HIDDEN"})
    only_tagged: BoolProperty(
        name="Only tagged / named empties", default=True,
        description="Ignore empties that are neither tagged rr3_point_type nor named "
                    "POINT_* / HINGE_* / TRANSFORM_*")
    only_selected: BoolProperty(
        name="Selected empties only", default=False,
        description="Write just the anchors that are selected. Off by default: a "
                    "car's anchors are scattered and selecting all of them before "
                    "every export is busywork - but a scene holding two cars' "
                    "anchors has no other way to export one of them")

    def execute(self, context):
        try:
            n, warnings = explib.export_points(self.filepath,
                                               only_tagged=self.only_tagged,
                                               only_selected=self.only_selected)
        except Exception as exc:  # noqa: BLE001
            self.report({"ERROR"}, f"RR3 .points export failed: {exc}")
            return {"CANCELLED"}
        for w in warnings:
            self.report({"WARNING"}, w)
        self.report({"INFO"}, f"wrote {n} anchor(s) to {os.path.basename(self.filepath)}")
        return {"FINISHED"}


class EXPORT_OT_rr3_banim(bpy.types.Operator, ExportHelper):
    bl_idname = "export_scene.rr3_banim"
    bl_label = "Export RR3 Part Animation (.banim)"
    bl_description = ("Write the animated part empties as a Real Racing 3 .banim file: "
                      "one track per empty, six channels (position XYZ, Euler XYZ)")
    bl_options = {"REGISTER"}

    filename_ext = ".banim"
    filter_glob: StringProperty(default="*.banim", options={"HIDDEN"})
    tracks_from: EnumProperty(
        name="Tracks from",
        items=(("AERO", "Active aero pivots (AERO_*)", "Every empty named AERO_*"),
               ("NAME", "Part names (WING_REAR, ...)",
                "The meshes whose name holds the part name below, one track per "
                "part, numbered in alphabetical order - how the game numbers them"),
               ("TAGGED", "Empties tagged rr3_track", "Empties carrying an rr3_track property"),
               ("SELECTED", "Selected empties", "The empties selected right now"),
               ("PARTS", "Tagged parts (drivers, characters)",
                "Every mesh carrying an rr3_track property - the way a driver rig "
                "is animated, one body part per track")),
        default="AERO")
    part_filter: StringProperty(
        name="Part name", default="WING",
        description="With 'Part names': the word a mesh name must contain to be "
                    "exported. WING picks up WING_REAR, WING_STRUT and the rest")
    fps: FloatProperty(name="FPS", default=0.0, min=0.0, soft_max=120.0,
                       description="0 = use the scene frame rate")
    duration_ms: FloatProperty(name="Duration (ms, 0 = from keys)", default=0.0, min=0.0)
    donor: StringProperty(
        name="Container from (optional)", subtype="FILE_PATH", default="",
        description="A shipped .banim whose magic, variant, version and event names "
                    "should be reused. Optional: without it the exporter writes the "
                    "magic every wing file uses and builds the per-track trailer from "
                    "the part names, which is what the game actually needs")

    def execute(self, context):
        try:
            n, keys, dur = explib.export_banim(
                self.filepath, tracks_from=self.tracks_from, fps=self.fps,
                duration_ms=self.duration_ms, part_filter=self.part_filter,
                donor=self.donor)
        except Exception as exc:  # noqa: BLE001
            self.report({"ERROR"}, f"RR3 .banim export failed: {exc}")
            return {"CANCELLED"}
        self.report({"INFO"}, f"wrote {n} track(s), {keys} key(s), {dur:.0f} ms")
        return {"FINISHED"}

    def draw(self, context):
        lay = self.layout
        lay.prop(self, "tracks_from")
        if self.tracks_from == "NAME":
            lay.prop(self, "part_filter")
            lay.label(text="One track per part, numbered by part name.")
        lay.prop(self, "fps")
        lay.prop(self, "duration_ms")
        lay.prop(self, "donor")
        lay.label(text="The trailer is built from the part names; a donor only "
                       "supplies the magic and the event names.", icon="INFO")


class EXPORT_OT_rr3_animxml(bpy.types.Operator, ExportHelper):
    bl_idname = "export_scene.rr3_animxml"
    bl_label = "Export RR3 Animation Clips (.xml)"
    bl_description = ("Write the _animations.xml clip table that tells the engine which "
                      "frame range of the .banim is which behaviour")
    bl_options = {"REGISTER"}

    filename_ext = ".xml"
    filter_glob: StringProperty(default="*.xml", options={"HIDDEN"})
    preset: EnumProperty(
        name="Clips",
        items=(("WING", "wing_initial / wing_up / wing_down",
                "The three clips an active aero car normally needs"),
               ("PIVOT", "wing_initial / pivot_up / pivot_down",
                "The pivot style used by most open wheel and GT cars")),
        default="WING")
    start_frame: FloatProperty(name="Rest frame", default=0.0)
    end_frame: FloatProperty(name="Open frame", default=30.0)

    def execute(self, context):
        try:
            if self.preset == "PIVOT":
                clips = [animxmllib.Clip("wing_initial", int(self.start_frame), int(self.end_frame)),
                         animxmllib.Clip("pivot_up", int(self.start_frame), int(self.end_frame)),
                         animxmllib.Clip("pivot_down", int(self.end_frame), int(self.start_frame))]
            else:
                clips = explib.wing_clips(self.start_frame, self.end_frame)
            problems = explib.export_animxml(self.filepath, clips)
        except Exception as exc:  # noqa: BLE001
            self.report({"ERROR"}, f"RR3 animation xml export failed: {exc}")
            return {"CANCELLED"}
        for p in problems:
            self.report({"WARNING"}, p)
        self.report({"INFO"}, f"wrote {len(clips)} clip(s)")
        return {"FINISHED"}


# --------------------------------------------------------------------------
# car building / paint
# --------------------------------------------------------------------------
class RR3_OT_build_car(bpy.types.Operator):
    bl_idname = "rr3.build_car"
    bl_label = "Build a New Car"
    bl_description = ("Clone a shipped car into a new car id: spec, the shared tables, "
                      "the livery file and the asset manifests")
    bl_options = {"REGISTER"}

    depot: StringProperty(name="Depot folder", subtype="DIR_PATH",
                          description="The game's .depot folder (read only)")
    pkg: StringProperty(name="Package folder", subtype="DIR_PATH",
                        description="The folder holding apk/res and .depot (read only)")
    out_dir: StringProperty(name="Output folder", subtype="DIR_PATH",
                            description="Where the new files are written")
    donor_name: StringProperty(name="Donor car", default="",
                               description="Folder name of a shipped car, e.g. 2012_lexus_lfa")
    new_name: StringProperty(name="New car name", default="",
                             description="Folder name for the new car, year first: 2012_my_car")
    new_id: IntProperty(name="New car id", default=0, min=0,
                        description="0 = the next free id")
    body_m3g: StringProperty(name="Body .m3g", subtype="FILE_PATH",
                             description="Optional: replaces the donor's _a.m3g")
    aero: BoolProperty(name="Active aero", default=True,
                       description="Set the DeployWhenBraking behaviour token")
    aliases: BoolProperty(name="Write donor-named texture aliases", default=True,
                          description="Keep this on: the engine looks textures up by the "
                                      "donor base name, without the copies every texture "
                                      "comes out magenta")

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=560)

    def execute(self, context):
        try:
            depot = bpy.path.abspath(self.depot)
            pkg = bpy.path.abspath(self.pkg) or depot
            out_dir = bpy.path.abspath(self.out_dir)
            new_id = self.new_id or carlib.free_car_id(depot)
            log = []
            info = carlib.build_car(
                depot, pkg, out_dir, new_id=new_id, new_name=self.new_name,
                donor_name=self.donor_name,
                body_m3g=bpy.path.abspath(self.body_m3g) or None,
                aero=self.aero, aliases=self.aliases, log=log.append)
        except Exception as exc:  # noqa: BLE001
            self.report({"ERROR"}, f"RR3 build car failed: {exc}")
            return {"CANCELLED"}

        block = bpy.data.texts.get("rr3_build_car") or bpy.data.texts.new("rr3_build_car")
        block.clear()
        block.write(f"new car {info['new_name']} (id {info['new_id']}) "
                    f"from {info['donor']}\n\n")
        block.write("\n".join(log))
        block.write(f"\n\nwing material: {info.get('wing_material')}\n")
        self.report({"INFO"}, f"built {info['new_name']} (id {info['new_id']}), "
                              f"see the Text Editor for the log")
        return {"FINISHED"}


class RR3_OT_set_paint(bpy.types.Operator):
    bl_idname = "rr3.set_part_material"
    bl_label = "Set Part Material"
    bl_description = ("Give one part of a car one material in every paint scheme "
                      "(writes the car's .liveries.bin.nct)")
    bl_options = {"REGISTER"}

    depot: StringProperty(name="Depot folder", subtype="DIR_PATH")
    car: StringProperty(name="Car", default="",
                        description="Folder name, e.g. 2012_lexus_lfa")
    part: StringProperty(name="Part", default="",
                         description="Mesh name, e.g. LOD_A_WING_REAR_mm_ext "
                                     "(use the Catalog button for the full list)")
    material: StringProperty(name="Material", default="",
                             description="Material name, e.g. car_paint_metallic_white")
    copy_body: BoolProperty(name="Copy the body paint instead", default=False,
                            description="Ignore Material and give the part whatever the "
                                        "body uses, per scheme (the usual wing fix)")

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=560)

    def execute(self, context):
        depot = bpy.path.abspath(self.depot)
        try:
            if self.copy_body:
                L = liverylib.load_car(depot, self.car)
                table = liverylib.load_slot_table(depot)
                info = L.copy_body_paint(self.part, table=table)
                liverylib.save(L, os.path.join(
                    depot, *liverylib.LIVERY_DIR.split("/"),
                    f"{self.car}.liveries.bin.nct"))
            else:
                info = carlib.set_part_material(depot, self.car, self.part,
                                                self.material)
        except Exception as exc:  # noqa: BLE001
            self.report({"ERROR"}, f"RR3 paint failed: {exc}")
            return {"CANCELLED"}
        self.report({"INFO"}, f"paint updated: {info}")
        return {"FINISHED"}


class RR3_OT_switch_paint(bpy.types.Operator):
    bl_idname = "rr3.switch_paint"
    bl_label = "Switch Paint Scheme"
    bl_description = ("Wire another paint preset of the car's game material to "
                      "Material Output (import with Materials = Game first)")
    bl_options = {"REGISTER", "UNDO"}

    paint: IntProperty(
        name="Paint scheme", default=0, min=0, max=63,
        description="Preset number to activate; 0 is the first scheme in the "
                    "car's .liveries.bin.nct",
    )

    def execute(self, context):
        changed = 0
        skipped = 0
        seen = set()
        for ob in context.selected_objects:
            if ob.type != "MESH":
                continue
            presets = int(ob.get("rr3_paint_slots") or 0)
            if presets <= 0:
                skipped += 1
                continue
            want = min(self.paint, presets - 1)
            for slot in ob.material_slots:
                mat = slot.material
                if mat is None or id(mat) in seen:
                    continue
                seen.add(id(mat))
                if _activate_preset(mat, want):
                    changed += 1
            ob["rr3_paint_slot"] = want
        if not changed:
            self.report({"WARNING"},
                        f"no mesh with paint presets selected ({skipped} skipped)")
            return {"CANCELLED"}
        self.report({"INFO"},
                    f"{changed} material(s) on paint preset {self.paint}")
        return {"FINISHED"}


class RR3_OT_catalog(bpy.types.Operator):
    bl_idname = "rr3.catalog"
    bl_label = "Material / Part Catalog"
    bl_description = ("Load every material and part name the game ships into the "
                      "Text Editor, so you know what you may type into the fields")
    bl_options = {"REGISTER"}

    which: EnumProperty(
        name="List",
        items=(("materials", "Materials", "Every material instance and its template"),
               ("paints", "Paint materials", "Only the car paint materials"),
               ("parts", "Part names", "Every mesh name with its livery slot"),
               ("tags", "Material tags", "The _mm_ tag suffixes and what they mean"),
               ("all", "Everything", "All of the above")),
        default="all")

    def execute(self, context):
        lines = []
        if self.which in ("materials", "all"):
            mats = cataloglib.materials()
            lines.append(f"=== MATERIALS ({len(mats)} instances from "
                         f"{len({r[1] for r in mats})} templates) ===")
            for inst, tmpl, app, _flags in mats:
                lines.append(f"  {inst:<44} {tmpl:<32} {app}")
            lines.append("")
        if self.which in ("paints", "all"):
            paints = cataloglib.paint_materials()
            lines.append(f"=== PAINT MATERIALS ({len(paints)}) ===")
            for name, tmpl, app, _flags in paints:
                lines.append(f"  {name:<44} {tmpl:<32} {app}")
            lines.append("")
        if self.which in ("tags", "all"):
            lines.append("=== _mm_ TAGS ===")
            for tag in cataloglib.tags():
                doc = cataloglib.TAG_DOC.get(tag, "")
                lines.append(f"  _mm_{tag:<20} {doc}")
            lines.append("")
        if self.which in ("parts", "all"):
            lines.append(f"=== PARTS ({len(cataloglib.parts())}) ===")
            for name, slot in cataloglib.parts():
                lines.append(f"  {slot:>5}  {name}")
        text = "\n".join(lines)
        block = bpy.data.texts.get("rr3_catalog") or bpy.data.texts.new("rr3_catalog")
        block.clear()
        block.write(text)
        self.report({"INFO"}, "catalog is in the Text Editor")
        return {"FINISHED"}


class RR3_OT_audit_paint(bpy.types.Operator):
    bl_idname = "rr3.audit_paint"
    bl_label = "Audit Part Materials"
    bl_description = ("Show which material every mesh of the imported car ends up with, "
                      "and whether it came from the paint scheme, the car or the default")
    bl_options = {"REGISTER"}

    depot: StringProperty(name="Depot folder", subtype="DIR_PATH")
    car: StringProperty(name="Car", default="")
    paint_index: IntProperty(name="Paint scheme (0 = all)", default=0, min=0)

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=520)

    def execute(self, context):
        depot = bpy.path.abspath(self.depot)
        meshes = sorted({ob.name.split(".")[0] for ob in context.scene.objects
                         if ob.type == "MESH" and "_mm_" in ob.name})
        try:
            rows = carlib.audit_paint(depot, self.car, meshes,
                                      self.paint_index or None)
        except Exception as exc:  # noqa: BLE001
            self.report({"ERROR"}, f"RR3 audit failed: {exc}")
            return {"CANCELLED"}
        lines = [f"=== {self.car} ==="]
        for mesh, slot, mat, level in rows:
            lines.append(f"  {mesh:<40} slot {slot:>5}  -> {mat:<36} {level}")
        block = bpy.data.texts.get("rr3_audit") or bpy.data.texts.new("rr3_audit")
        block.clear()
        block.write("\n".join(lines))
        self.report({"INFO"}, f"audited {len(rows)} mesh(es), see the Text Editor")
        return {"FINISHED"}


class RR3_OT_export_textures(bpy.types.Operator):
    bl_idname = "rr3.export_textures"
    bl_label = "Export Textures"
    bl_description = ("Unpack the game's private texture containers (.dxt.dds.z, "
                      ".dxt.dds.z.bin, .dxt.dds.bin, .rgb.pvr.z, .atc.dds.z) into "
                      "PNG or plain DDS")
    bl_options = {"REGISTER"}

    source: StringProperty(
        name="Source", subtype="DIR_PATH",
        description="A car folder, or any folder below the depot",
    )
    target: StringProperty(
        name="Write to", subtype="DIR_PATH",
        description="Where the PNG/DDS files go",
    )
    fmt: EnumProperty(
        name="Format",
        items=(("png", "PNG", "Decode to 8-bit PNG (needs no DDS support)"),
               ("dds", "DDS", "Keep the original block data")),
        default="png",
    )
    frame: IntProperty(
        name="Frame", default=0, min=0,
        description="Which frame of a multi-frame shadow map to use (0 = first)",
    )
    skip_existing: BoolProperty(name="Skip existing files", default=True)

    def invoke(self, context, event):
        if not self.source:
            self.source = bpy.path.abspath("//")
        if not self.target:
            self.target = os.path.join(tempfile.gettempdir(), "rr3_textures")
        return context.window_manager.invoke_props_dialog(self, width=560)

    def execute(self, context):
        src = bpy.path.abspath(self.source)
        dst = bpy.path.abspath(self.target)
        if not os.path.isdir(src):
            self.report({"ERROR"}, f"not a folder: {src}")
            return {"CANCELLED"}
        try:
            report = texportlib.export_tree(src, dst, self.fmt,
                                            skip_existing=self.skip_existing)
        except Exception as exc:  # noqa: BLE001
            self.report({"ERROR"}, f"RR3 texture export failed: {exc}")
            return {"CANCELLED"}
        written = len(report["written"])
        failed = report["failed"]
        skipped = len(report["skipped"])
        lines = [f"=== {src} -> {dst} ({self.fmt}) ===",
                 f"{written} written, {skipped} skipped, {len(failed)} failed"]
        for name, why in failed[:200]:
            lines.append(f"  FAILED {name}: {why}")
        block = bpy.data.texts.get("rr3_textures") or bpy.data.texts.new("rr3_textures")
        block.clear()
        block.write("\n".join(lines))
        if failed:
            self.report({"WARNING"},
                        f"{written} written, {len(failed)} failed (see the Text Editor)")
        else:
            self.report({"INFO"}, f"{written} texture(s) written to {dst}")
        return {"FINISHED"}


class RR3_OT_load_textures(bpy.types.Operator):
    bl_idname = "rr3.load_textures"
    bl_label = "Load Car Textures"
    bl_description = ("Decode every atlas and ramp of the selected car straight "
                      "into Blender images, so materials can use them")
    bl_options = {"REGISTER"}

    car_dir: StringProperty(name="Car folder", subtype="DIR_PATH")

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=560)

    def execute(self, context):
        car_dir = bpy.path.abspath(self.car_dir)
        if not os.path.isdir(car_dir):
            self.report({"ERROR"}, f"not a folder: {car_dir}")
            return {"CANCELLED"}
        try:
            report = _load_car_textures(car_dir)
        except Exception as exc:  # noqa: BLE001
            self.report({"ERROR"}, f"RR3 texture load failed: {exc}")
            return {"CANCELLED"}
        self.report({"INFO"},
                    f"{len(report['images'])} image(s) loaded, "
                    f"{len(report['failed'])} failed, "
                    f"{report['purged']['files']} stale file(s) and "
                    f"{report['purged']['images']} stale image(s) removed")
        return {"FINISHED"}


class RR3_OT_load_texture_files(bpy.types.Operator):
    """Decode exactly the texture files you pick, and nothing else.

    The whole-car loader above guesses which atlases a car needs from its livery
    table, so it cannot find art the table never mentions - special tyre treads,
    one-off interior sheets, a shader ramp you want to look at on its own.  This
    one takes a file list, so anything the game ships can be pulled in.
    """
    bl_idname = "rr3.load_texture_files"
    bl_label = "Load Textures"
    bl_description = ("Decode any number of game texture files (.dxt/.etc/.atc/"
                      ".ptc/.rgb.pvr, zipped or not) into Blender images")
    bl_options = {"REGISTER", "UNDO"}

    files: CollectionProperty(name="Files", type=bpy.types.OperatorFileListElement)
    directory: StringProperty(subtype="DIR_PATH")
    filter_glob: StringProperty(
        default="*.z;*.bin;*.dds;*.pvr;*.dxt;*.etc;*.atc;*.ptc",
        options={"HIDDEN"})
    as_ramps: BoolProperty(
        name="Treat as data (non-colour)",
        default=False,
        description="Tag the images Non-Color - what the 1024x1 shader ramps "
                    "need; leave it off for albedo and decal sheets")

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        directory = bpy.path.abspath(self.directory)
        names = [f.name for f in self.files if f.name]
        if not names:
            self.report({"ERROR"}, "no files picked")
            return {"CANCELLED"}
        cache = {}
        loaded, failed = [], []
        for name in names:
            path = os.path.join(directory, name) if directory else name
            if not os.path.isfile(path):
                failed.append((name, "not a file"))
                continue
            img = _image_for_path(path, cache)
            if img is None:
                failed.append((name, "decode failed"))
                continue
            if self.as_ramps:
                img.colorspace_settings.name = "Non-Color"
            loaded.append(img.name)
        if failed:
            for name, why in failed[:6]:
                print(f"[rr3] texture {name}: {why}")
        self.report({"INFO"} if loaded else {"ERROR"},
                    f"{len(loaded)} image(s) loaded, {len(failed)} failed")
        return {"FINISHED"} if loaded else {"CANCELLED"}


# --------------------------------------------------------------------------
# the N panel
# --------------------------------------------------------------------------
class RR3_PT_panel(bpy.types.Panel):
    bl_label = "Real Racing 3"
    bl_idname = "RR3_PT_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "RR3"

    def draw(self, context):
        layout = self.layout

        box = layout.box()
        box.label(text="Import", icon="IMPORT")
        col = box.column(align=True)
        col.operator("import_scene.rr3_vehicle", text="Whole car (folder)", icon="OUTLINER_OB_GROUP_INSTANCE")
        col.operator("import_scene.rr3_m3g", text="Model (.m3g)", icon="MESH_DATA")
        col.operator("import_scene.rr3_m3g_raw", text="Generic model (.m3g)", icon="MESH_CUBE")
        col.operator("import_scene.rr3_banim_clips", text="Animation clips (.banim + XML)",
                     icon="ARMATURE_DATA")
        col.operator("import_scene.rr3_banim_empties", text="Animation as empties (.banim)",
                     icon="EMPTY_AXIS")
        col.operator("import_scene.rr3_points", text="Anchors (.points)", icon="EMPTY_ARROWS")
        col.operator("import_scene.rr3_driver", text="Driver (posed)", icon="ARMATURE_DATA")

        box = layout.box()
        box.label(text="Export", icon="EXPORT")
        col = box.column(align=True)
        col.operator("export_scene.rr3_m3g", text="Model (.m3g)", icon="MESH_DATA")
        col.operator("export_scene.rr3_m3g_raw", text="Generic model (.m3g)", icon="MESH_CUBE")
        col.operator("export_scene.rr3_points", text="Anchors (.points)", icon="EMPTY_ARROWS")
        col.operator("export_scene.rr3_banim", text="Part animation (.banim)", icon="EMPTY_AXIS")
        col.operator("export_scene.rr3_animxml", text="Animation clips (.xml)", icon="FILE_TEXT")

        box = layout.box()
        box.label(text="Textures", icon="TEXTURE")
        col = box.column(align=True)
        col.operator("rr3.export_textures", text="Export textures", icon="FILE_IMAGE")
        col.operator("rr3.load_textures", text="Load car textures", icon="IMAGE_DATA")
        col.operator("rr3.load_texture_files", text="Load textures (pick files)",
                     icon="FILEBROWSER")

        box = layout.box()
        box.label(text="Car", icon="AUTO")
        col = box.column(align=True)
        col.operator("rr3.build_car", text="Build a new car", icon="ADD")
        col.operator("rr3.set_part_material", text="Set part material", icon="MATERIAL")
        col.operator("rr3.switch_paint", text="Switch paint scheme", icon="COLOR")
        col.operator("rr3.audit_paint", text="Audit part materials", icon="VIEWZOOM")

        box = layout.box()
        box.label(text="Reference", icon="INFO")
        col = box.column(align=True)
        col.operator("rr3.catalog", text="Material / part catalog", icon="TEXT")
        col.operator("rr3.report_to_text", text="File report", icon="TEXT")

        box = layout.box()
        box.label(text="Notes", icon="QUESTION")
        for line in ("One .m3g holds one LOD level.",
                     "  Export names it after the level",
                     "  (LOD_A.m3g, SHARED.m3g, INT_A.m3g)",
                     "  and the manager reads those names.",
                     "Animation basis == Blender basis:",
                     "  AERO_* empty loc/rot ARE the",
                     "  engine values (metres, radians).",
                     "Anchors sit at Rot180Z @ engine.",
                     "Active aero needs the empty token in",
                     "  the spec replaced by DeployWhenBraking,",
                     "  and a .banim + _animations.xml pair."):
            box.label(text=line)


# --------------------------------------------------------------------------
# registration
# --------------------------------------------------------------------------
class EXPORT_OT_rr3_m3g(bpy.types.Operator, ExportHelper):
    bl_idname = "export_scene.rr3_m3g"
    bl_label = "Export RR3 Model (.m3g)"
    bl_description = "Write the selected mesh objects (or all meshes) as a Real Racing 3 .m3g"
    bl_options = {"REGISTER"}

    filename_ext = ".m3g"
    filter_glob: StringProperty(default="*.m3g", options={"HIDDEN"})

    template: StringProperty(name="Template .m3g", subtype="FILE_PATH",
                             description="Copy the material list and author from this file")
    all_objects: BoolProperty(name="Export all meshes", default=False)
    use_world: BoolProperty(
        name="Apply object transforms", default=True,
        description="Bake each object's transform into the vertices. Meshes that "
                    "are animated are always written around their own origin "
                    "instead - the game places them at pivot + R @ vertex")
    flip_v: BoolProperty(name="Flip V", default=True)
    name_as: EnumProperty(
        name="File name",
        items=(("LOD", "The level it belongs to (LOD_A.m3g)",
                "Name the file after the collection the meshes are in, which is "
                "what the manager reads: LOD_A.m3g, SHARED.m3g, INT_A.m3g ..."),
               ("KEEP", "Whatever I typed in the file browser", "")),
        default="LOD",
        description="One .m3g holds one level, so the level is part of the name")
    pos_scale: FloatProperty(
        name="Position scale",
        default=0.0,
        min=0.0,
        soft_max=0.01,
        precision=6,
        description="Raw vertex units per metre: the file stores raw = metres / "
                    "scale, like the shipped cars (0.0022). 0 = use the template's "
                    "value, else fit the model to +-1024 raw units. Do not use 1.0: "
                    "the engine then takes a slow vertex path (stutter, broken "
                    "highlights)",
    )

    def execute(self, context):
        try:
            from . import m3gexport
            objs = [o for o in context.scene.objects if o.type == "MESH"] \
                if self.all_objects else ([o for o in context.selected_objects if o.type == "MESH"] \
                                          or [o for o in context.scene.objects if o.type == "MESH"])
            mixed = _lod_mixture(objs)
            if mixed:
                self.report({"ERROR"},
                            f"those meshes span LOD levels {', '.join(mixed)} - a .m3g "
                            "holds one level, so select one level at a time (they are "
                            "in <car>_LOD<X> collections)")
                return {"CANCELLED"}
            blob, n, scale = m3gexport.build_from_objects(
                objs, template=self.template or None, use_world=self.use_world,
                flip_v=self.flip_v, position_scale=self.pos_scale or None)
            out = self.filepath
            if self.name_as == "LOD":
                named = _lod_filename(objs)
                if named:
                    out = os.path.join(os.path.dirname(out), named)
            with open(out, "wb") as fh:
                fh.write(blob)
        except Exception as exc:  # noqa: BLE001
            self.report({"ERROR"}, f"RR3 m3g export failed: {exc}")
            return {"CANCELLED"}
        self.report({"INFO"},
                    f"wrote {os.path.basename(out)}, {n} part(s), {len(blob)} bytes, "
                    f"positionScale {scale:.10f}")
        if abs(scale - 1.0) < 1e-6:
            self.report({"WARNING"},
                        "positionScale == 1.0: the file is valid but the engine takes its "
                        "slow vertex path (scan line stutter, missing highlights)")
        return {"FINISHED"}


class EXPORT_OT_rr3_m3g_raw(bpy.types.Operator, ExportHelper):
    """Write any meshes as a plain .m3g the game can read - no template needed.

    The car exporter next door rebuilds a shipped car from a template so it keeps
    that car's material list, part descriptors and morph tails.  That is exactly
    what you do *not* want for a driver, a track prop or a test cube: those have
    no template to copy.  This one writes the meshes on their own and picks a
    position scale from the model.
    """
    bl_idname = "export_scene.rr3_m3g_raw"
    bl_label = "Export Generic Model (.m3g)"
    bl_description = ("Write the selected meshes (or all meshes) as a .m3g with no "
                      "template: material names come from the objects")
    bl_options = {"REGISTER"}

    filename_ext = ".m3g"
    filter_glob: StringProperty(default="*.m3g", options={"HIDDEN"})

    all_objects: BoolProperty(name="Export all meshes", default=False)
    use_world: BoolProperty(name="Apply object transforms", default=True)
    flip_v: BoolProperty(name="Flip V", default=True)
    scale_mode: EnumProperty(
        name="Position scale",
        items=(("AUTO", "Fit to +-1024 raw units",
                "How the cars are stored: raw = metres / 0.0022, so the vertices "
                "use the whole 16-bit range"),
               ("METRES", "Metres (positionScale 1.0)",
                "How the drivers and track models are stored: the raw integers are "
                "the metres, and the engine takes a slower vertex path"),
               ("FIXED", "Same as a shipped car (0.0021973)",
                "For a replacement car part, so it matches the file it goes into")),
        default="AUTO")
    pos_scale: FloatProperty(
        name="Custom scale", default=0.0, min=0.0, soft_max=0.01, precision=8,
        description="Raw vertex units per metre; overrides the choice above when "
                    "it is not 0")

    def execute(self, context):
        try:
            from . import m3gexport
            objs = [o for o in context.scene.objects if o.type == "MESH"] \
                if self.all_objects else ([o for o in context.selected_objects if o.type == "MESH"] \
                                          or [o for o in context.scene.objects if o.type == "MESH"])
            if self.pos_scale:
                scale = float(self.pos_scale)
            elif self.scale_mode == "METRES":
                scale = 1.0
            elif self.scale_mode == "FIXED":
                scale = m3gexport.m3gwrite.FACTORY_POSITION_SCALE
            else:
                scale = None
            blob, n, scale = m3gexport.build_from_objects(
                objs, template=None, use_world=self.use_world,
                flip_v=self.flip_v, position_scale=scale)
            with open(self.filepath, "wb") as fh:
                fh.write(blob)
        except Exception as exc:  # noqa: BLE001
            self.report({"ERROR"}, f"RR3 generic m3g export failed: {exc}")
            return {"CANCELLED"}
        self.report({"INFO"},
                    f"wrote {n} part(s), {len(blob)} bytes, positionScale {scale:.10f}")
        return {"FINISHED"}


def menu_func_export(self, context):
    self.layout.operator(EXPORT_OT_rr3_m3g.bl_idname, text="Real Racing 3 (.m3g)")
    self.layout.operator(EXPORT_OT_rr3_m3g_raw.bl_idname,
                         text="Real Racing 3 generic (.m3g)")


classes = (
    # import
    IMPORT_OT_rr3_vehicle,
    IMPORT_OT_rr3_m3g,
    IMPORT_OT_rr3_m3g_raw,
    IMPORT_OT_rr3_banim,
    IMPORT_OT_rr3_banim_clips,
    IMPORT_OT_rr3_banim_empties,
    IMPORT_OT_rr3_points,
    IMPORT_OT_rr3_driver,
    # export
    EXPORT_OT_rr3_m3g,
    EXPORT_OT_rr3_m3g_raw,
    EXPORT_OT_rr3_points,
    EXPORT_OT_rr3_banim,
    EXPORT_OT_rr3_animxml,
    # car
    RR3_OT_build_car,
    RR3_OT_set_paint,
    RR3_OT_switch_paint,
    RR3_OT_audit_paint,
    RR3_OT_catalog,
    # reports and panel
    RR3_OT_report_to_text,
    RR3_OT_export_textures,
    RR3_OT_load_textures,
    RR3_OT_load_texture_files,
    RR3_PT_panel,
)


def menu_func_import(self, context):
    self.layout.operator(IMPORT_OT_rr3_vehicle.bl_idname,
                         text="Real Racing 3 Car Folder (m3g + points + banim)")
    self.layout.operator(IMPORT_OT_rr3_m3g.bl_idname,
                         text="Real Racing 3 Model (.m3g)")
    self.layout.operator(IMPORT_OT_rr3_banim_clips.bl_idname,
                         text="Real Racing 3 Animation Clips (.banim + XML)")
    self.layout.operator(IMPORT_OT_rr3_driver.bl_idname,
                         text="Real Racing 3 Driver")
    self.layout.operator(IMPORT_OT_rr3_banim_empties.bl_idname,
                         text="Real Racing 3 Animation as Empties (.banim)")
    self.layout.operator(IMPORT_OT_rr3_banim.bl_idname,
                         text="Real Racing 3 Animation on a Model (.banim)")
    self.layout.operator(IMPORT_OT_rr3_points.bl_idname,
                         text="Real Racing 3 Anchors (.points)")


def menu_func_export(self, context):
    self.layout.operator(EXPORT_OT_rr3_m3g.bl_idname,
                         text="Real Racing 3 Model (.m3g)")
    self.layout.operator(EXPORT_OT_rr3_points.bl_idname,
                         text="Real Racing 3 Anchors (.points)")
    self.layout.operator(EXPORT_OT_rr3_banim.bl_idname,
                         text="Real Racing 3 Part Animation (.banim)")
    self.layout.operator(EXPORT_OT_rr3_animxml.bl_idname,
                         text="Real Racing 3 Animation Clips (.xml)")


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)
    bpy.types.TOPBAR_MT_file_export.append(menu_func_export)


def unregister():
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)
    bpy.types.TOPBAR_MT_file_export.remove(menu_func_export)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
