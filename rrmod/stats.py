"""The numbers on a car's screen: weight, top speed, 0-60, braking, grip, PR.

All of them live in the car's own spec file, not in a table, so editing one is a
matter of writing four bytes at a known offset.  :mod:`rr3lib.spec` already knows
where; this module is the thin layer the UI talks to:

* :func:`read` - what the game will show, in one dict;
* :func:`write` - stage a change, refusing anything the reader cannot confirm;
* :func:`compare` - the same fields read out of two cars, for the "this is what
  the donor drives like" column.

Two rules shape the whole module:

1. **Only confirmed positions are writable.**  The weight/speed/accel/braking/
   grip block sits at fixed token indices in every shipped file, so those are
   safe.  The two PRs have no fixed index but are found by shape (the first
   number after the ``CAR_NAME_*`` key, and the one right after it) and each is
   writable through its own method.  The engine figures are addressed from the
   gear count's byte offset, and the gear count itself is rebuilt rather than
   overwritten (see :meth:`rr3lib.spec.Spec.set_gears`).
2. **Nothing is written into the install.**  The caller hands in a working copy
   (see :mod:`rrmod.workspace`), and the Deploy tab is what pushes it.
"""

from __future__ import annotations

import os

from rr3lib import spec as speclib
from rr3lib import upgrades as uplib

#: The writable fields, with the label and the unit the game's own screen uses.
#: Order matters: it is the order the panel shows them in.
FIELDS = (
    ("weight_lb", "Weight", "lb"),
    ("top_speed", "Top speed", "mph"),
    ("top_speed_max", "Top speed, fully upgraded", "mph"),
    ("accel", "0-60 mph", "s"),
    ("accel_max", "0-60 mph, fully upgraded", "s"),
    ("braking", "60-0 mph", "ft"),
    ("braking_max", "Braking, fully upgraded", "ft"),
    ("grip", "Grip", "g"),
    ("grip_max", "Grip, fully upgraded", "g"),
    ("pr", "PR", ""),
    ("pr_max", "PR, fully upgraded", ""),
)

#: Fields that are words from a closed list rather than numbers.  They are
#: writable - each has a setter in :mod:`rr3lib.spec` - but they cannot go
#: through the numeric path, so they are listed separately and the dialog gives
#: each a dropdown instead of a text cell.
#:
#: ``drivetrain`` is which wheels are driven (``RWD``/``AWD``/``FWD``/``RLY``)
#: and ``car_class`` is the filter the game files the car under
#: (``Race``/``Supercar``/``Prod``).  Neither is derived from anything, so
#: writing one is exact.
WORDS = (
    ("car_class", "Class", ""),
    ("drivetrain", "Drivetrain", ""),
)

#: Read-only fields, shown but not editable.  Nothing is here any more: the
#: figures the game derives (the fully-upgraded PR) are offered as an override
#: with a warning instead, because a modded car's figures no longer match what
#: the game's own pipeline would have produced anyway.
READ_ONLY = ()

#: The engine figures, in the order the game's own screen shows them.  All of
#: them are writable, ``gears`` included - changing the count rebuilds the ratio
#: list behind it rather than overwriting a number in place.
ENGINE = (
    ("gears", "Gears", ""),
    ("final_drive", "Final drive", ""),
    ("power_hp", "Power", "hp"),
    ("power_rpm", "Power at", "rpm"),
    ("torque", "Torque", "lb-ft"),
    ("torque_rpm", "Torque at", "rpm"),
    ("redline", "Redline", "rpm"),
    ("limiter", "Limiter", "rpm"),
    ("shift_up", "Shift up at", "rpm"),
    ("shift_down", "Shift down at", "rpm"),
)

#: Everything the numeric table shows, in one list, for the table builders.
#: The order is the order the panel shows them in: the figures, then the derived
#: one, then the two words, then the engine.
ALL_FIELDS = FIELDS + READ_ONLY + WORDS + ENGINE

#: The four words and the two prices at the tail of the spec.  They are not table
#: rows: two of them are words from a closed list and two are money, so the
#: dialog gives them controls of their own instead of a text cell.  ``extra`` is
#: read out too - it holds ``r3_spec_logo.xml`` on the eight R3 specials - but it
#: is never written, because nothing here knows what else the game does with it.
TAIL = (
    ("aspiration", "Aspiration", ""),
    ("layout", "Layout", ""),
    ("unlock", "Unlock rule", ""),
    ("cash", "Price", "R$"),
    ("gold", "Gold price", "gold"),
)

#: The three strings the game's class filter uses.
CLASSES = ("Race", "Supercar", "Prod")

#: The words that go through a spec setter rather than ``set_stat``.
WORD_KEYS = tuple(key for key, _label, _unit in WORDS)
_WORD_KEYS = set(WORD_KEYS)

