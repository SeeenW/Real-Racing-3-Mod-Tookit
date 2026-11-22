"""Collect every English string the interface shows, for the translation table.

Builds each page the way the app does (with a real inventory when one can be
scanned, so the pages are fully populated), asks :mod:`rrmod.ui.translate` what it
would translate, and writes the union to ``rrmod/data/i18n/_source.json``.

Run ``python tools/gen_i18n.py`` after adding or rewording interface text; then
compare that file with the shipped ``zh-Hans.json`` - ``tools/test_rrmod.py``
fails if a string is missing from the table, so a stale table cannot ship.
"""

from __future__ import annotations

import json
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PySide6.QtWidgets import QApplication            # noqa: E402

from rrmod import depot as depotlib                    # noqa: E402
from rrmod import bootlog as bootloglib                # noqa: E402
from rrmod.ui import (                                 # noqa: E402
    animui,
    app as applayout,
    buildui,
    cars,
    deployui,
    gfxui,
    musicbatch,
    musicui,
    picker,
    seriesui,
    translate,
)

OUT = os.path.join(ROOT, "rrmod", "data", "i18n", "_source.json")


def pages(inv, career, texts, playlists, songs) -> list:
    found = []
    found.append(("WelcomeDialog", applayout.WelcomeDialog()))
    found.append(("MainWindow", applayout.MainWindow()))
    found.append(("AnimPane", animui.AnimPane()))
    found.append(("CarTable", cars.CarTable()))
    found.append(("DetailPane", cars.DetailPane()))
    found.append(("CarsPage", cars.CarsPage()))
    found.append(("GfxPage", gfxui.GfxPage()))
    # The boot log dialog is only built once a log has been read, so it is given
    # a stand-in report here rather than left out of the table - its column
    # headings and the notes about the keys the engine owns are interface copy.
    found.append(("BootLogDialog", gfxui.BootLogDialog({
        "profile": "AndroidHigh.plist",
        "platform": "AndroidHigh",
        "extensions": [],
        "keys": 2,
        "rows": [
            {"key": "AA_LEVEL", "wanted": 4, "got": 4,
             "state": bootloglib.TOOK},
            {"key": "MIPMAP_BIAS", "wanted": -2.0, "got": 0.0,
             "state": bootloglib.DIFFERS,
             "note": bootloglib.ENGINE_OWN["MIPMAP_BIAS"]},
        ],
        "counts": {bootloglib.TOOK: 1, bootloglib.DIFFERS: 1,
                   bootloglib.ABSENT: 0},
        "notes": list(bootloglib.ENGINE_OWN.values()),
    })))
    found.append(("MusicPage", musicui.MusicPage()))
    found.append(("DeployPage", deployui.DeployPage()))
    if career is not None:
        found.append(("SeriesPage", seriesui.SeriesPage()))
        found.append(("SeriesDialog", seriesui.SeriesDialog(career, texts)))
        from rrmod import series as serieslib
        names = serieslib.track_names(career)
        # The event dialog has copy of its own (its title, its field labels, the
        # note about unnamed types).  It only exists once an event is picked, so
        # it is built here from the first event the career file offers rather
        # than left out of the inventory.  Tiers hang off the career, not off a
        # series, so this walks ``career.tiers``.
        first = None
        for tier in career.tiers:
            for event in tier.events:
                first = {"track": event.track, "type": event.type,
                         "laps": event.laps, "fame": event.fame,
                         "reward": event.reward, "id": event.id}
                break
            if first:
                break
        if first is not None:
            found.append(("EventDialog",
                          seriesui.EventDialog(first, names)))
        if inv is not None:
            found.append(("CarPickerDialog", picker.CarPickerDialog(inv)))
        found.append(("TrackPickerDialog", picker.TrackPickerDialog(
            inv.depot if inv is not None else "", names)))
    if playlists:
        found.append(("BatchDialog", musicbatch.BatchDialog(playlists, songs)))
    if inv is not None:
        found.append(("BuildDialog", buildui.BuildDialog(inv)))
    return found


def main() -> int:
    appl = QApplication.instance() or QApplication([])
    inv = career = texts = None
    playlists = songs = []
    install = depotlib.default_install()
    if install:
        try:
            inv = depotlib.scan(install)
        except Exception as exc:                       # noqa: BLE001
            print(f"scan failed: {exc}")
    if inv is not None:
        try:
            from rrmod import series as serieslib
            career = serieslib.load(inv.root)
            texts = serieslib.load_texts(inv.depot)
        except Exception as exc:                       # noqa: BLE001
            print(f"career load failed: {exc}")
        try:
            from rrmod import music as musiclib
            playlists = [musiclib.load(p) for p in musiclib.list_playlists(inv.depot)]
            songs = musiclib.available_music(inv.depot)
        except Exception as exc:                       # noqa: BLE001
            print(f"music load failed: {exc}")

    seen: dict = {}
    for name, widget in pages(inv, career, texts, playlists, songs):
        for text in translate.strings(widget):
            seen.setdefault(text, []).append(name)
        widget.deleteLater()

    ordered = dict(sorted(seen.items(), key=lambda kv: kv[0].lower()))
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(ordered, fh, ensure_ascii=False, indent=1)
        fh.write("\n")
    print(f"{len(ordered)} strings -> {OUT}")
    appl.processEvents()
    return 0


if __name__ == "__main__":
    sys.exit(main())
