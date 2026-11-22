"""Making and editing race series, the way MonkeyTool's ``rr3series`` does.

A "series" is one championship in the career menu: a title, a description, a
list of tiers, and each tier holds the allowed cars and the races.  Everything
lives in ``data/events.dat.nct``; the titles and descriptions are keys that point
into ``gametext.txt`` and the twelve ``text_<lang>.txt`` files.

The recipe here is the game's own:

1. copy an existing series (the *template*), give it the next free id, and
   append it to the end of the series list - the limited-time-series records
   count series by index, so inserting anywhere else would shift them;
2. throw away the template's tiers and build the requested ones, copying an
   event of the same type from the template tier so every unedited field (the
   AI scaling, the slipstream flags, the reward curves) comes along;
3. hang the series on a page of one of the menu groups, taking it out of
   whatever group it was in first;
4. write the title and description into all fourteen text files at the same
   line index.

Nothing here guesses: a track name that the career file does not know, a group
that does not exist, a template with no events - all raise instead of writing
something the game will choke on.  And :func:`save` refuses to write unless the
file rebuilds byte for byte from the object it just produced.
"""

from __future__ import annotations

import os

from rr3lib import career as careerlib
from rr3lib import nct
from rr3lib import texts as textslib

EVENTS_REL = "/data/events.dat.nct"
DEFAULT_GROUP = "STREAM_GROUP_AMATEUR"
DEFAULT_TEMPLATE = 0

#: The largest value a ``u32`` field can hold.  Every number in an event is
#: written with ``struct.pack("<I", ...)``, so anything above this would wrap
#: silently instead of failing - the game would then read a lap count of 3 from
#: a field the user set to 4294967299.
U32_MAX = 0xFFFFFFFF

#: Every event type the game itself names.
#:
#: The game keeps this table in its own code.  In ``libRealRacing3.so`` it is an
#: array of 24-byte records at file offset ``0xae038``, each record
#: ``{pointer, 0x403, name pointer}``; the index into that array *is* the event
#: type number.  The dump, in order:
#:
#:     Elimination, Head 2 Head, Cup, Unknown Type, Endurance, Unknown Type,
#:     Unknown Type, Speed Record, Unknown Type, Autocross, Speedsnap,
#:     Drag Race, Hunter, Time Trial, Fuel, NASCAR, Speed Gate
#:
#: so 3, 5, 6 and 8 have no name in the game either - they are gaps in its own
#: enumeration, not names we failed to find.
#:
#: Two of the entries are confirmed a second way.  Type 13: all 434 series whose
#: title says "Time Trial" hold nothing but type 13.  Type 14: every one of its
#: 37 events carries a parameter block starting ``Fuel:<n>;forceManual``, and the
#: table calls type 14 "Fuel".  Type 9 is confirmed by the one tier in the whole
#: career that names its mode - "%S Autocross Throwdown" holds three type 9
#: events and nothing else.
#:
#: Monkey Tool's ``kRsTypes[] = {2,1,0,4,7,10,11,13}`` agrees with this table
#: for all eight of its entries, which is what makes the reading of the array
#: safe rather than merely plausible.
EVENT_TYPES = {
    0: "Elimination",
    1: "Head 2 Head",
    2: "Cup",
    4: "Endurance",
    7: "Speed Record",
    9: "Autocross",
    10: "Speedsnap",
    11: "Drag Race",
    12: "Hunter",
    13: "Time Trial",
    14: "Fuel",
    15: "NASCAR",
    16: "Speed Gate",
}

#: Types the game's own table leaves unnamed, so there is nothing to invent.
EVENT_TYPE_GAPS = (3, 5, 6, 8)


def type_name(code: int) -> str:
    """A name for an event type, or a plain number when the game has none.

    Types 3, 5, 6 and 8 are unnamed *in the game*: its own table says "Unknown
    Type" for them.  Saying so plainly is better than inventing a name, because
    the event dialog would then offer to "change" an event to the type it
    already has.
    """
    code = int(code)
    if code in EVENT_TYPES:
        return EVENT_TYPES[code]
    if code in EVENT_TYPE_GAPS:
        return f"Type {code} (the game leaves this one unnamed)"
    return f"Type {code}"


def types_in_use(c: "careerlib.Career") -> list:
    """Every event type this career file actually uses, smallest first.

    The new-event picker offers these rather than :data:`EVENT_TYPES` alone, so
    a series copied from a Gauntlet can still be given another Gauntlet event.
    """
    return sorted({e.type for tier in c.tiers for e in tier.events})

#: The series types seen in this depot.  7 is a limited-time series and must be
#: cleared on a copy, or the LTS records would point at the new series.
TYPE_LTS = 7


class SeriesError(Exception):
    pass


# ------------------------------------------------------------------ loading
def depot_of(root: str) -> str:
    """Accept either the install root or its ``.depot`` folder."""
    root = os.path.abspath(root)
    if os.path.basename(root) == ".depot":
        return root
    return os.path.join(root, ".depot")


def events_path(root: str) -> str:
    return os.path.join(depot_of(root), "data", "events.dat.nct")


