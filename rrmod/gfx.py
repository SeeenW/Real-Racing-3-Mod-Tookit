"""The graphics profile: ``AndroidHigh.plist`` and ``AndroidHigh.feats``.

The engine picks its quality tier from the device, then loads two files::

    platform AndroidHigh
    Loaded settings file: AndroidHigh.plist        <- AA, shadows, LOD, HDR, ...
    Loading shader features file: AndroidHigh.feats <- which shader macros compile

Both are plain XML wrapped in the same RC4 the ``.nct`` files use, so
:mod:`rr3lib.nct` reads and writes them without any external tool.  Both are
read from ``.depot/eds/`` and ``.depot/feats/`` at start-up; the copies under
``apk/res/`` are only the unpacked source and get overwritten, which is why the
``.depot`` one is the one that matters.

Two rules the engine enforces, both learned the hard way:

* ``PLIST_IDENTIFIER`` must keep saying ``AndroidHigh``.  Any other value makes
  the engine reject the file and fall back to defaults.
* A key that is not in the file is *not* zero - the engine keeps its own
  default.  So a profile is a set of overrides, not a full table.

This module only parses, compares and writes.  Nothing here knows about adb;
:mod:`rrmod.deploy` pushes the result.
"""

from __future__ import annotations

import os
import re

from rr3lib import nct

PLIST_REL = "eds/AndroidHigh.plist"
FEATS_REL = "feats/AndroidHigh.feats"

#: the only value the engine accepts here
IDENTIFIER = "AndroidHigh"

PLIST_RE = re.compile(
    r"<key>(?P<k>[^<]*)</key>\s*"
    r"(?:<(?P<t>true|false)/>"
    r"|<integer>(?P<i>-?\d+)</integer>"
    r"|<real>(?P<r>-?[\d.eE+]+)</real>"
    r"|<string>(?P<s>.*?)</string>)",
    re.S)

FEAT_RE = re.compile(r"<Key>(?P<k>[^<]*)</Key>\s*<Value>(?P<v>[^<]*)</Value>", re.S)


class GfxError(Exception):
    pass


# ---------------------------------------------------------------- plist I/O
def parse_plist(text: str) -> dict:
    """``{key: bool | int | float | str}`` for every typed key in the file."""
    out = {}
    for m in PLIST_RE.finditer(text):
        if m.group("t") is not None:
            out[m.group("k")] = (m.group("t") == "true")
        elif m.group("i") is not None:
            out[m.group("k")] = int(m.group("i"))
        elif m.group("r") is not None:
            out[m.group("k")] = float(m.group("r"))
        else:
            out[m.group("k")] = m.group("s")
    return out


def _fmt_plist(key: str, value) -> str:
    if isinstance(value, bool):
        return f"<key>{key}</key>\n\t<{'true' if value else 'false'}/>"
    if isinstance(value, int):
        return f"<key>{key}</key>\n\t<integer>{value}</integer>"
    if isinstance(value, float):
        text = "%g" % value
        if "." not in text and "e" not in text and "E" not in text:
            text += ".0"
        return f"<key>{key}</key>\n\t<real>{text}</real>"
    return f"<key>{key}</key>\n\t<string>{value}</string>"


def apply_plist(text: str, changes: dict) -> str:
    """Replace keys in place; append the ones that are not there yet."""
    missing = {}
    for key, value in changes.items():
        pattern = re.compile(
            r"<key>%s</key>\s*(?:<true/>|<false/>|<integer>-?\d+</integer>"
            r"|<real>-?[\d.eE+]+</real>|<string>.*?</string>)" % re.escape(key),
            re.S)
        if pattern.search(text):
            text = pattern.sub(lambda _m, k=key, v=value: _fmt_plist(k, v), text,
                               count=1)
        else:
            missing[key] = value
    if missing:
        add = "\n".join("\t" + _fmt_plist(k, v) for k, v in missing.items()) + "\n"
        if "</dict>" not in text:
            raise GfxError("the plist has no </dict> to add keys before")
        text = text.replace("</dict>", add + "</dict>", 1)
    return text


# ---------------------------------------------------------------- feats I/O
def parse_feats(text: str) -> dict:
    return {m.group("k"): (m.group("v").strip().lower() == "true")
            for m in FEAT_RE.finditer(text)}


