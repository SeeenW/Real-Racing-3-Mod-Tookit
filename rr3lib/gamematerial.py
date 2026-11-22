"""``materials.bin``: the game's material library and its shader bindings.

This is the file that answers *"what is a car material, really?"*.  It is a flat
stream of ``[u32 key][u32 len][ascii]`` records that has to be cut into two
tables (see ``docs/materials-格式.md`` for the full derivation):

1. **297 material state blocks**, each starting with key ``1738848819``: an
   instance name, a template name, an application, cull/blend/stencil modes,
   an RGBA and a shader flag list.
2. **186 shader bindings**, each starting with key ``1799195616``: the vertex and
   fragment shader files, the uniform assignments, and - the useful part - the
   texture slots.  ``[3]`` is the **fresnel LUT** and ``[4]`` the **specular
   LUT**, both 1024x1 ramps in ``vehicles/shaders/*.pvr``.

The instance name is what a livery table stores; the **template** name is what
the shader binding is keyed by (296 of the 297 instances match their template
name exactly).  So ``shader_for()`` looks the template up first and falls back to
the instance name.

Everything here is pure Python - no ``bpy`` - so the library can be tested
without Blender.
"""
from __future__ import annotations

import os
import struct
from dataclasses import dataclass, field

#: Where the file lives, relative to the depot root.
MATERIALS_BIN = "materials/materials.bin"

# ---- record keys (all verified against the shipped file) -------------------
K_TWOSIDED = 1738848819
K_BOOL2 = 2073958868
K_QUEUE = 500458687
K_PRIORITY = 1290375661
K_BOOL3 = 4050242743
K_BOOL4 = 4275232
K_INSTANCE = 1875587694
K_TEMPLATE = 1424680013
K_APPLICATION = 3133585612
K_CULL = 2002297458
K_BLEND = 3799239167
K_PRIMITIVE = 1649669188
K_STENCIL = 711227395
K_RGBA = 3519276840
K_FLAGS = 546467408

K_SHADER = 1799195616
K_VSH = 4259867639
K_FSH = 548181663
K_UNIFORM = 1720193402
K_TEXTURE = 950256928

#: Texture slots inside a shader binding.
SLOT_MASK = 2     # normal / spec mask
SLOT_FRESNEL = 3  # fresnel ramp
SLOT_SPECULAR = 4 # specular ramp

#: A material name starting with one of these is painted with the livery colour.
PAINT_PREFIXES = ("car_paint_", "car_bumper_paint_")


class MaterialError(Exception):
    pass


# ---------------------------------------------------------------------------
# records
# ---------------------------------------------------------------------------
def load_records(path: str) -> list[tuple[int, bytes]]:
    """Split the file into ``(key, value)`` records."""
    with open(path, "rb") as fh:
        data = fh.read()
    recs = []
    i = 0
    while i + 8 <= len(data):
        key, length = struct.unpack_from("<II", data, i)
        if length > 8192 or i + 8 + length > len(data):
            break
        recs.append((key, data[i + 8:i + 8 + length]))
        i += 8 + length
    return recs


def _text(raw: bytes) -> str:
    return raw.decode("ascii", "replace").strip()


def _rgba(raw: bytes) -> tuple:
    parts = [p.strip() for p in _text(raw).split(",")]
    out = []
    for p in parts[:4]:
        try:
            out.append(int(float(p)))
        except ValueError:
            out.append(0)
    while len(out) < 4:
        out.append(255)
    return tuple(out)


def _bool(raw: bytes) -> bool:
    return _text(raw).lower() in ("true", "1")


def _int(raw: bytes, default: int = 0) -> int:
    try:
        return int(float(_text(raw)))
    except ValueError:
        return default


# ---------------------------------------------------------------------------
# data model
# ---------------------------------------------------------------------------
@dataclass
class MaterialDef:
    """One material instance (one row of the 297)."""

    name: str = ""
    template: str = ""
    application: str = ""
    cull: str = ""
    blend: str = ""
    primitive: str = ""
    stencil: str = ""
    rgba: tuple = (255, 255, 255, 255)
    flags: tuple = ()
    twosided: bool = False
    queue: int = 0
    priority: int = 0
    alpha_test: bool = False

    @property
    def is_paint(self) -> bool:
        return self.name.startswith(PAINT_PREFIXES)

    @property
    def has_flag(self) -> tuple:
        return self.flags

    def flag(self, name: str) -> bool:
        return name in self.flags

    def flag_names(self) -> tuple:
        """The flag names as a plain tuple (``("FOG", "GLASS")``)."""
        return tuple(self.flags)