def load(root: str) -> careerlib.Career:
    """Parse the working copy's ``events.dat.nct``."""
    p = events_path(root)
    if not os.path.isfile(p):
        raise SeriesError(f"no career file at {p}")
    return careerlib.parse(nct.read(p))


def load_texts(root: str) -> textslib.Texts:
    """Read the fourteen text files out of the working copy."""
    return textslib.Texts.load(depot_of(root))


def track_names(c: careerlib.Career) -> list[str]:
    return sorted(c.track_names())


def group_keys(c: careerlib.Career) -> list[str]:
    """Every menu group a series can be put into, deepest path last."""
    out = []
    for path, node, _gi in c.groups():
        if node.type in (0, 1):
            out.append(node.key)
    return out


def templates(c: careerlib.Career) -> list[dict]:
    """Series that make good templates, best first.

    A career series (type 0) that already lives in a menu group is the safest
    shape to copy: its tiers, its event types and its requirement curves all
    match what the career menu expects.  Limited-time series (type 7) are left
    out - they carry a type the limited-time table indexes by position.
    """
    where = c.group_map()
    tiers = c.tier_map()
    out = []
    for s in c.series:
        if s.type == TYPE_LTS:
            continue
        rows = tiers.get(s.id) or []
        if not rows:
            continue
        group = where.get(s.id, "")
        out.append({
            "id": s.id,
            "key": s.title_key,
            "type": s.type,
            "tiers": len(rows),
            "events": sum(len(x.events) for x in rows),
            "group": group,
            "group_key": group.rsplit("/", 1)[-1] if group else "",
            "in_menu": bool(group),
            "good": s.type in (0, 8) and bool(group),
        })
    out.sort(key=lambda r: (not r["good"], r["id"]))
    return out


def group_paths(c: careerlib.Career) -> dict:
    """``{group key: "Super/Path"}`` for the menu."""
    return {node.key: path for path, node, _gi in c.groups() if node.type in (0, 1)}


# ------------------------------------------------------------------ reading
def list_series(c: careerlib.Career, t: textslib.Texts | None = None,
                *, with_group: bool = True) -> list[dict]:
    """One row per series: id, its key, its English title, where it lives."""
    where = c.group_map() if with_group else {}
    tiers = c.tier_map()
    out = []
    for s in c.series:
        rows = tiers.get(s.id, [])
        row = {
            "id": s.id,
            "key": s.title_key,
            "type": s.type,
            "title": t.get(s.title_key) if t else "",
            "tiers": len(rows),
            "events": sum(len(x.events) for x in rows),
            "group": "",
        }
        if with_group:
            path = where.get(s.id, "")
            row["group"] = path.rsplit("/", 1)[-1] if path else ""
            row["group_path"] = path
        out.append(row)
    out.sort(key=lambda r: r["id"])
    return out


def describe(c: careerlib.Career, series_id: int,
             t: textslib.Texts | None = None) -> dict:
    """Everything worth showing about one series."""
    s = c.series_by_id(series_id)
    if s is None:
        raise SeriesError(f"no series {series_id}")
    tiers = c.tiers_of(s.id)
    rows = []
    for tier in tiers:
        rows.append({
            "id": tier.id,
            "index": tier.index,
            "name_key": tier.name_key,
            "name": t.get(tier.name_key) if t else "",
            "cars": [car for car, _flags in tier.cars],
            "banners": [b.s for b in tier.banners if b.s],
            "events": [{
                "id": e.id,
                "type": e.type,
                "type_name": type_name(e.type),
                "track": e.track,
                "laps": e.laps,
                "fame": e.fame,
                "reward": e.reward,
            } for e in tier.events],
        })
    return {
        "id": s.id,
        "key": s.title_key,
        "title": t.get(s.title_key) if t else "",
        "desc_key": s.desc_key,
        "desc": t.get(s.desc_key) if t else "",
        "type": s.type,
        "is_lts": s.type == TYPE_LTS,
        "group": c.group_of(s.id),
        "requirements": sum(len(g) for g in s.requirements),
        "completion_reward": s.completion_reward,
        "reward_id": s.reward_id,
        "tiers": rows,
    }


def title_from(name: str) -> str:
    """A readable series title from a car folder name.

    ``2012_lexus_lfa_copy`` becomes ``Lexus Lfa Copy Cup``: the leading year is
    dropped, the rest is title-cased and the word Cup is added, which is the
    shape the studio's own single-make series use.
    """
    bits = [b for b in str(name or "").split("_") if b]
    if bits and bits[0].isdigit() and len(bits[0]) == 4:
        bits = bits[1:]
    words = [b.capitalize() for b in bits]
    stem = " ".join(words) or str(name or "New")
    return stem + " Cup"


def free_id(c: careerlib.Career) -> int:
    return c.max_series_id() + 1


# ------------------------------------------------------------------- helpers
def upper_slug(s: str) -> str:
    """``"My Cup!"`` -> ``"MY_CUP"``, the same way the game's tool does it."""
    out = []
    for ch in s:
        if "a" <= ch <= "z":
            out.append(ch.upper())
        elif ("A" <= ch <= "Z") or ("0" <= ch <= "9"):
            out.append(ch)
        elif out and out[-1] != "_":
            out.append("_")
    while out and out[-1] == "_":
        out.pop()
    return "".join(out) or "CUSTOM"


