"""What ``materials.bin`` contains, and which cars actually wear each row.

The game does not take a mesh's material from the model.  It looks the mesh slot
up in the car's livery table and uses *that* name; only when nothing is named
does it fall back to the shipped default.  So the interesting question about a
material is not "what does it look like" but "who points at it", and that is what
this module answers.

Three tables have to be joined to say anything useful:

``materials.bin``
    297 material instances and 186 shader bindings (``rr3lib.gamematerial``).
    A row carries an application, a blend mode, a colour and a set of feature
    flags; the shader behind it carries the specular ramp and the power.
``liveryStringTable.bin.nct``
    102 of those names also have a *slot number*, and a slot is what a livery
    row can point at.  A material without one cannot be named by any car, which
    is why the pickers only offer the 102.
``<car>.liveries.bin.nct``
    per car, per paint scheme: which mesh slot uses which material slot.

Nothing here writes.  Editing a material is editing a binary table with 297
interleaved records and no length prefixes to resynchronise on; a viewer that
tells you what a name means and who uses it is the useful half.
"""

from __future__ import annotations

import collections
import os

from rr3lib import gamematerial as gamematerial
from rr3lib import livery as liverylib

#: Where ``materials.bin`` lives, relative to ``.depot``.
MATERIALS_REL = "materials/materials.bin"

#: Application strings worth spelling out - the rest are shown as they are.
APPLICATIONS = {
    "appCarPaint": "car paint (livery colour, specular ramp)",
    "appCarWheels": "wheels (tyres, discs, rims)",
    "appCarGlass": "glass (refraction, tint)",
    "appCarLights": "lights (emissive, alpha)",
    "appCarBadge": "badges (flat decal)",
    "appCarDecal": "decals",
    "appDefault": "everything else",
}


class ManagerError(Exception):
    """Raised when the material tables cannot be read."""


def _depot(root: str) -> str:
    root = os.path.abspath(root)
    if os.path.basename(root) == ".depot":
        return root
    inner = os.path.join(root, ".depot")
    return inner if os.path.isdir(inner) else root


def library(depot: str):
    """The parsed ``materials.bin`` (raises ``ManagerError`` if it is missing)."""
    depot = _depot(depot)
    path = os.path.join(depot, *MATERIALS_REL.split("/"))
    if not os.path.isfile(path):
        raise ManagerError(f"this install has no {MATERIALS_REL}")
    try:
        return gamematerial.load(depot)
    except Exception as exc:                                   # noqa: BLE001
        raise ManagerError(f"{MATERIALS_REL} did not read: {exc}") from exc


def slots(depot: str) -> dict:
    """``{material name: livery slot}`` for the names a car can point at."""
    depot = _depot(depot)
    try:
        table = liverylib.load_slot_table(depot)
    except Exception:                                          # noqa: BLE001
        return {}
    out = {}
    for slot in range(len(table)):
        name = table.name(slot)
        if name and name.startswith("car_"):
            out[name] = slot
    return out


def usage(depot: str, *, log=None) -> dict:
    """``{material name: number of cars whose paints point at it}``.

    Reads every car's livery file, which is a couple of seconds on the full
    install; pass ``log`` to say so.  A car counts once per material however
    many of its paints or meshes name it, because the useful question is "how
    many cars would notice if this row changed".
    """
    depot = _depot(depot)
    try:
        table = liverylib.load_slot_table(depot)
    except Exception:                                          # noqa: BLE001
        return {}
    if log:
        log("reading every car's livery table...")
    counts = collections.Counter()
    folder = os.path.join(depot, "vehicles", "data", "liveries")
    if not os.path.isdir(folder):
        return {}
    for leaf in sorted(os.listdir(folder)):
        if not leaf.endswith(".liveries.bin.nct"):
            continue
        try:
            L = liverylib.load(os.path.join(folder, leaf))
        except Exception:                                      # noqa: BLE001
            continue
        seen = set()
        for source in [L] + list(L.paints):
            for _mesh_slot, mat_slot in getattr(source, "materials", ()):
                try:
                    text = table.name(int(mat_slot))
                except Exception:                              # noqa: BLE001
                    continue
                if text:
                    seen.add(text)
        counts.update(seen)
    return dict(counts)


