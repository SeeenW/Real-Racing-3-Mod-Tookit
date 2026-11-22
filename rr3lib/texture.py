"""`.dds.z` (zlib-compressed DDS) container reader.

RR3 ships every texture as  <car>_<name>.dxt.dds.z :

    u32 uncompressedSize
    zlib stream  ("78 da" ...)  ->  a complete DDS file

The same picture also exists as ``.etc.dds.z``, ``.atc.dds.z`` and
``.ptc.pvr.z``, one per GPU family; a depot only unpacks the copy its build
targets.  :func:`find_atlas` looks for all four and the decoders in
:mod:`rr3lib.ddsdecode` and :mod:`rr3lib.etcdecode` read all four.

Nothing is modified on disk; the caller gets the DDS bytes in memory.
"""
from __future__ import annotations

import os
import struct
import zlib

DDS_MAGIC = b"DDS "

FOURCC = {
    b"DXT1": "DXT1",
    b"DXT3": "DXT3",
    b"DXT5": "DXT5",
    b"ATI2": "ATI2",
    b"DX10": "DX10",
}


def is_dds_z(path: str) -> bool:
    return path.lower().endswith(".dds.z")


def read_dds_z(path: str) -> bytes:
    """Return the raw DDS file bytes stored inside a `.dds.z` container."""
    with open(path, "rb") as fh:
        raw = fh.read()
    if len(raw) < 8:
        raise ValueError(f"{path}: file too small")
    declared = struct.unpack_from("<I", raw, 0)[0]
    data = zlib.decompress(raw[4:])
    if len(data) != declared:
        raise ValueError(
            f"{path}: declared {declared} bytes but zlib produced {len(data)}"
        )
    if data[:4] != DDS_MAGIC:
        raise ValueError(f"{path}: not a DDS payload (magic {data[:4]!r})")
    return data


def dds_info(data: bytes) -> dict:
    """Parse the 128-byte DDS header (and DX10 extension if present)."""
    if data[:4] != DDS_MAGIC:
        raise ValueError("not a DDS payload")
    (size, flags, height, width, pitch, depth, mips) = struct.unpack_from("<7I", data, 4)
    pf_size, pf_flags, fourcc, bits, rm, gm, bm, am = struct.unpack_from("<8I", data, 76)
    caps, caps2, caps3, caps4, reserved2 = struct.unpack_from("<5I", data, 108)
    info = {
        "headerSize": size,
        "flags": flags,
        "width": width,
        "height": height,
        "pitchOrLinearSize": pitch,
        "depth": depth,
        "mipmaps": mips,
        "pixelFormatSize": pf_size,
        "pixelFormatFlags": pf_flags,
        "fourcc": fourcc.to_bytes(4, "little"),
        "bitsPerPixel": bits,
        "rMask": rm,
        "gMask": gm,
        "bMask": bm,
        "aMask": am,
        "caps": caps,
        "caps2": caps2,
        "dataOffset": 128,
    }
    fc = info["fourcc"]
    info["format"] = FOURCC.get(fc) or (fc.rstrip(b"\0").decode("ascii", "replace") or "RGBA")
    if info["format"] == "DX10" and len(data) >= 148:
        (dxgi, res, arr, misc, misc2) = struct.unpack_from("<5I", data, 128)
        info["dxgiFormat"] = dxgi
        info["dataOffset"] = 148
    return info


def describe(path: str) -> dict:
    data = read_dds_z(path)
    info = dds_info(data)
    info["path"] = path
    info["ddsBytes"] = len(data)
    info["mipChain"] = info["mipmaps"] or 1
    return info


# ---------------------------------------------------------------------------
# tag -> atlas
# ---------------------------------------------------------------------------
# A car material is named  "<material class>_mm_<tag>"  and the tag is the only
# link to a texture: the .m3g holds no Appearance / Image2D objects at all.
# Every car ships the same ten <car>_<tag>.dxt.dds.z atlases; tags without an
# atlas of their own are either untextured (paint / glass / emissive) or reuse
# one of the shipped atlases.  The table below was established by rendering the
# imported meshes with each candidate atlas (see analysis/tex_render.py).
TAG_ATLAS = {
    "badges": "badges",
    "cab": "cab",
    "int": "int",
    "lights": "lights",
    "misc": "misc",
    "sw": "sw",
    "wheel": "wheel",
    "wheel_blur": "wheel_blur",
    # paint / glass / emissive / damage materials: no albedo atlas in the data
    "ext": None,
    "chassis": None,
    "windows": None,
    "windows_cracked": None,
    "windows_shattered": None,
    "tyre": None,
    "rotor": None,
    "scratches": None,
    "cloak": None,
    "headlight_glow": None,
    "taillight_glow": None,
    "sidelight_glow": None,
    "banner": None,
}

ATLAS_SUFFIX = ".dxt.dds.z"

#: Every GPU family the game writes an atlas for, in the order we prefer them.
#: A depot unpacks only the copy its build targets, so an ETC or PVRTC build
#: holds ``<car>_<atlas>.etc.dds.z`` where this one holds ``.dxt.dds.z``.
ATLAS_SUFFIXES = (".dxt.dds.z", ".etc.dds.z", ".atc.dds.z", ".ptc.pvr.z")


def atlas_for_tag(tag: str) -> str | None:
    """Atlas name for a material tag (``None`` when the tag has no atlas)."""
    if not tag:
        return None
    return TAG_ATLAS.get(tag)


def find_atlas(car_dir: str, atlas: str) -> str | None:
    """Path of ``<car_dir>/<car>_<atlas><suffix>`` (None when absent).

    All four GPU families are tried, so this works on a depot unpacked for
    Mali or PowerVR as well as the DXT one.
    """
    try:
        names = sorted(os.listdir(car_dir))
    except OSError:
        return None
    for suffix in ATLAS_SUFFIXES:
        tail = f"_{atlas}{suffix}"
        for name in names:
            if name.endswith(tail):
                return os.path.join(car_dir, name)
    return None


def extract_dds(path: str, out_dir: str) -> str:
    """Decompress ``path`` into ``out_dir`` and return the extracted file path.

    A ``.dds.z`` container is stripped as usual; a ``.pvr.z`` one (the PowerVR
    copy of the same atlas) is stripped the same way, so the result is a plain
    ``.dds`` or ``.pvr`` file rather than an error.
    """
    os.makedirs(out_dir, exist_ok=True)
    stem = os.path.basename(path)
    if stem.lower().endswith(".z"):
        stem = stem[:-2]
    out = os.path.join(out_dir, stem)
    if path.lower().endswith(".pvr.z"):
        from . import pvr as pvrlib
        with open(path, "rb") as fh:
            data = pvrlib.inflate_z(fh.read(), path)
    else:
        data = read_dds_z(path)
    with open(out, "wb") as fh:
        fh.write(data)
    return out