def _template_tier(c: careerlib.Career, series_id: int):
    """The first tier of a series that actually has events."""
    best = None
    for tier in c.tiers:
        if tier.series_id != series_id or not tier.events:
            continue
        if best is None or tier.index < best.index:
            best = tier
    return best


def _checked(value, name: str, low: int = 0) -> int:
    """A number that will survive ``struct.pack("<I", ...)``.

    ``Event`` writes every number through ``w.u32``, which raises
    ``struct.error`` for a negative value and silently drops the high bits of
    anything above :data:`U32_MAX`.  Checking here turns both into one readable
    message before a single byte is written.
    """
    try:
        got = int(value)
    except (TypeError, ValueError) as exc:
        raise SeriesError(f"{name} must be a whole number, not {value!r}") from exc
    if got < low or got > U32_MAX:
        raise SeriesError(f"{name} must be between {low} and {U32_MAX}, not {got}")
    return got


def normalise_events(events) -> list[dict]:
    """Accept dicts or ``"Track:type:laps[:tier]"`` strings."""
    out = []
    for e in events or ():
        if isinstance(e, str):
            bits = e.split(":")
            if len(bits) < 3:
                raise SeriesError(f"an event needs Track:type:laps, not {e!r}")
            row = {"track": bits[0], "type": _checked(bits[1], "the type"),
                   "laps": _checked(bits[2], "the lap count")}
            if len(bits) > 3 and bits[3]:
                row["tier"] = _checked(bits[3], "the tier")
        else:
            row = dict(e)
        if not row.get("track"):
            raise SeriesError("an event needs a track name")
        row["type"] = _checked(row.get("type", 2), "the type")
        row["laps"] = _checked(row.get("laps", 1), "the lap count")
        row["tier"] = _checked(row.get("tier", 0), "the tier")
        for key in ("fame", "reward"):
            if row.get(key) not in (None, -1):
                row[key] = _checked(row[key], f"the {key}")
        row.setdefault("fame", -1)
        row.setdefault("reward", -1)
        out.append(row)
    return out


# -------------------------------------------------------------------- build
def build(c: careerlib.Career, t: textslib.Texts, *, template: int,
          title: str, description: str = "", cars=None, events=None,
          group: str = "", new_group: str = "", group_flavour: str = "",
          group_card: str = "", reward: str = "") -> dict:
    """Add a series to ``c`` and its text to ``t``; nothing is written yet.

    ``template`` is the series to copy the shape from.  ``events`` is a list of
    ``{"track","type","laps","tier"}`` dicts or ``"Track:type:laps[:tier]"``
    strings.  ``group`` names an existing menu group; ``new_group`` makes one
    instead, copied from the career menu's first group.
    """
    if not title.strip():
        raise SeriesError("a series needs a title")
    rows = normalise_events(events)
    if not rows:
        raise SeriesError("a new series needs at least one event")
    known = set(c.track_names())
    for row in rows:
        if row["track"] not in known:
            raise SeriesError(
                f'"{row["track"]}" is not one of the game\'s track names')

    src = c.series_by_id(template)
    if src is None:
        raise SeriesError(f"series {template} is not in the career file")
    base = _template_tier(c, template)
    if base is None:
        raise SeriesError(f"series {template} has no events to copy from")

    nid = c.max_series_id() + 1
    key = f"{upper_slug(title)}_{nid}"
    s = src.copy()
    s.id = nid
    s.title_key = "SERIES_TITLE_" + key
    # A copy of a limited-time series must not stay one: the LTS records are a
    # separate table that counts series by index, and they would point here.
    if s.type == TYPE_LTS:
        s.head[2].u = 0
    s.desc_key = "SERIES_DESC_" + key
    s.requirements = []
    if reward:
        s.completion_reward = reward
    s.reward_id = "NO_REWARD"
    c.series.append(s)

    made_tiers, made_events = _build_tiers(c, s, base, rows, cars)
    where = _place(c, s.id, group=group, new_group=new_group,
                   group_flavour=group_flavour, group_card=group_card, t=t)
    t.set(s.title_key, title)
    if description:
        t.set(s.desc_key, description)

    warnings = []
    # The copy keeps the template's type, which is what the game's own tool
    # does.  A limited-time template is the one exception - it is cleared,
    # because the LTS table counts series by index and would point here.
    if src.type == TYPE_LTS:
        warnings.append(
            f"the template ({template}) is a limited-time series; the copy was "
            f"made a normal one so the limited-time table does not claim it")
    elif src.type not in (0, 8):
        warnings.append(
            f"the template ({template}) is type {src.type}, so the copy is too; "
            f"career series are usually type 0 - try a template from the group "
            f"you are putting this in")

    return {
        "id": nid,
        "key": s.title_key,
        "title": title,
        "type": s.type,
        "tiers": made_tiers,
        "events": made_events,
        "group": where,
        "template": template,
        "cars": list(cars or ()),
        "warnings": warnings,
    }