@dataclass
class ShaderDef:
    """One shader binding (one row of the 186)."""

    name: str = ""
    vsh: str = ""
    fsh: str = ""
    uniforms: dict = field(default_factory=dict)   # name -> raw value text
    textures: dict = field(default_factory=dict)   # slot -> internal path

    def uniform_float(self, name: str, default: float = 0.0) -> float:
        raw = self.uniforms.get(name)
        if raw is None:
            return default
        try:
            return float(raw.replace(",", " ").split()[0])
        except (ValueError, IndexError):
            return default

    def uniform_rgb(self, name: str) -> tuple | None:
        raw = self.uniforms.get(name)
        if raw is None:
            return None
        try:
            return tuple(int(float(p)) for p in raw.split(",")[:3])
        except ValueError:
            return None

    def texture(self, slot: int) -> str | None:
        return self.textures.get(slot)


@dataclass
class Library:
    """Both tables, keyed by name."""

    materials: dict = field(default_factory=dict)  # instance name -> MaterialDef
    shaders: dict = field(default_factory=dict)    # shader name -> ShaderDef

    # ---- material -------------------------------------------------------
    def material(self, name: str) -> MaterialDef | None:
        return self.materials.get(name)

    def template_of(self, name: str) -> str:
        md = self.materials.get(name)
        return md.template if md else ""

    # ---- shader ---------------------------------------------------------
    def shader_for(self, name: str) -> ShaderDef | None:
        """The shader binding for a material instance name.

        The table is keyed by the **template**, not the instance, so
        ``car_alpha`` (template ``car_paint_gloss``) gets the gloss binding.
        """
        md = self.materials.get(name)
        if md is None:
            return self.shaders.get(name)
        return (self.shaders.get(md.template)
                or self.shaders.get(md.name)
                or self.shaders.get(name))

    def luts(self, name: str) -> tuple:
        """``(fresnel, specular, mask)`` internal paths for a material name."""
        sh = self.shader_for(name)
        if sh is None:
            return (None, None, None)
        return (sh.texture(SLOT_FRESNEL), sh.texture(SLOT_SPECULAR),
                sh.texture(SLOT_MASK))

    # ---- derived shading numbers ----------------------------------------
    def spec_power(self, name: str) -> float:
        """The ``mu_MaterialSpecularPower_Base`` the game feeds the shader."""
        sh = self.shader_for(name)
        if sh is None:
            return 0.0
        for key in ("mu_MaterialSpecularPower_Base", "mu_MaterialSpecularPower"):
            if key in sh.uniforms:
                return sh.uniform_float(key)
        return 0.0

    def spec_colour(self, name: str) -> tuple | None:
        sh = self.shader_for(name)
        if sh is None:
            return None
        for key in ("mu_MaterialSpecularColour_Base", "mu_MaterialSpecularColour"):
            rgb = sh.uniform_rgb(key)
            if rgb is not None:
                return rgb
        return None

    def spec_power_top(self, name: str) -> float:
        """The second lobe's exponent (``mu_MaterialSpecularPower_Top``).

        Car paint is shaded with two specular lobes: a broad base one and a
        sharp top one.  Gloss paint is sharp at the base (1000) and broad at the
        top (10); metallic paint is the other way round (8 and 1000).  The top
        lobe is what reads as the clear coat, so it maps onto Blender's coat.
        """
        sh = self.shader_for(name)
        if sh is None:
            return 0.0
        return sh.uniform_float("mu_MaterialSpecularPower_Top", 0.0)


def roughness_from_power(power: float) -> float:
    """Map the game's specular power onto a Principled roughness.

    The game's exponent is a Blinn-Phong ``n``: the half-vector lobe has a
    standard deviation of about ``sqrt(2 / (n + 2))``, which is exactly what
    Blender's roughness parameter means, so the mapping is the closed form
    rather than a fudge factor.  ``n = 1000`` (car_paint_gloss) gives 0.045,
    ``n = 8`` (metallic paint base) gives 0.45, ``n = 1`` (car_flat) gives 0.82.
    """
    if power <= 0.0:
        return 1.0
    r = (2.0 / (power + 2.0)) ** 0.5
    return max(0.02, min(1.0, r))


