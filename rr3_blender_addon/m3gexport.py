"""Blender objects -> RR3 .m3g (write side).

The reader lives in ``rr3lib.m3g``; the byte level writer in ``rr3lib.m3gwrite``.
This module only bridges Blender data to those builders:

* positions stay in metres here; ``rr3lib.m3gwrite`` stores them as float raw
  units plus a per-file ``positionScale`` (~0.0022, the shipped cars use e.g.
  0.0022958945482969284 for the Reventon body).  Never write ``scale = 1.0``:
  the engine then puts the mesh on a slow generic vertex path (in game:
  stuttering draw calls and missing highlights - v37 of the LFA, 2026-10-24);
* normals and colours are int16 with 4096 == 1.0;
* uvs are int16 with 512 == one UV tile, and the file convention is
  ``v = 1 - v_blender`` inside every tile;
* a colour vertex array is mandatory, every shipped mesh has one.

Part names matter: the engine looks parts up by their exact name, a mesh with an
unknown name is silently skipped (it does not crash).
"""

from __future__ import annotations

import math

from pathlib import Path

import bpy
from mathutils import Matrix, Vector

from .rr3lib import m3g, m3gwrite

#: Last resort encoding scale when neither the template nor the geometry can
#: supply one (the shipped cars use their own per-file value, see
#: ``rr3lib.m3gwrite.FACTORY_POSITION_SCALE``).
DEFAULT_POS_SCALE = m3gwrite.FACTORY_POSITION_SCALE
DEFAULT_UV_SCALE = 0.001953125              # 1/512, one UV tile
NRM_FIXED = 4096.0
UV_FIXED = 512.0


def read_template(path):
    """Material names, author and per part name the unknown byte blocks.

    The two opaque blocks inside a mesh payload (81 bytes after the kind, 50
    bytes after the name) are not constant across parts - a mesh carrying a
    block taken from a different part crashes the renderer - so they are copied
    from the template part with the same name, and a part the template does not
    know simply keeps the generic template values.
    """
    if not path:
        return [], m3gwrite.DEFAULT_AUTHOR, {}
    doc = m3g.M3G(str(path))
    raw = Path(str(path)).read_bytes()
    names = []
    for obj in doc.objects:
        if obj.type == m3g.T_MATERIAL_LIST:
            names = list(obj.data.get("materials") or [])
            break
    per_part = {}
    for obj in doc.objects:
        if obj.type != m3g.T_MESH:
            continue
        d = obj.data
        nb = d["name"].encode()
        gap1 = raw[obj.offset + 12:obj.offset + 12 + 81]
        at = d["nameOffset"] + len(nb) + 1
        gap2 = raw[at:at + 50]
        vb = doc.resolve(d["vertexBuffer"], m3g.T_VERTEX_BUFFER)
        parsed = 8 + 4 + 81 + 4 + len(nb) + 1 + 50 + 4 + 4 + 8 * len(d["submeshes"])
        per_part[d["name"]] = {
            "gaps": (gap1, gap2),
            "tail": raw[obj.offset + parsed:obj.offset + obj.length],
            "position_scale": float(vb.data.get("positionScale") or 1.0),
            "material": int(d.get("materialId") or 0),
        }
    return names, (doc.author or m3gwrite.DEFAULT_AUTHOR), per_part


def _fixed(values, scale, count, fallback=0):
    """Clamp/round a float list into fixed point ints."""
    if not values:
        return [fallback] * count
    out = []
    for v in values:
        n = int(round(float(v) * scale))
        out.append(max(-32768, min(32767, n)))
    if len(out) < count:
        out.extend([fallback] * (count - len(out)))
    return out[:count]


# Blender is Z up, the game data is Y up with the nose towards -z.  The importer
# maps (x, y, z) -> (x, -z, y); going back we need (x, y, z) -> (x, z, -y).
UV_TILES = 4.0  # file uvs address a 4x4 tiling of the atlas

#: The largest texcoord the file can hold, in Blender UV units (one unit = one
#: page tile).  The field is int16 with 512 units to the model tile and 4 model
#: tiles to the page, so 32767 / 512 / 4 = 15.99 - and ``m3gwrite`` saturates
#: rather than complaining, which would pin the coordinate to the page corner.
UV_LIMIT = 15.9

_M3G_AXIS = Matrix(((1.0, 0.0, 0.0),
                    (0.0, 0.0, 1.0),
                    (0.0, -1.0, 0.0)))


