"""Turn parsed RR3 ``.m3g`` objects into plain Python geometry.

The ``.m3g`` files used by Real Racing 3 store geometry as

    Mesh -> VertexBuffer -> VertexArray(s) + IndexBuffer

with every cross reference stored as a 1-based object-table index.  This module
resolves those references and returns simple float tuples so that both the text
dumper and the Blender importer can share the same code.

Coordinates are used exactly as stored in the file (no unit conversion, no axis
swapping).  Callers decide how to place the model.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from . import m3g as m3glib
from .m3g import M3G, Obj

Vec3 = tuple[float, float, float]

# --- texture coordinates -------------------------------------------------
# RR3 stores UVs in a 4x4 "tile" space: u spans 0..4 and v spans -3..1.  The
# game's shader divides by 4 and flips v.  The transform below maps the observed
# ranges exactly onto 0..1, which is what Blender (and any glTF consumer) wants:
#     u' = u / 4
#     v' = (1 - v) / 4
# Keeping it here (instead of changing the parser) means the text dumps still
# show the raw numbers.
UV_SCALE = 0.25
UV_FLIP_V = True


def blender_uvs(uvs: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Convert stored UVs to the 0..1, V-up convention Blender expects."""
    out = []
    for u, v in uvs:
        uu = u * UV_SCALE
        vv = (1.0 - v) * UV_SCALE if UV_FLIP_V else v * UV_SCALE
        out.append((uu, vv))
    return out


@dataclass
class Submesh:
    index_buffer: int = 0
    appearance: int = 0
    first_index: int = 0
    index_count: int = 0
    is_strip: bool = False
    triangles: list[tuple[int, int, int]] = field(default_factory=list)


@dataclass
class MeshData:
    name: str
    material_id: int
    material_name: str
    positions: list[Vec3]
    normals: list[Vec3]
    colors: list[tuple[float, float, float, float]]
    uvs: list[tuple[float, float]]
    submeshes: list[Submesh]
    position_scale: float
    position_bias: Vec3
    texcoord_scale: tuple[float, float]
    texcoord_bias: tuple[float, float]
    warnings: list[str] = field(default_factory=list)

    @property
    def triangles(self) -> list[tuple[int, int, int]]:
        out: list[tuple[int, int, int]] = []
        for s in self.submeshes:
            out.extend(s.triangles)
        return out

    @property
    def bbox(self) -> tuple[Vec3, Vec3] | None:
        if not self.positions:
            return None
        xs = [p[0] for p in self.positions]
        ys = [p[1] for p in self.positions]
        zs = [p[2] for p in self.positions]
        return (min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs))


def _chunks(values: list[float], n: int) -> list[tuple]:
    return [tuple(values[i : i + n]) for i in range(0, len(values) - n + 1, n)]


def _strip_to_triangles(strip: list[int]) -> list[tuple[int, int, int]]:
    tris = []
    for i in range(len(strip) - 2):
        a, b, c = strip[i], strip[i + 1], strip[i + 2]
        if i % 2:
            a, b = b, a
        if a != b and b != c and a != c:
            tris.append((a, b, c))
    return tris


def _index_triangles(ib: Obj) -> tuple[list[tuple[int, int, int]], bool]:
    idx = [int(v) for v in ib.data.get("indices", [])]
    lengths = ib.data.get("stripLengths") or []
    strip = bool(ib.data.get("isTriStrip"))
    if not idx:
        return [], strip
    if not strip and not lengths:
        return [tuple(idx[i : i + 3]) for i in range(0, len(idx) - 2, 3)], False
    tris: list[tuple[int, int, int]] = []
    pos = 0
    for ln in lengths or [len(idx)]:
        part = idx[pos : pos + ln]
        pos += ln
        if strip:
            tris.extend(_strip_to_triangles(part))
        else:
            tris.extend(tuple(part[i : i + 3]) for i in range(0, len(part) - 2, 3))
    return tris, strip


