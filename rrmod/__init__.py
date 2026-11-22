"""The game resource manager for Real Racing 3 mods.

``rrmod`` is a standalone desktop program (PySide6) that sits next to the
Blender add-on:

* the **add-on** only builds geometry and animation and writes a folder with a
  ``car.json`` manifest next to it;
* **this program** owns everything else - which cars are installed, which of
  them are ours, the game tables (spec / appearance / liveries / manifests) and
  pushing to a device over adb.

Layering::

    rrmod.depot    scan the install, tell vanilla from mod, rr3mods.json
    rrmod.workspace the working copy every edit lands in before it is pushed
    rrmod.modpack  the car.json contract the Blender add-on may write
    rrmod.slots    the 17 file slots a car has, and the names the game wants
    rrmod.edit     write game tables back (manifests, files, whole cars)
    rrmod.deploy   adb: push, permissions, logcat verification, restore
    rrmod.music    the BGM playlists under Tracks/data
    rrmod.series   the career file and the text tables behind it
    rrmod.gfx      the graphics profile (eds/*.plist, feats/*.feats)
    rrmod.share    zipping a car up for someone else, and taking one in
    rrmod.cars     the reference spreadsheet (PR, class, top speed, ...)
    rrmod.stats    the spec's performance numbers, read and written
    rrmod.anim     the wing animation: tracks, pivots and the xml clips
    rrmod.animcopy copying an animation from one car onto another
    rrmod.materials which material a mesh wears, and the texture pages
    rrmod.textures  a page out as a picture, and a picture back in as a page
    rrmod.matmanager every row of materials.bin, and how many cars wear it
    rrmod.paints   the paint finishes and swatches the game's customiser offers
    rrmod.brands   the manufacturers and their logo art
    rrmod.thumbs   car pictures cut out of the game's own atlases
    rrmod.atlas    the same, for any atlas folder (track cards, event art)
    rrmod.tracks   the 162 track names, their circuit and their picture
    rrmod.maps     pictures the user brings for a circuit that has no card
    rrmod.i18n     the interface languages
    rrmod.profile  which pages the studio shows, and which the manager does
    rrmod.history  the undo steps: a folder of copies per edit, with a title
    rrmod.project  a ``.rr3proj``: the staged bytes *and* the answers behind them
    rrmod.deps     who names a shared texture page, and who brought it
    rrmod.backup   what a push is about to overwrite, so it can be taken back
    rrmod.pack     the ``.rr3mod`` format: one file, plus what it needs
    rrmod.publish  gathering a car, a career or a logo into such a pack
    rrmod.ui       the windows

Everything below the ``ui`` package is pure Python and importable without Qt,
so it can be tested head-less.
"""

from __future__ import annotations

import os
import sys

# ``rr3lib`` is a sibling of this package; make the import work no matter what
# the current directory is (double-clicked script, frozen exe, ...).
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

__version__ = "0.1.0"
__all__ = ["depot", "workspace", "modpack", "slots", "edit", "deploy", "music",
           "series", "gfx", "share", "cars", "stats", "anim", "animcopy",
           "materials", "textures", "matmanager", "paints", "brands",
           "thumbs", "atlas",
           "tracks", "maps", "i18n", "profile", "history", "project", "deps",
           "backup", "pack", "publish", "ui"]
