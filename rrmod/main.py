"""Entry point: ``python -m rrmod`` or ``python rrmod/main.py``.

Asks for the game folder on the first run, then opens the main window on the
install it used last time.  ``--install`` skips the question, ``--check`` runs the
headless self test instead of the GUI.

``--studio`` and ``--manager`` open the same build showing only the pages of one
of the two programs.  They are flags rather than two executables because the
difference is a set of visible tabs: a second binary would be the same 110 MB
again, and every fix would have to be made in two places.
"""

from __future__ import annotations

import os
import sys


def _ensure_importable() -> None:
    """Make ``rr3lib`` importable when this file is run directly."""
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)
    if root not in sys.path:
        sys.path.insert(0, root)


def check(install: str = "") -> int:
    """Headless smoke test: scan, read the music, count the parts."""
    from rrmod import depot as depotlib
    from rrmod import music as musiclib

    try:
        from rrmod.ui import settings as settingslib
        print("settings file:", settingslib.path())
        print("remembered install:", settingslib.install() or "(none)")
        install = install or settingslib.install()
    except Exception as exc:                     # no Qt is not fatal for --check
        print("settings unavailable:", exc)

    root = depotlib.find_install(install) or depotlib.default_install()
    if not root:
        print("no install found; pass one on the command line")
        return 2
    print("install:", root)
    inv = depotlib.scan(root)
    print("scan:", inv.summary(), "in %.2f s" % inv.scan_seconds)
    print("next free id:", inv.free_id())
    for e in inv.cars[:3]:
        print("  ", e.car_id, e.name, e.label, e.lods, e.liveries)
    detail = depotlib.car_detail(inv, inv.cars[0])
    print("detail keys:", sorted(k for k in detail if not k.startswith("_")))
    playlists = musiclib.scan(inv.depot)
    print("playlists:", len(playlists), "|", playlists[0].summary())
    print("music files:", len(musiclib.available_music(inv.depot)))
    print("catalogue:", depotlib.catalogue_summary())
    # The data folder has to be found from inside the frozen bundle too; when the
    # first build left it out the language menu silently did nothing.
    from rrmod import cars as carlib
    from rrmod import i18n
    print("languages:", i18n.available())
    print("translation entries:", {c: len(i18n.table(c)) for c in i18n.available()})
    print("car reference rows:", len(carlib.load()))
    from rrmod import profile as profilelib
    print("profiles:", {name: len(profilelib.pages(name))
                        for name in profilelib.PROFILES})
    if inv.warnings:
        print("warnings:", len(inv.warnings))
        for w in inv.warnings[:5]:
            print("  ", w)
    if "--ui" in sys.argv[1:]:
        _check_ui(root)
    return 0


def _check_ui(install: str) -> None:
    """Build the window offscreen and switch language, to prove both work.

    ``--check`` proves the data files are readable; this proves the switch acts on
    live widgets, which is the part that looked broken when the tables were
    missing from the build.
    """
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from rrmod import i18n
    from rrmod.ui import app as applayout
    from rrmod.ui import translate

    qapp = QApplication.instance() or QApplication([])
    win = applayout.MainWindow(install, "")
    before = [win.tabs.tabText(i) for i in range(win.tabs.count())]
    print("tabs (English):", before)
    print("translated strings:", translate.apply(win))
    i18n.set_language("zh-Hans")
    win.retranslate()
    during = [win.tabs.tabText(i) for i in range(win.tabs.count())]
    print("tabs (Chinese):", during)
    print("switch worked:", during != before and during[0] != before[0])
    i18n.set_language(i18n.DEFAULT)
    win.retranslate()
    after = [win.tabs.tabText(i) for i in range(win.tabs.count())]
    print("switched back cleanly:", after == before)
    # Close it the way the user would: the window owns background threads and
    # dropping the last reference while one is running aborts the process.
    win.close()
    qapp.processEvents()
    del win
    qapp.processEvents()


def main(argv=None) -> int:
    _ensure_importable()
    argv = list(sys.argv[1:] if argv is None else argv)
    install = ""
    if "--install" in argv:
        i = argv.index("--install")
        if i + 1 < len(argv):
            install = argv[i + 1]
            del argv[i:i + 2]
    if "--check" in argv:
        return check(install)

    from PySide6.QtWidgets import QApplication, QDialog

    from rrmod import i18n
    from rrmod import profile as profilelib
    from rrmod.ui import app as applayout
    from rrmod.ui import settings as settingslib
    from rrmod.ui import translate

    qapp = QApplication(sys.argv[:1])
    # The flags win over the remembered choice: somebody who double-clicks the
    # studio shortcut is asking for the studio, whatever they used last time.
    wanted = settingslib.profile()
    for name in ("studio", "manager"):
        if f"--{name}" in argv:
            wanted = name
    if "--all" in argv:
        wanted = "both"
    settingslib.set_profile(wanted)
    qapp.setApplicationName(profilelib.title(wanted))
    saved = settingslib.language()
    if saved:
        i18n.set_language(saved)

    install = install or settingslib.install()
    reference = settingslib.reference()
    if not install:
        dlg = applayout.WelcomeDialog()
        if i18n.language() != i18n.DEFAULT:
            translate.window_title(dlg)
            translate.apply(dlg)
        # QDialog.Accepted, not dlg.Accepted: PySide only exposes enum members on
        # the class, an instance lookup raises AttributeError.
        if dlg.exec() != QDialog.Accepted:
            return 0
        values = dlg.values()
        install = values["install"]
        reference = values["reference"] or reference
        settingslib.set_install(install)
        # The texture format is answered once, here, and every later page write
        # follows it.  Leaving it to a per-file guess is what produced pages in
        # a family this install's GPU cannot read.
        settingslib.set_texture_family(values.get("family") or "auto")
        if reference:
            settingslib.set_reference(reference)

    win = applayout.MainWindow(install, reference)
    geo = settingslib.geometry()
    if geo is not None:
        win.restoreGeometry(geo)
    if i18n.language() != i18n.DEFAULT:
        win.retranslate()
    win.show()
    code = qapp.exec()
    settingslib.set_geometry(win.saveGeometry())
    return code


if __name__ == "__main__":
    raise SystemExit(main())