def extract_mesh(m: M3G, mesh: Obj) -> MeshData:
    d = mesh.data
    name = d.get("name", f"mesh{mesh.index}")
    material_id = int(d.get("materialId", 0) or 0)
    materials = m.materials
    # RR3 writes a 0-based index into the material list, not the 1-based
    # index the JSR-184 spec suggests: 91/91 Reventon meshes only match the
    # ``_mm_<tag>`` suffix in their own name with the 0-based reading.
    material_name = materials[material_id] if 0 <= material_id < len(materials) else ""

    vb = m.resolve(d.get("vertexBuffer"), m3glib.T_VERTEX_BUFFER)
    data = vb.data if vb is not None else {}
    pos_va = m.resolve(data.get("positions"), m3glib.T_VERTEX_ARRAY)
    scale = float(data.get("positionScale", 1.0) or 1.0)
    bias = tuple(float(v) for v in (data.get("positionBias") or (0.0, 0.0, 0.0)))

    positions: list[Vec3] = []
    if pos_va is not None:
        vals = [float(v) for v in pos_va.data.get("values", [])]
        positions = [
            (x * scale + bias[0], y * scale + bias[1], z * scale + bias[2])
            for x, y, z in _chunks(vals, 3)
        ]

    normals: list[Vec3] = []
    nrm_va = m.resolve(data.get("normals"), m3glib.T_VERTEX_ARRAY)
    if nrm_va is not None:
        vals = [float(v) for v in nrm_va.data.get("values", [])]
        # RR3 stores normals as fixed point with 4096 == 1.0 (|n| comes out as
        # ~4096), so normalise them: Blender's custom split normals need unit
        # vectors, otherwise the shading is half-bright / half-dark.
        for x, y, z in _chunks(vals, 3):
            ln = math.sqrt(x * x + y * y + z * z)
            if ln > 1e-9:
                normals.append((x / ln, y / ln, z / ln))
            else:
                normals.append((0.0, 0.0, 1.0))

    colors: list[tuple[float, float, float, float]] = []
    col_va = m.resolve(data.get("colors"), m3glib.T_VERTEX_ARRAY)
    if col_va is not None:
        vals = [float(v) for v in col_va.data.get("values", [])]
        n = int(col_va.data.get("componentCount", 4) or 4)
        size = int(col_va.data.get("componentSize", 1) or 1)
        div = 255.0 if (n == 4 and size == 1) else 1.0
        for c in _chunks(vals, n):
            c = tuple(v / div for v in c)
            colors.append((c + (1.0,) * 4)[:4])
    else:
        rgba = data.get("colorRGBA") or (255, 255, 255, 255)
        colors = [tuple(float(c) / 255.0 for c in rgba[:4])] * len(positions)

    uvs: list[tuple[float, float]] = []
    tc_scale = (1.0, 1.0)
    tc_bias = (0.0, 0.0)
    layers = data.get("texcoords") or []
    if layers:
        layer = layers[0]
        tc_scale = (float(layer.get("scale", 1.0)), float(layer.get("scale", 1.0)))
        b = layer.get("bias") or (0.0, 0.0, 0.0)
        tc_bias = (float(b[0]), float(b[1]))
        tc_va = m.resolve(layer.get("array"), m3glib.T_VERTEX_ARRAY)
        if tc_va is not None:
            vals = [float(v) for v in tc_va.data.get("values", [])]
            n = int(tc_va.data.get("componentCount", 2) or 2)
            for i in range(0, len(vals) - n + 1, n):
                u = vals[i] * tc_scale[0] + tc_bias[0]
                v = vals[i + 1] * tc_scale[1] + tc_bias[1]
                uvs.append((u, v))

    warnings: list[str] = []
    submeshes: list[Submesh] = []
    for si, sub in enumerate(d.get("submeshes") or []):
        ib = m.resolve(sub.get("indexBuffer"), m3glib.T_TRI_STRIP_ARRAY)
        if ib is None:
            warnings.append(f"submesh {si}: index buffer not resolvable")
            continue
        tris, strip = _index_triangles(ib)
        idx = [int(v) for v in ib.data.get("indices", [])]
        submeshes.append(
            Submesh(
                index_buffer=int(ib.index),
                appearance=int(sub.get("appearance") or 0),
                first_index=0,
                index_count=len(idx),
                is_strip=strip,
                triangles=tris,
            )
        )

    top = max((i for t in submeshes for tri in t.triangles for i in tri), default=-1)
    if positions and top >= len(positions):
        warnings.append(
            f"index {top} exceeds the {len(positions)} available positions"
        )

    return MeshData(
        name=name,
        material_id=material_id,
        material_name=material_name,
        positions=positions,
        normals=normals,
        colors=colors,
        uvs=uvs,
        submeshes=submeshes,
        position_scale=scale,
        position_bias=bias,  # type: ignore[arg-type]
        texcoord_scale=tc_scale,
        texcoord_bias=tc_bias,
        warnings=warnings,
    )