def _build_tiers(c: careerlib.Career, s: careerlib.Series, base, rows,
                 cars) -> tuple[int, int]:
    """Replace the copy's tiers with the requested ones; returns the counts."""
    wanted = max(row["tier"] for row in rows) + 1
    c.tiers = [x for x in c.tiers if x.series_id != s.id]
    max_tier = c.max_tier_id()
    max_event = c.max_event_id()
    made_tiers = made_events = 0
    for index in range(wanted):
        tier = base.copy()
        tier.index = index
        max_tier += 1
        tier.id = max_tier
        tier.series_id = s.id
        tier.head[5].u = 0          # unlocked by the series
        tier.head[6].u = 0          # no trophy requirement
        tier.head[0].s = "TIER_NAME_NUMBERED"
        tier.head[1].s = "GAMETEXT_TIER_NAME_NUMBERED"
        tier.events = []
        for row in rows:
            if row["tier"] != index:
                continue
            event = _pick_event(base, row["type"])
            max_event += 1
            event.type = row["type"]
            event.id = max_event
            event.track = row["track"]
            if row["laps"] > 0:
                event.laps = row["laps"]
            if row["fame"] >= 0:
                event.fame = row["fame"]
            if row["reward"] >= 0:
                event.reward = row["reward"]
            tier.events.append(event)
            made_events += 1
        if cars:
            tier.cars = [(int(cid), 3) for cid in cars]
        c.tiers.append(tier)
        made_tiers += 1
    return made_tiers, made_events


def _pick_event(base, wanted_type: int):
    """The template tier's event of this type, else its first one."""
    for event in base.events:
        if event.type == wanted_type:
            return event.copy()
    return base.events[0].copy()


def _place(c: careerlib.Career, series_id: int, *, group: str, new_group: str,
           group_flavour: str, group_card: str, t: textslib.Texts) -> str:
    """Hang the series on a page of its own inside one menu group."""
    nodes = [(path, node) for path, node, _gi in c.groups() if node.type in (0, 1)]
    target = None
    if new_group:
        career_group = None
        for g in c.super_groups:
            if g.kind == 0:
                career_group = g
                break
        if career_group is None and c.super_groups:
            career_group = c.super_groups[0]
        if career_group is None or not career_group.groups:
            raise SeriesError("the career menu has no groups to copy")
        template = None
        for cand in career_group.groups:
            if cand.type == 0:
                template = cand
                break
        if template is None:
            template = career_group.groups[0]
        node = template.copy()
        node.type = 0
        node.children = []
        node.pages = []
        node.type2 = b""
        slug = upper_slug(new_group)
        node.key = "STREAM_GROUP_" + slug
        node.base[1].s = "GAMETEXT_STREAM_GROUP_" + slug + "_FLAVOUR"
        if group_card:
            node.card = group_card
        node.base2[0].s = ""
        t.set(node.key, new_group)
        t.set(node.base[1].s, group_flavour or new_group)
        career_group.groups.insert(0, node)
        target = node
    else:
        want = group or DEFAULT_GROUP
        for _path, node in nodes:
            if node.key == want:
                target = node
                break
        if target is None:
            raise SeriesError(f"no menu group called {want}")

    # out of every group it was in, then a page of its own
    for _path, node in nodes:
        for page in node.pages:
            while series_id in page:
                page.remove(series_id)
        node.pages = [p for p in node.pages if p]
    target.pages.append([series_id])
    return target.key


# ------------------------------------------------------------------ editing
def retitle(c: careerlib.Career, t: textslib.Texts, series_id: int, *,
            title: str = "", description: str = "", cars=None,
            events=None, group: str = "") -> dict:
    """Change an existing series in place: its text, cars, events, menu group."""
    s = c.series_by_id(series_id)
    if s is None:
        raise SeriesError(f"no series {series_id}")
    out = {"id": series_id, "changed": []}
    if title:
        t.set(s.title_key, title)
        out["changed"].append("title")
    if description:
        t.set(s.desc_key, description)
        out["changed"].append("description")
    if events:
        out["events"] = set_events(c, series_id, events, cars=cars)
        out["changed"].append("events")
        if cars:
            out["changed"].append("cars")
    elif cars:
        ids = [(int(cid), 3) for cid in cars]
        for tier in c.tiers_of(series_id):
            tier.cars = list(ids)
        out["changed"].append("cars")
    if group:
        _place(c, series_id, group=group, new_group="", group_flavour="",
               group_card="", t=t)
        out["changed"].append("group")
    return out


def set_cars(c: careerlib.Career, series_id: int, cars) -> int:
    """Replace the allowed cars of every tier of a series."""
    s = c.series_by_id(series_id)
    if s is None:
        raise SeriesError(f"no series {series_id}")
    ids = [(int(cid), 3) for cid in cars or ()]
    tiers = c.tiers_of(series_id)
    for tier in tiers:
        tier.cars = list(ids)
    return len(tiers)


