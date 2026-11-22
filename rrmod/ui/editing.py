"""One place that answers "where should this edit be written?".

**Everything is written straight into the install.**  There is no working copy
and no staging step any more: an edit lands in the folder the game reads, and
the *next* thing you do is look at it in game.  The safety net is
:mod:`rrmod.share`'s car backup (the "Back up this car" button) plus the undo
history :mod:`rrmod.history` keeps - every file an edit touches is copied into
``<install>/_rrmod_backup/<stamp>/`` before it is written, so a bad change can
be rolled back file by file or the whole car can be restored from a backup zip.

The pages do not care which of those two they are talking to: they ask this
object for a root and hand it to the ``rrmod.edit`` helpers.  Keeping that
facade is what made the switch from workspace to in-place a one-file change.
"""
from __future__ import annotations

import os


class Editor:
    """The install, plus the little that a page needs from it."""

    #: False while the pages still expected a staging area.  Kept so a caller
    #: that asks "is anything waiting?" gets a truthful answer instead of an
    #: AttributeError.
    has_workspace = False

    def __init__(self, install: str):
        self.install = install
        self._device = None

    # ------------------------------------------------------------------ basics
    @property
    def root(self) -> str:
        """The root the edit helpers should be given - the install itself."""
        return self.install

    @property
    def depot(self) -> str:
        """The ``.depot`` a page should read tables from."""
        return os.path.join(self.install, ".depot")

    def set_device(self, device) -> None:
        self._device = device

    def ensure(self, *, log=None) -> dict:
        """Nothing to prepare any more; kept so the callers stay unchanged."""
        return {"root": self.install, "created": 0, "files": 0}

    def summary(self) -> dict:
        """The shape the pages have always expected, with nothing in it.

        ``files`` and ``cars`` are kept even though they are always empty: the
        pages print "N file(s) staged" from them, and a page that has to know
        whether a key exists before reading it is a page that will one day forget.
        """
        return {"root": self.install, "mode": "in place", "staged": 0,
                "files": 0, "cars": []}

    def pending(self) -> list:
        """Nothing is ever "waiting": an edit is already in the game files."""
        return []

    # ------------------------------------------------------------------- a car
    def for_car(self, name: str) -> str:
        """The root to edit ``name`` through.  The install, always."""
        return self.install

    def for_tables(self, donor: str = "") -> str:
        return self.install

    def for_materials(self) -> str:
        return self.depot

    def for_gfx(self) -> str:
        return self.depot

    def for_music(self) -> str:
        return os.path.join(self.depot, "Tracks", "data")

    def for_career(self) -> str:
        return self.install

    # --------------------------------------------------------------- collecting
    def capture(self, car: str = "", *, log=None) -> list:
        """Nothing to collect - the file is already in place."""
        return []

    def capture_music(self, *, log=None) -> list:
        return []

    def capture_paths(self, rels, *, log=None) -> list:
        return []

    def staged(self, car: str = "") -> list:
        return []

    # ------------------------------------------------------------------ reading
    def read_root(self, car: str = "") -> str:
        """Where to read a car from: the install, which is also what was written."""
        return self.install

    def has_car(self, car: str) -> bool:
        return os.path.isdir(os.path.join(self.depot, "vehicles", car))

    def has_music(self) -> bool:
        return os.path.isdir(os.path.join(self.depot, "Tracks", "data"))

    def music_root(self) -> str:
        return self.depot

    def discard_car(self, car: str) -> int:
        """There is nothing staged to discard; undo lives in the history dock."""
        return 0