def metallic_from_fresnel(mean: float) -> float:
    """Guess a metallic value from the average of the fresnel ramp.

    A dielectric clear coat ramps to about 0.28, chrome to about 0.66, and
    ``car_flat`` is 0.0.  Mapping that onto 0..1 puts clear-coated paint at 0
    (correct - it is a dielectric) and chrome near 0.8.  It is an approximation:
    the real shader samples the ramp per pixel with a fresnel term.
    """
    return max(0.0, min(1.0, (mean - 0.35) / 0.40))


# ---------------------------------------------------------------------------
# parsing
# ---------------------------------------------------------------------------
def material_blocks(recs) -> list:
    """Cut the record stream at every ``K_TWOSIDED`` and read the fields."""
    starts = [j for j, (k, _v) in enumerate(recs) if k == K_TWOSIDED]
    starts.append(len(recs))
    out = []
    for a in range(len(starts) - 1):
        chunk = recs[starts[a]:starts[a + 1]]
        first = {}
        for k, v in chunk:
            first.setdefault(k, v)
        name = _text(first.get(K_INSTANCE, b""))
        if not name:
            continue
        out.append(MaterialDef(
            name=name,
            template=_text(first.get(K_TEMPLATE, b"")) or name,
            application=_text(first.get(K_APPLICATION, b"")),
            cull=_text(first.get(K_CULL, b"")),
            blend=_text(first.get(K_BLEND, b"")),
            primitive=_text(first.get(K_PRIMITIVE, b"")),
            stencil=_text(first.get(K_STENCIL, b"")),
            rgba=_rgba(first.get(K_RGBA, b"255,255,255,255")),
            flags=tuple(p.strip() for p in _text(first.get(K_FLAGS, b"")).split(",")
                        if p.strip()),
            twosided=_bool(first.get(K_TWOSIDED, b"false")),
            queue=_int(first.get(K_QUEUE, b"0")),
            priority=_int(first.get(K_PRIORITY, b"0")),
            alpha_test=_bool(first.get(K_BOOL2, b"false")),
        ))
    return out


def shader_blocks(recs) -> list:
    """Read every ``K_SHADER`` group: vsh, fsh, uniforms and texture slots."""
    out = []
    j = 0
    while j < len(recs):
        if recs[j][0] != K_SHADER:
            j += 1
            continue
        sh = ShaderDef(name=_text(recs[j][1]))
        j += 1
        while j < len(recs) and recs[j][0] in (K_VSH, K_FSH, K_UNIFORM, K_TEXTURE):
            k, v = recs[j]
            text = _text(v)
            if k == K_VSH:
                sh.vsh = text
            elif k == K_FSH:
                sh.fsh = text
            elif k == K_UNIFORM:
                # one record may carry several assignments, one per line
                for line in text.splitlines():
                    head, sep, value = line.partition("=")
                    if sep:
                        sh.uniforms[head.strip()] = value.strip()
            else:
                # one record may carry several "[slot]path" lines
                for line in text.splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    slot = None
                    if line.startswith("[") and "]" in line:
                        end = line.index("]")
                        try:
                            slot = int(line[1:end])
                        except ValueError:
                            slot = None
                        line = line[end + 1:].strip()
                    if slot is not None:
                        sh.textures[slot] = line
            j += 1
        out.append(sh)
    return out


def load(depot: str) -> Library:
    """Read ``<depot>/materials/materials.bin`` into a :class:`Library`."""
    path = os.path.join(depot, *MATERIALS_BIN.split("/"))
    if not os.path.isfile(path):
        raise MaterialError(f"no materials.bin at {path}")
    recs = load_records(path)
    lib = Library()
    for md in material_blocks(recs):
        lib.materials[md.name] = md
    for sh in shader_blocks(recs):
        lib.shaders[sh.name] = sh
    if not lib.materials:
        raise MaterialError(f"{path}: no material blocks found")
    return lib