#: Bounds that keep a typo from producing a car the game cannot load.  The
#: performance block is read by the physics code without a sanity check, so a
#: zero weight or a 5000 mph top speed crashes the race rather than the menu.
LIMITS = {
    "weight_lb": (400, 9000),
    "top_speed": (30, 400),
    "top_speed_max": (30, 500),
    "accel": (0.5, 30.0),
    "accel_max": (0.5, 30.0),
    "braking": (30.0, 400.0),
    "braking_max": (30.0, 400.0),
    "grip": (0.2, 3.0),
    "grip_max": (0.2, 3.0),
    # The shipped cars run from 0.1 (a 1974 911 Targa) to about 100; anything
    # outside this is a typo rather than a slow car.  The maximum PR runs a
    # little higher: the MP4-X is 145.
    "pr": (0.1, 200.0),
    "pr_max": (0.1, 250.0),
    # Shipped cars use 1 (the single-speed Formula E cars) to 10 gears; the
    # reader accepts up to 12, which is where _engine_index stops believing a
    # number is a gear count.
    "gears": (1, 12),
}
LIMITS.update(speclib.ENGINE_LIMITS)

#: Fields whose writer is not ``Spec.set_stat`` (they are found by shape, not by
#: fixed token index).  ``write`` dispatches on this.
_BY_SHAPE = {"pr": "set_pr", "pr_max": "set_pr_max"}

#: Engine figures go through ``Spec.set_engine``, which needs them as one dict
#: because a rebuild of the token list happens once for the whole batch.
_ENGINE_KEYS = {key for key, _label, _unit in ENGINE if key != "gears"}


class StatsError(Exception):
    pass


def spec_path(root: str, car: str) -> str:
    """The car's spec file, found the same way the rest of the manager finds it."""
    from . import anim as animlib

    return animlib.spec_path(root, car)


def load(root: str, car: str):
    """The parsed spec, or ``None`` when the car has none."""
    path = spec_path(root, car)
    if not path or not os.path.isfile(path):
        return None
    return speclib.load_spec(os.path.join(root, ".depot"), os.path.basename(path)[:-8])


def read(root: str, car: str) -> dict:
    """Every field this module knows about, plus the path it came from."""
    spec = load(root, car)
    if spec is None:
        return {"car": car, "spec": "", "fields": {}, "missing": [k for k, _l, _u in
                                                                 ALL_FIELDS]}
    values = spec.stats()
    out = {"car": car, "spec": spec_path(root, car), "fields": {},
           "tail": {key: values.get(key) for key, _l, _u in TAIL},
           "missing": []}
    for key, label, unit in ALL_FIELDS:
        value = values.get(key)
        out["fields"][key] = {"value": value, "label": label, "unit": unit,
                              "writable": key in LIMITS or key in _WORD_KEYS}
        if value is None:
            out["missing"].append(key)
    return out


def validate(changes: dict) -> list:
    """Problems with a proposed edit, as human-readable strings."""
    problems = []
    for key, value in changes.items():
        if key in _WORD_KEYS:
            words = classes() if key == "car_class" else drivetrains()
            if str(value) not in words:
                problems.append(
                    f"{key}: {value!r} is not one the game knows "
                    f"(it offers {', '.join(words)})")
            continue
        if key not in LIMITS:
            problems.append(f"{key} cannot be written")
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            problems.append(f"{key}: {value!r} is not a number")
            continue
        low, high = LIMITS[key]
        if not low <= number <= high:
            problems.append(f"{key}: {number:g} is outside {low:g}..{high:g}")
            continue
        if key == "gears" and number < 2:
            # The one-gear cars are the Formula E racers, whose single ratio is
            # their final drive.  A car cannot be *given* that layout: there is
            # no forward gear list to rebuild from.
            problems.append("gears: a car needs at least two - the ratio list "
                            "has to have a forward gear to rebuild")
            continue
        if key == "gears" and number != int(number):
            # The count decides how many ratios follow it, so half a gear is
            # not a number the file can hold.
            problems.append(f"gears: {number:g} is not a whole number")
    return problems


