"""Per-car, per-paint material resolution: the game's own answer to
*"which shader and which texture does this mesh use?"*

The chain has four links and every one of them is data, not guesswork:

1. **mesh name -> part slot** in ``liveryStringTable.bin.nct``
   (``LOD_A_BODY_mm_ext`` -> ``1930``).
2. **part slot -> material slot**, three levels deep
   (``livery.resolve_material``): the paint scheme's override wins, then the
   car's own ``.liveries.bin.nct``, then ``default.liveries.bin.nct``.
3. **material slot -> material name** (``car_paint_gloss``) in the same table.
4. **material name -> shader + LUTs** in ``materials.bin``
   (``rr3lib/gamematerial.py``).

Textures come from the same livery file: it maps texture slots to internal
paths, and a paint scheme may override a slot with its own atlas.  The tag
after ``_mm_`` names the slot as ``ext_<tag>`` (or ``int_<tag>``), which is why
``_mm_ext`` on a paint scheme resolves to that scheme's ``_ext_<colour>`` atlas.

The internal paths end in ``.ptc.pvr.z`` while the shipped files are usually
``.dxt.dds.z``, and a path may or may not carry a ``livery/`` prefix, so
:func:`resolve_texture` tries the car folder first and the ``vehicles`` root
second, and tries every GPU family's suffix at each of them.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from . import gamematerial as gamelib
from . import livery as liverylib
from . import texture as texturelib

#: Internal texture path suffixes seen in the livery tables.  The tables name
#: the PowerVR copy (``.ptc.pvr.z``) no matter which one the depot ships.
INTERNAL_SUFFIXES = (".ptc.pvr.z", ".ptc.dds.z", ".etc.dds.z", ".atc.dds.z",
                     ".dxt.dds.z", ".pvr.z", ".dds.z")
#: On-disk suffixes, in the order we prefer them.  A depot unpacked for Mali or
#: an older Adreno holds ``.etc.dds.z`` / ``.atc.dds.z`` where this one holds
#: ``.dxt.dds.z``, and every one of them decodes.
DISK_SUFFIXES = (".dxt.dds.z", ".etc.dds.z", ".atc.dds.z", ".ptc.pvr.z",
                 ".dds.z", ".pvr.z")


class CarMaterialError(Exception):
    pass


# ---------------------------------------------------------------------------
# texture paths
# ---------------------------------------------------------------------------
def internal_stem(internal: str) -> str:
    """``livery/x_ext_red.ptc.pvr.z`` -> ``livery/x_ext_red``."""
    for suffix in INTERNAL_SUFFIXES:
        if internal.lower().endswith(suffix):
            return internal[:-len(suffix)]
    return internal


def resolve_texture(depot: str, car: str, internal: str) -> str | None:
    """Disk path of a livery texture, or ``None``.

    The tables are inconsistent about the ``livery/`` prefix, so both the car
    folder and the ``vehicles`` root are tried.  That takes the hit rate from
    31 % to 93 % across the 540 cars that ship a livery file.
    """
    if not internal:
        return None
    stem = internal_stem(internal)
    vehicles = os.path.join(depot, "vehicles")
    for base in (os.path.join(vehicles, car, stem),
                 os.path.join(vehicles, stem)):
        for ext in DISK_SUFFIXES:
            path = base + ext
            if os.path.isfile(path):
                return path
    return None


# ---------------------------------------------------------------------------
# slot lookups
# ---------------------------------------------------------------------------
def texture_slot_for_tag(table, tag: str) -> int | None:
    """Texture slot for a ``_mm_`` tag: ``ext_<tag>`` first, then ``int_<tag>``."""
    if not tag:
        return None
    for candidate in ("ext_" + tag, "int_" + tag, tag):
        slot = table.slot(candidate)
        if slot is not None:
            return slot
    return None


def texture_path_for_tag(L, table, tag: str, paint_index: int | None = None,
                         default=None) -> str | None:
    """Internal path a tag's atlas resolves to, honouring the paint override.

    Three levels, in the order the game uses them: the paint scheme's own
    override, then the car's texture row, then ``default.liveries.bin.nct``.

    That last level is what supplies the **shared** atlases: a tyre, a brake
    disc, a window pane and the chassis have no per-car art at all - they point
    at ``vehicles/common/`` (``car_tyre_tread``, ``car_rotor_00``,
    ``car_windows``, ``car_chassis``).  153 of the 540 cars ship no ``ext_tyre``
    row of their own, 155 no ``ext_rotor`` and 90 no ``ext_windows``, so without
    this fallback exactly those cars came out with untextured tyres and glass.
    """
    slot = texture_slot_for_tag(table, tag)
    if slot is None:
        return None
    if paint_index is not None and 0 <= paint_index < len(L.paints):
        hit = L.paints[paint_index].texture_of(slot)
        if hit is not None:
            return hit.decode("utf-8", "replace")
    for s, path in L.textures:
        if s == slot:
            return path.decode("utf-8", "replace")
    if default is not None:
        for s, path in default.textures:
            if s == slot:
                return path.decode("utf-8", "replace")
    return None


# ---------------------------------------------------------------------------
# the resolved material
# ---------------------------------------------------------------------------
@dataclass
class ResolvedMaterial:
    """Everything Blender needs for one mesh under one paint scheme."""

    mesh: str = ""
    material: str = ""          # game material instance name
    level: str = ""             # "paint" / "car" / "default" / "none"
    tag: str = ""               # the _mm_ suffix
    application: str = ""
    #: internal path from the livery table (may be None for untextured parts)
    texture_internal: str | None = None
    #: absolute path of the decoded-from atlas on disk
    texture_file: str | None = None
    fresnel: str | None = None
    specular: str | None = None
    spec_power: float = 0.0
    #: ``mu_MaterialSpecularPower_Top``: the clear-coat lobe
    spec_power_top: float = 0.0
    roughness: float = 1.0
    metallic: float = 0.0
    #: mean of the fresnel ramp (0..1), the raw number behind ``metallic``
    fresnel_mean: float | None = None
    #: ``mu_MaterialSpecularColour_Base`` as 0..1 RGB
    spec_colour: tuple | None = None
    #: Principled clear-coat roughness when the top lobe is sharp enough
    coat: float | None = None
    #: the material's own flag names (``GLASS``, ``FOG``, ``TIRES`` ...)
    flags: tuple = ()
    paint_rgb: tuple | None = None
    notes: list = field(default_factory=list)

    @property
    def key(self) -> str:
        """Stable per-(paint, mesh) name for the Blender material."""
        return self.material or "rr3_material"


def _tag_of(mesh: str) -> str:
    return mesh.rpartition("_mm_")[2] if "_mm_" in mesh else ""


def paint_colour(L, paint_index: int | None) -> tuple | None:
    """The paint scheme's RGB, as a 0..1 tuple, or ``None``."""
    if paint_index is None or not (0 <= paint_index < len(L.paints)):
        return None
    rgb = L.paints[paint_index].rgb
    if len(rgb) < 3:
        return None
    return (rgb[0] / 255.0, rgb[1] / 255.0, rgb[2] / 255.0)