def add_tier(c: careerlib.Career, series_id: int, *, events=None,
             cars=None) -> dict:
    """Append one tier to a series, leaving every other tier alone.

    The new tier is a copy of the series' *last* tier, so it inherits the reward
    curve, the banners and the flags that series already uses.  With no
    ``events`` it also inherits that tier's races, which is what "one more of the
    same" usually means.  Nothing else in the file moves: the existing tiers keep
    their ids and their indices, which is the whole point - :func:`set_events`
    rebuilds the list and renumbers everything.
    """
    s = c.series_by_id(series_id)
    if s is None:
        raise SeriesError(f"no series {series_id}")
    tiers = c.tiers_of(series_id)
    if not tiers:
        raise SeriesError(
            f"series {series_id} has no tier to copy the shape from")
    base = tiers[-1]
    rows = normalise_events(events)
    if not rows:
        rows = [{"track": e.track, "type": e.type, "laps": e.laps,
                 "fame": e.fame, "reward": e.reward, "tier": 0}
                for e in base.events]
        if not rows:
            raise SeriesError(
                f"the last tier of series {series_id} has no events to copy")
    known = set(c.track_names())
    for row in rows:
        if row["track"] not in known:
            raise SeriesError(
                f'"{row["track"]}" is not one of the game\'s track names')

    index = max(t.index for t in tiers) + 1
    tier = base.copy()
    tier.index = index
    tier.id = c.max_tier_id() + 1
    tier.series_id = series_id
    tier.events = []
    max_event = c.max_event_id()
    for row in rows:
        event = _pick_event(base, row["type"])
        max_event += 1
        event.type = row["type"]
        event.id = max_event
        event.track = row["track"]
        if row["laps"] > 0:
            event.laps = row["laps"]
        if row["fame"] >= 0:
            event.fame = row["fame"]
        if row["reward"] >= 0:
            event.reward = row["reward"]
        tier.events.append(event)
    if cars is not None:
        tier.cars = [(int(cid), 3) for cid in cars]
    c.tiers.append(tier)
    return {"id": series_id, "tier": tier.id, "index": index,
            "events": len(tier.events), "cars": [c0 for c0, _f in tier.cars]}


def remove_tier(c: careerlib.Career, series_id: int, tier_id: int) -> dict:
    """Drop one tier of a series; the rest keep their ids and their indices.

    A series must keep at least one tier - the game offers a series through its
    tiers, so a series with none is a menu row that opens nothing.  The indices of
    the tiers after the removed one are pulled down by one so they stay 0..n-1,
    which is the only renumbering that has to happen.
    """
    s = c.series_by_id(series_id)
    if s is None:
        raise SeriesError(f"no series {series_id}")
    tiers = c.tiers_of(series_id)
    victim = next((t for t in tiers if t.id == tier_id), None)
    if victim is None:
        raise SeriesError(f"series {series_id} has no tier {tier_id}")
    if len(tiers) <= 1:
        raise SeriesError(
            f"series {series_id} has one tier left; a series with none cannot be "
            f"opened in the game - delete the series instead")
    c.tiers = [t for t in c.tiers if t.id != tier_id]
    for tier in c.tiers_of(series_id):
        if tier.index > victim.index:
            tier.index -= 1
    return {"id": series_id, "tier": tier_id, "removed_index": victim.index,
            "tiers": len(tiers) - 1,
            "events": sum(len(t.events) for t in c.tiers_of(series_id))}


def set_event(c: careerlib.Career, series_id: int, event_id: int, *,
              track: str = "", type: int = -1, laps: int = -1,
              fame: int = -1, reward: int = -1) -> dict:
    """Change one event in place; the other events and every tier id stay put.

    ``-1`` (and an empty ``track``) means "leave that field as it is", so the
    caller can hand back a form without having to know every value.  Nothing is
    renumbered: unlike :func:`set_events`, which drops the tiers and builds new
    ones, this edits the record the game already reads.
    """
    s = c.series_by_id(series_id)
    if s is None:
        raise SeriesError(f"no series {series_id}")
    found = None
    for tier in c.tiers_of(series_id):
        for event in tier.events:
            if event.id == event_id:
                found = event
                break
        if found is not None:
            break
    if found is None:
        raise SeriesError(f"series {series_id} has no event {event_id}")

    changed = []
    if track and track != found.track:
        if track not in set(c.track_names()):
            raise SeriesError(f'"{track}" is not one of the game\'s track names')
        found.track = track
        changed.append("track")
    if type >= 0 and type != found.type:
        found.type = _checked(type, "the type")
        changed.append("type")
    if laps >= 0 and laps != found.laps:
        found.laps = _checked(laps, "the lap count")
        changed.append("laps")
    if fame >= 0 and fame != found.fame:
        found.fame = _checked(fame, "the fame")
        changed.append("fame")
    if reward >= 0 and reward != found.reward:
        found.reward = _checked(reward, "the reward")
        changed.append("reward")
    return {"id": series_id, "event": event_id, "changed": changed,
            "track": found.track, "type": found.type, "laps": found.laps,
            "fame": found.fame, "reward": found.reward}


