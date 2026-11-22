"""RR3 ``.points`` (anchor point table) reader.

Reverse engineered from the shipped assets; every field below was validated by
walking whole files to the exact byte length (578+ of 958 files in the retail
data cast, and 100% of the files that ship without an override table).

Container layout - all little-endian, nothing is padded::

    u16  version          always 2 in the shipped data
    u16  recordCount
    recordCount x record:
        u16 type         0 = point, 1 = spline, 2 = hinge, 3 = transform
        u16 size         payload length that follows (name + extra data)
        cstr name        NUL terminated ASCII, counted inside ``size``
        ...  extra data  ``size - len(name)-1`` bytes, meaning depends on type
    u16  overrideCount
    overrideCount x override:
        cstr name
        cstr value       free form text such as b"SCALE 0.7\\r\\n"

Extra data per type (verified against all 927 shipped files - every payload
consumes exactly to the record end, zero slack):

    type 0  point     12 bytes = 3 x f32 position (engine units, 1 m = 32 units)
    type 1  spline    u16 splineCount, then splineCount x
                      (u16 pointCount + pointCount x 3 f32).
                      There is no flags field - the first u16 is the count.
                      Counts per spline may differ (e.g. [10, 10, 13]).
    type 2  hinge     48 bytes = 3 x f32 position + 9 x f32 row major 3x3
                      orientation matrix (rows are the local axes)
    type 3  transform 64 bytes = 16 x f32 row major 4x4 matrix; the last
                      column is the translation and its w is 1.0. The upper
                      3x3 is a pure rotation (rows are unit length). Used for
                      exhaust/effect anchors that need an orientation, which a
                      type 0 point cannot express.

The reader never guesses: if a record's ``size`` does not match the expected
layout for its type the raw bytes are kept and a warning is recorded.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass, field
from pathlib import Path

TYPE_POINT = 0
TYPE_SPLINE = 1
TYPE_HINGE = 2
TYPE_TRANSFORM = 3
TYPE_UNKNOWN3 = TYPE_TRANSFORM  # backwards-compatible alias

TYPE_NAMES = {
    TYPE_POINT: "point",
    TYPE_SPLINE: "spline",
    TYPE_HINGE: "hinge",
    TYPE_TRANSFORM: "transform",
}


class PointsError(Exception):
    pass


@dataclass
class PointRecord:
    index: int
    type: int
    name: str
    size: int
    offset: int  # byte offset of the record header in the file
    position: tuple[float, float, float] | None = None
    matrix: tuple[float, ...] | None = None  # 9 floats, row major (hinge)
    spline_points: list[tuple[float, float, float]] = field(default_factory=list)
    splines: list[list[tuple[float, float, float]]] = field(default_factory=list)
    transform: tuple[float, ...] | None = None  # 16 floats, row major 4x4
    raw: bytes = b""

    @property
    def type_name(self) -> str:
        return TYPE_NAMES.get(self.type, f"type{self.type}")

    @property
    def spline_flags(self) -> int | None:
        """Deprecated: type 1 has no flags field, only a spline count.

        Kept as a property so old callers get the count instead of crashing.
        """
        if self.type != TYPE_SPLINE:
            return None
        return len(self.splines) or None


@dataclass
class Override:
    index: int
    name: str
    value: str


@dataclass
class PointsFile:
    path: Path
    version: int
    records: list[PointRecord]
    overrides: list[Override]
    warnings: list[str] = field(default_factory=list)
    trailing: bytes = b""
    #: False when the file simply stops after the records with no trailing
    #: ``u16 overrideCount``.  44 shipped files (the 0-record ``wheel_*.points``)
    #: do that; everything else writes the count, usually ``0``.
    override_field: bool = True

    def find(self, name: str) -> PointRecord | None:
        for r in self.records:
            if r.name == name:
                return r
        return None


def _cstr(d: bytes, p: int, end: int) -> tuple[str, int]:
    q = d.find(b"\0", p, end)
    if q < 0:
        raise PointsError(f"unterminated string at {p:#x}")
    return d[p:q].decode("utf-8", "replace"), q + 1


def load(path: str | Path) -> PointsFile:
    path = Path(path)
    d = path.read_bytes()
    warnings: list[str] = []
    if len(d) < 4:
        raise PointsError("file too small for a .points container")

    version, count = struct.unpack_from("<HH", d, 0)
    pos = 4
    records: list[PointRecord] = []
    for i in range(count):
        if pos + 4 > len(d):
            warnings.append(f"record {i}: truncated header at {pos:#x}")
            break
        rtype, size = struct.unpack_from("<HH", d, pos)
        hdr = pos
        pos += 4
        if pos + size > len(d):
            warnings.append(
                f"record {i}: payload {size} bytes at {pos:#x} runs past EOF"
            )
            break
        end = pos + size
        name, npos = _cstr(d, pos, end)
        extra = d[npos:end]
        rec = PointRecord(index=i, type=rtype, name=name, size=size, offset=hdr)
        rec.raw = extra
        _decode_extra(rec, extra, warnings)
        records.append(rec)
        pos = end

    overrides: list[Override] = []
    override_field = False
    if pos + 2 <= len(d):
        override_field = True
        opos = pos
        ocount = struct.unpack_from("<H", d, pos)[0]
        pos += 2
        ok = True
        for i in range(ocount):
            try:
                nm, pos = _cstr(d, pos, len(d))
                val, pos = _cstr(d, pos, len(d))
            except PointsError as e:
                warnings.append(f"override {i}: {e}")
                ok = False
                break
            overrides.append(Override(i, nm, val))
        if not ok:
            pos = opos
            warnings.append("override table looks broken; kept as trailing bytes")

    trailing = d[pos:]
    if trailing:
        warnings.append(f"{len(trailing)} unparsed trailing bytes at {pos:#x}")

    return PointsFile(path, version, records, overrides, warnings, trailing,
                      override_field)


def _decode_extra(rec: PointRecord, extra: bytes, warnings: list[str]):
    n = len(extra)
    if rec.type == TYPE_POINT:
        if n == 12:
            rec.position = struct.unpack("<3f", extra)
        else:
            warnings.append(
                f"record {rec.index} ({rec.name}): point type with {n} extra bytes"
            )
    elif rec.type == TYPE_HINGE:
        if n == 48:
            v = struct.unpack("<12f", extra)
            rec.position = v[0:3]
            rec.matrix = v[3:12]
        else:
            warnings.append(
                f"record {rec.index} ({rec.name}): hinge type with {n} extra bytes"
            )
    elif rec.type == TYPE_SPLINE:
        # u16 splineCount, then splineCount x (u16 pointCount + pointCount * 12B)
        if n < 2:
            warnings.append(f"record {rec.index} ({rec.name}): spline payload too short")
            return
        count = struct.unpack_from("<H", extra, 0)[0]
        pos = 2
        lists: list[list[tuple[float, float, float]]] = []
        ok = True
        for _ in range(count):
            if pos + 2 > n:
                ok = False
                break
            npts = struct.unpack_from("<H", extra, pos)[0]
            pos += 2
            if pos + npts * 12 > n:
                ok = False
                break
            vals = struct.unpack_from("<%df" % (npts * 3), extra, pos)
            lists.append(
                [(vals[k], vals[k + 1], vals[k + 2]) for k in range(0, npts * 3, 3)]
            )
            pos += npts * 12
        if ok and pos == n and lists:
            rec.splines = lists
            rec.spline_points = lists[0]
        else:
            warnings.append(
                f"record {rec.index} ({rec.name}): spline payload {n} bytes does not "
                f"decompose into {count} vertex lists (stopped at {pos})"
            )
    elif rec.type == TYPE_UNKNOWN3:
        if n == 64:
            rec.transform = struct.unpack("<16f", extra)
        else:
            warnings.append(
                f"record {rec.index} ({rec.name}): transform type with {n} extra bytes"
            )
    else:
        warnings.append(
            f"record {rec.index} ({rec.name}): unknown record type {rec.type} "
            f"({n} extra bytes)"
        )


# --------------------------------------------------------------------------
# textual report
# --------------------------------------------------------------------------


POINT_SCALE = 32.0          # 引擎世界单位 = 1/32 米（游戏内模型矩阵缩放 32 倍，已由抓帧确认）
SCALE_CANDIDATES = (
    ("1/32", POINT_SCALE),
    ("1/31", 31.0),
    ("1/33", 33.0),
)


def _m(v):
    return v / POINT_SCALE


def anchor_table(pf: PointsFile) -> str:
    """一张表：所有锚点的米制坐标（世界单位 / 32）。"""
    out: list[str] = []
    a = out.append
    a("# 锚点坐标表（米）。引擎世界单位 = 1/32 米，游戏内模型矩阵缩放 32 倍。")
    a("# 轴向：x = 右, y = 前, z = 上；原点是车辆自身的水平中心线（z=0 为地面）。")
    head = "%-34s %6s %10s %10s %10s" % ("name", "type", "x(m)", "y(m)", "z(m)")
    a(head)
    a("-" * len(head))
    for r in pf.records:
        if r.position is None:
            continue
        x, y, z = r.position
        a("%-34s %6s %10.4f %10.4f %10.4f" % (r.name, r.type_name, _m(x), _m(y), _m(z)))
    return "\n".join(out)


def scale_table(pf: PointsFile) -> str:
    """米制坐标 + 另两个候选除数，方便复核。"""
    out: list[str] = []
    a = out.append
    a("# 换算复核：同一组原始值分别按 1/32（标准）、1/31、1/33 换算")
    head = "%-30s %20s" % ("name", "raw x y z")
    for label, _d in SCALE_CANDIDATES:
        head += "  %-24s" % ("m @" + label)
    a(head)
    for r in pf.records:
        if r.position is None:
            continue
        x, y, z = r.position
        row = "%-30s %8.2f %8.2f %8.2f" % (r.name, x, y, z)
        for _label, d in SCALE_CANDIDATES:
            row += "  %-24s" % ("%.4f %.4f %.4f" % (x / d, y / d, z / d))
        a(row)
    return "\n".join(out)


def format_report(pf: PointsFile) -> str:
    out: list[str] = []
    a = out.append
    a("# RR3 .points dump（锚点 / 铰链）")
    a(f"文件: {pf.path}")
    a(f"字节: {pf.path.stat().st_size}")
    a(f"版本: {pf.version}")
    a(f"记录: {len(pf.records)}")
    a("")
    a("单位：文件里存的是整数/浮点的“引擎世界单位”，1 米 = 32 单位。")
    a("游戏内模型矩阵的缩放正好是 32（用 RenderDoc 抓帧确认），因此 米 = 原始值 / 32。")
    a("方向：x = 右, y = 前, z = 上；z = 0 是地面，模型原点在轮轴高度（模型 y = -0.2985 即地面）。")
    a("")
    a(anchor_table(pf))
    a("")
    a("=" * 78)
    a("逐条明细")
    a("=" * 78)
    for r in pf.records:
        a(f"[{r.index:3d}] {r.type_name:<8} {r.name}")
        a(f"      offset={r.offset:#06x} size={r.size} type={r.type}")
        if r.position is not None:
            x, y, z = r.position
            a(f"      raw:     {x:.6f} {y:.6f} {z:.6f}")
            a(f"      metres:  {_m(x):.4f} {_m(y):.4f} {_m(z):.4f}")
        if r.matrix is not None:
            m = r.matrix
            a("      铰链/朝向矩阵（3x3，行向量，单位向量）:")
            for row in range(3):
                a(
                    "        axis %d: % .6f % .6f % .6f"
                    % (row, m[row * 3], m[row * 3 + 1], m[row * 3 + 2])
                )
        if r.type == TYPE_SPLINE:
            a(f"      splines: {len(r.splines)}")
            for li, pts in enumerate(r.splines):
                a(f"      list {li}: {len(pts)} points")
                for k, p in enumerate(pts):
                    a(
                        "        [%2d] raw %8.3f %8.3f %8.3f  |  m %7.4f %7.4f %7.4f"
                        % (k, p[0], p[1], p[2], _m(p[0]), _m(p[1]), _m(p[2]))
                    )
        if r.transform is not None:
            t = r.transform
            a("      变换矩阵（4x4，行主序，最后一列为平移）:")
            for row in range(4):
                a(
                    "        row %d: % .6f % .6f % .6f % .6f"
                    % (row, t[row * 4], t[row * 4 + 1], t[row * 4 + 2], t[row * 4 + 3])
                )
            a(
                "        translation (m): %.4f %.4f %.4f"
                % (_m(t[12]), _m(t[13]), _m(t[14]))
            )
        if r.type not in (TYPE_POINT, TYPE_SPLINE, TYPE_HINGE, TYPE_TRANSFORM) or (
            r.raw and r.position is None and not r.splines and r.transform is None
        ):
            a(f"      raw bytes: {r.raw.hex(' ')}")
        a("")
    a(f"overrides: {len(pf.overrides)}")
    for o in pf.overrides:
        a(f"[{o.index:3d}] {o.name} = {o.value!r}")
    if pf.trailing:
        a("")
        a(f"unparsed trailing bytes: {len(pf.trailing)}")
        a(f"  {pf.trailing.hex(' ')}")
    if pf.warnings:
        a("")
        a("warnings:")
        for w in pf.warnings:
            a(f"  ! {w}")
    a("")
    a(scale_table(pf))
    return "\n".join(out) + "\n"