def resolve(depot: str, car: str, mesh: str, *, L=None, table=None,
            default=None, library=None, paint_index: int | None = None
            ) -> ResolvedMaterial:
    """Resolve one mesh under one paint scheme (``None`` = no scheme at all)."""
    if L is None:
        L = liverylib.load_car(depot, car)
    if table is None:
        table = liverylib.load_slot_table(depot)
    if default is None:
        try:
            default = liverylib.load_default(depot)
        except Exception:  # noqa: BLE001 - the fallback table is optional
            default = None
    if library is None:
        library = gamelib.load(depot)

    out = ResolvedMaterial(mesh=mesh, tag=_tag_of(mesh))

    part_slot = table.part_slot(mesh)
    if part_slot is None:
        out.notes.append("mesh is not in the livery string table")
        return out
    mat_slot, level = liverylib.resolve_material(L, part_slot, default, paint_index)
    out.level = level
    if mat_slot is None:
        out.notes.append("no material at any level")
        return out
    out.material = table.name(mat_slot)
    if out.material.startswith("?"):
        out.notes.append(f"material slot {mat_slot} is outside the string table")
        out.material = ""
        return out

    md = library.material(out.material)
    if md is None:
        out.notes.append(f"{out.material} is not in materials.bin")
    else:
        out.application = md.application
        out.flags = tuple(md.flag_names())
        out.spec_power = library.spec_power(out.material)
        out.spec_power_top = library.spec_power_top(out.material)
        out.roughness = gamelib.roughness_from_power(out.spec_power)
        out.fresnel, out.specular, _mask = library.luts(out.material)
        mean = gamelib.ramp_mean(depot, out.fresnel) if out.fresnel else None
        if mean is not None:
            out.metallic = gamelib.metallic_from_fresnel(mean)
            out.fresnel_mean = mean
        colour = library.spec_colour(out.material)
        if colour is not None:
            out.spec_colour = colour
            # the top lobe only reads as a clear coat when it is sharp
            if out.spec_power_top >= 200.0:
                out.coat = gamelib.roughness_from_power(out.spec_power_top)

    internal = texture_path_for_tag(L, table, out.tag, paint_index, default)
    if internal is None and out.tag:
        out.notes.append(f"no livery texture slot for tag {out.tag}")
    out.texture_internal = internal
    if internal:
        out.texture_file = resolve_texture(depot, car, internal)
        if out.texture_file is None:
            out.notes.append(f"texture not on disk: {internal}")

    out.paint_rgb = paint_colour(L, paint_index)
    return out


