"""Lookup helpers over :mod:`rr3lib.catalog_data`.

The embedded tables describe what the *shipped* cars use, which is exactly the
set of names the engine understands.  Nothing here reads game files, so the
addon can validate a name with no data cast present.

Three things are worth knowing before using a name:

**Materials come in instances, not templates.**  ``materials.bin`` holds 297
material records built from 137 base templates.  ``car_paint_gloss`` is a
*template*; the records derived from it include ``car_paint_gloss`` itself
(``appCarPaint`` - the real car paint), ``car_alpha`` (``appDefault`` with
``ALPHA_MODULATE`` - a UI material that happens to share the template),
``car_gloss``, and the two ``appCarBumperPaint`` variants.  Only the instance
name is written into a livery table, and the engine picks the record by name,
so the *paint* ones are the ``appCarPaint`` rows.

**A part name is a mesh name.**  ``LOD_A_BODY_mm_ext`` means: LOD A, the BODY
group, tag ``ext``.  The tag decides which atlas page and render group the mesh
uses; the part name decides the material through the livery tables.

**Only names in these tables work.**  A mesh whose name is not in
``liveryStringTable`` has no slot, so no livery override can ever target it and
the engine falls back to a hard coded material.
"""

from __future__ import annotations

from . import catalog_data

#: Tags that appear after ``_mm_`` in a part name, with what they select.
TAG_DOC = {
    "ext": "exterior paint - the body shell, doors, bumpers, wings",
    "misc": "exterior trim - black plastic, grilles, underbody",
    "badges": "badges and emblems (separate atlas, alpha)",
    "lights": "lamp lenses (uses the lights atlas)",
    "cab": "cabin / interior shell seen through the glass",
    "chassis": "chassis, suspension arms, engine bay",
    "windows": "glass",
    "windows_cracked": "glass, cracked damage state",
    "windows_shattered": "glass, shattered damage state",
    "int": "interior",
    "sw": "steering wheel",
    "wheel": "wheel rim",
    "wheel_blur": "wheel rim, motion blur LOD",
    "tyre": "tyre",
    "rotor": "brake rotor",
    "cloak": "cloak / cover geometry",
    "banner": "banner decal",
    "scratches": "scratch overlay",
    "headlight_glow": "headlight glow sprite",
    "sidelight_glow": "sidelight glow sprite",
    "taillight_glow": "taillight glow sprite",
    "mat00": "interior trim slot 0 (carbon fibre)",
    "mat01": "interior trim slot 1 (leather)",
    "mat02": "interior trim slot 2 (stitching, alpha)",
    "mat03": "interior trim slot 3 (vinyl)",
    "mat04": "interior trim slot 4 (suede)",
    "mat05": "interior trim slot 5 (carpet / rubber)",
    "mat06": "interior trim slot 6 (aluminium)",
    "mat07": "interior trim slot 7 (spare)",
}

#: Application -> what it does, for picking a material record.
APPLICATION_DOC = {
    "appCarPaint": "car paint: fresnel + specular LUT, writes stencil 4",
    "appCarBumperPaint": "bumper paint: same family, slightly different flags",
    "appCarWheels": "wheels and tyres",
    "appCarDash": "interior / dashboard",
    "appCarMirror": "mirrors",
    "appCarDecoration": "decals and livery overlays",
    "appDefault": "generic opaque or alpha surface",
    "appDepthSort": "transparent, depth sorted",
    "appOverlays": "screen overlays",
    "appProjectedLights": "projected light decals",
    "appShadows": "shadow blobs",
    "appSkids": "skid marks",
    "appGhostCar": "ghost car",
    "appGhostCarBrakeLights": "ghost car brake lights",
    "appTree": "trees",
    "appTreeLines": "tree billboards",
    "appTreeLinesOuter": "outer tree billboards",
    "appBuildingalpha": "alpha tested buildings",
    "appFence": "fences",
    "appCrowd": "crowd billboards",
    "appSkyBack": "skybox back",
    "appSkyFront": "skybox front",
    "appDepthWriteOnly": "depth only",
    "appFlareBlocker": "lens flare occluder",
}

