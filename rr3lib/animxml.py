"""``<car>_animations.xml`` — the small state machine beside a car's ``_wing.banim``.

A car with active aero (or a moving spoiler, or a driver) ships two animation
files:

* ``<car>_wing.banim`` — the curves, one track per moving part
* ``<car>_animations.xml`` — which *frame range* of those curves each named
  transition plays

The XML is tiny and looks like this (``2006_mercedes_slr_mclaren_722``)::

    <anims>
      <anim name="wing_initial"><frames start="0"  end="0"  /></anim>
      <anim name="neutral_to_speed"><frames start="0"  end="10" /></anim>
      <anim name="speed_to_brake"><frames start="10" end="30" /></anim>
      <anim name="brake_to_speed"><frames start="30" end="10" /></anim>
    </anims>

Frame numbers are banim frames at **33 ms each** (30.303 fps): the Reventon's
``wing_up 0 -> 45`` is 1485 ms, which is exactly its ``_wing.banim`` duration,
and the Porsche 718's ``0 -> 74`` is 2442 ms, also exact.  That is why
:data:`FRAME_MS` is 33.0 and not 1000/30.

A clip whose ``end`` is below its ``start`` plays **backwards** (``wing_down``
45 -> 0), so the frame range carries its direction.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

#: One banim frame. 45 frames x 33 ms == the Reventon's 1485 ms wing animation.
FRAME_MS = 33.0

_ANIM_RE = re.compile(
    r'<anim\s+name="([^"]+)"\s*>\s*<frames\s+start="(-?\d+)"\s+end="(-?\d+)"\s*/?>',
    re.IGNORECASE,
)

#: The names the game uses, with what each one means.
CLIP_DOC = {
    "wing_initial": "rest pose (folded / retracted)",
    "wing_race_initial": "rest pose used during a race",
    "wing_up": "extend the aero (brake flap up)",
    "wing_down": "retract the aero",
    "pivot_up": "raise the moving pivot",
    "pivot_down": "lower the moving pivot",
    "neutral_to_speed": "spoiler neutral -> high-speed position",
    "speed_to_neutral": "high-speed -> neutral",
    "speed_to_brake": "high-speed -> air-brake position",
    "brake_to_speed": "air-brake -> high-speed",
    "neutral_to_brake": "neutral -> air-brake",
    "brake_to_neutral": "air-brake -> neutral",
}


@dataclass
class Clip:
    """One named transition: a frame range of the car's banim."""

    name: str
    start: int
    end: int

    @property
    def reversed(self) -> bool:
        return self.end < self.start

    @property
    def start_ms(self) -> float:
        return self.start * FRAME_MS

    @property
    def end_ms(self) -> float:
        return self.end * FRAME_MS

    @property
    def frames(self) -> int:
        return abs(self.end - self.start)

    @property
    def duration_ms(self) -> float:
        return self.frames * FRAME_MS

    def doc(self) -> str:
        return CLIP_DOC.get(self.name, "")


def find_xml(banim_path: str) -> str | None:
    """The ``_animations.xml`` that belongs to ``banim_path``, if it is there.

    ``driver/driver.banim`` has none; ``<car>_wing.banim`` sits next to
    ``<car>_animations.xml``.
    """
    folder = os.path.dirname(os.path.abspath(banim_path))
    stem = os.path.basename(banim_path)
    for suffix in (".banim",):
        if stem.lower().endswith(suffix):
            stem = stem[: -len(suffix)]
            break
    for name in (stem + "_animations.xml", "animations.xml"):
        cand = os.path.join(folder, name)
        if os.path.isfile(cand):
            return cand
    # any *_animations.xml in the same folder (a renamed banim still finds it)
    try:
        for entry in sorted(os.listdir(folder)):
            if entry.lower().endswith("_animations.xml"):
                return os.path.join(folder, entry)
    except OSError:
        pass
    return None


def parse(text: str) -> list[Clip]:
    """Parse XML text into clips, in file order."""
    return [Clip(m.group(1), int(m.group(2)), int(m.group(3)))
            for m in _ANIM_RE.finditer(text)]


def load(path: str) -> list[Clip]:
    """Parse an ``_animations.xml`` file into clips."""
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        return parse(fh.read())