def apply_feats(text: str, changes: dict) -> str:
    for key, value in changes.items():
        want = "true" if value else "false"
        pattern = re.compile(r"<Key>%s</Key>(\s*)<Value>[^<]*</Value>"
                             % re.escape(key), re.S)
        if pattern.search(text):
            text = pattern.sub(
                lambda m, k=key, v=want: f"<Key>{k}</Key>{m.group(1)}<Value>{v}</Value>",
                text, count=1)
        else:
            if "</Device>" not in text:
                raise GfxError("the feats file has no </Device> to add keys before")
            add = f"    <Key>{key}</Key>\n    <Value>{want}</Value>\n"
            text = text.replace("  </Device>", add + "  </Device>", 1)
    return text


# ------------------------------------------------------------------ profiles
#
# Every entry is "what to change relative to the file on disk", never a full
# table.  ``high`` is empty on purpose: that is the file the game ships with.
PROFILES = {
    "low": {
        "AA_LEVEL": 0, "MIPMAP_BIAS": 2.0, "CUBE_MAP_DIMENSIONS": 256,
        "USE_ANISOTROPIC_FILTERING": False, "USE_HDR_POST_PROCESS": False,
        "TONEMAP": False, "GAMMA_CORRECTION": False, "ENV_MAP_HDR": False,
        "CAR_PLANAR_REFLECTION": False, "CAR_AMBIENT_OCCLUSION": False,
        "USE_REALTIME_CAR_SHADOW_MAPS": False,
        "STREAMING_CAR_SHADOW_MAPS": False, "PARTICLE_CAST_SHADOW": False,
        "HIGH_RES_MENU": False, "TEXTURE_MIPMAP_LEVELS_TO_SKIP": 1,
        "LIGHTMAP_MIPMAP_LEVELS_TO_SKIP": 1, "REDUCED_PNG_BITDEPTH": True,
        "AUDIO_MIX_RATE": 22050, "EXPECTED_RENDERER": "GL_ES_2",
        "FONT_PAGE_SIZE": 0, "MENU_MAX_GARAGE_CARS_VISIBLE": 12,
        "MENU_CAR_CACHE_SIZE": 4,
    },
    "mid": {
        "AA_LEVEL": 0, "MIPMAP_BIAS": 0.0, "CUBE_MAP_DIMENSIONS": 512,
        "USE_ANISOTROPIC_FILTERING": False, "USE_HDR_POST_PROCESS": False,
        "TONEMAP": False, "GAMMA_CORRECTION": False, "ENV_MAP_HDR": False,
        "CAR_PLANAR_REFLECTION": False, "CAR_AMBIENT_OCCLUSION": False,
        "USE_REALTIME_CAR_SHADOW_MAPS": False,
        "STREAMING_CAR_SHADOW_MAPS": False, "PARTICLE_CAST_SHADOW": False,
        "HIGH_RES_MENU": False, "TEXTURE_MIPMAP_LEVELS_TO_SKIP": 0,
        "LIGHTMAP_MIPMAP_LEVELS_TO_SKIP": 0, "REDUCED_PNG_BITDEPTH": True,
        "AUDIO_MIX_RATE": 24000, "EXPECTED_RENDERER": "GL_ES_2",
        "FONT_PAGE_SIZE": 1024,
    },
    "high": {},
    "ultra": {
        "AA_LEVEL": 4, "MIPMAP_BIAS": -2.0, "CUBE_MAP_DIMENSIONS": 1024,
        "USE_ANISOTROPIC_FILTERING": True, "USE_HDR_POST_PROCESS": True,
        "USE_HDR_AUTOMATIC_EXPOSURE": True, "TONEMAP": True,
        "GAMMA_CORRECTION": True, "ENV_MAP_HDR": True,
        "ENV_MAP_DYNAMIC_BLUR": True, "CAR_PLANAR_REFLECTION": True,
        "CAR_AMBIENT_OCCLUSION": True, "CAR_INTERIOR_SHADOW_MAPS": True,
        "USE_REALTIME_CAR_SHADOW_MAPS": True,
        "STREAMING_CAR_SHADOW_MAPS": True, "PARTICLE_CAST_SHADOW": True,
        "HIGH_RES_MENU": True, "CREATE_FULL_SCREEN_BUFFERS": True,
        "USE_32BIT_COLOR_BUFFER": True, "REDUCED_PNG_BITDEPTH": False,
        "TEXTURE_MIPMAP_LEVELS_TO_SKIP": 0,
        "LIGHTMAP_MIPMAP_LEVELS_TO_SKIP": 0, "AUDIO_MIX_RATE": 48000,
        "EXPECTED_RENDERER": "GL_ES_3", "FONT_PAGE_SIZE": 2048,
        "LENS_FLARE_SCALE": 16.0, "PROP_MIN_COVERAGE": 0.005,
        "UNIQUE_ENGINE_RAMP_LIMIT": 14, "PARTY_PLAY_MAX_AI_OPP": 12,
        "PARTY_PLAY_MAX_AI_OPP_NASCAR": 22,
        "MENU_MAX_GARAGE_CARS_VISIBLE": 99, "MENU_CAR_CACHE_SIZE": 12,
    },
    "insane": {
        "AA_LEVEL": 8, "MIPMAP_BIAS": -3.0, "CUBE_MAP_DIMENSIONS": 2048,
        "CUSTOMISATION_DECAL_TEXTURE_SIZE": 1024,
        "CUSTOMISATION_LIVERY_TEXTURE_SIZE": 2048,
        "PIXEL_THRESHOLD_NORMAL": 4, "PIXEL_THRESHOLD_CUBEMAP_NORMAL": 50,
        "PIXEL_THRESHOLD_CUBEMAP_HIGH_DETAIL": 20,
        "PIXEL_THRESHOLD_CUBEMAP_LOW_DETAIL": 100,
        "SUPPORTS_BIG_TRACKS": True,
    },
}

