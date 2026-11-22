"""Dump Real Racing 3 assets (``.m3g`` / ``.points`` / ``.banim`` / ``.dashplanes``).

Drag any of those files - or a whole folder, or a car folder - onto
``rr3dump.bat`` and the readable reports appear in ``dump\\`` next to this
script.  ``rr3dump_json.bat`` writes ``.json`` instead of ``.txt``.

Command line
------------
    python rr3dump.py -o D:\\out --format both --max-keys 0 "path\\to\\file.banim"

    -o / --out     output folder (default: ``dump\\`` beside this script)
    --format       ``txt`` (default), ``json`` or ``both``
    --max-keys     how many keyframes the .banim text report prints per curve
                   (0 = all; the JSON always carries every key)
    --frames       decode only the first N animation frames (0 = all)
    --no-anim      skip the per-frame decode, keep the raw curves only

What gets written
-----------------
Per input file ``<name>`` (the file name *including* its extension):

    <name>.txt              human readable report
    <name>.json             the same data as JSON

For a folder (and for a car folder in particular) there are three more:

    <folder>_report.txt     first/last frame, anchors, every frame
    <folder>_frames.csv     one row per part per frame, BOM so Excel opens it
    <folder>_assembly.txt   wheel mounts, tyre radii, aero pivots, motion rules

Every run also appends to ``index.txt`` (``<input>\\t<output>`` per line) so a
big batch can be traced back.

Units
-----
``.banim`` rotations are degrees: ``deg = raw * 180 / 32768``.  Positions are
``raw / 65536`` metres for every banim, wing files included.  ``.points`` and
``.dashplanes`` store engine world units, ``metres = raw / 32``.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import struct
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rr3lib import (  # noqa: E402
    banim,
    dashplanes,
    geometry,
    m3g,
    parts,
    points,
    rig,
)

#: File types this tool understands.
DEFAULT_SUFFIXES = (".banim", ".points", ".m3g", ".dashplanes")

#: Where reports go when ``-o`` is not given.
DEFAULT_OUT = ROOT / "dump"

#: ``--format`` choices.
FORMATS = ("txt", "json", "both")

#: 1 m = 32 engine world units, for ``.points`` / ``.dashplanes``.
POINT_SCALE = 32.0

#: Frame rate used for the per-frame tables and the CSV.
FPS = 30.0

CSV_HEADER = ("file", "part", "t_ms", "x_m", "y_m", "z_m",
              "rx_deg", "ry_deg", "rz_deg")

MOTION_RULES = """\
MOTION RULES (decoded)
  * wheel spin   : about the wheel's own local X axis, angle += v / tyre_radius
                   per second (the game computes this from the car's speed;
                   no wheel curve is stored in any .banim)
  * wheel steer  : front wheels only, about the chassis up axis at WHEEL_FL/FR
  * wheel_blur   : a second rim mesh (radius = rim radius) swapped in above a
                   speed threshold; identical pivot, slower UV rotation
  * active aero  : each *_WING* part is a child of its pivot; the pivot itself
                   translates (ch0..2, 1/65536 m) and rotates (ch3..5, 1/32768
                   rad, Euler XYZ) along the wing banim's own key times
  * playing      : <car>_animations.xml maps clip names to banim frame ranges,
                   e.g. wing_up 0..75, wing_down 75..0 (30 fps timeline)"""

UNIT_NOTES = """\
单位说明
  * xyz 单位是米，模型坐标：x = 右, y = 上, z = 车头方向。
      - 空力部件枢轴 = 原始值 / 65536
      - 驾驶员关节   = 原始值 / 65536
      - .points 锚点 = 原始值 / 32（游戏内 32 倍缩放已验证）
  * 旋转单位是度，欧拉 XYZ，角度 = 原始值 × 180 / 32768。
    负值 = 前倾 / 向下，正值 = 后翘 / 向上。
  * 网格本身已按静止姿态建模，所以第 1 帧的角度是"作者姿态基准"；
    套到网格上时应使用"变化"一行的 Δrot（末帧 − 首帧），否则会重复旋转一次。
  * 轮子没有关键帧：转速 = 车速 / 轮胎半径，绕轮心局部 X 轴；前轮另绕竖直轴转向。"""


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------
def _out_name(src: Path, ext: str) -> str:
    """``wing.banim`` -> ``wing.banim.txt`` (the whole name, extension kept)."""
    return src.name + ext


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\r\n")
    return path


def _write_json(path: Path, data) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, indent=2, ensure_ascii=False)
    path.write_text(text, encoding="utf-8", newline="\r\n")
    return path


def _bits(value: float) -> str:
    """The raw 32 bits of a float, as the file stores it."""
    return "0x%08x" % struct.unpack("<I", struct.pack("<f", value))[0]


def _round(values, digits: int) -> list[float]:
    return [round(float(v), digits) for v in values]


def _metres(position) -> list[float]:
    return [round(float(v) / POINT_SCALE, 4) for v in position]


def _hex_bytes(raw: bytes) -> str:
    return " ".join(f"{b:02x}" for b in raw)


# --------------------------------------------------------------------------
# .points
# --------------------------------------------------------------------------
def _points_json(pf: points.PointsFile) -> dict:
    def record(rec: points.PointRecord) -> dict:
        return {
            "index": rec.index,
            "type": rec.type,
            "typeName": rec.type_name,
            "name": rec.name,
            "offset": rec.offset,
            "size": rec.size,
            "position": list(rec.position) if rec.position else None,
            "positionMetres": _metres(rec.position) if rec.position else None,
            "matrix": list(rec.matrix) if rec.matrix else None,
            "splineFlags": rec.spline_flags,
            "splinePoints": [list(p) for p in rec.spline_points],
            "splinePointsMetres": [_metres(p) for p in rec.spline_points],
            "splines": [[list(p) for p in spline] for spline in rec.splines],
            "raw": _hex_bytes(rec.raw),
        }

    return {
        "kind": "points",
        "file": str(pf.path),
        "version": pf.version,
        "positionUnit": "engine world unit, 1 m = 32 units",
        "positionMetresFormula": "metres = raw / 32",
        "records": [record(r) for r in pf.records],
        "overrides": [{"index": o.index, "name": o.name, "value": o.value}
                      for o in pf.overrides],
        "warnings": list(pf.warnings),
    }


# --------------------------------------------------------------------------
# .m3g
# --------------------------------------------------------------------------
def _mesh_json(model: m3g.M3G, obj) -> dict:
    md = geometry.extract_mesh(model, obj)
    box = md.bbox
    return {
        "object": obj.index,
        "name": md.name,
        "materialId": md.material_id,
        "materialName": md.material_name,
        "vertices": len(md.positions),
        "triangles": len(md.triangles),
        "bbox": {"min": list(box[0]), "max": list(box[1])} if box else None,
        "positionScale": md.position_scale,
        "positionBias": list(md.position_bias),
        "texcoordScale": list(md.texcoord_scale),
        "texcoordBias": list(md.texcoord_bias),
        "submeshes": [
            {
                "indexBuffer": s.index_buffer,
                "appearance": s.appearance,
                "indices": s.index_count,
                "isStrip": s.is_strip,
                "triangles": len(s.triangles),
            }
            for s in md.submeshes
        ],
        "warnings": list(md.warnings),
    }


def _m3g_json(model: m3g.M3G) -> dict:
    types: dict[str, int] = {}
    for obj in model.objects:
        key = str(obj.type)
        types[key] = types.get(key, 0) + 1
    return {
        "kind": "m3g",
        "file": str(model.path),
        "bytes": len(model.buf),
        "version": model.version,
        "author": model.author,
        "objects": len(model.objects),
        "sections": model.sections,
        "objectTypes": types,
        "materials": list(model.materials),
        "meshes": [_mesh_json(model, o) for o in model.of_type(m3g.T_MESH)],
        "warnings": list(model.warnings),
    }


# --------------------------------------------------------------------------
# .dashplanes
# --------------------------------------------------------------------------
def _dashplanes_json(dp) -> dict:
    return {
        "file": dp.path.name,
        "size": dp.size,
        # DashPlanes.count is the header tag, not a plane count - use the list.
        "count": len(dp.planes),
        "tag": dp.tag,
        "positionUnit": "1/32 m, model space (x right, y forward, z up)",
        "planes": [
            {
                "index": plane.index,
                "name": plane.name,
                "offset": plane.offset,
                "font": plane.font,
                "rgb": list(plane.rgb),
                "size": list(plane.size),
                "flags": list(plane.flags),
                "extra": plane.extra,
                "position": list(plane.position),
                "matrix": list(plane.matrix),
            }
            for plane in dp.planes
        ],
        "warnings": list(dp.warnings),
    }


# --------------------------------------------------------------------------
# .banim
# --------------------------------------------------------------------------
def _banim_model(banim_path: Path, track_count: int):
    """Best-effort lookup of the ``.m3g`` a ``.banim`` drives, for part names."""
    try:
        return rig.find_model(banim_path, track_count)
    except Exception:  # noqa: BLE001 - a missing model is not an error
        return None


def _banim_names(b: banim.Banim, model_path=None) -> list[str]:
    if model_path is not None:
        try:
            return rig.track_names(b, rig.mesh_names_of(model_path))
        except Exception:  # noqa: BLE001
            pass
    return rig.track_names(b)


def _banim_json(b: banim.Banim, *, frames: int, anim: bool) -> dict:
    model_path = _banim_model(b.path, b.num_tracks)
    names = _banim_names(b, model_path)
    roles = rig.roles_for(b)

    keys = [{"index": i, "timeMs": t, "value": v, "valueBits": _bits(v)}
            for i, (t, v) in enumerate(b.keys)]

    data = {
        "kind": "banim",
        "file": str(b.path),
        "bytes": b.size,
        "magic": f"0x{b.magic:08x}",
        "variant": b.variant,
        "version": b.version,
        "fieldA": b.field_a,
        "numTracks": b.num_tracks,
        "durationMs": b.duration_ms,
        "headerSize": b.header_size,
        "dataOffset": b.data_offset,
        "layout": b.layout,
        "totalKeys": b.total_keys,
        "keysShown": len(keys),
        "tracks": [
            {
                "index": t.index,
                "indexRaw": t.index_raw,
                "curves": [{"index": c.index, "numKeys": c.num_keys,
                            "startKey": c.start_key} for c in t.curves],
            }
            for t in b.tracks
        ],
        "keys": keys,
        "trailer": {
            "offset": b.trailer_offset,
            "words": list(b.trailer_words),
            "pad": b.trailer_pad,
        },
        "properties": [[k, v] for k, v in b.properties],
        "eventNames": list(b.names),
        "warnings": list(b.warnings),
    }

    if not anim:
        return data

    decoded = []
    for t in rig.frame_times(b, FPS, frames):
        rows = []
        for i in range(b.num_tracks):
            state = rig.part_state(b, i, t, names[i], roles[i] if i < len(roles) else "")
            raw = rig.sample_track(b, b.tracks[i], t)
            rows.append({
                "track": i,
                "name": names[i] if i < len(names) else f"track{i:02d}",
                "position": _round(state.position, 6),
                "rotationDeg": _round(state.rotation_deg, 4),
                # the raw channel value, before the 180/32768 conversion
                "rotationRaw": [int(round(raw[3 + k])) for k in range(3)],
                "matrix": [_round(row, 6) for row in state.matrix],
            })
        decoded.append({"timeMs": t, "parts": rows})

    data["animation"] = {
        "space": rig.AXIS_DOC,
        "positionUnit": "metre (raw / 65536)",
        "rotationUnit": "degree (raw * 180/32768), Euler XYZ",
        "channelMap": "ch0..ch2 position, ch3..ch5 rotation (curve 2*i)",
        "boundModel": model_path.name if model_path is not None else None,
        "fps": FPS,
        "parts": [
            {
                "track": i,
                "name": names[i] if i < len(names) else f"track{i:02d}",
                "role": roles[i] if i < len(roles) else "",
            }
            for i in range(b.num_tracks)
        ],
        "frames": decoded,
    }
    return data


def _banim_text(b: banim.Banim, *, max_keys: int, frames: int, anim: bool) -> str:
    """The raw dump followed by the decoded per-frame table."""
    text = banim.format_report(b, max_keys=max_keys, per_curve=True)
    if not anim:
        return text
    model_path = _banim_model(b.path, b.num_tracks)
    names = _banim_names(b, model_path)
    return text + "\n" + rig.format_report(b, names, FPS, frames)


# --------------------------------------------------------------------------
# one file
# --------------------------------------------------------------------------
def dump_file(path, out_dir, fmt: str = "txt", max_keys: int = 0,
              frames: int = 0, anim: bool = True) -> list[Path]:
    """Dump one asset.  Returns the files written.

    ``fmt`` is ``"txt"``, ``"json"`` or ``"both"``.  ``max_keys`` limits how
    many keyframes the .banim text report prints per curve (0 = all);
    ``frames`` limits the per-frame decode (0 = all) and ``anim=False`` skips
    it entirely.
    """
    src = Path(path)
    out = Path(out_dir)
    fmt = (fmt or "txt").lower()
    if fmt not in FORMATS:
        raise ValueError(f"format must be one of {FORMATS}, not {fmt!r}")
    suffix = src.suffix.lower()
    if suffix not in DEFAULT_SUFFIXES:
        raise ValueError(f"{src.name}: not a dumpable file (want {DEFAULT_SUFFIXES})")

    want_txt = fmt in ("txt", "both")
    want_json = fmt in ("json", "both")
    written: list[Path] = []

    if suffix == ".banim":
        b = banim.load(src)
        if want_txt:
            written.append(_write(out / _out_name(src, ".txt"),
                                  _banim_text(b, max_keys=max_keys,
                                              frames=frames, anim=anim)))
        if want_json:
            written.append(_write_json(out / _out_name(src, ".json"),
                                       _banim_json(b, frames=frames, anim=anim)))
    elif suffix == ".points":
        pf = points.load(src)
        if want_txt:
            written.append(_write(out / _out_name(src, ".txt"),
                                  points.format_report(pf)))
        if want_json:
            written.append(_write_json(out / _out_name(src, ".json"),
                                       _points_json(pf)))
    elif suffix == ".m3g":
        model = m3g.M3G(src)
        if want_txt:
            written.append(_write(out / _out_name(src, ".txt"),
                                  geometry.format_report(model)))
        if want_json:
            written.append(_write_json(out / _out_name(src, ".json"),
                                       _m3g_json(model)))
    else:  # .dashplanes
        dp = dashplanes.load(src)
        if want_txt:
            written.append(_write(out / _out_name(src, ".txt"),
                                  dashplanes.format_report(dp)))
        if want_json:
            written.append(_write_json(out / _out_name(src, ".json"),
                                       _dashplanes_json(dp)))
    return written


# --------------------------------------------------------------------------
# a folder: the combined report, the CSV and the assembly plan
# --------------------------------------------------------------------------
def _banims_in(folder: Path) -> list[Path]:
    return sorted(p for p in folder.iterdir()
                  if p.is_file() and p.suffix.lower() == ".banim")


def _points_in(folder: Path) -> list[Path]:
    return sorted(p for p in folder.iterdir()
                  if p.is_file() and p.suffix.lower() == ".points")


def format_report_folder(folder, fps: float = FPS) -> str:
    """The three-section report: first/last frame, anchors, every frame."""
    folder = Path(folder)
    lines: list[str] = []
    add = lines.append
    bar = "=" * 78

    add(bar)
    add(f"RR3 report: {folder.name}")
    add(f"source     : {folder}")
    add(f"generated  : {time.strftime('%Y-%m-%d %H:%M:%S')}")
    add(f"fps sample : {fps:g}")
    add(bar)
    add("")
    add("1. 首末两帧 (first / last frame)")
    add("")

    for path in _banims_in(folder):
        b = banim.load(path)
        names = _banim_names(b, _banim_model(path, b.num_tracks))
        roles = rig.roles_for(b)
        add(f"[{path.name}]  tracks={b.num_tracks}  duration={b.duration_ms:g} ms"
            f"  keys={b.total_keys}  layout={b.layout}")
        duration = b.duration_ms or 0.0
        for i in range(b.num_tracks):
            name = names[i] if i < len(names) else f"track{i:02d}"
            role = roles[i] if i < len(roles) else ""
            label = f"{name} [{role}]" if role and role != f"track {i}" else name
            first = rig.part_state(b, i, 0.0, name, role)
            last = rig.part_state(b, i, duration, name, role)
            add(f"  track {i} {label}")
            add(f"      起始 (t = 0 ms)   xyz = ({first.position[0]:.3f},"
                f" {first.position[1]:.3f}, {first.position[2]:.3f}) m"
                f"   rot = ({first.rotation_deg[0]:.2f},"
                f" {first.rotation_deg[1]:.2f}, {first.rotation_deg[2]:.2f}) °")
            add(f"      末帧 (t = {duration:g} ms)   xyz = ({last.position[0]:.3f},"
                f" {last.position[1]:.3f}, {last.position[2]:.3f}) m"
                f"   rot = ({last.rotation_deg[0]:.2f},"
                f" {last.rotation_deg[1]:.2f}, {last.rotation_deg[2]:.2f}) °")
            delta = [last.position[k] - first.position[k] for k in range(3)]
            drot = [last.rotation_deg[k] - first.rotation_deg[k] for k in range(3)]
            add(f"      变化                Δxyz = ({delta[0]:.4f},"
                f" {delta[1]:.4f}, {delta[2]:.4f}) m"
                f"   Δrot = ({drot[0]:.3f}, {drot[1]:.3f}, {drot[2]:.3f}) °")
        add("")
    add("")
    add("2. 锚点位置 (.points)")
    add("")
    for path in _points_in(folder):
        pf = points.load(path)
        add(f"[{path.name}]  version={pf.version}  records={len(pf.records)}"
            f"  overrides={len(pf.overrides)}")
        add(f"  {'name':<36} {'x (m)':>10} {'y (m)':>12} {'z (m)':>12}")
        add("  " + "-" * 66)
        for rec in pf.records:
            if rec.position is None:
                add(f"  {rec.name:<36} {'-':>10} {'-':>12} {'-':>12}")
                continue
            x, y, z = _metres(rec.position)
            add(f"  {rec.name:<36} {x:>10.4f} {y:>12.4f} {z:>12.4f}")
        add("")
    add("")
    add("3. banim 全部帧 (all frames)")
    add("")
    for path in _banims_in(folder):
        b = banim.load(path)
        names = _banim_names(b, _banim_model(path, b.num_tracks))
        roles = rig.roles_for(b)
        times = rig.frame_times(b, fps, 0)
        add(f"[{path.name}]  frames={len(times)}  fps={fps:g}")
        for i in range(b.num_tracks):
            name = names[i] if i < len(names) else f"track{i:02d}"
            role = roles[i] if i < len(roles) else ""
            label = f"{name} [{role}]" if role and role != f"track {i}" else name
            add(f"  track {i} {label}")
            add(f"      {'t (ms)':>8} {'x (m)':>10} {'y (m)':>10} {'z (m)':>10}"
                f" {'rx (deg)':>10} {'ry (deg)':>10} {'rz (deg)':>10}")
            for t in times:
                state = rig.part_state(b, i, t, name, role)
                px, py, pz = state.position
                rx, ry, rz = state.rotation_deg
                add(f"      {t:8.1f} {px:10.4f} {py:10.4f} {pz:10.4f}"
                    f" {rx:10.3f} {ry:10.3f} {rz:10.3f}")
            add("")
    add("")
    add("")
    add(UNIT_NOTES)
    return "\r\n".join(lines) + "\r\n"


def write_frames_csv(folder, out_path, fps: float = FPS) -> Path:
    """One row per part per frame; BOM so Excel opens it on a double click."""
    folder = Path(folder)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh, lineterminator="\r\n")
        writer.writerow(CSV_HEADER)
        for path in _banims_in(folder):
            b = banim.load(path)
            names = _banim_names(b, _banim_model(path, b.num_tracks))
            roles = rig.roles_for(b)
            for t in rig.frame_times(b, fps, 0):
                for i in range(b.num_tracks):
                    name = names[i] if i < len(names) else f"track{i:02d}"
                    role = roles[i] if i < len(roles) else ""
                    state = rig.part_state(b, i, t, name, role)
                    # model space (x right, y up, z forward), metres
                    mx, my, mz = parts.anim_to_model(state.position)
                    rx, ry, rz = state.rotation_deg
                    label = f"track {i} {name}"
                    if role and role != f"track {i}":
                        label += f" [{role}]"
                    writer.writerow([
                        path.name, label, round(t, 1),
                        f"{mx:.4f}", f"{my:.4f}", f"{mz:.4f}",
                        f"{rx:.3f}", f"{ry:.3f}", f"{rz:.3f}",
                    ])
    return out_path


def format_assembly(car_dir, car: str, lod: str = "A") -> str:
    """``parts.format_report`` plus the wheel radii and the motion rules."""
    plan = parts.build_plan(str(car_dir), car, lod)
    lines = [parts.format_report(plan, show_keys=0)]

    shared = plan.shared_file
    lines.append("")
    lines.append("WHEEL MESHES")
    if shared and plan.wheels.front_wheel:
        rows = (
            ("front", plan.wheels.front_wheel),
            ("rear", plan.wheels.rear_wheel or plan.wheels.front_wheel),
            ("tyre", plan.wheels.front_tyre),
            ("blur", plan.wheels.front_wheel_blur),
        )
        for label, mesh in rows:
            if not mesh:
                continue
            try:
                radius = parts.wheel_radius(shared, mesh)
            except Exception as exc:  # noqa: BLE001
                lines.append(f"  {label:<6} {mesh:<34} ! {exc}")
                continue
            lines.append(f"  {label:<6} {mesh:<34} radius={radius:.4f} m")
    else:
        lines.append("  (no _shared.m3g - this model has no wheels)")

    lines.append("")
    lines.append(MOTION_RULES)
    lines.append("")
    return "\r\n".join(lines) + "\r\n"


def dump_folder(folder, out_dir, fmt: str = "txt", max_keys: int = 0,
                frames: int = 0, anim: bool = True, report: bool = True,
                log=print) -> list[Path]:
    """Dump every asset in ``folder`` plus the three combined reports."""
    folder = Path(folder)
    out = Path(out_dir)
    written: list[Path] = []
    files = sorted(p for p in folder.iterdir()
                   if p.is_file() and p.suffix.lower() in DEFAULT_SUFFIXES)
    for path in files:
        try:
            written.extend(dump_file(path, out, fmt, max_keys, frames, anim))
        except Exception as exc:  # noqa: BLE001 - keep going, report at the end
            log(f"[fail] {path.name}: {type(exc).__name__}: {exc}")
    if not report or not files:
        return written

    name = folder.name
    if _banims_in(folder):
        written.append(_write(out / f"{name}_report.txt",
                              format_report_folder(folder)))
        written.append(write_frames_csv(folder, out / f"{name}_frames.csv"))
    if _points_in(folder) or (folder / f"{name}_a.m3g").exists():
        try:
            written.append(_write(out / f"{name}_assembly.txt",
                                  format_assembly(folder, name, "A")))
        except Exception as exc:  # noqa: BLE001
            log(f"[fail] {name}_assembly.txt: {type(exc).__name__}: {exc}")
    return written


# --------------------------------------------------------------------------
# command line
# --------------------------------------------------------------------------
def _append_index(out_dir: Path, pairs: list[tuple[Path, Path]]) -> None:
    if not pairs:
        return
    index = out_dir / "index.txt"
    out_dir.mkdir(parents=True, exist_ok=True)
    with index.open("a", encoding="utf-8", newline="\n") as fh:
        for src, dst in pairs:
            fh.write(f"{src}\t{dst}\n")


def collect(targets) -> tuple[list[Path], list[Path]]:
    """Split the command line into files and folders, expanding nothing else."""
    files: list[Path] = []
    folders: list[Path] = []
    for target in targets:
        path = Path(target).expanduser()
        if path.is_dir():
            folders.append(path)
        elif path.is_file():
            files.append(path)
        else:
            raise SystemExit(f"not found: {target}")
    return files, folders


def run(targets, *, out_dir=DEFAULT_OUT, fmt="txt", max_keys=0, frames=0,
        anim=True, log=print) -> dict:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    files, folders = collect(targets)
    written: list[Path] = []
    failures = 0
    t0 = time.time()
    for path in files:
        try:
            written.extend(dump_file(path, out, fmt, max_keys, frames, anim))
        except Exception as exc:  # noqa: BLE001
            failures += 1
            log(f"[fail] {path}: {type(exc).__name__}: {exc}")
    for folder in folders:
        try:
            written.extend(dump_folder(folder, out, fmt, max_keys, frames,
                                       anim, log=log))
        except Exception as exc:  # noqa: BLE001
            failures += 1
            log(f"[fail] {folder}: {type(exc).__name__}: {exc}")
    _append_index(out, [(p, p) for p in written])
    return {
        "out": str(out),
        "files": written,
        "failures": failures,
        "seconds": round(time.time() - t0, 2),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="rr3dump",
        description="Dump Real Racing 3 .m3g / .points / .banim / .dashplanes.",
    )
    parser.add_argument("paths", nargs="*",
                        help="files or folders (a car folder gives the extra "
                             "report, CSV and assembly plan)")
    parser.add_argument("-o", "--out", default=str(DEFAULT_OUT),
                        help=f"output folder (default: {DEFAULT_OUT})")
    parser.add_argument("--format", default="txt", choices=FORMATS,
                        help="txt (default), json, or both")
    parser.add_argument("--max-keys", type=int, default=0,
                        help="keyframes printed per curve in the .banim text "
                             "report (0 = all)")
    parser.add_argument("--frames", type=int, default=0,
                        help="decode only the first N animation frames "
                             "(0 = all)")
    parser.add_argument("--no-anim", action="store_true",
                        help="skip the per-frame decode, keep the raw curves")
    args = parser.parse_args(argv)

    targets = args.paths
    if not targets:
        parser.print_help()
        return 2

    result = run(targets, out_dir=args.out, fmt=args.format,
                 max_keys=args.max_keys, frames=args.frames,
                 anim=not args.no_anim)
    print(f"wrote {len(result['files'])} file(s) to {result['out']}"
          f" in {result['seconds']}s")
    for path in result["files"]:
        print(f"  {path.name}  {path.stat().st_size} bytes")
    if result["failures"]:
        print(f"{result['failures']} input(s) failed", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