def format_report(clips: list[Clip], source: str = "") -> str:
    """Human readable clip table, for the text reports."""
    if not clips:
        return "no <anim> entries\n"
    out = []
    if source:
        out.append(f"source : {source}")
    out.append(f"{'clip':<20} {'frames':>11} {'time (ms)':>15}  note")
    for c in clips:
        fr = f"{c.start:>5} -> {c.end:<5}"
        tm = f"{c.start_ms:>6.0f} -> {c.end_ms:<6.0f}"
        note = "backwards" if c.reversed else ""
        doc = c.doc()
        if doc:
            note = f"{note}; {doc}" if note else doc
        out.append(f"{c.name:<20} {fr} {tm}  {note}")
    return "\n".join(out) + "\n"


# ------------------------------------------------------------------- writing
#: The order the shipped files use.  The game looks clips up by name, so the
#: order is cosmetic - but keeping it makes a rebuilt file look like an
#: original one, which matters when diffing.
CLIP_ORDER = (
    "wing_initial", "wing_race_initial", "wing_up", "wing_down",
    "pivot_up", "pivot_down",
    "neutral_to_speed", "speed_to_neutral", "speed_to_brake",
    "brake_to_speed", "neutral_to_brake", "brake_to_neutral",
)


def sort_clips(clips: list[Clip]) -> list[Clip]:
    """Order clips the way the shipped files do (unknown names last, as given)."""
    rank = {n: i for i, n in enumerate(CLIP_ORDER)}
    return sorted(clips, key=lambda c: (rank.get(c.name, len(rank)),))


def build(clips: list[Clip], *, sort: bool = False, header: bool = True) -> str:
    """Render clips back to ``_animations.xml`` text.

    ``sort`` is off by default so an edited file keeps its original order; the
    game looks clips up by name, so the order is cosmetic either way.
    """
    if sort:
        clips = sort_clips(clips)
    out = []
    if header:
        out.append('<?xml version="1.0"?>')
        out.append("")
    out.append("<anims>")
    for c in clips:
        out.append(f'\t<anim name="{c.name}">')
        out.append(f'\t\t<frames start="{c.start}" end="{c.end}" />')
        out.append("\t</anim>")
    out.append("</anims>")
    return "\n".join(out) + "\n"


def save(clips: list[Clip], path: str, *, sort: bool = False) -> int:
    """Write clips to ``path``; returns the character count."""
    text = build(clips, sort=sort)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    return len(text)


# --------------------------------------------------------------- authoring
def frames_for(ms: float) -> int:
    """Milliseconds -> the frame number the XML wants (rounded, >= 0)."""
    return max(0, int(round(ms / FRAME_MS)))


def wing_pair(start_frame: int, end_frame: int) -> list[Clip]:
    """The minimal active-aero set: rest, extend, retract.

    ``wing_up`` runs ``start -> end`` and ``wing_down`` runs it back, so the
    retract clip is the reverse of the extend clip.  ``wing_initial`` holds the
    rest pose at ``start_frame``.
    """
    return [
        Clip("wing_initial", start_frame, start_frame),
        Clip("wing_up", start_frame, end_frame),
        Clip("wing_down", end_frame, start_frame),
    ]


def full_set(neutral: int, speed: int, brake: int) -> list[Clip]:
    """All six transitions of the three-pose spoiler (NASCAR style)."""
    return [
        Clip("wing_initial", neutral, neutral),
        Clip("neutral_to_speed", neutral, speed),
        Clip("speed_to_neutral", speed, neutral),
        Clip("speed_to_brake", speed, brake),
        Clip("brake_to_speed", brake, speed),
        Clip("neutral_to_brake", neutral, brake),
        Clip("brake_to_neutral", brake, neutral),
    ]


def validate(clips: list[Clip], duration_ms: float | None = None) -> list[str]:
    """Return warnings about a clip set."""
    out: list[str] = []
    seen = set()
    for c in clips:
        if c.name in seen:
            out.append(f"duplicate clip {c.name!r} (the last one wins)")
        seen.add(c.name)
        if c.name not in CLIP_DOC:
            out.append(f"{c.name!r} is not a name the game asks for - ignored")
        if c.start < 0 or c.end < 0:
            out.append(f"{c.name}: negative frame number")
        if duration_ms is not None:
            limit = frames_for(duration_ms)
            worst = max(c.start, c.end)
            if worst > limit:
                out.append(
                    f"{c.name}: frame {worst} is past the end of the banim "
                    f"({limit} frames / {duration_ms:g} ms)"
                )
    if "wing_initial" not in seen:
        out.append("no wing_initial clip - the part may sit in its modelled pose")
    return out