#: shader macros the Android profile leaves off but the desktop ones turn on
FEATS_ULTRA = {
    "PLANAR_REFLECTION": True, "NORMAL_MAP": True, "WORLD_NORMAL_MAP": True,
    "GLOSS_MAP": True, "WORLD_GLOSS_MAP": True, "SHADOW_MAP_NEAREST": True,
    "SHADOW_MAP_LINEAR": True, "SHADOW_MAP_VSM": True, "SHADOW_MAP_PCF": True,
    "SHADOW_MAP_DITHER": True, "HDR_LENS_DISTORTION": True,
    "LENS_DISTORTION_CHROMATIC_ABERRATION": True, "CACHED_SHADOW_MAP": True,
    "UPDATE_CACHED_SHADOW_MAP": True, "MOTION_BLUR_CAMERA": True,
    "MOTION_BLUR_CAMERA_WRITE_ALPHA": True, "SPEC_FLAKES": True,
}

FEATS_LOW = {
    "PLANAR_REFLECTION": False, "NORMAL_MAP": False, "WORLD_NORMAL_MAP": False,
    "GLOSS_MAP": False, "WORLD_GLOSS_MAP": False, "SHADOW_MAP_NEAREST": False,
    "SHADOW_MAP_LINEAR": False, "SHADOW_MAP_VSM": False,
    "SHADOW_MAP_PCF": False, "SHADOW_MAP_DITHER": False,
    "HDR_LENS_DISTORTION": False,
    "LENS_DISTORTION_CHROMATIC_ABERRATION": False,
    "CACHED_SHADOW_MAP": False, "UPDATE_CACHED_SHADOW_MAP": False,
    "MOTION_BLUR_CAMERA": False, "MOTION_BLUR_CAMERA_WRITE_ALPHA": False,
    "SPEC_FLAKES": False, "DEPTH_OF_FIELD": False, "BLOOM": False,
}


def plist_layer(profile: str) -> dict:
    """The plist overrides for a named profile (``insane`` includes ``ultra``)."""
    if profile == "insane":
        out = dict(PROFILES["ultra"])
        out.update(PROFILES["insane"])
        return out
    if profile not in PROFILES:
        raise GfxError(f"unknown profile {profile!r} "
                       f"(have: {', '.join(PROFILES)})")
    return dict(PROFILES[profile])


def feats_layer(profile: str) -> dict:
    if profile == "low":
        return dict(FEATS_LOW)
    if profile in ("ultra", "insane"):
        return dict(FEATS_ULTRA)
    if profile == "mid":
        return {"SPEC_FLAKES": False}
    if profile == "high":
        return {}
    raise GfxError(f"unknown profile {profile!r}")


# -------------------------------------------------------------------- files
class GfxFile:
    """One of the two files: its plaintext text and the values in it."""

    def __init__(self, path: str, kind: str, text: str):
        self.path = path
        self.kind = kind                      # "plist" or "feats"
        self.text = text
        self.values = (parse_plist(text) if kind == "plist"
                       else parse_feats(text))

    def __len__(self) -> int:
        return len(self.values)

    def get(self, key: str, default=None):
        return self.values.get(key, default)

    def summary(self) -> dict:
        vals = self.values
        bools = sum(1 for v in vals.values() if isinstance(v, bool))
        return {"kind": self.kind, "path": self.path, "keys": len(vals),
                "bools": bools, "bytes": len(self.text)}