def find_depot(start: str) -> str | None:
    """Walk up from a car folder until a folder with ``materials/`` is found."""
    cur = os.path.abspath(start)
    for _ in range(8):
        if os.path.isfile(os.path.join(cur, *MATERIALS_BIN.split("/"))):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    return None


# ---------------------------------------------------------------------------
# LUT files on disk
# ---------------------------------------------------------------------------
#: A shader binding names its ramp as ``vehicles/shaders/fresnel_gloss.pvr`` but
#: the file on disk is ``vehicles/shaders/fresnel_gloss.rgb.pvr`` - the ``.rgb``
#: infix is the pixel layout, which the binding leaves out.
_LUT_CACHE: dict = {}
_RAMP_CACHE: dict = {}


def resolve_lut(depot: str, internal: str) -> str | None:
    """Disk path of a shader ramp, or ``None``.

    Placeholders such as ``<texname>_refl.pvr`` (used by the garage and track
    shaders) resolve to ``None`` on purpose.
    """
    if not internal or internal.startswith("<"):
        return None
    key = (depot, internal)
    if key in _LUT_CACHE:
        return _LUT_CACHE[key]
    candidates = [internal]
    if internal.lower().endswith(".pvr"):
        candidates.append(internal[:-4] + ".rgb.pvr")
    found = None
    for cand in candidates:
        path = os.path.join(depot, *cand.split("/"))
        if os.path.isfile(path):
            found = path
            break
    _LUT_CACHE[key] = found
    return found


def ramp_mean(depot: str, internal: str) -> float | None:
    """Average brightness (0..1) of a 1024x1 ramp, or ``None``."""
    key = (depot, internal)
    if key in _RAMP_CACHE:
        return _RAMP_CACHE[key]
    path = resolve_lut(depot, internal)
    mean = None
    if path is not None:
        try:
            from . import pvr as pvrlib
            img = pvrlib.read(path)
        except Exception:  # noqa: BLE001 - a broken ramp must not stop an import
            img = None
        if img is not None:
            ch = img.channels
            total = sum(img.pixels[i * ch] for i in range(img.width))
            mean = total / (img.width * 255.0)
    _RAMP_CACHE[key] = mean
    return mean


# ---------------------------------------------------------------------------
# writing: cloning a material
# ---------------------------------------------------------------------------
#: The one record every material block starts with, and therefore the only
#: reliable place to cut the stream.  A block is ``K_TWOSIDED`` first, then five
#: more single-value records, then the instance, template, application and modes.
K_BLOCK_START = K_TWOSIDED


def block_spans(recs) -> list:
    """``[(start, end, name)]`` for every material block in the record stream.

    The file opens with eight records that belong to no block (``unknown``,
    ``appDefault``, ...) - a default row the engine reads before the real ones -
    and closes with the shader table.  Cutting on ``K_TWOSIDED`` gives 297 spans,
    the last of which has no instance name: it is the default row of the shader
    table's first entry, not a material.  Callers skip nameless spans.

    The spans are returned in file order, which is the order the engine reads.
    """
    starts = [j for j, (k, _v) in enumerate(recs) if k == K_BLOCK_START]
    if not starts:
        return []
    # the shader table starts at the first K_SHADER; a K_TWOSIDED after it is
    # not a material block, so stop there
    end = len(recs)
    for j, (k, _v) in enumerate(recs):
        if k == K_SHADER:
            end = j
            break
    starts = [j for j in starts if j < end]
    out = []
    for i, a in enumerate(starts):
        b = starts[i + 1] if i + 1 < len(starts) else end
        name = ""
        for k, v in recs[a:b]:
            if k == K_INSTANCE:
                name = _text(v)
                break
        out.append((a, b, name))
    return out


def encode_record(key: int, value: bytes) -> bytes:
    """One ``[u32 key][u32 len][payload]`` record."""
    return struct.pack("<II", key, len(value)) + value


def encode_records(recs) -> bytes:
    """The whole stream back to bytes - ``encode_records(load_records(p)) == p``."""
    return b"".join(encode_record(k, v) for k, v in recs)