def catalogue(depot: str, *, with_usage: bool = True, log=None) -> dict:
    """Every material row, joined with its slot and how many cars use it."""
    depot = _depot(depot)
    lib = library(depot)
    slot_of = slots(depot)
    used = usage(depot, log=log) if with_usage else {}
    rows = []
    for name in sorted(lib.materials):
        mat = lib.materials[name]
        shader = lib.shader_for(name)
        rows.append({
            "name": name,
            "template": mat.template or "",
            "application": mat.application or "",
            "applicationText": APPLICATIONS.get(mat.application or "", ""),
            "blend": mat.blend or "",
            "cull": mat.cull or "",
            "rgba": tuple(mat.rgba),
            "flags": tuple(mat.flags),
            "paint": bool(mat.is_paint),
            "slot": slot_of.get(name),
            "writable": name in slot_of,
            "cars": used.get(name, 0),
            "shader": getattr(shader, "name", "") if shader else "",
        })
    return {
        "materials": rows,
        "shaders": len(lib.shaders),
        "total": len(rows),
        "writable": sum(1 for r in rows if r["writable"]),
        "used": sum(1 for r in rows if r["cars"]),
    }


def details(depot: str, name: str) -> dict:
    """Everything the two tables say about one material."""
    depot = _depot(depot)
    lib = library(depot)
    mat = lib.material(name)
    if mat is None:
        raise ManagerError(f"there is no material called {name!r}")
    shader = lib.shader_for(name)
    slot_of = slots(depot)
    out = {
        "name": name,
        "template": mat.template or "",
        "application": mat.application or "",
        "applicationText": APPLICATIONS.get(mat.application or "", ""),
        "blend": mat.blend or "",
        "cull": mat.cull or "",
        "primitive": mat.primitive or "",
        "rgba": tuple(mat.rgba),
        "flags": tuple(mat.flags),
        "twosided": bool(mat.twosided),
        "queue": mat.queue,
        "priority": mat.priority,
        "alphaTest": bool(mat.alpha_test),
        "paint": bool(mat.is_paint),
        "slot": slot_of.get(name),
        "writable": name in slot_of,
        "shader": "",
        "textures": [],
        "uniforms": [],
    }
    if shader is not None:
        out["shader"] = shader.name
        out["vertexShader"] = shader.vsh
        out["fragmentShader"] = shader.fsh
        out["textures"] = [(int(k), v) for k, v in sorted(shader.textures.items())]
        out["uniforms"] = sorted(shader.uniforms.items())
    try:
        out["specularPower"] = lib.spec_power(name)
        out["specularColour"] = lib.spec_colour(name)
        out["roughness"] = gamematerial.roughness_from_power(out["specularPower"])
    except Exception:                                          # noqa: BLE001
        out["specularPower"] = None
        out["specularColour"] = None
        out["roughness"] = None
    return out


def paints(depot: str) -> list:
    """The names a livery row can point at to make something look painted."""
    return sorted(n for n in slots(depot) if n.startswith("car_paint_")
                  or n.startswith("car_bumper_paint_"))


def summary(depot: str) -> dict:
    depot = _depot(depot)
    lib = library(depot)
    slot_of = slots(depot)
    return {
        "materials": len(lib.materials),
        "shaders": len(lib.shaders),
        "writable": sum(1 for n in lib.materials if n in slot_of),
        "paints": len(paints(depot)),
    }


def selftest(depot: str) -> int:
    """Return the number of surprises (0 is good)."""
    bad = 0
    try:
        lib = library(depot)
    except ManagerError as exc:
        print("  FAIL", exc)
        return 1
    print(f"  {len(lib.materials)} materials, {len(lib.shaders)} shaders")
    slot_of = slots(depot)
    print(f"  {len(slot_of)} of them have a livery slot")
    missing = [n for n in slot_of if lib.material(n) is None]
    if missing:
        print(f"  FAIL {len(missing)} slot names are not in materials.bin: {missing[:4]}")
        bad += len(missing)
    sample = next((n for n in slot_of if n.startswith("car_paint_")), "")
    if sample:
        info = details(depot, sample)
        print(f"  {sample}: {info['application']} flags={len(info['flags'])} "
              f"roughness={info['roughness']}")
        if not info["shader"]:
            print("  FAIL that paint has no shader binding")
            bad += 1
    return bad