def plist_path(depot: str) -> str:
    return os.path.join(depot, *PLIST_REL.split("/"))


def feats_path(depot: str) -> str:
    return os.path.join(depot, *FEATS_REL.split("/"))


def read(path: str, kind: str = "") -> GfxFile:
    """Decrypt and parse one file.  ``kind`` is guessed from the name."""
    if not kind:
        kind = "feats" if path.lower().endswith(".feats") else "plist"
    plain = nct.read(path)
    try:
        text = plain.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise GfxError(f"{os.path.basename(path)} is not UTF-8 XML: {exc}") from exc
    if kind == "plist" and "<plist" not in text:
        raise GfxError(f"{os.path.basename(path)} is not a plist")
    if kind == "feats" and "<ShaderFeatures" not in text:
        raise GfxError(f"{os.path.basename(path)} is not a shader features file")
    return GfxFile(path, kind, text)


def read_pair(depot: str) -> tuple:
    """``(plist GfxFile, feats GfxFile)``; either may be None when missing."""
    out = []
    for path, kind in ((plist_path(depot), "plist"), (feats_path(depot), "feats")):
        out.append(read(path, kind) if os.path.exists(path) else None)
    return tuple(out)


def write(file: GfxFile, path: str = "") -> int:
    """Re-encrypt and write.  Returns the number of bytes on disk."""
    path = path or file.path
    blob = file.text.encode("utf-8")
    nct.write(path, blob)
    return os.path.getsize(path)


# ------------------------------------------------------------------ planning
def plan(depot: str, profile: str, *, custom: dict | None = None,
         custom_feats: dict | None = None, base: str = "") -> dict:
    """What a profile would change, without writing anything.

    ``base`` names one of the shipped profiles to start from instead of the file
    on disk - ``base="AndroidXtraHigh"`` with ``profile="high"`` copies that
    profile over verbatim, which is how a device family's settings are borrowed.

    Returns ``{"profile", "base", "plist": [(key, before, after)], "feats": [...],
    "texts": {"plist": new text, "feats": new text}, "warnings": [...]}``.
    """
    plist, feats = read_pair(depot)
    if plist is None and feats is None:
        raise GfxError("this install has no eds/AndroidHigh.plist or "
                       "feats/AndroidHigh.feats")
    changes = plist_layer(profile)
    changes.update(custom or {})
    # the identifier is not a quality knob: changing it makes the engine throw
    # the whole file away
    changes.pop("PLIST_IDENTIFIER", None)
    fchanges = feats_layer(profile)
    fchanges.update(custom_feats or {})

    warnings = []
    out = {"profile": profile, "base": base, "plist": [], "feats": [],
           "texts": {}, "warnings": warnings}

    if plist is not None:
        start = plist.text
        if base:
            start = base_text(depot, base)
            warnings.append(f"starting from eds/{base}.plist rather than the "
                            f"file on disk")
            # the identity of the file is not part of what is being borrowed:
            # copying another family's PLIST_IDENTIFIER would make the engine
            # throw the whole file away
            start = apply_plist(start, {k: plist.values[k] for k in DEVICE_KEYS
                                        if k in plist.values})
        new_text = apply_plist(start, changes)
        after = parse_plist(new_text)
        for key, value in changes.items():
            if key not in plist.values:
                warnings.append(f"plist key {key} is not in the file; "
                                f"it will be appended")
        # A base profile rewrites every key it carries, not just the ones the
        # chosen tier names, so the diff has to be taken over the union of both
        # files - otherwise "copy XtraHigh over" would report no changes at all.
        for key in sorted(set(plist.values) | set(after)):
            if plist.values.get(key) != after.get(key):
                out["plist"].append((key, plist.values.get(key), after.get(key)))
        out["texts"]["plist"] = new_text
        if after.get("PLIST_IDENTIFIER") != IDENTIFIER:
            warnings.append("PLIST_IDENTIFIER is not AndroidHigh - the engine "
                            "will ignore this file")
        if after.get("HAS_PHOTO_MODE") and not plist.values.get("HAS_PHOTO_MODE"):
            warnings.append("HAS_PHOTO_MODE is on. The Android build has no "
                            "photo-mode assets: the game dies in the car-select "
                            "scene with this set (verified 2026-11-07).")
        if after.get("GUI_LAYOUT_EXTENSION") != plist.values.get("GUI_LAYOUT_EXTENSION"):
            ext = after.get("GUI_LAYOUT_EXTENSION")
            warnings.append(f"GUI_LAYOUT_EXTENSION is {ext!r}; the Android "
                            f"package only ships 480x320, 960x640 and 2048x1536")
    else:
        warnings.append("no eds/AndroidHigh.plist in this install")

    if feats is not None:
        new_text = apply_feats(feats.text, fchanges)
        after = parse_feats(new_text)
        for key, value in fchanges.items():
            if key not in feats.values:
                warnings.append(f"feats key {key} is not in the file; "
                                f"it will be appended")
            if feats.values.get(key) != after.get(key):
                out["feats"].append((key, feats.values.get(key), after.get(key)))
        out["texts"]["feats"] = new_text
    else:
        warnings.append("no feats/AndroidHigh.feats in this install")

    out["changes"] = len(out["plist"]) + len(out["feats"])
    return out


