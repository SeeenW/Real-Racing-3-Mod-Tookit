"""The ``car.json`` contract between the Blender add-on and this program.

The add-on's job ends when it has written a folder of files.  That folder is
handed over with a manifest next to it, and this program does the rest.  The
manifest is deliberately small and human editable - it names files, it does not
describe geometry::

    {
      "format": 1,
      "name": "2020_mclaren_speedtail_wing",
      "kind": "replace",              // "new" | "replace"
      "donor": "2020_mclaren_speedtail",   // required for "new"
      "identity": {                    // only used by "new"
        "year": 2020, "make": "McLaren", "model": "Speedtail",
        "display_key": "CAR_NAME_SPEEDTAIL",
        "model_token": "SPEEDTAIL"
      },
      "files": {
        "A": "LOD_A.m3g", "B": "LOD_B.m3g", "shared": "SHARED.m3g",
        "int_a": "INT_A.m3g", "wing_banim": "wing.banim",
        "animations": "wing_animations.xml", "points": "car.points"
      },
      "aero": [
        {"part": "LOD_A_WING_REAR_LEFT", "track": 0},
        {"part": "LOD_A_WING_REAR_RIGHT", "track": 1}
      ],
      "liveries": {"wing_part": "LOD_A_WING_REAR_mm_ext"}
    }

Two things this file is *not* allowed to be vague about: a body LOD has to be
present (``files.A``), and for ``kind == "new"`` a donor has to be named - a new
car is a clone of an existing one, because every game table row is keyed by a
car id that must already exist somewhere.
"""

from __future__ import annotations

import json
import os

MANIFEST = "car.json"
FORMAT = 1

#: Keys in ``files`` and whether they are required.
REQUIRED = ("A",)
OPTIONAL = ("B", "C", "D", "E", "F", "G", "H", "shared", "int_a", "int_b",
            "frontend", "wing_banim", "animations", "points", "int_points",
            "dashplanes")

KINDS = ("new", "replace")


class PackError(Exception):
    pass


class ModPack:
    """A folder of exported files plus its ``car.json``."""

    def __init__(self, path: str, data: dict):
        self.path = os.path.abspath(path)
        self.data = data
        self.warnings = []

    # ---- identity ----------------------------------------------------
    @property
    def name(self) -> str:
        return self.data.get("name") or os.path.basename(self.path)

    @property
    def kind(self) -> str:
        return self.data.get("kind") or "replace"

    @property
    def donor(self) -> str:
        return self.data.get("donor") or ""

    @property
    def identity(self) -> dict:
        return dict(self.data.get("identity") or {})

    @property
    def aero(self) -> list:
        return list(self.data.get("aero") or [])

    # ---- files -------------------------------------------------------
    def file(self, key: str) -> str:
        """Absolute path for one ``files`` entry, or ``""``."""
        rel = (self.data.get("files") or {}).get(key)
        if not rel:
            return ""
        p = os.path.join(self.path, rel)
        return p if os.path.isfile(p) else ""

    def files(self) -> dict:
        return {k: self.file(k) for k in REQUIRED + OPTIONAL if self.file(k)}

    def body(self) -> str:
        return self.file("A")

    def missing(self) -> list:
        out = [k for k in REQUIRED if not self.file(k)]
        for key, rel in (self.data.get("files") or {}).items():
            if key in REQUIRED + OPTIONAL and rel and not self.file(key):
                out.append(f"{key} -> {rel}")
        return out

    def validate(self) -> list:
        """Problems that must be fixed before a build.  Empty means good."""
        bad = list(self.missing())
        if self.kind not in KINDS:
            bad.append(f"kind {self.kind!r} is not one of {KINDS}")
        if self.kind == "new" and not self.donor:
            bad.append("kind 'new' needs a donor car name")
        if not self.body():
            bad.append("no body LOD (files.A)")
        return bad

    def summary(self) -> str:
        return (f"{self.name} [{self.kind}] "
                f"{len(self.files())} file(s)"
                + (f", donor {self.donor}" if self.donor else ""))


def load(path: str) -> ModPack:
    """Load ``<folder>/car.json``.  ``path`` may be the folder or the file."""
    if os.path.isdir(path):
        p = os.path.join(path, MANIFEST)
        if not os.path.isfile(p):
            raise PackError(f"{path} has no {MANIFEST}")
    else:
        p = path
    try:
        with open(p, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as exc:
        raise PackError(f"{p}: {exc}") from exc
    fmt = data.get("format", FORMAT)
    if fmt != FORMAT:
        raise PackError(f"{p}: format {fmt}, this program speaks {FORMAT}")
    return ModPack(os.path.dirname(p), data)


def find(folder: str) -> str:
    """Return the ``car.json`` path in a folder, or ``""``."""
    p = os.path.join(folder, MANIFEST)
    return p if os.path.isfile(p) else ""


def dump(pack: ModPack) -> str:
    return json.dumps(pack.data, indent=2, ensure_ascii=False) + "\n"


def save(pack: ModPack, path: str = "") -> str:
    path = path or os.path.join(pack.path, MANIFEST)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(dump(pack))
    return path