def write(root: str, car: str, changes: dict) -> dict:
    """Apply ``changes`` to the car's spec inside ``root``.

    ``root`` must be a working copy - writing into a read-only install fails with
    a permission error, which is the whole reason the workspace exists.
    """
    problems = validate(changes)
    if problems:
        raise StatsError("; ".join(problems))
    spec = load(root, car)
    if spec is None:
        raise StatsError(f"{car} has no spec file")
    before = spec.stats()
    changed = []
    engine = {}
    for key, value in changes.items():
        if key in _WORD_KEYS:
            # Class and drivetrain are strings at fixed indices; each has its
            # own setter in the spec, and neither takes a number.
            got = (spec.set_class(str(value)) if key == "car_class"
                   else spec.set_drivetrain(str(value)))
            if got:
                changed.append(key)
            continue
        if key == "gears":
            # Not a byte write: the count decides how many ratios follow it, so
            # the list is rebuilt and everything after it re-read to prove it.
            if spec.set_gears(int(round(float(value)))):
                changed.append(key)
            continue
        if key in _ENGINE_KEYS:
            engine[key] = float(value)
            continue
        writer = _BY_SHAPE.get(key)
        if writer:
            got = getattr(spec, writer)(float(value))
        else:
            got = spec.set_stat(key, value)
        if got:
            changed.append(key)
    if engine:
        changed.extend(spec.set_engine(engine))
    out = {"car": car, "spec": spec_path(root, car), "changed": changed,
           "before": {k: before.get(k) for k in changes},
           "after": {k: spec.stats().get(k) for k in changes}}
    if changed:
        speclib.save_spec(spec, out["spec"])
    return out


def sound(root: str, car: str) -> dict:
    """The engine-sound triple the car asks for, plus the families on disk."""
    spec = load(root, car)
    if spec is None:
        return {"car": car, "accel": "", "decel": "", "idle": "", "family": "",
                "families": families(root), "writable": False}
    got = spec.sound()
    got.update(car=car, families=families(root), writable=bool(got["accel"]))
    return got


def families(root: str) -> list:
    """Every ``audio/Vehicles/<family>`` folder the install ships, sorted."""
    folder = os.path.join(root, ".depot", "audio", "Vehicles")
    try:
        names = sorted(d for d in os.listdir(folder)
                       if os.path.isdir(os.path.join(folder, d)))
    except OSError:
        return []
    return names


def set_sound(root: str, car: str, family: str) -> dict:
    """Point the car at another engine-sound family, inside ``root``."""
    spec = load(root, car)
    if spec is None:
        raise StatsError(f"{car} has no spec file")
    before = spec.sound()
    changed = spec.set_sound(family)
    out = {"car": car, "spec": spec_path(root, car), "changed": changed,
           "before": before, "after": spec.sound()}
    if changed:
        speclib.save_spec(spec, out["spec"])
    return out


def aspirations() -> tuple:
    """The aspiration words the game accepts, in the order it lists them."""
    return tuple(name.decode("ascii") for name in speclib.ASPIRATIONS)


def layouts() -> tuple:
    """The drivetrain layouts the game accepts."""
    return tuple(name.decode("ascii") for name in speclib.LAYOUTS)


def drivetrains() -> tuple:
    """The driven-wheel words the game accepts: ``RWD``, ``AWD``, ``FWD``, ``RLY``.

    Read off the 541 shipped specs: 443 rear, 82 all, 12 front and 3 rally.  A
    car whose spec holds something else is offered the four and nothing more -
    the value feeds the physics code, and a word it does not know is a car that
    does not drive.
    """
    return tuple(name.decode("ascii") for name in speclib.DRIVETRAINS)


def classes() -> tuple:
    """The class words the game's filter uses: ``Race``, ``Supercar``, ``Prod``."""
    return CLASSES


def tail(root: str, car: str) -> dict:
    """The aspiration, the layout, the unlock rule and the two prices."""
    out = {"car": car, "aspiration": "", "layout": "", "unlock": "", "extra": "",
           "cash": 0, "gold": 0, "writable": False,
           "aspirations": aspirations(), "layouts": layouts()}
    spec = load(root, car)
    if spec is None:
        return out
    out.update(spec.tail())
    out["writable"] = True
    return out


def set_tail(root: str, car: str, *, aspiration=None, layout=None, unlock=None,
             cash=None, gold=None) -> dict:
    """Write whichever of the tail fields were passed, inside ``root``.

    ``None`` means "leave it alone", which is what the dialog passes for a
    control the user never touched; writing a value that is already there is a
    no-op anyway, so the caller can also pass everything it shows.
    """
    spec = load(root, car)
    if spec is None:
        raise StatsError(f"{car} has no spec file")
    before = spec.tail()
    changed = []
    if aspiration is not None and spec.set_aspiration(str(aspiration)):
        changed.append("aspiration")
    if layout is not None and spec.set_layout(str(layout)):
        changed.append("layout")
    if unlock is not None and spec.set_unlock(str(unlock)):
        changed.append("unlock")
    if cash is not None or gold is not None:
        if spec.set_price(cash=cash, gold=gold):
            changed.append("price")
    out = {"car": car, "spec": spec_path(root, car), "changed": changed,
           "before": before, "after": spec.tail()}
    if changed:
        speclib.save_spec(spec, out["spec"])
    return out


