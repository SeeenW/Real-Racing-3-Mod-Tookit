"""Which file goes in which slot, worked out from the folder itself.

The Blender side has no memory between runs: it writes files and stops.  So the
contract is the file name - ``LOD_A.m3g`` is the A body LOD, ``SHARED.m3g`` is
the shared model, ``wing.banim`` is the active aero animation - and this module
turns a folder of them into a slot table the dialog can show.

Two things this is careful about:

* **A slot is not a guess we keep to ourselves.**  The dialog shows every slot
  the game allows with the file currently mapped to it, so a wrong guess is
  visible and fixable before anything is written.
* **The target name is the game's, not the user's.**  ``LOD_A.m3g`` becomes
  ``<car>_a.m3g`` on the way in; nothing here requires the exported file to
  already carry the car's name.

The slot keys are the ones :mod:`rrmod.modpack` and :mod:`rrmod.deploy` already
speak, so a table built here drops straight into a build.
"""

from __future__ import annotations

import os
import re

MANIFEST = "car.json"

#: ``(key, label, the name the game uses, required)``, in the order a car is
#: built up.  ``{car}`` is replaced by the car's folder name.
SLOTS = (
    ("A", "Body LOD A (the model you see up close)", "{car}_a.m3g", True),
    ("B", "Body LOD B", "{car}_b.m3g", False),
    ("C", "Body LOD C", "{car}_c.m3g", False),
    ("D", "Body LOD D", "{car}_d.m3g", False),
    ("E", "Body LOD E", "{car}_e.m3g", False),
    ("F", "Body LOD F", "{car}_f.m3g", False),
    ("G", "Body LOD G", "{car}_g.m3g", False),
    ("H", "Body LOD H", "{car}_h.m3g", False),
    ("shared", "Wheels and tyres (every LOD uses this one)", "{car}_shared.m3g", False),
    ("int_a", "Interior LOD A", "{car}_int_a.m3g", False),
    ("int_b", "Interior LOD B", "{car}_int_b.m3g", False),
    ("frontend", "Menu / showroom model", "{car}_frontend.m3g", False),
    ("wing_banim", "Active aero animation", "{car}_wing.banim", False),
    ("animations", "Which aero clips the game plays", "{car}_animations.xml", False),
    ("points", "Anchors and hinges", "{car}.points", False),
    ("int_points", "Interior anchors", "{car}_int.points", False),
    ("dashplanes", "Dashboard display planes", "{car}.dashplanes", False),
)

#: Slot keys in order.
KEYS = tuple(slot[0] for slot in SLOTS)
#: Slot key -> the name the game expects.
TARGETS = {slot[0]: slot[2] for slot in SLOTS}
#: Slot key -> the human label.
LABELS = {slot[0]: slot[1] for slot in SLOTS}
#: The slots a build cannot do without.
REQUIRED = tuple(slot[0] for slot in SLOTS if slot[3])

#: Suffix -> slot, longest first so ``_int_a.m3g`` never reads as LOD A.  Both
#: spellings are accepted: the exporter may write ``SHARED.m3g`` or a file that
#: already carries the car's name, ``2012_lexus_lfa_shared.m3g``.
#:
#: The bare ``int_a.m3g`` spelling has to be listed too, and *before* the body
#: LODs can get a look at it: ``int_a.m3g`` ends with ``_a.m3g``, so the bare
#: name loop would otherwise file the interior under body LOD A and then report
#: the real ``LOD_A.m3g`` as unused.
_BY_NAME = (
    ("_int_a.m3g", "int_a"),
    ("_int_b.m3g", "int_b"),
    ("int_a.m3g", "int_a"),
    ("int_b.m3g", "int_b"),
    ("_shared.m3g", "shared"),
    ("_frontend.m3g", "frontend"),
    ("_wing.banim", "wing_banim"),
    ("_animations.xml", "animations"),
    ("_int.points", "int_points"),
    ("int.points", "int_points"),
    (".dashplanes", "dashplanes"),
    (".points", "points"),
)

#: ``LOD_A.m3g`` / ``lod_c.M3G`` / ``LOD_A_model.m3g``.
_LOD_RE = re.compile(r"^lod[_-]([a-h])(?:[_-][a-z0-9_]*)?\.m3g$", re.I)


class SlotError(Exception):
    pass


def guess(folder: str) -> dict:
    """Map the files in ``folder`` onto slots by name.

    Returns ``{key: absolute path}``.  Anything that cannot be placed is left
    out; :func:`problems` reports it so the dialog can say so out loud.
    """
    found: dict = {}
    for name in sorted(os.listdir(folder)):
        path = os.path.join(folder, name)
        if not os.path.isfile(path):
            continue
        key = slot_of(name)
        if key and key not in found:
            found[key] = path
    return found


def slot_of(filename: str) -> str:
    """Which slot a file name belongs to, or ``""``."""
    low = filename.lower()
    match = _LOD_RE.match(low)
    if match:
        return match.group(1).upper()
    for suffix, key in _BY_NAME:
        if low.endswith(suffix):
            return key
    # Bare names: SHARED.m3g, wing.banim, car.points, animations.xml ...
    for key, _label, template, _required in SLOTS:
        bare = template.replace("{car}", "").lstrip("_").lower()
        if low == bare or low.endswith("_" + bare) or low.endswith("." + bare):
            return key
    return ""