def set_events(c: careerlib.Career, series_id: int, events, *,
               cars=None) -> dict:
    """Replace the whole event list of an existing series.

    The tiers are rebuilt from the series' own first tier, so the reward curve,
    the banners and the flags stay whatever that series already used.  Every tier
    is dropped and re-created, which means the tier ids change; nothing else in
    the file refers to them, so that is safe.
    """
    s = c.series_by_id(series_id)
    if s is None:
        raise SeriesError(f"no series {series_id}")
    rows = normalise_events(events)
    if not rows:
        raise SeriesError("a series needs at least one event")
    known = set(c.track_names())
    for row in rows:
        if row["track"] not in known:
            raise SeriesError(
                f'"{row["track"]}" is not one of the game\'s track names')

    base = _template_tier(c, series_id)
    if base is None:
        raise SeriesError(f"series {series_id} has no tier to rebuild from")
    old_tiers = len(c.tiers_of(series_id))
    made_tiers, made_events = _build_tiers(c, s, base, rows, cars)
    return {"id": series_id, "tiers": made_tiers, "events": made_events,
            "replaced_tiers": old_tiers}


def remove(c: careerlib.Career, t: textslib.Texts, series_id: int) -> dict:
    """Take a series out of the career: its tiers, its menu page, its text."""
    s = c.series_by_id(series_id)
    if s is None:
        raise SeriesError(f"no series {series_id}")
    title_key, desc_key = s.title_key, s.desc_key
    c.series = [x for x in c.series if x.id != series_id]
    c.tiers = [x for x in c.tiers if x.series_id != series_id]
    for _path, node, _gi in c.groups():
        for page in node.pages:
            while series_id in page:
                page.remove(series_id)
        node.pages = [p for p in node.pages if p]
    t.remove(title_key)
    t.remove(desc_key)
    return {"id": series_id, "key": title_key}


# ------------------------------------------------------------------- saving
def stage_dir(root: str) -> str:
    """Where edited career files go.

    An unpacked install is normally read-only, so the edits are staged next to
    the mods file - the same place the graphics page uses - and then pushed.
    """
    from . import depot as depotlib

    return os.path.join(depotlib.state_dir(depot_of(root)), "career")


def career_leaves() -> list[str]:
    """The fourteen files a career edit touches, as paths inside ``.depot``."""
    return ["data/events.dat.nct", "gametext.txt"] + [
        f"text_{lang}.txt" for lang in textslib.LANGUAGES]


def pull_from_device(dev, root: str, *, log=print) -> dict:
    """Copy the device's career files into the staging folder and read them.

    The local depot is a pristine backup, so it never has the series that were
    added on the device.  Editing its copy and pushing that would delete them -
    :func:`rrmod.deploy.check_career` refuses exactly that.  The way to edit a
    career that already has mods in it is therefore to start from the device's
    own file, which is what this does: pull the fourteen files into the staging
    folder, then hand back that folder so the page reads from it.

    Returns ``{"dir", "files", "missing", "career", "texts"}``.
    """
    from . import deploy as deploylib

    dest = stage_dir(root)
    # Mirror the install layout so load() and load_texts() can read the folder
    # back: both look under ``<root>/.depot``.
    os.makedirs(os.path.join(dest, ".depot", "data"), exist_ok=True)
    files, missing = [], []
    for rel in career_leaves():
        local = os.path.join(dest, ".depot", *rel.split("/"))
        blob = deploylib._pull_bytes(dev, f".depot/{rel}", local)
        if blob:
            files.append({"leaf": os.path.basename(rel), "path": local,
                          "bytes": len(blob)})
            log(f"  pulled {rel} ({len(blob):,} bytes)")
        else:
            missing.append(rel)
            log(f"  MISSING on the device: {rel}")
    if "data/events.dat.nct" in missing:
        raise SeriesError(
            "the device has no events.dat.nct - cannot read its career")
    return {"dir": dest, "files": files, "missing": missing,
            "career": load(dest), "texts": load_texts(dest)}


# ------------------------------------------------------------------- cards
#: The career menu's cards live in this atlas, one per screen size.  A group's
#: ``base[3]`` names the picture inside it (``events/career/<name>``).
CARD_FOLDER = "events/career"
CARD_ATLAS = "sprites.android.atlas"


def card_atlases(depot: str) -> list:
    """Every ``gui_assets/<size>/events/career/sprites.android.atlas`` present."""
    from . import atlas as atlaslib

    out = []
    base = os.path.join(depot, "gui_assets")
    if not os.path.isdir(base):
        return out
    for size in atlaslib.SIZES:
        path = os.path.join(base, size, *CARD_FOLDER.split("/"), CARD_ATLAS)
        if os.path.isfile(path):
            out.append(path)
    return out