def apply(depot: str, result: dict, *, out_dir: str = "") -> dict:
    """Write a :func:`plan` result.  Returns a report.

    An unpacked install is normally read-only, so the new files go to
    ``out_dir`` (default: a folder under the manager's state directory) and
    :mod:`rrmod.deploy` pushes them.  ``out_dir`` may be the install itself when
    the user has a writable copy.
    """
    written = {}
    if not out_dir:
        from . import depot as depotlib
        out_dir = os.path.join(depotlib.state_dir(depot), "gfx")
    for kind, rel in (("plist", PLIST_REL), ("feats", FEATS_REL)):
        text = result["texts"].get(kind)
        if text is None:
            continue
        target = os.path.join(out_dir, *rel.split("/"))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        blob = text.encode("utf-8")
        nct.write(target, blob)
        written[kind] = {"path": target, "rel": rel,
                         "bytes": os.path.getsize(target)}
    return written


def describe(depot: str) -> dict:
    """What the install has right now, for the page header."""
    plist, feats = read_pair(depot)
    out = {"plist": None, "feats": None}
    for kind, obj in (("plist", plist), ("feats", feats)):
        if obj is None:
            continue
        out[kind] = obj.summary()
        if kind == "plist":
            out[kind]["identifier"] = obj.get("PLIST_IDENTIFIER")
            out[kind]["aa"] = obj.get("AA_LEVEL")
            out[kind]["mipmap_bias"] = obj.get("MIPMAP_BIAS")
            out[kind]["renderer"] = obj.get("EXPECTED_RENDERER")
    return out


def is_stock(depot: str) -> bool:
    """True when the live ``.depot`` copies are byte identical to ``apk/res``.

    The engine reads ``.depot`` and the unpacker writes ``apk/res`` from the
    package, so the two agreeing means nobody has changed the profile yet.
    """
    for rel in (PLIST_REL, FEATS_REL):
        live = os.path.join(depot, *rel.split("/"))
        source = os.path.join(os.path.dirname(depot), "apk", "res",
                              *rel.split("/"))
        if not (os.path.exists(live) and os.path.exists(source)):
            continue
        try:
            if open(live, "rb").read() != open(source, "rb").read():
                return False
        except OSError:
            return False
    return True


def match_profile(depot: str) -> str:
    """Which named profile the files on disk currently look like, if any."""
    try:
        plist, feats = read_pair(depot)
    except GfxError:
        return ""
    if plist is None:
        return ""
    for name in ("insane", "ultra", "mid", "low"):
        want = plist_layer(name)
        if all(plist.get(k) == v for k, v in want.items()):
            return name
    return "stock" if is_stock(depot) else "custom"


def editable_keys(depot: str, kind: str = "plist") -> list:
    """``[(key, value)]`` sorted, for the key editor."""
    plist, feats = read_pair(depot)
    obj = plist if kind == "plist" else feats
    if obj is None:
        return []
    return sorted(obj.values.items())


# ------------------------------------------------------------ factory profiles
#
# The install ships 42 plists, one per device family, and every one of them has
# the same 113 keys.  That makes them a catalogue of the values the engine
# actually accepts: a key is only ever one of the values some profile uses, so
# the editor can offer a drop down instead of a blank box.  It also means a
# profile can be used as a *starting point* - "AndroidXtraHigh but with my own
# touches" - without inventing a whole table.
#: keys that identify the file rather than describe a quality setting.  The
#: engine throws a plist away when the identifier does not match the device
#: family, so it is never offered for editing and never copied from a base
#: profile.
LOCKED_KEYS = ("PLIST_IDENTIFIER", "DEVICE_DESCRIPTION", "Notes:")

