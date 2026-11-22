"""Writer for the Real Racing 3 flavour of JSR-184 (.m3g) files.

The reader in :mod:`rr3lib.m3g` was reverse engineered field by field from the
shipped assets, so this module is the mirror image of it: it emits exactly the
same payload layouts.

Two ways to use it:

* :func:`rebuild_exact` - re-serialise a parsed file byte for byte (used as a
  self test: if the framing were wrong the bytes would not match).
* :class:`M3GBuilder` - assemble a brand new file from vertex data, i.e. what a
  Blender/FBX exporter needs.

Both emit the RR3 variants, not the strict JSR-184 ones:

* section header ``u8 compression, i32 totalLength, i32 uncompressedLength``
  with ``totalLength = 13 + len(objects) + 4`` (the trailing checksum counts)
  and ``uncompressedLength = len(objects) + 4``;
* array objects (vertex arrays, index buffers) start with a 12 byte prefix,
  meshes with an 8 byte prefix;
* meshes use ``kind = 7`` (81 unknown bytes, then the material index, the NUL
  terminated name, 50 unknown bytes);
* the material index in a mesh is **0 based** into the type 24 material list;
* index buffers use ``encoding = 130`` (u16 list);
* positions are float raw units plus a per-file ``positionScale`` around 0.0022
  (never 1.0 - see :data:`FACTORY_POSITION_SCALE`).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

MAGIC = bytes((0xAB, 0x4A, 0x53, 0x52, 0x31, 0x38, 0x34, 0xBB, 0x0D, 0x0A, 0x1A, 0x0A))
DEFAULT_AUTHOR = "Firemint Game Development 2005"

#: Shipped cars store positions as float raw units plus a per-file
#: ``positionScale`` of roughly 0.0022, so the raw values land around +-1024 and
#: the reader multiplies them back (``metres = raw * scale + bias``).  The scale
#: is not cosmetics: the engine puts a mesh whose scale is **not** 1.0 on its
#: static vertex path, while ``scale = 1.0`` takes a slower generic path - in
#: game that showed up as stuttering draw calls and missing highlights (v36/v37
#: of the Lexus LFA, 2026-10-24: identical world space, only the scale differed).
#: Everything written by :func:`build_file` therefore defaults to this convention.
FACTORY_POSITION_SCALE = 0.0021973606199026108  # 2012 Lexus LFA, raw +-1024

#: Keep raw coordinates in the +-1024 band the shipped files use; the scale is
#: derived from the model (``scale = peak / 1024``), which reproduces the factory
#: value of a car to within 0.1 %.
RAW_UNIT_RANGE = 1024.0

T_FILE_INFO = 0
T_APPEARANCE = 3
T_GROUP = 9
T_IMAGE2D = 10
T_TRI_STRIP_ARRAY = 11
T_MESH = 14
T_VERTEX_ARRAY = 20
T_VERTEX_BUFFER = 21
T_MATERIAL_LIST = 24

#: 81 bytes that sit between the mesh kind and the material index.  Mostly
#: constant, but byte 26 is the length of the mesh name - all 36068 meshes in
#: the shipped depot agree on that, and a mesh whose byte 26 disagrees with its
#: own name is one of the ways the renderer can be made to fault.
MESH_GAP_AFTER_KIND = bytes.fromhex(
    "0000000001000000000100000001000000000200000004000000160000000300"
    "000001000000000600000011000000000000000000000000000000000000803f"
    "0400000001000000010500000004000000"
)

#: 50 bytes between the mesh name and the vertex buffer index.  This one is
#: byte for byte identical in all 36068 shipped meshes, so it is a constant
#: rather than something per part.  It used to be written as zeros here, which
#: is *not* what the game ships: a mesh with this block zeroed crashes the
#: renderer on load (SIGSEGV, null pointer dereference) even though every other
#: field of the mesh parses.
MESH_GAP_AFTER_NAME = bytes.fromhex(
    "01000000000000000000000080000080"
    "3f0000803f0000803f00000000000000"
    "000000000000000000000101ffffffff"
    "ff00"
)


def _cstr(text: str) -> bytes:
    return text.encode("utf-8") + b"\x00"


def _f32(value: float) -> bytes:
    return struct.pack("<f", float(value))


def _clamp16(value: int) -> int:
    """int16 saturate - the fixed point fields must not overflow."""
    return -32768 if value < -32768 else (32767 if value > 32767 else value)


def _i32(value: int) -> bytes:
    return struct.pack("<i", int(value))


@dataclass
class M3GObject:
    type: int
    payload: bytes

    def pack(self) -> bytes:
        return bytes((self.type,)) + _i32(len(self.payload)) + self.payload


# --------------------------------------------------------------------------
# object builders
# --------------------------------------------------------------------------
def vertex_array(
    values: Sequence[float],
    component_count: int,
    component_size: int = 4,
    count: int | None = None,
    prefix: bytes | None = None,
) -> M3GObject:
    """Type 20.  ``values`` is a flat list of ``count * component_count`` numbers."""
    count = int(count if count is not None else len(values) / component_count)
    if component_size == 4:
        data = struct.pack("<%df" % len(values), *[float(v) for v in values])
    elif component_size == 2:
        data = struct.pack("<%dh" % len(values),
                           *[_clamp16(int(round(v))) for v in values])
    elif component_size == 1:
        data = struct.pack("<%db" % len(values), *[int(round(v)) for v in values])
    else:
        raise ValueError("component size must be 1, 2 or 4")
    head = (prefix or bytes(12))
    payload = b"".join((
        head,
        bytes((component_size, component_count, 0)),
        struct.pack("<H", count),
        data,
    ))
    return M3GObject(T_VERTEX_ARRAY, payload)


def index_buffer(
    indices: Sequence[int],
    encoding: int = 130,
    is_tri_strip: bool = False,
    strip_lengths: Sequence[int] | None = None,
    prefix: bytes | None = None,
) -> M3GObject:
    """Type 11.  RR3 uses ``encoding`` 130 (a plain u16 triangle list)."""
    values = list(indices)
    if encoding == 128:
        data = struct.pack("<%di" % len(values), *values)
    elif encoding == 129:
        data = struct.pack("<%dB" % len(values), *values)
    elif encoding == 130:
        data = struct.pack("<%dH" % len(values), *values)
    else:
        raise ValueError("encoding must be 128, 129 or 130")
    strips = list(strip_lengths) if strip_lengths is not None else [len(values)]
    payload = b"".join((
        (prefix or (bytes(8) + _i32(1) + _i32(0) + _i32(1))),
        bytes((1 if is_tri_strip else 0, encoding)),
        _i32(len(values)),
        data,
        _i32(len(strips)),
        b"".join(_i32(n) for n in strips),
    ))
    return M3GObject(T_TRI_STRIP_ARRAY, payload)


def vertex_buffer(
    positions: int,
    normals: int = 0,
    colors: int = 0,
    texcoords: Iterable[tuple[int, tuple[float, float, float], float]] = (),
    position_bias: tuple[float, float, float] = (0.0, 0.0, 0.0),
    position_scale: float = 1.0,
    rgba: bytes = b"\xff\xff\xff\xff",
    prefix: bytes | None = None,
) -> M3GObject:
    """Type 21.  ``texcoords`` holds ``(array_index, bias_model_xyz, scale)``.

    Note the bias handling in the reader: the stored Y bias is ``1.0 - bias_y``,
    so a model bias of ``(0, 1, 0)`` is written as ``0.0``.
    """
    layers = list(texcoords)
    payload = b"".join((
        (prefix or bytes(12)),
        rgba,
        _i32(positions),
        _f32(position_bias[0]), _f32(position_bias[1]), _f32(position_bias[2]),
        _f32(position_scale),
        _i32(normals),
        _i32(colors),
        _i32(len(layers)),
        b"".join(
            _i32(idx) + _f32(bias[0]) + _f32(1.0 - bias[1]) + _f32(bias[2]) + _f32(scale)
            for idx, bias, scale in layers
        ),
    ))
    return M3GObject(T_VERTEX_BUFFER, payload)


def mesh(
    name: str,
    material_id: int,
    vertex_buffer_index: int,
    submeshes: Sequence[tuple[int, int]],
    kind: int = 7,
    prefix: bytes | None = None,
    gap_after_kind: bytes | None = None,
    gap_after_name: bytes | None = None,
    tail: bytes = b"",
) -> M3GObject:
    """Type 14.  ``submeshes`` is a list of ``(index_buffer, appearance)``."""
    gap1 = bytearray((gap_after_kind or MESH_GAP_AFTER_KIND)[:81])
    if len(gap1) == 81:
        # byte 26 of the kind gap is the length of this mesh's name.  A gap
        # copied from a template part with a shorter or longer name would
        # otherwise carry the wrong length, and the shipped depot never
        # disagrees with itself here (36068 out of 36068 meshes agree).
        gap1[26] = len(name.encode("utf-8")) % 256
    payload = b"".join((
        (prefix or bytes(8)),
        _i32(kind),
        bytes(gap1),
        _i32(material_id),
        _cstr(name),
        (gap_after_name or MESH_GAP_AFTER_NAME)[:50],
        _i32(vertex_buffer_index),
        _i32(len(submeshes)),
        b"".join(_i32(ib) + _i32(ap) for ib, ap in submeshes),
        tail,
    ))
    return M3GObject(T_MESH, payload)


def material_list(names: Sequence[str]) -> M3GObject:
    """Type 24 - the only place a material name is stored."""
    payload = _i32(len(names)) + b"".join(_cstr(n) for n in names)
    return M3GObject(T_MATERIAL_LIST, payload)


def file_info(total_size: int, content_size: int | None = None,
              author: str = DEFAULT_AUTHOR) -> M3GObject:
    """Type 0 - version byte, two sizes and the author string."""
    payload = (
        bytes((1,))
        + bytes(2)  # two unused bytes before the sizes
        + _i32(total_size)
        + _i32(content_size if content_size is not None else total_size - 60)
        + _cstr(author)
    )
    return M3GObject(T_FILE_INFO, payload)


# --------------------------------------------------------------------------
# section / file assembly
# --------------------------------------------------------------------------
def section_bytes(objects: Sequence[M3GObject], checksum: int = 0) -> bytes:
    body = b"".join(o.pack() for o in objects)
    # header is 9 bytes (compression + totalLength + uncompressedLength), the
    # trailing checksum is counted by totalLength but not by uncompressedLength
    total = 9 + len(body) + 4
    return b"".join((
        bytes((0,)),
        _i32(total),
        _i32(len(body)),
        body,
        struct.pack("<I", checksum & 0xFFFFFFFF),
    ))


def write_file(path: str | Path, sections: Sequence[Sequence[M3GObject]],
               checksums: Sequence[int] | None = None,
               magic: bytes = MAGIC) -> Path:
    """Assemble a complete .m3g file.

    ``sections`` must already contain the type 0 file-info object if you want
    one (RR3 always ships it in the first section).
    """
    path = Path(path)
    data = magic + b"".join(
        section_bytes(objs, checksums[i] if checksums else 0)
        for i, objs in enumerate(sections)
    )
    path.write_bytes(data)
    return path


def rebuild_exact(src) -> bytes:
    """Re-serialise a parsed :class:`rr3lib.m3g.M3G` byte for byte.

    The checksums are copied from the source, so a mismatch would mean the
    framing or the object headers are wrong.
    """
    from . import m3g as reader  # local import: avoids a cycle

    if not isinstance(src, reader.M3G):
        src = reader.M3G(src)
    out = bytearray(src.buf[:12])
    for sec in src.sections:
        objs = [M3GObject(o.type, src.buf[o.offset:o.offset + o.length])
                for o in src.objects if o.section == sec["index"]]
        stored = bytes(int(part, 16) for part in sec["checksum"].split())
        checksum = int.from_bytes(stored, "little")
        out += section_bytes(objs, checksum)
    return bytes(out)


# --------------------------------------------------------------------------
# convenience: one mesh -> a whole file
# --------------------------------------------------------------------------
@dataclass
class MeshPart:
    """One drawable: positions/normals/uvs/colours plus triangle indices.

    ``positions`` are metres (Blender space *after* the axis conversion); the
    writer turns them into the raw units the vertex array stores.
    """

    name: str
    positions: list[float]
    triangles: list[int]
    normals: list[float] | None = None
    uvs: list[float] | None = None
    colors: list[float] | None = None
    material: int = 0
    uv_scale: float = 0.001953125
    #: fixed point denominators (the shipped files store normals, colours and
    #: uvs as int16 with 4096 == 1.0 and 512 == one uv tile)
    normal_fixed: float = 4096.0
    color_fixed: float = 4096.0
    uv_fixed: float = 512.0
    #: the 81 / 50 unknown byte blocks of the mesh this part replaces
    gaps: tuple | None = None
    extra: dict = field(default_factory=dict)


def _fixed(values, nverts: int, denom: float) -> list[float]:
    """Scale a float list to the fixed point range the field stores."""
    scale = len(values) / (nverts * 3) if values else 1.0
    if scale > 2.1:  # a 3 component list passed for a 2 component field
        pass
    return [v * denom for v in values]


def auto_position_scale(parts: Sequence[MeshPart], raw_range: float = RAW_UNIT_RANGE) -> float:
    """A ``position_scale`` that maps the model's peak coordinate to ``raw_range``.

    This is how the shipped files look: a car whose vertices span +-2.25 m has
    ``positionScale = 2.25 / 1024 = 0.0021973`` and raw values around +-1024.
    """
    peak = 0.0
    for part in parts:
        for v in part.positions:
            a = abs(float(v))
            if a > peak:
                peak = a
    if peak <= 1e-6:
        return FACTORY_POSITION_SCALE
    return peak / float(raw_range)


def build_file(parts: Sequence[MeshPart], materials: Sequence[str],
               author: str = DEFAULT_AUTHOR,
               position_scale: float | None = None) -> bytes:
    """Create a single section file holding the given meshes.

    ``MeshPart.positions`` are metres; they are divided by the file level
    ``position_scale`` when packed, so the vertex array holds raw units and the
    vertex buffer declares the scale (the shipped convention, see
    :data:`FACTORY_POSITION_SCALE`).  ``position_scale=None`` derives one from
    the model (peak coordinate / 1024); a part can still pin its own value with
    ``part.extra["position_scale"]``.

    Object order follows what the shipped files use: all vertex arrays first,
    then vertex buffers, then index buffers, then meshes, then the material
    list.  References are 1 based indexes into that table.
    """
    if position_scale is None:
        position_scale = auto_position_scale(parts)
    objs: list[M3GObject] = []
    base = 1  # the file-info object is object #1

    def add(obj: M3GObject) -> int:
        objs.append(obj)
        return len(objs) + 1  # 1 based, file-info counted

    plans = []
    for part in parts:
        nverts = len(part.positions) // 3
        scale = float(part.extra.get("position_scale") or position_scale)
        raw = [float(v) / scale for v in part.positions]
        pos = add(vertex_array(raw, 3, 4, nverts))
        nrm = add(vertex_array(_fixed(part.normals, nverts, part.normal_fixed),
                               3, 2, nverts))
        colours = part.colors if part.colors else [1.0] * (nverts * 3)
        col = add(vertex_array(_fixed(colours, nverts, part.color_fixed),
                               3, 2, nverts))
        uv = 0
        if part.uvs:
            uv = add(vertex_array(_fixed(part.uvs, nverts, part.uv_fixed),
                                  2, 2, nverts))
        plans.append((part, nverts, pos, nrm, col, uv, scale))

    vb_refs = []
    for part, nverts, pos, nrm, col, uv, scale in plans:
        layers = [(uv, (0.0, 1.0, 0.0), part.uv_scale)] if uv else []
        vb_refs.append(add(vertex_buffer(
            pos, nrm, col, layers, position_scale=scale)))

    ib_refs = []
    for part, *_ in plans:
        ib_refs.append(add(index_buffer(part.triangles)))

    for (part, *_), vb, ib in zip(plans, vb_refs, ib_refs):
        gap1, gap2 = part.gaps if part.gaps else (None, None)
        add(mesh(part.name, part.material, vb, [(ib, 0)],
                 gap_after_kind=gap1, gap_after_name=gap2,
                 tail=part.extra.get("tail", b"")))

    add(material_list(materials))

    # two passes: the file-info object records the total size
    def assemble(total: int) -> bytes:
        # the shipped files use two sections: a tiny header section holding the
        # file-info object, then the section with the actual objects
        info = file_info(total, total, author)
        return (MAGIC + section_bytes([info]) + section_bytes(objs))

    total = len(assemble(0))
    return assemble(total)
