"""The BGM playlists: which song plays on which track, per event.

Each ``Tracks/data/<track>-<time>-<id>.bin.nct`` is a small RC4-wrapped record
stream (``u32 key, u32 len, value``).  Three keys hold the menu music::

    0xBB463310  Music_Track_1
    0xBB463313  Music_Track_2
    0xBB463312  Music_Track_3

Their values are file names under ``audio/music/``.  All 167 files parse and
re-encrypt byte for byte, so this needs no external tool at all - the old
``analysis/music_tool.py`` shelled out to MonkeyTool for the codec.
"""

from __future__ import annotations

import os
import struct

from rr3lib import nct

TRACK_DIR = "Tracks/data"

#: key -> slot label, in the order the game reads them
SLOTS = ((0xBB463310, "Music_Track_1"),
         (0xBB463313, "Music_Track_2"),
         (0xBB463312, "Music_Track_3"))

MUSIC_DIR = "audio/music"


class MusicError(Exception):
    pass


# --------------------------------------------------------------------- records
def parse_records(plain: bytes) -> list:
    """``[(key, value bytes)]`` from an already decrypted blob."""
    out = []
    pos = 0
    n = len(plain)
    while pos + 8 <= n:
        key, size = struct.unpack_from("<II", plain, pos)
        pos += 8
        if pos + size > n:
            raise MusicError(f"record 0x{key:08X} runs past the end of the file")
        out.append((key, plain[pos:pos + size]))
        pos += size
    return out


def build_records(records) -> bytes:
    out = bytearray()
    for key, value in records:
        out += struct.pack("<II", key, len(value)) + value
    return bytes(out)


def _text(value: bytes) -> str:
    return value.rstrip(b"\x00").decode("utf-8", "replace")


def _bytes(text: str) -> bytes:
    return text.encode("utf-8") + b"\x00"


# ------------------------------------------------------------------ playlists
class Playlist:
    """One ``Tracks/data`` file."""

    def __init__(self, path: str, records: list):
        self.path = path
        self.records = records

    @property
    def name(self) -> str:
        return os.path.basename(self.path)

    def songs(self) -> dict:
        """``{slot_label: filename}`` for the three music keys."""
        got = {}
        for key, value in self.records:
            for slot_key, label in SLOTS:
                if key == slot_key:
                    got[label] = _text(value)
        return got

    def set_song(self, label: str, filename: str) -> bool:
        """Change one slot.  Returns True when something actually changed."""
        for slot_key, slot_label in SLOTS:
            if slot_label != label:
                continue
            for i, (key, value) in enumerate(self.records):
                if key == slot_key:
                    if _text(value) == filename:
                        return False
                    self.records[i] = (key, _bytes(filename))
                    return True
            self.records.append((slot_key, _bytes(filename)))
            return True
        raise MusicError(f"unknown slot {label!r}")

    def clear(self, label: str) -> bool:
        for slot_key, slot_label in SLOTS:
            if slot_label == label:
                before = len(self.records)
                self.records = [(k, v) for k, v in self.records if k != slot_key]
                return len(self.records) != before
        raise MusicError(f"unknown slot {label!r}")

    def to_bytes(self) -> bytes:
        return build_records(self.records)

    def summary(self) -> str:
        return f"{self.name}: " + ", ".join(
            f"{k}={v or '-'}" for k, v in self.songs().items())


def load(path: str) -> Playlist:
    return Playlist(path, parse_records(nct.read(path)))


def save(pl: Playlist, path: str = "") -> int:
    path = path or pl.path
    blob = pl.to_bytes()
    nct.write(path, blob)
    return len(blob)


def list_playlists(depot: str) -> list:
    folder = os.path.join(depot, *TRACK_DIR.split("/"))
    if not os.path.isdir(folder):
        return []
    return sorted(os.path.join(folder, f) for f in os.listdir(folder)
                  if f.endswith(".bin.nct"))


def available_music(depot: str) -> list:
    folder = os.path.join(depot, *MUSIC_DIR.split("/"))
    if not os.path.isdir(folder):
        return []
    return sorted(f for f in os.listdir(folder) if f.lower().endswith(".mp3"))