# ---------------------------------------------------------------------------
# whole car
# ---------------------------------------------------------------------------
@dataclass
class PaintScheme:
    """One paint scheme with the material of every mesh resolved."""

    index: int = 0
    name: str = ""
    rgb: tuple | None = None
    materials: dict = field(default_factory=dict)   # mesh -> ResolvedMaterial
    notes: list = field(default_factory=list)

    def material_for(self, mesh: str) -> ResolvedMaterial | None:
        return self.materials.get(mesh)

    def bl_names(self, car: str) -> dict:
        """``mesh -> "<car>_<scheme>_<material>"`` for Blender."""
        stem = self.name or f"paint{self.index + 1:02d}"
        stem = "".join(c if (c.isalnum() or c in "-_") else "_" for c in stem)
        return {mesh: f"{car}_{stem}_{rm.material or 'rr3'}"
                for mesh, rm in self.materials.items()}


def car_materials(depot: str, car: str, meshes, *, paint_indices=None,
                  library=None, L=None, table=None, default=None) -> list:
    """Resolve every mesh under every paint scheme the car ships.

    ``paint_indices=None`` means every scheme.  Returns a list of
    :class:`PaintScheme` in scheme order.
    """
    if L is None:
        L = liverylib.load_car(depot, car)
    if table is None:
        table = liverylib.load_slot_table(depot)
    if default is None:
        try:
            default = liverylib.load_default(depot)
        except Exception:  # noqa: BLE001
            default = None
    if library is None:
        library = gamelib.load(depot)

    if paint_indices is None:
        indices = list(range(len(L.paints)))
    else:
        indices = [i for i in paint_indices if 0 <= i < len(L.paints)]

    out = []
    for i in indices:
        paint = L.paints[i]
        scheme = PaintScheme(index=i, name=paint.name(), rgb=paint_colour(L, i))
        for mesh in meshes:
            scheme.materials[mesh] = resolve(
                depot, car, mesh, L=L, table=table, default=default,
                library=library, paint_index=i)
        missing = [m for m, rm in scheme.materials.items() if not rm.material]
        if missing:
            scheme.notes.append(f"{len(missing)} mesh(es) without a material")
        out.append(scheme)
    return out


def summary(schemes) -> str:
    """A short human-readable report, for logs and the Text Editor."""
    lines = []
    for scheme in schemes:
        rgb = scheme.rgb
        colour = ("#%02x%02x%02x" % tuple(int(c * 255) for c in rgb)
                  if rgb else "?")
        lines.append(f"paint {scheme.index + 1}: {scheme.name} {colour} "
                     f"({len(scheme.materials)} meshes)")
        for mesh in sorted(scheme.materials):
            rm = scheme.materials[mesh]
            tex = os.path.basename(rm.texture_file) if rm.texture_file else "-"
            lines.append(f"    {mesh:<40} {rm.material:<32} {rm.level:<8} "
                         f"rough {rm.roughness:.2f} metal {rm.metallic:.2f}  {tex}")
    return "\n".join(lines)


def selftest(depot: str | None = None, cars: int = 2) -> int:
    """Resolve a few real cars and report coverage."""
    if not depot:
        depot = os.environ.get("RR3_DEPOT", "")
    if not depot or not os.path.isdir(depot):
        print("carmaterial selftest: no depot (set RR3_DEPOT)")
        return 2
    import glob

    from . import geometry as geometrylib
    from . import m3g as m3glib

    names = [os.path.basename(p) for p in
             sorted(glob.glob(os.path.join(depot, "vehicles", "*")))
             if os.path.isdir(p)]
    checked = 0
    failures = 0
    for car in names:
        body = os.path.join(depot, "vehicles", car, car + "_a.m3g")
        if not os.path.isfile(body):
            continue
        if not os.path.isfile(os.path.join(
                depot, "vehicles", "data", "liveries",
                car + ".liveries.bin.nct")):
            continue
        meshes = [md.name for md in geometrylib.all_meshes(m3glib.M3G(body))]
        schemes = car_materials(depot, car, meshes)
        total = sum(len(s.materials) for s in schemes)
        with_mat = sum(1 for s in schemes for rm in s.materials.values()
                       if rm.material)
        with_tex = sum(1 for s in schemes for rm in s.materials.values()
                       if rm.texture_file)
        print(f"{car}: {len(schemes)} scheme(s), {len(meshes)} mesh(es), "
              f"materials {with_mat}/{total}, textures {with_tex}/{total}")
        if with_mat < total * 0.95:
            failures += 1
        checked += 1
        if checked >= cars:
            break
    print(f"carmaterial selftest: {checked} car(s), {failures} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(selftest())
