"""RR3 `.dashplanes` reader (HUD text planes).

The file lists the LCD text quads drawn on the dashboard (and on the steering
wheel hub for cars that have one).  Layout::

    u32 tag            4 or 5 in every sampled file; selects the record flavour
    per plane:
        cstr  name         "dash_lcd_kmhmph" / "wheel_lcd_gear" ...
        16 f32 transform   column-major 4x4, translation in the 4th column
        tail               tag 5: 3 f32 size, 2 u32 flags, f32 extra,
                                 cstr font, 3 u8 RGB
                           tag 4: 2-3 f32 size, a few flag bytes
                                 (no font, no colour)

Records are packed with **no alignment padding**, so the stride is not fixed;
this reader locates each plane by its name and then decodes whatever fits in
the gap up to the next name.  Fields that are absent stay ``None``.
"""
import re
import struct

NAME_RE = re.compile(rb"(?:dash|wheel)_lcd_[A-Za-z0-9_]+\x00")
FONT_RE = re.compile(rb"[A-Za-z][A-Za-z0-9_]{2,30}\x00")


class Plane:
    """One HUD text quad."""

    __slots__ = ("index", "name", "offset", "matrix", "size", "flags",
                 "extra", "font", "rgb", "tail", "warnings")

    def __init__(self, index, name, offset, matrix, size=None, flags=None,
                 extra=None, font=None, rgb=None, tail=b"", warnings=None):
        self.index = index
        self.name = name
        self.offset = offset
        self.matrix = matrix
        self.size = size
        self.flags = flags
        self.extra = extra
        self.font = font
        self.rgb = rgb
        self.tail = tail
        self.warnings = warnings or []

    @property
    def position(self):
        """Translation from the column-major 4x4, in file units."""
        m = self.matrix
        return (m[12], m[13], m[14])

    @property
    def basis(self):
        """The 3x3 rotation part, as three column vectors."""
        m = self.matrix
        return ((m[0], m[1], m[2]),
                (m[4], m[5], m[6]),
                (m[8], m[9], m[10]))


class DashPlanes:
    def __init__(self, path, tag, planes, size, warnings):
        self.path = path
        self.tag = tag
        self.planes = planes
        self.size = size
        self.warnings = warnings

    @property
    def count(self):
        """Kept for older callers; this is the header tag, not a plane count."""
        return self.tag


def _decode_tail(tail):
    """Pull size/flags/font/RGB out of the bytes that follow the matrix."""
    out = {"size": None, "flags": None, "extra": None, "font": None,
           "rgb": None}
    if len(tail) >= 12:
        vals = struct.unpack_from("<3f", tail, 0)
        out["size"] = vals if len(tail) >= 12 else None
        if len(tail) < 24:  # tag 4 short form
            out["size"] = vals[:2]
    fm = FONT_RE.search(tail)
    if fm:
        out["font"] = fm.group()[:-1].decode("ascii")
        rgb = tail[fm.end():fm.end() + 3]
        if len(rgb) == 3:
            out["rgb"] = tuple(rgb)
        head = tail[:fm.start()]
        if len(head) >= 24:
            out["size"] = struct.unpack_from("<3f", head, 0)
            out["flags"] = struct.unpack_from("<2I", head, 12)
            out["extra"] = struct.unpack_from("<f", head, 20)[0]
    return out


def load(path):
    data = open(path, "rb").read()
    if len(data) < 4:
        raise ValueError("file too short")
    tag = struct.unpack_from("<I", data, 0)[0]
    matches = list(NAME_RE.finditer(data))
    planes = []
    warnings = [] if tag in (4, 5) else [f"unexpected header tag {tag}"]
    for idx, m in enumerate(matches):
        off = m.start()
        name = m.group()[:-1].decode("ascii")
        p = m.end()
        nxt = matches[idx + 1].start() if idx + 1 < len(matches) else len(data)
        if p + 64 > len(data):
            warnings.append(f"{name}: truncated transform")
            continue
        matrix = struct.unpack_from("<16f", data, p)
        tail = data[p + 64:nxt]
        fields = _decode_tail(tail)
        planes.append(Plane(idx, name, off, matrix, tail=tail, **fields))
    if not planes:
        warnings.append("no HUD planes found")
    return DashPlanes(path, tag, planes, len(data), warnings)


def format_report(dp, show_matrix=True):
    out = [f"FILE : {dp.path}",
           f"SIZE : {dp.size} B",
           f"HEADER TAG: {dp.tag}   (4 = short record, 5 = record with font and"
           f" colour; it is NOT a plane count)",
           f"PLANES: {len(dp.planes)}",
           "",
           "The file places the dashboard LCD text quads.  Positions are in the",
           "model space of the car (Y up, Z forward) with 1/32 m units, the same",
           "convention as .points.  It holds no part pivots, no steering wheel",
           "data and no animation keys.",
           ""]
    for pl in dp.planes:
        out.append(f"[{pl.index}] {pl.name}")
        out.append(f"    offset 0x{pl.offset:04x}  tag {dp.tag}")
        if pl.font is not None:
            out.append(f"    font {pl.font!r}  rgb {pl.rgb}")
        else:
            out.append("    font (none in this record flavour)")
        if pl.size is not None:
            out.append("    size " + " ".join(f"{v:.6g}" for v in pl.size))
        if pl.flags is not None:
            out.append(f"    flags {pl.flags[0]} {pl.flags[1]}  "
                       f"extra {pl.extra:.6g}")
        pos = pl.position
        out.append(f"    position raw ({pos[0]:.4f}, {pos[1]:.4f}, "
                   f"{pos[2]:.4f})  ->  /32 m ({pos[0] / 32:.4f}, "
                   f"{pos[1] / 32:.4f}, {pos[2] / 32:.4f})")
        if show_matrix:
            for r in range(4):
                row = pl.matrix[r * 4:r * 4 + 4]
                out.append("      | " + " ".join(f"{v:>10.5f}" for v in row)
                           + " |")
        if pl.tail and pl.font is None:
            out.append("    tail bytes " + pl.tail.hex(" "))
        out.append("")
    for w in dp.warnings:
        out.append(f"WARNING: {w}")
    return "\n".join(out)