#: The paint materials, i.e. the ones a livery override should target.
PAINT_MATERIALS = (
    "car_paint_gloss", "car_paint_matte", "car_paint_matte_high",
    "car_paint_chrome", "car_paint_gold", "car_paint_carbon_fibre",
    "car_paint_pearl_blue",
    "car_paint_metallic_white", "car_paint_metallic_warm",
    "car_paint_metallic_cool", "car_paint_metallic_cool_light",
    "car_paint_metallic_red", "car_paint_metallic_blue",
    "car_paint_metallic_darkblue", "car_paint_metallic_purple",
    "car_paint_metallic_green", "car_paint_metallic_green_light",
    "car_paint_metallic_bloodred", "car_paint_metallic_bloodorange",
    "car_paint_metallic_orange", "car_paint_metallic_yellow",
    "car_paint_metallic_spec_yellow", "car_paint_metallic_spec_orange",
    "car_paint_metallic_spec_red", "car_paint_metallic_spec_white",
    "car_paint_candy_pink", "car_paint_candy_apple",
    "car_paint_candy_tangerine", "car_paint_candy_cherry",
    "car_paint_candy_copper", "car_paint_candy_lime",
    "car_paint_candy_emerald", "car_paint_candy_lemon",
    "car_paint_candy_blue", "car_paint_candy_violet",
    "car_paint_candy_pearl",
)


def materials() -> list[tuple[str, str, str, str]]:
    """Every material instance as ``(name, template, application, flags)``."""
    return [tuple(r) for r in catalog_data.raw()["materials"]]


def material_names() -> list[str]:
    """Every material instance name, sorted."""
    return [r[0] for r in materials()]


def material(name: str) -> tuple[str, str, str, str] | None:
    """One material row, or ``None``."""
    for r in materials():
        if r[0] == name:
            return tuple(r)
    return None


def material_variants(template: str) -> list[tuple[str, str, str, str]]:
    """Every instance built from ``template`` - e.g. all ``car_paint_gloss``."""
    return [r for r in materials() if r[1] == template]


def paint_materials() -> list[tuple[str, str, str, str]]:
    """The paint family, i.e. the ones worth putting on a body part."""
    return [r for r in materials() if r[2] == "appCarPaint"]


def parts() -> list[tuple[str, int]]:
    """Every part name as ``(name, liveryStringTable slot)``."""
    return [(r[0], r[1]) for r in catalog_data.raw()["parts"]]


def part_names() -> list[str]:
    return [r[0] for r in parts()]


def part_slot(name: str) -> int | None:
    """The ``liveryStringTable`` slot for a part name, or ``None``.

    ``None`` means the engine has no slot for this name, so no livery table can
    ever refer to it - rename the mesh instead of trying to paint it.
    """
    for n, s in parts():
        if n == name:
            return s
    return None


def tags() -> list[str]:
    """Every ``_mm_`` tag in use, sorted."""
    out = set()
    for n in part_names():
        if "_mm_" in n:
            out.add(n.rsplit("_mm_", 1)[1])
    return sorted(out)


def split_part(name: str) -> tuple[str, str, str]:
    """``LOD_A_BODY_mm_ext`` -> ``("A", "LOD_A_BODY", "ext")``.

    A name without ``_mm_`` returns an empty tag; a name without the ``LOD_X_``
    prefix returns an empty LOD.
    """
    lod = ""
    base = name
    if name.startswith("LOD_") and len(name) > 5 and name[5] == "_":
        lod = name[4]
        base = name[6:]
    tag = ""
    if "_mm_" in base:
        base, tag = base.rsplit("_mm_", 1)
        base = "LOD_%s_%s" % (lod, base) if lod else base
    return lod, base, tag


def bases() -> list[str]:
    """Every distinct part base name (without the ``_mm_`` tag)."""
    return sorted({split_part(n)[1] for n in part_names()})


def parts_for_base(base: str) -> list[str]:
    """Every tagged variant of one base, e.g. all ``LOD_A_BODY_mm_*``."""
    return [n for n in part_names() if split_part(n)[1] == base]


def parts_with_tag(tag: str) -> list[str]:
    """Every part using one tag, e.g. every ``_mm_ext`` mesh."""
    return [n for n in part_names() if split_part(n)[2] == tag]


def search(text: str, limit: int = 40) -> list[str]:
    """Case insensitive substring search over part names."""
    low = text.lower()
    return [n for n in part_names() if low in n.lower()][:limit]


def summary() -> str:
    """A short human readable description, for the report operator."""
    mats = materials()
    paint = paint_materials()
    lines = [
        f"materials : {len(mats)} instances from "
        f"{len({r[1] for r in mats})} templates ({len(paint)} of them car paint)",
        f"parts     : {len(part_names())} names, "
        f"{len(bases())} bases, {len(tags())} tags",
        "",
        "paint materials (use these on a body part):",
    ]
    for name in PAINT_MATERIALS:
        row = material(name)
        if row is None:
            continue
        flags = row[3] or "(no flags)"
        lines.append(f"  {name:<34} {flags}")
    return "\n".join(lines)