def routes(root: str) -> list:
    """Every upgrade route the install ships, as ``{name, areas, steps, template}``.

    The ten ``PROD_01``..``RACE_03`` blocks come first, because they are the ones
    worth copying when a car has no route of its own; everything else is a car's
    or a racing class's own tree.
    """
    try:
        table = uplib.load(os.path.join(root, ".depot"))
    except (uplib.UpgradesError, OSError):
        return []
    templates = {route.name for route in table.packs()}
    out = []
    for route in table.routes:
        out.append({"name": route.name, "areas": len(route.areas),
                    "steps": len(route.steps), "template": route.name in templates})
    out.sort(key=lambda row: (not row["template"], row["name"]))
    return out


def route(root: str, car: str) -> dict:
    """The upgrade route the car follows, plus what the install offers."""
    spec = load(root, car)
    if spec is None:
        return {"car": car, "key": "", "route": None, "routes": routes(root),
                "writable": False}
    key = spec.upgrade_route()
    try:
        table = uplib.load(os.path.join(root, ".depot"))
    except (uplib.UpgradesError, OSError):
        table = None
    found = table.get(key) if table is not None else None
    out = {"car": car, "key": key, "routes": routes(root), "writable": True,
           "route": None}
    if found is not None:
        out["route"] = {"name": found.name, "areas": list(found.areas),
                        "curves": list(found.curves),
                        "steps": list(found.steps),
                        "effects": list(found.effects)}
    return out


def set_route(root: str, car: str, key: str) -> dict:
    """Point the car at another upgrade route, inside ``root``.

    ``key`` must name a block that exists, because a key that names nothing
    leaves the car with no tuning screen at all and no message saying why.  An
    empty ``key`` is refused for the same reason: 75 shipped cars do carry an
    empty key, but that is a property of the car, not something to choose.
    """
    key = (key or "").strip()
    if not key:
        raise StatsError("an upgrade route needs a name")
    try:
        table = uplib.load(os.path.join(root, ".depot"))
    except (uplib.UpgradesError, OSError) as exc:
        raise StatsError(str(exc)) from exc
    if table.get(key) is None:
        raise StatsError(f"there is no upgrade route called {key!r} in this install")
    spec = load(root, car)
    if spec is None:
        raise StatsError(f"{car} has no spec file")
    before = spec.upgrade_route()
    changed = spec.set_upgrade_route(key)
    out = {"car": car, "spec": spec_path(root, car), "changed": changed,
           "before": before, "after": spec.upgrade_route()}
    if changed:
        speclib.save_spec(spec, out["spec"])
    return out


def describe(root: str, car: str) -> str:
    """One line for a table cell: ``3360 lb  202 mph  0-60 3.6s  PR 46.7``."""
    got = read(root, car)["fields"]
    parts = []
    for key, fmt in (("weight_lb", "{:.0f} lb"), ("top_speed", "{:.0f} mph"),
                     ("accel", "0-60 {:.1f}s"), ("grip", "{:.2f} g"),
                     ("pr", "PR {:.1f}")):
        value = got.get(key, {}).get("value")
        if value:
            parts.append(fmt.format(value))
    return "  ".join(parts)


def compare(root: str, one: str, other: str) -> dict:
    """Side-by-side fields for two cars, used by the build dialog."""
    left = read(root, one)["fields"]
    right = read(root, other)["fields"] if other else {}
    rows = []
    for key, label, unit in ALL_FIELDS:
        rows.append({
            "key": key, "label": label, "unit": unit,
            "one": left.get(key, {}).get("value"),
            "other": right.get(key, {}).get("value"),
        })
    return {"one": one, "other": other, "rows": rows}


def _shown(value, key: str) -> str:
    """Round for display without losing the number's own precision."""
    if value is None:
        return "-"
    if isinstance(value, str):
        return value
    if key in ("weight_lb", "top_speed", "top_speed_max", "power_rpm", "torque_rpm",
               "redline", "limiter", "gears", "power_hp", "torque"):
        return f"{value:.0f}"
    return f"{value:.2f}".rstrip("0").rstrip(".")


def selftest(root: str, car: str = "") -> int:
    """Print what one car says about itself; handy from the command line."""
    from . import depot as depotlib

    inv = depotlib.scan(root)
    car = car or (inv.cars[0].name if inv.cars else "")
    if not car:
        print("no cars")
        return 1
    got = read(root, car)
    print(f"{car}  ({os.path.basename(got['spec']) or 'no spec'})")
    for key, label, unit in ALL_FIELDS:
        item = got["fields"].get(key, {})
        shown = _shown(item.get("value"), key)
        print(f"  {label:32s} {shown:>10s} {unit}"
              f"{'' if item.get('writable') else '   (read only)'}")
    if got["missing"]:
        print("  missing:", ", ".join(got["missing"]))
    return 0