def scan(depot: str, progress=None) -> list:
    """Load every playlist.  167 files take ~0.1 s."""
    paths = list_playlists(depot)
    out = []
    total = len(paths) or 1
    for i, p in enumerate(paths):
        if progress and i % 20 == 0:
            progress(i / total)
        try:
            out.append(load(p))
        except Exception as exc:                 # noqa: BLE001
            raise MusicError(f"{os.path.basename(p)}: {exc}") from exc
    if progress:
        progress(1.0)
    return out


def playlist_title(pl: Playlist) -> str:
    """``bathurst-circuit-afternoon-101`` -> ``Bathurst Circuit Afternoon``."""
    stem = pl.name[: -len(".bin.nct")]
    bits = stem.split("-")
    words = [b for b in bits if not b.isdigit()]
    text = " ".join(words).replace("_", " ")
    return text.title()


#: the time-of-day word a playlist name carries
TIMES = ("dawn", "morning", "noon", "afternoon", "sunset", "night")

#: tracks that are played by the front end rather than by a race.  They live in
#: the same folder, so a "spread these songs over the calendar" plan has to skip
#: them or the menu music ends up in the middle of a lap.
MENU_SONGS = ("Menu_Music.mp3", "Garage_Music.mp3", "LoadingScreen.mp3",
              "IntroCinematic.mp3", "IntroLogos.mp3")


def race_songs(songs) -> list:
    """The audio files that belong to a race, in name order."""
    return [s for s in songs if s not in MENU_SONGS]


def is_menu_song(filename: str) -> bool:
    return filename in MENU_SONGS


def track_key(pl: Playlist) -> str:
    """The circuit a playlist belongs to, without the time of day.

    ``bathurst-circuit-night-198`` -> ``bathurst-circuit``.  Every event is one
    circuit at one time of day, so this is what "the tracks" means in the UI:
    the same circuit shows up two to four times with different music.
    """
    stem = pl.name[: -len(".bin.nct")]
    bits = [b for b in stem.split("-") if not b.isdigit()]
    while bits and bits[-1] in TIMES:
        bits.pop()
    return "-".join(bits) or stem


def track_title(key: str) -> str:
    return key.replace("-", " ").replace("_", " ").title()


def time_of_day(pl: Playlist) -> str:
    stem = pl.name[: -len(".bin.nct")]
    bits = [b for b in stem.split("-") if not b.isdigit()]
    return bits[-1] if bits and bits[-1] in TIMES else ""


def group_by_track(playlists) -> dict:
    """``{circuit key: [playlist, ...]}``, in name order."""
    out: dict = {}
    for pl in playlists:
        out.setdefault(track_key(pl), []).append(pl)
    for pls in out.values():
        pls.sort(key=lambda p: (TIMES.index(time_of_day(p))
                                if time_of_day(p) in TIMES else 99, p.name))
    return dict(sorted(out.items()))


def usage(playlists) -> dict:
    """``{song filename: how many slots use it}``."""
    out: dict = {}
    for pl in playlists:
        for _label, song in pl.songs().items():
            if song:
                out[song] = out.get(song, 0) + 1
    return dict(sorted(out.items()))


def unused(playlists, songs) -> list:
    used = usage(playlists)
    return [s for s in songs if not used.get(s)]


def shuffle(playlists, songs, *, seed: int = 0, keep_first: bool = False) -> dict:
    """Fill the three slots of every playlist from ``songs`` at random.

    The draw is seeded, so pressing preview twice gives the same answer and the
    plan can be looked at before it is staged.  Songs are drawn without an
    immediate repeat: a playlist never gets the same track in two slots, and no
    two neighbouring playlists get the identical triple, which is what makes a
    random assignment sound random rather than broken.
    """
    import random

    pool = [s for s in songs if s]
    if not pool:
        raise MusicError("no songs to shuffle")
    rng = random.Random(seed)
    out = {}
    last = None
    for pl in playlists:
        for _attempt in range(24):
            picked = rng.sample(pool, min(len(LABELS), len(pool)))
            while len(picked) < len(LABELS):
                picked.append(picked[len(picked) % len(pool)])
            if picked != last:
                break
        else:
            picked = pool[:len(LABELS)]
        values = {label: picked[j] for j, label in enumerate(LABELS)}
        if keep_first:
            before = _current(pl)
            if before.get(LABELS[0]):
                values[LABELS[0]] = before[LABELS[0]]
        out[pl.name] = values
        last = picked
    return out