def _uv_overflows(uv_layer) -> bool:
    """True when any coordinate is past what the int16 texcoord field holds.

    Checked once per mesh, not per vertex, because the answer decides *how* the
    whole set is written: folding one vertex and not its neighbour is exactly
    the discontinuity this test exists to avoid.
    """
    if uv_layer is None:
        return False
    for datum in uv_layer:
        if abs(datum.uv[0]) > UV_LIMIT or abs(datum.uv[1]) > UV_LIMIT:
            return True
    return False


def _has_action(ob) -> bool:
    ad = ob.animation_data
    return bool(ad is not None and ad.action is not None)


def engine_material(ob) -> str:
    """The material name the game expects, not the one Blender shows.

    The vehicle importer rewrites every material into something Blender can
    drive (``2012_lexus_lfa_car_paint_metallic_white_paint``) and keeps the name
    the file had in ``ob["rr3_material"]``.  Writing the Blender name back into
    an exported ``.m3g`` loses the ``_mm_<tag>`` suffix the art pipeline put
    there, and a mesh whose material tag no longer matches its own name is a
    mesh the engine cannot place.

    The tag is taken from the *object* name, because that is the name the engine
    looks the part up by: renaming ``LOD_A_WING_REAR_mm_ext`` to
    ``LOD_A_WING_REAR_mm_misc`` has to change its material too, or the wing
    comes out with the wrong shader.  The prefix (``Vehicle Exterior``,
    ``Vehicle Interior``, ``arms.psd``, ``Multimaterial``) is whatever the
    artists typed and is carried through unchanged.
    """
    name = ob.get("rr3_material") or ""
    if not name and ob.data.materials:
        first = ob.data.materials[0]
        name = first.name if first else ""
    if not name:
        return ""
    tag = ob.name.rpartition("_mm_")[2] if "_mm_" in ob.name else ""
    if not tag:
        return name
    prefix = name.rpartition("_mm_")[0] if "_mm_" in name else name
    return f"{prefix}_mm_{tag}"


def _is_animated(ob) -> bool:
    """True when this mesh is moved by the ``.banim`` rather than by the body.

    A wing part the user split out is animated itself; one the vehicle importer
    rigged is parented to an ``AERO_*`` empty and the empty carries the keys.
    Both cases count: either way the game, not the file, decides where the part
    goes, so the vertices have to stay relative to the part's origin.
    """
    if _has_action(ob):
        return True
    parent = ob.parent
    for _ in range(8):
        if parent is None:
            return False
        if parent.name.startswith("AERO_") or _has_action(parent):
            return True
        parent = parent.parent
    return False