def read_picture(path: str) -> tuple:
    """``(w, h, channels, top-down pixels)`` for a PNG or JPEG file.

    Qt does the work when it can, because it knows about JPEG and every PNG
    variant.  ``QImage`` needs a running ``QGuiApplication`` though, so a plain
    PNG is also decoded here - the same eight-bit truecolour and truecolour-
    with-alpha layouts the rest of the project writes.  That keeps the module
    usable from a script.
    """
    try:
        from PySide6.QtGui import QImage
    except Exception:                            # noqa: BLE001 - no Qt at all
        QImage = None
    if QImage is not None:
        image = QImage(path)
        if not image.isNull():
            image = image.convertToFormat(QImage.Format_RGBA8888)
            width, height = image.width(), image.height()
            stride = image.bytesPerLine()
            data = bytes(image.constBits())
            row = width * 4
            pixels = b"".join(data[y * stride:y * stride + row]
                              for y in range(height))
            return width, height, 4, pixels
    if path.lower().endswith(".png"):
        return _read_png(path)
    raise SeriesError(f"{os.path.basename(path)} could not be read")


def _read_png(path: str) -> tuple:
    """Decode an 8-bit PNG without Qt; returns ``(w, h, 4, pixels)``."""
    import struct
    import zlib

    with open(path, "rb") as fh:
        data = fh.read()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise SeriesError(f"{os.path.basename(path)} is not a PNG")
    at = 8
    width = height = depth = colour = -1
    idat = bytearray()
    palette = b""
    while at + 8 <= len(data):
        length = struct.unpack_from(">I", data, at)[0]
        tag = data[at + 4:at + 8]
        body = data[at + 8:at + 8 + length]
        at += 12 + length
        if tag == b"IHDR":
            width, height, depth, colour = struct.unpack_from(">IIBB", body, 0)
        elif tag == b"PLTE":
            palette = body
        elif tag == b"IDAT":
            idat += body
        elif tag == b"IEND":
            break
    if width <= 0 or height <= 0:
        raise SeriesError(f"{os.path.basename(path)}: no header")
    if depth != 8 or colour not in (2, 6):
        raise SeriesError(
            f"{os.path.basename(path)}: only 8-bit rgb and rgba PNGs are read "
            f"here (this one is {depth}-bit, colour type {colour})")
    channels = 4 if colour == 6 else 3
    raw = zlib.decompress(bytes(idat))
    stride = width * channels
    out = bytearray(stride * height)
    prev = bytearray(stride)
    src = 0
    for y in range(height):
        kind = raw[src]
        src += 1
        line = bytearray(raw[src:src + stride])
        src += stride
        if kind == 1:
            for i in range(channels, stride):
                line[i] = (line[i] + line[i - channels]) & 0xFF
        elif kind == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif kind == 3:
            for i in range(stride):
                left = line[i - channels] if i >= channels else 0
                line[i] = (line[i] + ((left + prev[i]) >> 1)) & 0xFF
        elif kind == 4:
            for i in range(stride):
                a = line[i - channels] if i >= channels else 0
                b = prev[i]
                c = prev[i - channels] if i >= channels else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pred = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[i] = (line[i] + pred) & 0xFF
        out[y * stride:(y + 1) * stride] = line
        prev = line
    if channels == 3:
        rgba = bytearray(width * height * 4)
        for i in range(width * height):
            rgba[i * 4:i * 4 + 3] = out[i * 3:i * 3 + 3]
            rgba[i * 4 + 3] = 255
        return width, height, 4, bytes(rgba)
    return width, height, 4, bytes(out)