def summary(playlists) -> dict:
    """Which songs are used how often (for the overview page)."""
    used = {}
    for pl in playlists:
        for label, song in pl.songs().items():
            if song:
                used.setdefault(song, []).append((pl.name, label))
    return {"playlists": len(playlists),
            "songs_used": len(used),
            "songs": used}


# ------------------------------------------------------------------- batching
#
# The helpers below all return ``{playlist name: {slot label: filename}}`` and
# never touch a file.  The UI merges the result into its pending-edits dict, so a
# batch is staged and saved exactly like a single-slot change.
LABELS = tuple(label for _key, label in SLOTS)


def _current(pl: Playlist) -> dict:
    songs = pl.songs()
    return {label: songs.get(label, "") for label in LABELS}


def assign(pl: Playlist, values: dict) -> dict:
    """``values`` may name any subset of the three slots."""
    out = _current(pl)
    for label, filename in values.items():
        if label not in LABELS:
            raise MusicError(f"unknown slot {label!r}")
        out[label] = filename or ""
    return out


def cycle(playlists, songs, *, start: int = 0, keep_first: bool = False) -> dict:
    """Walk ``songs`` around the three slots, one step per playlist.

    With ``songs = ["a", "b", "c"]`` the first playlist gets a/b/c, the second
    b/c/a, the third c/a/b and so on.  That is the shape the game's own data
    uses for the long race calendars - neighbouring events share two of three
    tracks instead of repeating the same triple 40 times.
    """
    songs = [s for s in songs if s]
    if not songs:
        raise MusicError("no songs to cycle")
    out = {}
    n = len(songs)
    for i, pl in enumerate(playlists):
        base = (start + i) % n
        values = {label: songs[(base + j) % n] for j, label in enumerate(LABELS)}
        if keep_first:
            before = _current(pl)
            if before.get(LABELS[0]):
                values[LABELS[0]] = before[LABELS[0]]
        out[pl.name] = values
    return out


def rotate(playlists, steps: int = 1) -> dict:
    """Shift the three slots of every playlist (1 or 2)."""
    steps = int(steps) % len(LABELS)
    out = {}
    for pl in playlists:
        before = _current(pl)
        values = {}
        for j, label in enumerate(LABELS):
            values[label] = before[LABELS[(j + steps) % len(LABELS)]]
        out[pl.name] = values
    return out


def replace_song(playlists, old: str, new: str) -> dict:
    """Swap one filename for another wherever it appears."""
    out = {}
    for pl in playlists:
        before = _current(pl)
        if old not in before.values():
            continue
        out[pl.name] = {label: (new if value == old else value)
                        for label, value in before.items()}
    return out


def clear_slot(playlists, label: str) -> dict:
    if label not in LABELS:
        raise MusicError(f"unknown slot {label!r}")
    return {pl.name: assign(pl, {label: ""}) for pl in playlists}


def diff(playlists, plan: dict) -> int:
    """How many slot values a plan would actually change."""
    by_name = {pl.name: pl for pl in playlists}
    n = 0
    for name, values in plan.items():
        pl = by_name.get(name)
        if pl is None:
            continue
        before = _current(pl)
        n += sum(1 for label, value in values.items()
                 if (value or "") != before.get(label, ""))
    return n


def plan_to_edits(plan: dict, playlists=None) -> dict:
    """``{(playlist name, slot label): filename}`` - the UI's dirty format.

    When ``playlists`` is given, values that already match the playlist are
    dropped, so the "N change(s)" counter only counts real work.
    """
    by_name = {pl.name: pl for pl in (playlists or [])}
    out = {}
    for name, values in plan.items():
        pl = by_name.get(name)
        before = _current(pl) if pl is not None else {}
        for label, value in values.items():
            value = value or ""
            if pl is not None and value == before.get(label, ""):
                continue
            out[(name, label)] = value
    return out