def problems(folder: str, mapping: dict, *, required: bool = True) -> list:
    """Everything that would stop a build, in the words the dialog shows.

    ``required=False`` is for changing a car that is already installed: there
    the folder is optional and only the slots that were actually mapped matter,
    because the rest of the car's files stay exactly as they are.  ``folder``
    may be empty in that case - nothing is scanned for spare files.
    """
    out = []
    if required:
        for key in REQUIRED:
            if not mapping.get(key):
                out.append(f"no file for {LABELS[key]} ({TARGETS[key]})")
    if folder and os.path.isdir(folder):
        on_disk = sorted(
            n for n in os.listdir(folder)
            if os.path.isfile(os.path.join(folder, n)) and n.lower().endswith(
                (".m3g", ".banim", ".xml", ".points", ".dashplanes")))
        used = {os.path.basename(p).lower() for p in mapping.values() if p}
        spare = [n for n in on_disk if n.lower() not in used]
        if spare:
            out.append("not used: " + ", ".join(spare))
    seen: dict = {}
    for key, path in mapping.items():
        if not path:
            continue
        if not os.path.isfile(path):
            out.append(f"{os.path.basename(path)} is missing")
            continue
        low = os.path.basename(path).lower()
        if low in seen:
            out.append(f"{os.path.basename(path)} is in two slots")
        seen[low] = key
    return out


def target_name(key: str, car: str) -> str:
    """The file name the game expects for ``key`` on car ``car``."""
    template = TARGETS.get(key)
    if template is None:
        raise SlotError(f"{key!r} is not a slot")
    return template.replace("{car}", car)


def plan(mapping: dict, car: str) -> list:
    """``[(key, source, target file name)]`` for everything that is mapped."""
    out = []
    for key in KEYS:
        source = mapping.get(key)
        if source:
            out.append((key, source, target_name(key, car)))
    return out


def rename_plan(mapping: dict, car: str) -> dict:
    """``{target file name: source path}``, ready to copy into a car folder."""
    return {name: source for _key, source, name in plan(mapping, car)}


def summary(mapping: dict) -> str:
    used = [k for k in KEYS if mapping.get(k)]
    if not used:
        return "no files mapped"
    return (f"{len(used)} of {len(KEYS)} slots filled: "
            + ", ".join(used))


def describe(mapping: dict) -> list:
    """``[(key, label, target, source or "")]`` for every slot, filled or not."""
    out = []
    for key, label, template, _required in SLOTS:
        out.append((key, label, template, mapping.get(key, "")))
    return out


# ------------------------------------------------------------------ the pack
class SlotPack:
    """A slot table wearing the same clothes as a ``car.json`` pack.

    :func:`rrmod.edit.install_pack` and :mod:`rrmod.modpack` both speak
    "something with ``files()`` and ``body()``", so a table the dialog built by
    hand can be handed straight to them.  This is what makes ``car.json``
    optional: the folder and the slot table are the truth, the manifest is a
    convenience that only carries the identity strings a folder cannot express.
    """

    def __init__(self, path: str, mapping: dict, *, name: str = "",
                 kind: str = "new", donor: str = "",
                 identity: dict | None = None):
        self.path = os.path.abspath(path) if path else ""
        self.mapping = dict(mapping)
        self._name = name or os.path.basename(self.path)
        self._kind = kind
        self._donor = donor
        self._identity = dict(identity or {})
        self.warnings: list = []

    # ---- what the builders ask for -----------------------------------
    @property
    def name(self) -> str:
        return self._name

    @property
    def kind(self) -> str:
        return self._kind

    @property
    def donor(self) -> str:
        return self._donor

    @property
    def identity(self) -> dict:
        return dict(self._identity)

    @property
    def aero(self) -> list:
        return []

    def file(self, key: str) -> str:
        path = self.mapping.get(key) or ""
        return path if path and os.path.isfile(path) else ""

    def files(self) -> dict:
        return {k: self.file(k) for k in KEYS if self.file(k)}

    def body(self) -> str:
        return self.file("A")

    def missing(self) -> list:
        return [f"no file for {LABELS[k]}" for k in REQUIRED if not self.file(k)]

    def validate(self) -> list:
        bad = list(self.missing())
        if self._kind not in ("new", "replace"):
            bad.append(f"kind {self._kind!r} is not 'new' or 'replace'")
        if self._kind == "new" and not self._donor:
            bad.append("a new car needs a donor")
        return bad

    def summary(self) -> str:
        return (f"{self._name} [{self._kind}] {len(self.files())} file(s)"
                + (f", donor {self._donor}" if self._donor else ""))


def from_pack(pack) -> dict:
    """Read a ``car.json`` pack into a slot table (absolute paths)."""
    out = {}
    for key in KEYS:
        path = pack.file(key)
        if path:
            out[key] = path
    return out


def read_folder(folder: str) -> dict:
    """The slot table for a folder: ``car.json`` first, file names after.

    A folder with no manifest still works, which is the point - the Blender side
    writes files and stops.
    """
    mapping = {}
    manifest = os.path.join(folder, MANIFEST)
    if os.path.isfile(manifest):
        try:
            from . import modpack as packlib
            mapping.update(from_pack(packlib.load(folder)))
        except Exception:                       # noqa: BLE001
            pass
    for key, path in guess(folder).items():
        mapping.setdefault(key, path)
    return mapping