def collect_parts(objects, *, position_scale=None, uv_scale=DEFAULT_UV_SCALE,
                  use_world=False, flip_v=True, merge=False, convert_axes=True,
                  local_when_animated=True, wrap_uv=True):
    """Turn Blender mesh objects into ``m3gwrite.MeshPart`` values.

    Positions stay in metres; ``rr3lib.m3gwrite`` divides them by the file level
    position scale when it packs the raw vertex array.  Pass ``position_scale``
    only to pin the encoding of these parts (usually a template's per-file
    value, or nothing at all).

    ``local_when_animated`` overrides ``use_world`` for a mesh that is animated
    (it has an action of its own, or its parent does).  A ``.m3g`` has no node
    tree, so an animated part's motion can only live in the ``.banim``: the game
    puts the part at ``pivot + R @ vertex``, which means the vertices have to be
    measured from the part's own origin.  Baking the world transform in as well
    would place the part at ``pivot + R @ (vertex + origin)`` - twice its offset
    from the car, which is why a wing exported that way floats away from the
    body.  Static parts are unaffected: they sit at their origin anyway.

    ``wrap_uv`` folds a UV set into 0..1 **only when it would not fit the
    field**.  The texcoord array is int16 with 512 units to the tile, so the
    largest coordinate the file can hold is 16 page tiles, and anything past
    that is silently saturated to the corner - the shipped data does run past it
    (the No Limits grille to u = 19, a decal strip to u = 51), so folding is
    still the fallback.

    But folding is lossy in a way that only shows on a *tiled* material: a
    triangle whose corners straddle a tile boundary gets ``u % 1`` on both ends
    and then interpolates *backwards* across the tile, which draws as a smear.
    92% of this car's carbon triangles do exactly that, so a UV set that fits is
    now written verbatim - the sampler repeats with period one either way, and
    a coordinate of 10 tiles is both representable and correct.  Pass
    ``wrap_uv=False`` to write a set verbatim even when it does not fit; that
    only makes sense when the caller knows the range.
    """
    parts = []
    for ob in objects:
        if ob.type != "MESH" or not ob.data.polygons:
            continue
        me = ob.data
        me.calc_loop_triangles()
        world = ob.matrix_world if use_world else None
        if world is not None and local_when_animated and _is_animated(ob):
            world = None

        uv_layer = me.uv_layers.active.data if me.uv_layers.active else None
        fold = wrap_uv and _uv_overflows(uv_layer)
        col_layer = None
        for attr in me.color_attributes:
            if attr.domain == "POINT":
                col_layer = attr.data
                break

        uvs = []
        for tri in me.loop_triangles:
            for li in tri.loops:
                if uv_layer is not None:
                    u, v = uv_layer[li].uv
                    if fold:
                        u %= 1.0
                        v %= 1.0
                else:
                    u, v = 0.0, 0.0
                # The shipped data addresses a 4x4 tiling of the atlas and the
                # importer used u' = u / 4, v' = (1 - v) / 4.
                #
                # U inverts to u = 4 u'.  V is not symmetric with it: the vertex
                # buffer declares a texcoord bias of +1.0 (see
                # ``m3gwrite.vertex_buffer``: a model bias of (0, 1, 0) is
                # stored as 0.0 and the reader adds the 1.0 back), so the model
                # space v the importer flipped is already ``raw/512 + 1``.  The
                # 1.0 in ``1 - 4v`` therefore cancels against that bias and the
                # stored value is simply ``-4 v'``.  Writing ``1 - 4v'`` as
                # well shifted every mesh by exactly one atlas tile vertically.
                vv = (-UV_TILES * v) if flip_v else (v * UV_TILES)
                uvs.extend((u * UV_TILES, vv))

        # rebuild the vertex list in loop order so the uv array lines up; the
        # index buffer then simply walks 0..n-1.
        # Normals MUST come from the *corner* (loop) normals: the vertices are
        # already split per loop, so hard edges stay hard.  Using v.normal here
        # averaged every sharp edge away and made cut-out parts (wing) inherit
        # the body's smooth shading.
        corner = _corner_normals(me)
        loop_pos, loop_nrm, loop_col = [], [], []
        for tri in me.loop_triangles:
            for li in tri.loops:
                vi = me.loops[li].vertex_index
                v = me.vertices[vi]
                co = v.co.copy()
                if world is not None:
                    co = world @ co
                if convert_axes:
                    co = _M3G_AXIS @ co
                loop_pos.extend((co.x, co.y, co.z))
                n = corner[li].copy() if corner is not None else v.normal.copy()
                if world is not None:
                    n = (world.to_3x3() @ n)
                    if n.length:
                        n.normalize()
                if convert_axes:
                    n = (_M3G_AXIS @ n)
                    if n.length:
                        n.normalize()
                loop_nrm.extend((n.x, n.y, n.z))
                if col_layer is not None and vi < len(col_layer):
                    c = col_layer[vi].color
                    loop_col.extend((c[0], c[1], c[2]))
                else:
                    loop_col.extend((1.0, 1.0, 1.0))

        # colour attributes come back as 0..1 floats, 0..255 bytes or 0..4096
        # fixed point depending on who wrote them - normalise to 0..1, the
        # writer scales them to the file's 4096 == 1.0 convention
        cmax = max((abs(c) for c in loop_col), default=0.0)
        if cmax > 4000.0:
            loop_col = [c / 4096.0 for c in loop_col]
        elif cmax > 1.5:
            loop_col = [c / 255.0 for c in loop_col]

        indices = list(range(len(loop_pos) // 3))

        mat_name = engine_material(ob)

        parts.append(m3gwrite.MeshPart(
            name=_safe_name(ob.name),
            positions=loop_pos,
            triangles=indices,
            normals=loop_nrm,
            uvs=uvs,
            colors=loop_col,
            material=0,
            uv_scale=uv_scale,
        ))
        parts[-1].extra["material_name"] = mat_name
        if position_scale:
            parts[-1].extra["position_scale"] = float(position_scale)
    return parts


def _corner_normals(me):
    """Per-loop normals, honouring custom split normals and sharp edges.

    ``Mesh.corner_normals`` exists in Blender 4.1+ and already resolves custom
    split normals, auto-smooth and sharp edges; older builds fall back to
    ``calc_normals_split`` which fills ``loop.normal``.  Returns None when
    neither is available so callers can fall back to vertex normals.
    """
    try:
        cn = me.corner_normals
        if cn is not None and len(cn) == len(me.loops):
            return [Vector(c.vector) for c in cn]
    except (AttributeError, TypeError):
        pass
    try:
        me.calc_normals_split()
    except (AttributeError, RuntimeError):
        return None
    try:
        return [Vector(l.normal) for l in me.loops]
    except AttributeError:
        return None


def _safe_name(name):
    out = []
    for ch in name:
        out.append(ch if (ch.isalnum() or ch in "_-.") else "_")
    clean = "".join(out)
    return clean[:63] or "part"


def build(parts, *, materials=None, author=None, position_scale=None) -> bytes:
    return m3gwrite.build_file(parts, list(materials or ["Vehicle Exterior"]),
                               author=author or m3gwrite.DEFAULT_AUTHOR,
                               position_scale=position_scale)


def template_position_scale(per_part):
    """The per-file ``positionScale`` the template was written with, if any.

    A shipped car declares the same scale on every vertex buffer (0.0021973 for
    the LFA, 0.0022959 for the Reventon); taking the most common value keeps a
    handful of odd meshes from hijacking it.  ``1.0`` is treated as "no
    information" - that is what our own older output used, and copying it would
    preserve the bug this scale exists to avoid.
    """
    counts: dict[float, int] = {}
    for info in (per_part or {}).values():
        s = float(info.get("position_scale") or 0.0)
        if s > 1e-6 and abs(s - 1.0) > 1e-4:
            counts[s] = counts.get(s, 0) + 1
    if not counts:
        return 0.0
    return max(counts.items(), key=lambda kv: kv[1])[0]


def build_from_objects(objects, *, template=None, position_scale=None,
                       uv_scale=DEFAULT_UV_SCALE, use_world=False, flip_v=True,
                       author=None, parts_info=None, wrap_uv=True):
    mat_names, tpl_author, per_part = read_template(template)
    scale = float(position_scale or 0.0) or template_position_scale(per_part) or None
    parts = collect_parts(objects, position_scale=scale,
                          uv_scale=uv_scale, use_world=use_world, flip_v=flip_v,
                          wrap_uv=wrap_uv)
    if not parts:
        raise ValueError("no mesh objects with faces to export")
    if scale is None:
        # resolve the same way m3gwrite.build_file would, so the caller can
        # report the value that actually went into the vertex buffers
        scale = m3gwrite.auto_position_scale(parts)
    # Write the parts in the template's order, not the collection's.  Nothing in
    # the format requires it, but every shipped file puts the body shell first
    # and the damage and camera variants after it, and matching that keeps a
    # rebuilt file comparable with the one it replaces.  A part the template
    # never had (a wing cut out of the body) keeps its place among the rest and
    # lands wherever its name falls.
    tpl_order = {name: i for i, name in enumerate(per_part)}
    parts.sort(key=lambda p: tpl_order.get(p.name, len(tpl_order)))
    # The material list keeps the template's order, gaps and all.  Rebuilding it
    # in first-use order looks tidier and is wrong: a shipped LOD A carries five
    # to seven slots no mesh refers to, and the index in each mesh is a position
    # in *that* list.  Reordering it silently points every mesh at a different
    # material - the LFA ended up with the paint slot reading the badges atlas,
    # which the game draws as the magenta "missing texture" checkerboard.
    final = list(mat_names) or ["Vehicle Exterior"]
    for part in parts:
        info = per_part.get(part.name)
        if info:
            part.gaps = info["gaps"]
            if info.get("tail"):
                part.extra["tail"] = info["tail"]
        name = part.extra.get("material_name") or ""
        if not name and info and 0 <= info.get("material", 0) < len(mat_names):
            name = mat_names[info["material"]]
        if name not in final:
            # a part the template never had, so its material is new too
            final.append(name)
        part.material = final.index(name)
    blob = build(parts, materials=final, author=author or tpl_author,
                 position_scale=scale)
    return blob, len(parts), float(scale)