def clone_block(recs, name: str, new_name: str, *,
                template: str = "", overrides=None) -> bytes:
    """Bytes of material block ``name`` with its instance renamed.

    The block is copied verbatim except for the ``K_INSTANCE`` payload, so the
    clone inherits every other field - application, cull and blend modes, the
    stencil, the RGBA and the flag list - from the material it was copied from.
    That is deliberate: a new material that reuses an existing *template* must
    look like an instance of it, or the shader binding lookup fails.

    ``template`` renames the ``K_TEMPLATE`` payload as well, for the case where
    the clone should share another material's shader.  ``overrides`` is a dict of
    ``{key: bytes}`` applied after the rename, for the fields a caller wants to
    change (the flag list, the RGBA).

    Raises :class:`MaterialError` if the material is not there.
    """
    spans = {n: (a, b) for a, b, n in block_spans(recs)}
    if name not in spans:
        raise MaterialError(f"no material block called {name}")
    a, b = spans[name]
    if not new_name:
        raise MaterialError("a clone needs a name")
    if new_name in spans:
        raise MaterialError(f"{new_name} is already a material")
    chunk = recs[a:b]
    seen_instance = False
    out = bytearray()
    for key, value in chunk:
        if key == K_INSTANCE:
            value = new_name.encode("ascii", "replace")
            seen_instance = True
        elif key == K_TEMPLATE and template:
            value = template.encode("ascii", "replace")
        elif overrides and key in overrides:
            value = overrides[key]
        out += encode_record(key, value)
    if not seen_instance:
        raise MaterialError(f"the block called {name} has no instance name")
    return bytes(out)


def insert_block(recs, blob: bytes) -> bytes:
    """The whole file with ``blob`` added at the end of the material table.

    The two tables are stored back to back and the shader table is keyed by name,
    so a material may be appended anywhere in the first table.  Appending at its
    end keeps every existing offset unchanged and leaves the shader table where
    the engine expects it - the file simply grows by the size of the new block.
    """
    spans = block_spans(recs)
    end = spans[-1][1] if spans else len(recs)
    head = encode_records(recs[:end])
    tail = encode_records(recs[end:])
    return head + blob + tail


def insert_blocks(recs, blobs) -> bytes:
    """The whole file with several encoded blocks added to the material table.

    The same argument as :func:`insert_block`, done once: concatenating the blobs
    and appending them together means the record list is walked once and the
    result is identical to inserting them one after another.
    """
    spans = block_spans(recs)
    end = spans[-1][1] if spans else len(recs)
    return (encode_records(recs[:end]) + b"".join(blobs)
            + encode_records(recs[end:]))


def save_bytes(depot: str, data: bytes) -> str:
    """Write a rebuilt ``materials.bin`` and return its path."""
    path = os.path.join(depot, *MATERIALS_BIN.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(data)
    return path


# ---------------------------------------------------------------------------
# self test
# ---------------------------------------------------------------------------
def selftest(depot: str | None = None) -> int:
    """Read the library and report what it found."""
    if not depot:
        depot = os.environ.get("RR3_DEPOT", "")
    if not depot or not os.path.isdir(depot):
        print("gamematerial selftest: no depot (set RR3_DEPOT)")
        return 2
    lib = load(depot)
    paints = [m for m in lib.materials.values() if m.is_paint]
    bound = sum(1 for m in lib.materials.values() if lib.shader_for(m.name))
    luts = [m.name for m in lib.materials.values()
            if lib.luts(m.name)[0] and lib.luts(m.name)[1]]
    print(f"materials    : {len(lib.materials)}")
    print(f"  templates  : {len({m.template for m in lib.materials.values()})}")
    print(f"  paint      : {len(paints)}")
    print(f"  with shader: {bound}")
    print(f"  with LUTs  : {len(luts)}")
    print(f"shaders      : {len(lib.shaders)}")
    bad = []
    for name in sorted(luts):
        f, s, _m = lib.luts(name)
        for internal in (f, s):
            if not internal or internal.startswith("<"):
                continue  # "<texname>_refl.pvr": the garage/track placeholder
            if resolve_lut(depot, internal) is None:
                bad.append((name, internal))
    for name, internal in bad[:20]:
        print(f"  missing ramp for {name}: {internal}")
    print(f"ramp files   : {'all present' if not bad else str(len(bad)) + ' missing'}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(selftest())