#: Keys that describe the *device* rather than the picture quality.  Borrowing
#: another family's plist copies these too, and that is how a working install
#: stops booting: ``HAS_PHOTO_MODE`` comes on in every SimRig/iPad profile, but
#: the Android build has no photo-mode assets and the engine dies natively in
#: the car-select scene (verified by bisecting a crashing device, 2026-11-07 -
#: ``HAS_PHOTO_MODE`` alone turns "boots fine" into "F DEBUG tombstone").
#: ``GUI_LAYOUT_EXTENSION`` is the same story: iOS/TV profiles point at
#: ``_1024x768`` and the Android package only ships 480x320/960x640/2048x1536.
#: When a plan starts from a ``base`` profile these are taken from the file on
#: disk instead, so borrowing never breaks the device it is pushed to.
DEVICE_KEYS = LOCKED_KEYS + (
    "GUI_LAYOUT_EXTENSION", "GUI_ATLAS_OVERRIDE", "GUI_IMAGE_AUTO_SCALE",
    "EXPECTED_SCREEN_WIDTH", "EXPECTED_SCREEN_HEIGHT", "3D_SCENE_SCALE",
    "HAS_PHOTO_MODE", "SUPPORT_EXTERNAL_SCREEN", "EXTERNAL_DISPLAY_DEFAULT_RES",
    "USE_PAUSE_BLUR", "USE_PBR_WATER", "MOBILE_INTERNET_4G_NAME_LIST",
)


def factory_dir(depot: str) -> str:
    return os.path.join(depot, "eds")


def factory_profiles(depot: str) -> list:
    """Every plist the install ships with, by leaf name, minus the live one."""
    folder = factory_dir(depot)
    if not os.path.isdir(folder):
        return []
    out = []
    for leaf in sorted(os.listdir(folder)):
        if not leaf.endswith(".plist"):
            continue
        out.append(leaf[:-6])
    return out


def factory_read(depot: str, name: str):
    """One of the shipped plists as a :class:`GfxFile`, or ``None``."""
    path = os.path.join(factory_dir(depot), name + ".plist")
    if not os.path.isfile(path):
        return None
    try:
        return read(path, "plist")
    except GfxError:
        return None


def choices(depot: str, kind: str = "plist") -> dict:
    """``{key: [values]}`` gathered from every shipped profile.

    Keys whose value never varies are absent: there is nothing to choose, so the
    editor should not pretend otherwise.
    """
    seen: dict = {}
    if kind == "plist":
        for name in factory_profiles(depot):
            obj = factory_read(depot, name)
            if obj is None:
                continue
            for key, value in obj.values.items():
                seen.setdefault(key, [])
                if value not in seen[key]:
                    seen[key].append(value)
    else:
        folder = os.path.join(depot, "feats")
        if os.path.isdir(folder):
            for leaf in sorted(os.listdir(folder)):
                if not leaf.endswith(".feats"):
                    continue
                try:
                    obj = read(os.path.join(folder, leaf), "feats")
                except GfxError:
                    continue
                for key, value in obj.values.items():
                    seen.setdefault(key, [])
                    if value not in seen[key]:
                        seen[key].append(value)
    return {k: v for k, v in seen.items() if len(v) > 1 and k not in LOCKED_KEYS}


def base_text(depot: str, base: str = "") -> str:
    """The plist text a plan should start from.

    Empty means the file on disk (the usual case).  A factory profile name means
    "start from that one instead", which is how a user copies, say, the iPad
    profile onto Android and then edits it.
    """
    if not base:
        plist, _feats = read_pair(depot)
        if plist is None:
            raise GfxError("this install has no eds/AndroidHigh.plist")
        return plist.text
    obj = factory_read(depot, base)
    if obj is None:
        raise GfxError(f"this install ships no eds/{base}.plist")
    return obj.text


def coerce(old, text: str):
    """Turn what the user typed into the type the key already has."""
    text = text.strip()
    if isinstance(old, bool):
        low = text.lower()
        if low in ("true", "1", "yes", "on"):
            return True
        if low in ("false", "0", "no", "off"):
            return False
        raise GfxError(f"{text!r} is not true or false")
    if isinstance(old, int):
        return int(text, 0)
    if isinstance(old, float):
        return float(text)
    return text
