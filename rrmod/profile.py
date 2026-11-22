"""Which pages a given copy of the program shows.

There are two programs, and they are the same program with a different set of
pages visible.  That is deliberate: the parts that read and write the game's
tables are one body of code, and duplicating them so that two executables could
each have their own would mean two places to fix every bug.

The split is by **who owns the truth**:

``studio``
    Making a mod.  It needs the car pages, the career editor, the brands, the
    material library and the dependency view - everything that reads or writes
    the working copy.  It does not need a device: a studio has no target.

``manager``
    Installing a mod.  It needs the car list (to see what is installed), the
    music and graphics pages, the dependency view (to say what a pack is
    missing) and the deploy page.  It does not need the career editor or the
    brand editor, because a pack carries its own rows.

``both`` is the full window, which is what ``--all`` gives and what the
development runs use.
"""

from __future__ import annotations

#: Profile names, in the order a menu should list them.
PROFILES = ("studio", "manager", "both")

#: What each profile calls itself.
TITLES = {
    "studio": "RR3 Mod Studio",
    "manager": "RR3 Mod Manager",
    "both": "RR3 Mod Manager",
}

#: Page key -> (tab title, profiles that show it).
#:
#: The key is the attribute name on :class:`rrmod.ui.app.MainWindow`, which is
#: also what the tab order below refers to; keeping one name for both means a
#: page cannot be added to one and forgotten in the other.
PAGES = {
    "cars": ("Cars", ("studio", "manager", "both")),
    "music": ("Music", ("manager", "both")),
    "gfx": ("Graphics", ("manager", "both")),
    "career": ("Career", ("studio", "both")),
    "brands": ("Brands", ("studio", "both")),
    "materials": ("Materials", ("studio", "manager", "both")),
    "deps": ("Dependencies", ("studio", "manager", "both")),
    "decals": ("Decals", ("studio", "both")),
    "publish": ("Publish", ("studio", "both")),
    # The page is called "Test" because that is what it is for now: edits land in
    # the game folder directly, so this is where you check whether the device has
    # them.  The key stays "deploy" - it is a key, not a label, and every page
    # looks itself up by it.
    "deploy": ("Test", ("manager", "both")),
    "about": ("About", ("studio", "manager", "both")),
}

#: The order tabs are added in, for every profile.
ORDER = ("cars", "music", "gfx", "career", "brands", "materials", "deps",
         "decals", "publish", "deploy", "about")


class ProfileError(Exception):
    pass


def check(name: str) -> str:
    """Return ``name`` if it is a profile, else raise."""
    if name not in PROFILES:
        raise ProfileError(f"{name!r} is not one of {PROFILES}")
    return name


def pages(profile: str = "both") -> list:
    """The page keys a profile shows, in tab order."""
    check(profile)
    return [k for k in ORDER if profile in PAGES[k][1]]


def hidden(profile: str = "both") -> list:
    """The page keys a profile leaves out."""
    check(profile)
    return [k for k in ORDER if profile not in PAGES[k][1]]


def title(profile: str = "both") -> str:
    check(profile)
    return TITLES[profile]


def label(profile: str) -> str:
    """The human name of a profile, for a menu entry."""
    check(profile)
    return {"studio": "Mod studio", "manager": "Mod manager",
            "both": "Everything"}[profile]


def summary(profile: str = "both") -> str:
    """One line: what this copy is for."""
    check(profile)
    if profile == "studio":
        return ("Making mods: cars, careers, brands, materials and what depends "
                "on what. Nothing here talks to a device.")
    if profile == "manager":
        return ("Installing mods: what is installed, what a pack is missing, "
                "and pushing to a device or a folder.")
    return "Every page, for working on the program itself."


def selftest() -> int:
    """The page sets have to partition sensibly; prove the invariants."""
    bad = 0
    for name in PROFILES:
        got = pages(name)
        if name == "both" and got != list(ORDER):
            print(f"FAIL both shows {got}")
            bad += 1
        if name != "both" and not got:
            print(f"FAIL {name} shows nothing")
            bad += 1
        if "about" not in got:
            print(f"FAIL {name} hides About")
            bad += 1
        if set(got) & set(hidden(name)):
            print(f"FAIL {name} shows and hides the same page")
            bad += 1
    studio, manager = set(pages("studio")), set(pages("manager"))
    if studio & manager != {"cars", "materials", "deps", "about"}:
        print(f"FAIL the two programs share {sorted(studio & manager)}")
        bad += 1
    if set(pages("studio")) | set(pages("manager")) != set(ORDER):
        print("FAIL the two programs together do not cover every page")
        bad += 1
    print(f"profiles: {'ok' if not bad else str(bad) + ' bad'}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(selftest())