def all_meshes(m: M3G) -> list[MeshData]:
    return [extract_mesh(m, o) for o in m.of_type(m3glib.T_MESH)]


def format_report(m: M3G) -> str:
    """Human readable structural dump of a ``.m3g`` file."""
    out: list[str] = []
    a = out.append
    a("# RR3 .m3g dump")
    a(f"file: {m.path}")
    a(f"bytes: {len(m.buf)}")
    a(f"version: {m.version}")
    a(f"author: {m.author!r}")
    a(f"objects: {len(m.objects)}")
    a(f"sections: {len(m.sections)}")
    for s in m.sections:
        a(
            f"  section {s['index']}: compression={s['compression']} "
            f"totalLength={s['totalLength']} uncompressed={s['uncompressedLength']} "
            f"objects={s['objects']} checksum={s['checksum']}"
        )
    counts: dict[int, int] = {}
    for o in m.objects:
        counts[o.type] = counts.get(o.type, 0) + 1
    a("object types: " + ", ".join(f"{t}={c}" for t, c in sorted(counts.items())))
    mats = m.materials
    if mats:
        a(f"materials ({len(mats)}):")
        for i, n in enumerate(mats):
            a(f"  [{i:2d}] {n}")
    a("")
    meshes = m.of_type(m3glib.T_MESH)
    a(f"meshes ({len(meshes)}):")
    total_v = total_t = 0
    for o in meshes:
        md = extract_mesh(m, o)
        bb = md.bbox
        total_v += len(md.positions)
        total_t += len(md.triangles)
        a(
            f"  obj {o.index:4d} {md.name!r} material={md.material_id} "
            f"({md.material_name!r}) verts={len(md.positions)} "
            f"tris={len(md.triangles)} submeshes={len(md.submeshes)}"
        )
        a(
            f"      positionScale={md.position_scale!r} "
            f"positionBias={md.position_bias} "
            f"texcoordScale={md.texcoord_scale} texcoordBias={md.texcoord_bias}"
        )
        if bb:
            a(
                "      bbox min=(%.6f, %.6f, %.6f) max=(%.6f, %.6f, %.6f)"
                % (*bb[0], *bb[1])
            )
        for si, sub in enumerate(md.submeshes):
            a(
                f"      submesh {si}: indexBuffer={sub.index_buffer} "
                f"appearance={sub.appearance} indices={sub.index_count} "
                f"strip={sub.is_strip} tris={len(sub.triangles)}"
            )
        for w in md.warnings:
            a(f"      ! {w}")
    a(f"total: {len(meshes)} meshes, {total_v} vertices, {total_t} triangles")
    if m.warnings:
        a("")
        a("warnings:")
        for w in m.warnings:
            a(f"  ! {w}")
    return "\n".join(out) + "\n"