def add_card(depot: str, picture: str, name: str, *,
             out_dir: str, log=print) -> dict:
    """Turn a picture into a group card and stage it next to the career files.

    A card is a page of its own in ``gui_assets/<size>/events/career/``: the
    sheets are packed edge to edge, so there is no room inside an existing page,
    and the engine does not care which page a picture sits on.  MonkeyTool does
    the same thing.  Every screen size gets the same picture at the size that
    size's own cards use (680x942 on the 2048x1536 sheet).

    Returns ``{"card": "events/career/<name>", "files": [(local, remote_rel)]}``.
    """
    from . import atlas as atlaslib

    atlases = card_atlases(depot)
    if not atlases:
        raise SeriesError(
            "no gui_assets/<size>/events/career/sprites.android.atlas was found")
    width, height, channels, pixels = read_picture(picture)
    if channels != 4:
        raise SeriesError("the picture has no alpha channel")
    files = []
    for atlas_path in atlases:
        size = os.path.basename(os.path.dirname(os.path.dirname(
            os.path.dirname(atlas_path))))
        try:
            card_w, card_h = atlaslib.card_size(atlas_path)
        except atlaslib.AtlasError as exc:
            raise SeriesError(str(exc)) from exc
        use_w, use_h = (card_w, card_h) if card_w > 16 and card_h > 16 else (
            width, height)
        use = atlaslib.resize(width, height, channels, pixels, use_w, use_h)
        try:
            xml, leaf, page = atlaslib.add_picture(
                atlas_path, name, use_w, use_h, channels, use)
        except atlaslib.AtlasError as exc:
            raise SeriesError(str(exc)) from exc
        rel_dir = f"gui_assets/{size}/{CARD_FOLDER}"
        xml_local = os.path.join(out_dir, *rel_dir.split("/"), CARD_ATLAS)
        os.makedirs(os.path.dirname(xml_local), exist_ok=True)
        with open(xml_local, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(xml)
        page_local = os.path.join(out_dir, *rel_dir.split("/"), leaf)
        with open(page_local, "wb") as fh:
            fh.write(page)
        files.append((xml_local, f".depot/{rel_dir}/{CARD_ATLAS}"))
        files.append((page_local, f".depot/{rel_dir}/{leaf}"))
        log(f"  card {name}: {use_w}x{use_h} on {size} as {leaf} "
            f"({len(page):,} bytes)")
    return {"card": f"{CARD_FOLDER}/{name}", "files": files,
            "width": width, "height": height, "sizes": len(atlases)}


def card_name(title: str) -> str:
    """``LFA Cup`` -> ``stream_group_lfa_cup_card.png``."""
    slug = []
    for ch in title.lower():
        if ch.isalnum():
            slug.append(ch)
        elif slug and slug[-1] != "_":
            slug.append("_")
    while slug and slug[-1] == "_":
        slug.pop()
    return "stream_group_" + ("".join(slug) or "custom") + "_card.png"


def write(c: careerlib.Career, t: textslib.Texts | None = None, *,
          out_dir: str, log=print) -> dict:
    """Write the career file and any changed text file into ``out_dir``.

    An unpacked install is normally read-only, so nothing is written in place:
    the files land in ``out_dir`` mirroring the ``.depot`` layout, and
    :mod:`rrmod.deploy` pushes them.  The career file is checked by rebuilding
    it and comparing bytes before a single byte is written - the same guard
    MonkeyTool uses, and the reason a malformed edit cannot reach the game.
    """
    plain = c.to_bytes()
    if careerlib.parse(plain).to_bytes() != plain:
        raise SeriesError(
            "the career file did not read back byte for byte - nothing was written")

    out = {"career": None, "texts": [], "files": []}
    # Mirror an install, not a bare .depot: the staging folder then reads back
    # through load()/load_texts() like any other root, which is what makes
    # "read from device, edit, save, read again" a single consistent copy.
    target = os.path.join(out_dir, ".depot", *EVENTS_REL.lstrip("/").split("/"))
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "wb") as fh:
        fh.write(nct.crypt(plain))
    out["career"] = {"path": target, "rel": EVENTS_REL,
                     "bytes": os.path.getsize(target)}
    log(f"  events.dat.nct: {out['career']['bytes']:,} bytes")

    if t is not None and t.changed():
        for leaf, blob in t.blobs(only_changed=True).items():
            path = os.path.join(out_dir, ".depot", leaf)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as fh:
                fh.write(blob)
            out["texts"].append({"leaf": leaf, "path": path,
                                 "rel": "/" + leaf, "bytes": len(blob)})
        log(f"  text files: {', '.join(x['leaf'] for x in out['texts'])}")
    return out


def place(root: str, *, template: int, title: str, description: str = "",
          cars=None, events=None, group: str = "", new_group: str = "",
          group_flavour: str = "", group_card: str = "",
          register_in: str = "", log=print) -> dict:
    """Add a series to the career in ``root`` and write it back there.

    This is :func:`build` and :func:`write` in one step, for the callers that
    have a working copy rather than a loaded career in hand - the build dialog,
    which has just made a car and wants to give it somewhere to race.  When no
    ``events`` are given the template's own first tier is copied, which is what
    makes "same races as the series I copied, but only my car may enter" the
    default rather than something the user has to type out.

    ``register_in`` is a depot to record the series in (see
    :func:`rrmod.depot.register_series`); pass the install's depot so the
    Career page can tell a series we made from one the studio shipped.
    """
    c = load(root)
    t = load_texts(root)
    rows = normalise_events(events)
    if not rows:
        # Copy the template's shape, so the new series has races to run even
        # when the caller only said "put this car somewhere".
        info = describe(c, template, t)
        for tier in info["tiers"][:1]:
            for event in tier["events"]:
                rows.append({"track": event["track"], "type": event["type"],
                             "laps": event["laps"], "tier": 0})
        if not rows:
            raise SeriesError(
                f"series {template} has no events to copy, so the new series "
                f"would have nothing to race")
    # A series with no description shows a blank panel in the menu, and the
    # copy's description key is new, so the template's text does not carry over.
    if not description:
        description = f"One-make racing: {title}."
    made = build(c, t, template=template, title=title,
                 description=description, cars=cars, events=rows, group=group,
                 new_group=new_group, group_flavour=group_flavour,
                 group_card=group_card)
    written = write(c, t, out_dir=root, log=log)
    written["made"] = made
    if register_in:
        from . import depot as depotlib
        try:
            depotlib.register_series(register_in, made["id"], title=made["title"],
                                     group=made["group"],
                                     template=made["template"])
        except Exception as exc:              # noqa: BLE001 - the file is what matters
            log(f"  could not record the new series: {exc}")
    return written


def plan(written: dict) -> list:
    """``[(local, remote_rel, lock)]`` for a deploy of what :func:`write` made."""
    out = []
    career = written.get("career")
    if career:
        out.append((career["path"], ".depot/data/events.dat.nct", False))
    for item in written.get("texts") or ():
        out.append((item["path"], ".depot/" + item["leaf"], False))
    for local, remote in written.get("files") or ():
        out.append((local, remote, False))
    return out
