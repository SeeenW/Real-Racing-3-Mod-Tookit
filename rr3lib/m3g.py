"""RR3 / Firemint M3G (JSR-184 v1 flavour) reader.

Layout recovered from RaduMC/M3G2FBX and verified byte-exactly against
Real Racing 3 assets.  Everything is little-endian.

file:
    12   magic  AB "JSR184" BB 0D 0A 1A 0A
    ...  sections until EOF
section:
    u8   compressionScheme           (0 = none)
    i32  totalSectionLength
    i32  uncompressedLength
    ...  objects until sectionEnd (= sectionPayloadStart + total - 13)
    i32  checksum
object:
    u8   type
    i32  payloadLength
    ...  payload
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass, field
from pathlib import Path

MAGIC = bytes.fromhex("ab4a5352313834bb0d0a1a0a")

# object type ids
T_FILE_INFO = 0
T_APPEARANCE = 3
T_GROUP = 9
T_IMAGE2D = 10
T_TRI_STRIP_ARRAY = 11
T_MESH = 14
T_VERTEX_ARRAY = 20
T_VERTEX_BUFFER = 21
T_MATERIAL_LIST = 24


class M3GError(Exception):
    pass


@dataclass
class Obj:
    index: int
    section: int
    type: int
    offset: int  # payload start
    length: int
    data: dict = field(default_factory=dict)


class Reader:
    """Bounds-checked little-endian cursor."""

    __slots__ = ("b", "p", "end")

    def __init__(self, buf: bytes, pos: int = 0, end: int | None = None):
        self.b = buf
        self.p = pos
        self.end = len(buf) if end is None else end

    def need(self, n: int):
        if self.p + n > self.end:
            raise M3GError(
                f"read past end: want {n} at {self.p:#x}, limit {self.end:#x}"
            )

    def skip(self, n: int):
        self.need(n)
        self.p += n

    def u8(self) -> int:
        self.need(1)
        v = self.b[self.p]
        self.p += 1
        return v

    def i8(self) -> int:
        self.need(1)
        v = struct.unpack_from("<b", self.b, self.p)[0]
        self.p += 1
        return v

    def u16(self) -> int:
        self.need(2)
        v = struct.unpack_from("<H", self.b, self.p)[0]
        self.p += 2
        return v

    def i16(self) -> int:
        self.need(2)
        v = struct.unpack_from("<h", self.b, self.p)[0]
        self.p += 2
        return v

    def u32(self) -> int:
        self.need(4)
        v = struct.unpack_from("<I", self.b, self.p)[0]
        self.p += 4
        return v

    def i32(self) -> int:
        self.need(4)
        v = struct.unpack_from("<i", self.b, self.p)[0]
        self.p += 4
        return v

    def f32(self) -> float:
        self.need(4)
        v = struct.unpack_from("<f", self.b, self.p)[0]
        self.p += 4
        return v

    def f32s(self, n: int) -> list[float]:
        self.need(4 * n)
        v = list(struct.unpack_from("<%df" % n, self.b, self.p))
        self.p += 4 * n
        return v

    def cstr(self) -> str:
        start = self.p
        while True:
            if self.p >= self.end:
                raise M3GError(f"unterminated string at {start:#x}")
            if self.b[self.p] == 0:
                s = self.b[start : self.p].decode("utf-8", "replace")
                self.p += 1
                return s
            self.p += 1

    def raw(self, n: int) -> bytes:
        self.need(n)
        v = self.b[self.p : self.p + n]
        self.p += n
        return v

    @property
    def left(self) -> int:
        return self.end - self.p


# --------------------------------------------------------------------------
# object payload parsers
# --------------------------------------------------------------------------


def _user_parameters(r: Reader, out: dict, kinds: dict[int, str]):
    """i32 count, then per entry i32 id, i32 length, length bytes."""
    n = r.i32()
    if n < 0 or n > 4096:
        raise M3GError(f"bogus user parameter count {n}")
    for _ in range(n):
        pid = r.i32()
        plen = r.i32()
        if plen < 0:
            raise M3GError(f"bogus user parameter length {plen}")
        payload = r.raw(plen)
        kind = kinds.get(pid)
        if kind is None:
            continue
        if kind == "str":
            out.setdefault("params", {})[pid] = payload.split(b"\0")[0].decode(
                "utf-8", "replace"
            )
        elif kind == "float":
            out.setdefault("params", {})[pid] = (
                struct.unpack("<f", payload[:4])[0] if len(payload) >= 4 else None
            )
        elif kind == "rgba":
            out.setdefault("params", {})[pid] = (
                list(struct.unpack("<4f", payload[:16])) if len(payload) >= 16 else None
            )
        else:
            out.setdefault("params", {})[pid] = payload


def parse_file_info(r: Reader) -> dict:
    d = {}
    d["version"] = r.u8()
    r.skip(2)  # always 0 in the retail files
    d["totalFileSize"] = r.u32()
    d["approximateContentSize"] = r.u32()
    d["author"] = r.cstr()
    return d


def parse_image2d(r: Reader) -> dict:
    d = {}
    r.skip(4)
    ntracks = r.i32()
    if ntracks < 0 or ntracks > 4096:
        raise M3GError(f"Image2D bogus track count {ntracks}")
    r.skip(4 * ntracks)
    _user_parameters(r, d, {0: "str", 900: "str"})
    d["format"] = r.u8()
    d["width"] = r.i32()
    d["height"] = r.i32()
    r.skip(12)
    return d


def parse_appearance(r: Reader) -> dict:
    d = {}
    r.skip(4)
    ntracks = r.i32()
    if ntracks < 0 or ntracks > 4096:
        raise M3GError(f"Appearance bogus track count {ntracks}")
    r.skip(4 * ntracks)
    _user_parameters(
        r,
        d,
        {0: "str", 1: "raw", 2: "str", 600: "float", 601: "rgba"},
    )
    d["layer"] = r.u8()
    d["compositingMode"] = r.i32()
    d["fog"] = r.i32()
    d["polygonMode"] = r.i32()
    d["material"] = r.i32()
    ntex = r.i32()
    if ntex < 0 or ntex > 256:
        raise M3GError(f"Appearance bogus texture count {ntex}")
    d["textures"] = [r.i32() for _ in range(ntex)]
    return d


def parse_mesh(r: Reader, version: int) -> dict:
    d = {}
    r.skip(8)
    kind = r.i32()
    d["kind"] = kind
    d["materialId"] = None
    if kind == 5:
        r.skip(48)
    elif kind == 6:
        r.skip(56)
        d["materialId"] = r.i32()
    elif kind == 7:
        r.skip(81)
        d["materialId"] = r.i32()
    else:
        raise M3GError(f"unsupported mesh kind {kind}")

    d["name"] = r.cstr()
    d["nameOffset"] = r.p - len(d["name"]) - 1
    r.skip(50)
    d["vertexBuffer"] = r.i32()
    subcount = r.i32()
    if subcount < 0 or subcount > 4096:
        raise M3GError(f"bogus submesh count {subcount}")
    subs = []
    for _ in range(subcount):
        sub = {"indexBuffer": r.i32()}
        if version == 1:
            sub["appearance"] = r.i32()
        subs.append(sub)
    d["submeshes"] = subs
    return d


def parse_group(r: Reader) -> dict:
    """Node in the scene graph (rare in RR3 LOD files)."""
    from math import acos, atan2, degrees, sqrt

    d = {}
    r.skip(4)
    ntracks = r.i32()
    if ntracks < 0 or ntracks > 4096:
        raise M3GError(f"Group bogus track count {ntracks}")
    r.skip(4 * ntracks)
    _user_parameters(r, d, {0: "str", 2: "raw"})

    d["translation"] = [0.0, 0.0, 0.0]
    d["scale"] = [1.0, 1.0, 1.0]
    d["euler"] = [0.0, 0.0, 0.0]
    if r.u8():
        d["translation"] = r.f32s(3)
        d["scale"] = r.f32s(3)
        angle = r.f32()
        axis = r.f32s(3)
        d["euler"] = angle_axis_to_euler(angle, axis)
    if r.u8():
        d["generalTransform"] = r.f32s(16)
    r.skip(7)
    if r.u8():
        n = r.i16()
        if n < 0:
            raise M3GError("bogus group block")
        r.skip(n * 16)
        n2 = r.i16()
        for _ in range(max(0, n2)):
            ln = r.i16()
            r.skip(ln + 9)
    nchild = r.i32()
    if nchild < 0 or nchild > 65536:
        raise M3GError(f"bogus child count {nchild}")
    d["children"] = [r.i32() for _ in range(nchild)]
    return d


def angle_axis_to_euler(angle: float, axis: list[float]) -> list[float]:
    """Same conversion the reference converter uses (returns degrees)."""
    x, y, z = axis
    n = math.sqrt(x * x + y * y + z * z)
    if n < 1e-12:
        return [0.0, 0.0, 0.0]
    x, y, z = x / n, y / n, z / n
    a = math.radians(angle)
    c, s = math.cos(a), math.sin(a)
    t = 1 - c
    m00 = t * x * x + c
    m01 = t * x * y - s * z
    m02 = t * x * z + s * y
    m10 = t * x * y + s * z
    m11 = t * y * y + c
    m12 = t * y * z - s * x
    m20 = t * x * z - s * y
    m21 = t * y * z + s * x
    m22 = t * z * z + c
    # reference: {bank, heading, -attitude}
    heading = math.atan2(m02, m22)
    attitude = math.asin(max(-1.0, min(1.0, -m12)))
    bank = math.atan2(m10, m11)
    return [math.degrees(bank), math.degrees(heading), -math.degrees(attitude)]


def parse_vertex_buffer(r: Reader, version: int) -> dict:
    d = {}
    r.skip(12)
    d["colorRGBA"] = list(r.raw(4))
    d["positions"] = r.i32()
    d["positionBias"] = r.f32s(3)
    d["positionScale"] = r.f32()
    d["normals"] = r.i32()
    d["colors"] = r.i32()
    ntex = r.i32()
    d["texcoordCountRaw"] = ntex
    ntex = abs(ntex)
    if ntex > 64:
        raise M3GError(f"bogus texcoord layer count {ntex}")
    layers = []
    for _ in range(ntex):
        lay = {"array": r.i32()}
        lay["bias"] = r.f32s(3)
        lay["bias"][1] = 1.0 - lay["bias"][1]
        lay["scale"] = r.f32()
        layers.append(lay)
    d["texcoords"] = layers
    if r.left >= 8:
        d["tangents"] = r.i32()
        d["binormals"] = r.i32()
    else:
        d["tangents"] = 0
        d["binormals"] = 0
    return d


def parse_vertex_array(r: Reader) -> dict:
    d = {}
    r.skip(12)  # common object prefix (same 12 bytes as the other array objects)
    d["componentSize"] = r.u8()
    d["componentCount"] = r.u8()
    d["encoding"] = r.u8()
    d["vertexCount"] = r.u16()
    if d["componentSize"] not in (1, 2, 4):
        raise M3GError(f"unsupported component size {d['componentSize']}")
    if d["encoding"] != 0:
        raise M3GError(f"unsupported vertex encoding {d['encoding']}")
    n = d["vertexCount"] * d["componentCount"]
    cs = d["componentSize"]
    if cs == 1:
        d["values"] = list(struct.unpack_from("<%db" % n, r.b, r.p)) if n else []
    elif cs == 2:
        d["values"] = list(struct.unpack_from("<%dh" % n, r.b, r.p)) if n else []
    else:
        d["values"] = list(struct.unpack_from("<%df" % n, r.b, r.p)) if n else []
    r.p += n * cs
    return d


def parse_index_buffer(r: Reader) -> dict:
    d = {}
    r.skip(20)
    d["isTriStrip"] = bool(r.u8())
    encoding = r.u8()
    d["encoding"] = encoding
    indices: list[int] = []
    strips: list[int] = []
    start = 0
    if encoding in (0, 1, 2):
        if encoding == 0:
            start = r.i32()
        elif encoding == 1:
            start = r.u8()
        else:
            start = r.u16()
        n = r.i32()
        if n < 0 or n > 1 << 20:
            raise M3GError(f"bogus strip count {n}")
        strips = [r.i32() for _ in range(n)]
        total = sum(strips)
        indices = list(range(start, start + total))
    elif encoding in (128, 129, 130):
        n = r.i32()
        if n < 0 or n > 1 << 26:
            raise M3GError(f"bogus index count {n}")
        if encoding == 128:
            indices = list(struct.unpack_from("<%di" % n, r.b, r.p)) if n else []
            r.p += 4 * n
        elif encoding == 129:
            indices = list(struct.unpack_from("<%dB" % n, r.b, r.p)) if n else []
            r.p += n
        else:
            indices = list(struct.unpack_from("<%dH" % n, r.b, r.p)) if n else []
            r.p += 2 * n
        # strip lengths follow (one entry per strip); a list has a single strip
        if r.left >= 4:
            sc = r.i32()
            if 0 <= sc <= 1 << 20:
                strips = [r.i32() for _ in range(sc)]
    else:
        raise M3GError(f"unsupported index encoding {encoding}")
    d["indices"] = indices
    d["stripLengths"] = strips
    return d


def parse_material_list(r: Reader) -> dict:
    n = r.i32()
    if n < 0 or n > 65536:
        raise M3GError(f"bogus material count {n}")
    return {"materials": [r.cstr() for _ in range(n)]}


PARSERS = {
    T_FILE_INFO: lambda r, v: parse_file_info(r),
    T_APPEARANCE: lambda r, v: parse_appearance(r),
    T_GROUP: lambda r, v: parse_group(r),
    T_IMAGE2D: lambda r, v: parse_image2d(r),
    T_TRI_STRIP_ARRAY: lambda r, v: parse_index_buffer(r),
    T_MESH: lambda r, v: parse_mesh(r, v),
    T_VERTEX_ARRAY: lambda r, v: parse_vertex_array(r),
    T_VERTEX_BUFFER: lambda r, v: parse_vertex_buffer(r, v),
    T_MATERIAL_LIST: lambda r, v: parse_material_list(r),
}


# --------------------------------------------------------------------------
# file
# --------------------------------------------------------------------------


class M3G:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.buf = self.path.read_bytes()
        self.version = 1
        self.author = ""
        self.objects: list[Obj] = []
        self.warnings: list[str] = []
        self.sections: list[dict] = []
        self._parse()

    # -- structure ---------------------------------------------------------
    def _parse(self):
        b = self.buf
        if len(b) < 16:
            raise M3GError("file too small")
        magic = b[:12]
        if magic != MAGIC:
            if magic[1:7] == b"IM2M3G":
                self.version = 2
            elif magic[1:7] == b"IM3M3G":
                self.version = 3
            else:
                raise M3GError(f"not an M3G file (magic {magic.hex(' ')})")
        pos = 12
        secno = 0
        while pos + 9 <= len(b):
            comp = b[pos]
            total = struct.unpack_from("<i", b, pos + 1)[0]
            unc = struct.unpack_from("<i", b, pos + 5)[0]
            payload_start = pos + 9
            if comp != 0:
                raise M3GError(
                    f"section {secno} uses compression scheme {comp}; "
                    "this reader only handles uncompressed RR3 files"
                )
            if total < 13:
                raise M3GError(f"section {secno} has bogus length {total}")
            secend = min(payload_start + total - 13, len(b))
            p = payload_start
            nobj = 0
            while p + 5 <= secend:
                t = b[p]
                ln = struct.unpack_from("<i", b, p + 1)[0]
                if ln < 0 or p + 5 + ln > len(b):
                    self.warnings.append(
                        f"section {secno}: bad object length {ln} at {p:#x}; stopping section"
                    )
                    break
                self.objects.append(Obj(len(self.objects), secno, t, p + 5, ln))
                nobj += 1
                p = p + 5 + ln
            self.sections.append(
                {
                    "index": secno,
                    "compression": comp,
                    "totalLength": total,
                    "uncompressedLength": unc,
                    "objects": nobj,
                    "checksum": b[secend : secend + 4].hex(" "),
                }
            )
            if p != secend:
                self.warnings.append(
                    f"section {secno}: objects ended at {p:#x} but section ends at {secend:#x}"
                )
            pos = secend + 4
            secno += 1
            if secno > 512:
                self.warnings.append("too many sections; stopping")
                break

        # typed parse
        for o in self.objects:
            fn = PARSERS.get(o.type)
            if fn is None:
                continue
            r = Reader(b, o.offset, o.offset + o.length)
            try:
                o.data = fn(r, self.version)
                if r.left > 0:
                    o.data["_unparsed"] = r.left
            except (M3GError, struct.error) as e:
                o.data = {"_error": str(e)}

        # file info object carries version/author
        for o in self.objects:
            if o.type == T_FILE_INFO and "author" in o.data:
                self.author = o.data["author"]
                break

    # -- helpers -----------------------------------------------------------
    def of_type(self, t: int) -> list[Obj]:
        return [o for o in self.objects if o.type == t]

    def obj(self, i: int) -> Obj | None:
        if i is None or i < 0 or i >= len(self.objects):
            return None
        return self.objects[i]

    def resolve(self, ref: int | None, expected: int | None = None) -> Obj | None:
        """Resolve an object reference.

        RR3 stores these as 1-based indices into the object table (verified:
        mesh.vertexBuffer == object_table_id + 1).  Fall back to other nearby
        conventions only if the expected type does not line up.
        """
        if ref is None or ref <= 0:
            return None
        for delta in (1, 0, 2):
            i = ref - delta
            if 0 <= i < len(self.objects):
                o = self.objects[i]
                if expected is None or o.type == expected:
                    return o
        return None

    @property
    def materials(self) -> list[str]:
        for o in self.objects:
            if o.type == T_MATERIAL_LIST:
                return o.data.get("materials", [])
        return []

    def images(self) -> list[dict]:
        out = []
        for o in self.objects:
            if o.type == T_IMAGE2D and "_error" not in o.data:
                d = dict(o.data)
                d["object"] = o.index
                p = d.get("params", {})
                d["name"] = p.get(0, "")
                d["path"] = p.get(900, "")
                out.append(d)
        return out

    def vertex_array_values(self, idx: int) -> list[float]:
        o = self.obj(idx)
        if o is None or o.type != T_VERTEX_ARRAY:
            return []
        return o.data.get("values", [])

    def vertex_array_count(self, idx: int) -> int:
        o = self.obj(idx)
        if o is None:
            return 0
        return o.data.get("vertexCount", 0)
