"""Push to a device over adb: locate it, copy files, fix permissions, verify.

Everything about adb is lazy here.  The old ``analysis/rr3adb.py`` resolves the
device at import time and calls ``SystemExit`` when none answers, which is
unacceptable inside a GUI - the program has to start, show the car list and only
complain when the user actually presses Deploy.

Facts this module encodes
-------------------------
* MuMu ships its own adb at ``<MuMu>\\nx_device\\<version>\\shell\\adb.exe`` and
  the version folder changes on every update, so it is resolved by glob.
* MuMu's adb server listens on **5038**; the stock one on 5037.
* The device root is ``/storage/emulated/0/Android/data/com.ea.games.r3_rra/files``.
* Files belong to ``10041:1078`` (``ext_data_rw``).  The three ``asset_list_*``
  manifests must be ``chmod 444``; other files are ``660`` and folders ``2770``.
  Folders need the search bit, so they never share a mode with files.
* The engine verifies the manifests, so a size/hash mismatch triggers a
  re-download of the whole car instead of a load.
"""

from __future__ import annotations

import glob
import hashlib
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import time

from rr3lib import appearance as applib
from rr3lib import career as careerlib
from rr3lib import nct as nctlib
from rr3lib import spec as speclib
from rr3lib import texts as textlib

MUMU_ROOT = r"D:\Program Files\Netease\MuMu"
PKG = "com.ea.games.r3_rra"
DEV = f"/storage/emulated/0/Android/data/{PKG}/files"
UID = "10041"
GID = "1078"

SERIALS = ("127.0.0.1:16384", "127.0.0.1:5555", "emulator-5554")
PORTS = ("5038", "5037")

#: What the user typed on the Deploy tab.  Kept here rather than read from the
#: settings file so this module stays free of the UI package; the page sets it
#: once on connect and every later push reuses it without asking again.
_DEFAULT_ENDPOINT = {"serial": "", "port": ""}


def set_default_endpoint(serial: str = "", port: str = "") -> None:
    _DEFAULT_ENDPOINT["serial"] = serial or ""
    _DEFAULT_ENDPOINT["port"] = port or ""


def default_endpoint() -> tuple:
    return (_DEFAULT_ENDPOINT["serial"], _DEFAULT_ENDPOINT["port"])

#: Manifest files that must end up read only, and the ones that stay writable.
LOCKED = ("apk/res/asset_list_vehicle_data.txt",
          "apk/res/asset_list_vehicle_",
          "apk/res/asset_list_base.txt")

#: logcat lines worth showing the user after a launch.
MARKERS = (
    "StartListDownload", "ASSET DOWNLOAD ERROR", "all files up to date",
    "nTotalDownloadBytes", "Asset List not found", "is missing LOD",
    "Failed to match suspension", "Couldn't find", "FATAL", "Fatal signal",
    "loadSuspension", "loadCarDamageThresholds", "loadCarAppearance",
    "Invalid material", "Missing material",
)


class DeployError(Exception):
    pass


# ------------------------------------------------------------------ discovery
def _version_key(path: str):
    try:
        v = os.path.basename(os.path.dirname(os.path.dirname(path)))
        return tuple(int(x) for x in v.split("."))
    except Exception:                            # noqa: BLE001
        return (0,)


def find_adb() -> str:
    """Newest MuMu adb, else whatever is on PATH."""
    cands = glob.glob(os.path.join(MUMU_ROOT, "nx_device", "*", "shell", "adb.exe"))
    cands += glob.glob(os.path.join(MUMU_ROOT, "nx_main", "adb.exe"))
    cands = [c for c in cands if os.path.isfile(c)]
    if cands:
        cands.sort(key=_version_key, reverse=True)
        return cands[0]
    w = shutil.which("adb")
    return w or ""


def _env(port: str = "") -> dict:
    e = dict(os.environ)
    if port:
        e["ANDROID_ADB_SERVER_PORT"] = port
    e["PYTHONIOENCODING"] = "utf-8"
    return e


#: Server ports already proved to answer, so the probe below runs once per port
#: rather than before every adb call.
_PORT_OK = {}

#: The port the last successful call actually used, after the fallback above.
#: ``probe`` reports this instead of echoing what it was asked for, so the
#: interface saves a setting that works rather than the one that did not.
#: ``tried`` separates "nothing has run yet" from "the fallback chose the default
#: port", which is itself a value worth reporting.
_EFFECTIVE_PORT = {"port": "", "tried": False}


def _port_works(adb: str, port: str, timeout: int = 6) -> bool:
    """True when a real adb server answers on ``port`` and knows about a device.

    ``adb version`` is not a good test: with no server running it *starts* one
    on whatever port it was told, so it reports success on a port that then
    cannot see the device (the emulator is attached to the default server).
    ``adb devices`` on its own is not enough either - it prints the
    ``List of devices attached`` header even when the list is empty, so any
    server that answers at all would pass.  The test is a real device line.
    """
    if port in _PORT_OK:
        return _PORT_OK[port]
    r = _run_once(adb, ["devices"], port, timeout)
    text = (r.stdout or "") if r and r.returncode == 0 else ""
    ok = any(line.strip().endswith(("\tdevice", " device"))
             for line in text.splitlines())
    if not ok:
        # A port with no server behind it hangs until the timeout, which the
        # interface then reports as "adb sees no devices" - so remember that this
        # port is dead and stop paying the timeout on every call.
        _PORT_OK[port] = False
    else:
        _PORT_OK[port] = True
    return ok


def _run(adb: str, args, port: str = "", timeout: int = 30):
    """Run adb, ignoring a remembered server port that has nothing behind it.

    ``ANDROID_ADB_SERVER_PORT`` names the *server* port, which is 5037 unless
    something changed it - not the port the emulator's own adbd listens on
    (5555, 16384, ...).  A remembered value of 5555 made every call hang until
    the timeout expired, which the interface reported as "adb sees no devices":
    the server it had been told to talk to never answered.  Checking the port
    once and falling back to the default turns that dead end into a connection.
    """
    if port and not _port_works(adb, port):
        port = ""
    _EFFECTIVE_PORT["port"] = port
    _EFFECTIVE_PORT["tried"] = True
    return _run_once(adb, args, port, timeout)


def effective_port(requested: str = "") -> str:
    """The server port that last worked, or ``requested`` if nothing ran yet.

    A remembered 5555 is the emulator's own adbd port, not the adb server's, so
    every call to it hangs.  The fallback in :func:`_run` makes that harmless,
    but the interface used to save the requested value straight back into
    ``settings.ini``, so the dead setting came back every session.  Reporting
    the port that actually answered breaks that loop - including when the answer
    is "the default port", which comes back as an empty string.
    """
    if not _EFFECTIVE_PORT["tried"]:
        return requested
    return _EFFECTIVE_PORT["port"]


def _run_once(adb: str, args, port: str, timeout: int):
    try:
        return subprocess.run([adb, *args], capture_output=True, text=True,
                              encoding="utf-8", errors="replace",
                              env=_env(port), timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None


class Device:
    """One adb endpoint.  Create with :func:`connect`."""

    def __init__(self, adb: str, serial: str, port: str):
        self.adb = adb
        self.serial = serial
        self.port = port

    def __repr__(self) -> str:
        return f"<Device {self.serial} via {self.adb}>"

    # ---- primitives --------------------------------------------------
    def run(self, *args, timeout: int = 300):
        r = _run(self.adb, ["-s", self.serial, *args], self.port, timeout)
        if r is None:
            raise DeployError(f"adb {' '.join(args)} timed out")
        return r

    def sh(self, cmd: str, check: bool = False):
        r = self.run("shell", cmd)
        if check and r.returncode != 0:
            raise DeployError(f"shell failed: {cmd}\n{r.stderr[:400]}")
        return r

    def su(self, cmd: str, check: bool = False):
        return self.sh("su -c " + _quote(cmd), check=check)

    def is_root(self) -> bool:
        """True when ``su`` actually grants root, not when adb runs as root.

        ``adb shell id`` always answers ``uid=2000(shell)`` on this emulator even
        though ``su`` works, so the useful question is whether the elevated shell
        comes back as uid 0 - the push code chowns and chmods through it.
        """
        r = self.su("id")
        return "uid=0" in (r.stdout or "")

    # ---- file transfer ----------------------------------------------
    def push(self, local: str, remote_rel: str, *, lock: bool = False) -> dict:
        remote = f"{DEV}/{remote_rel}"
        self.su(f"mkdir -p {_quote(os.path.dirname(remote))}")
        r = self.run("push", local, remote)
        if r.returncode != 0:
            raise DeployError(f"push failed: {local}\n{r.stderr[:400]}")
        self.su(f"chown {UID}:{GID} {_quote(remote)}")
        self.su(f"chmod {'444' if lock else '644'} {_quote(remote)}")
        return {"local": local, "remote": remote,
                "size": os.path.getsize(local), "locked": lock}

    def push_tree(self, local_dir: str, remote_rel: str) -> dict:
        remote = f"{DEV}/{remote_rel}"
        self.su(f"mkdir -p {_quote(remote)}")
        r = self.run("push", local_dir + os.sep + ".", remote)
        if r.returncode != 0:
            raise DeployError(f"push dir failed: {local_dir}\n{r.stderr[:400]}")
        self.su(f"chown -R {UID}:{GID} {_quote(remote)}")
        self.fix_permissions(remote_rel)
        n = sum(len(f) for _d, _s, f in os.walk(local_dir))
        return {"local": local_dir, "remote": remote, "files": n}

    def fix_permissions(self, remote_rel: str) -> None:
        """Give folders and files their own modes, never one mode for both.

        ``chmod -R 644`` looks harmless but it clears the execute bit on every
        folder it walks into, and a folder without execute cannot be *searched* -
        the game then cannot stat anything inside it.  That is not a theoretical
        mistake: a push that ended in ``chmod 660 <car>/*`` turned the car's
        ``livery`` folder into ``drw-rw----`` and the six paint atlases inside it
        became unreadable, which the renderer draws as the magenta "missing
        texture" checkerboard.  Folders get ``2770`` (the setgid bit keeps the
        group right for files the engine writes) and files get ``660``.
        """
        root = f"{DEV}/{remote_rel}"
        self.su(f"find {_quote(root)} -type d -exec chmod 2770 {{}} +")
        self.su(f"find {_quote(root)} -type f -exec chmod 660 {{}} +")

    def remove(self, remote_rel: str, *, tree: bool = False):
        self.su(f"rm -rf {_quote(f'{DEV}/{remote_rel}')}")

    def exists(self, remote_rel: str) -> bool:
        r = self.su(f"test -e {_quote(f'{DEV}/{remote_rel}')} && echo yes")
        return "yes" in (r.stdout or "")

    # ---- app control -------------------------------------------------
    def stop(self):
        self.sh(f"am force-stop {PKG}")

    def launch(self):
        self.sh(f"monkey -p {PKG} -c android.intent.category.LAUNCHER 1")

    def clear_log(self):
        self.run("logcat", "-c")

    def logcat(self, seconds: float = 30.0, path: str = "") -> str:
        """Collect logcat for ``seconds``; returns the text (also saved)."""
        try:
            proc = subprocess.Popen(
                [self.adb, "-s", self.serial, "logcat", "-v", "threadtime"],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                encoding="utf-8", errors="replace", env=_env(self.port))
        except OSError as exc:
            raise DeployError(f"logcat failed: {exc}") from exc
        lines = []
        t0 = time.time()
        try:
            while time.time() - t0 < seconds:
                line = proc.stdout.readline()
                if not line:
                    break
                lines.append(line)
        finally:
            proc.kill()
        text = "".join(lines)
        if path:
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            with open(path, "w", encoding="utf-8", errors="replace") as fh:
                fh.write(text)
        return text


def _quote(s: str) -> str:
    return "'" + s.replace("'", "'\\''") + "'"


def parse_endpoint(text: str) -> tuple:
    """``"127.0.0.1:16384"`` -> ``("127.0.0.1:16384", "")``.

    A serial can be either ``host:port`` or a plain name like ``emulator-5554``.
    The adb server port is a separate thing entirely (MuMu listens on 5038 while
    the device sits on 16384) and is only worth setting when the default is
    wrong, so an empty second half means "whatever the environment says".
    """
    text = (text or "").strip()
    if not text:
        return ("", "")
    if "@" in text:
        # "5038@127.0.0.1:16384" - server port in front, the way some tools write it
        port, _, serial = text.partition("@")
        return (serial.strip(), port.strip())
    return (text, "")


def devices(adb_path: str = "", port: str = "") -> list:
    """What ``adb devices`` actually reports, as ``[(serial, state)]``."""
    adb = adb_path or find_adb()
    if not adb or not os.path.isfile(adb):
        return []
    r = _run(adb, ["devices"], port, 20)
    out = []
    for line in (r.stdout or "").splitlines() if r else ():
        line = line.strip()
        if not line or line.lower().startswith("list of devices"):
            continue
        if line.startswith("*"):
            continue
        parts = line.split()
        if len(parts) >= 2:
            out.append((parts[0], parts[1]))
    return out


def connect(adb_path: str = "", *, serial: str = "", port: str = "",
            timeout: int = 15) -> Device:
    """Return a working :class:`Device` or raise :class:`DeployError`.

    With ``serial`` given, that endpoint is used as-is (connecting first when it
    looks like ``host:port``) and nothing else is tried - the caller knows what
    it wants.  Without it, every serial ``adb devices`` lists is tried before
    falling back to the guesses below, so a second emulator instance or a device
    on a non-default port is found without editing the source.  When neither is
    given, whatever the Deploy tab last used is tried first.
    """
    if not serial and not port:
        serial, port = default_endpoint()
    adb = adb_path or find_adb()
    if not adb or not os.path.isfile(adb):
        raise DeployError(
            "adb.exe not found. Looked under " + MUMU_ROOT +
            " and on PATH - point the manager at adb in Settings.")

    def usable(candidate: str, port_: str, attempts: int = 3) -> bool:
        # A cold adb server answers ``devices`` from the client it is about to
        # spawn and then drops the first ``shell`` while the daemon finishes
        # starting, so one attempt reports a device that is plainly there as
        # "did not answer".  The retry is not a workaround for a wrong address:
        # it costs nothing when the server is already warm and it is the only
        # thing that makes a just-launched emulator connectable.
        for i in range(attempts):
            r = _run(adb, ["-s", candidate, "shell", "echo ok"], port_,
                     timeout + i * 10)
            if r and r.returncode == 0 and "ok" in (r.stdout or ""):
                return True
            if i + 1 < attempts:
                time.sleep(1.0 + i)
        return False

    # Bring the server up once, up front.  ``adb devices`` is the cheapest call
    # that spawns it, and doing it here keeps the spawn out of the ``shell``
    # attempt above.
    _run(adb, ["start-server"], port, timeout)

    if serial:
        if ":" in serial:
            _run(adb, ["connect", serial], port, timeout)
        if not usable(serial, port):
            raise DeployError(
                f"{serial} did not answer. Check the emulator is running and that "
                f"the port is the one adb is listening on (MuMu usually uses "
                f"127.0.0.1:16384 with the server on 5038).")
        dev = Device(adb, serial, port)
        dev.su("true")
        return dev

    tried = []
    # Real answers first: whatever the server already knows about.
    for candidate, state in devices(adb, port):
        if state != "device":
            tried.append(f"{candidate} ({state})")
            continue
        if usable(candidate, port):
            dev = Device(adb, candidate, port)
            dev.su("true")
            return dev
        tried.append(f"{candidate}@{port or 'default'}")

    for server_port in ([port] if port else PORTS):
        for guess in SERIALS:
            if ":" in guess:
                _run(adb, ["connect", guess], server_port, timeout)
            if usable(guess, server_port):
                dev = Device(adb, guess, server_port)
                dev.su("true")
                return dev
            tried.append(f"{guess}@{server_port}")
    raise DeployError(
        "no device answered (" + ", ".join(tried) + "). Start the emulator, or "
        "type its address on the Deploy tab (adb connect host:port).")


def probe(adb_path: str = "", *, serial: str = "", port: str = "") -> dict:
    """Non-raising connection report for the UI.

    ``port`` in the answer is the one that actually worked, which is not always
    the one that was asked for: the Deploy tab saves this value back into
    ``settings.ini``, so echoing a port that was silently ignored would keep the
    next session starting from the same dead setting.
    """
    adb = adb_path or find_adb()
    try:
        dev = connect(adb, serial=serial, port=port)
    except DeployError as exc:
        return {"ok": False, "error": str(exc), "adb": adb,
                "devices": devices(adb, port)}
    model = dev.sh("getprop ro.product.model").stdout.strip()
    return {"ok": True, "adb": dev.adb, "serial": dev.serial,
            "port": effective_port(dev.port), "model": model,
            "root": dev.is_root(),
            "devices": devices(dev.adb, effective_port(dev.port))}


# ---------------------------------------------------------------- push plans
def plan_replace(root: str, name: str, files: dict) -> list:
    """``[(local, remote_rel, lock)]`` for replacing files of an existing car.

    ``files`` maps ``"A"``/``"shared"``/``"wing_banim"``/... to local paths.
    """
    out = []
    for key, local in files.items():
        if not local:
            continue
        if key == "wing_banim":
            remote = f".depot/vehicles/{name}/{name}_wing.banim"
        elif key == "animations":
            remote = f".depot/vehicles/{name}/{name}_animations.xml"
        elif key == "points":
            remote = f".depot/vehicles/{name}/{name}.points"
        elif key == "int_points":
            remote = f".depot/vehicles/{name}/{name}_int.points"
        elif key == "dashplanes":
            remote = f".depot/vehicles/{name}/{name}.dashplanes"
        else:
            remote = f".depot/vehicles/{name}/{name}_{key.lower()}.m3g"
        out.append((local, remote, False))
    return out


def plan_gfx(gfx_written: dict) -> list:
    """``[(local, remote_rel, lock)]`` for a graphics profile.

    The engine reads ``.depot/eds/AndroidHigh.plist`` and
    ``.depot/feats/AndroidHigh.feats``; the copies under ``apk/res`` are only
    the unpacked source and are ignored at start-up, so they are not touched.
    """
    out = []
    for kind, rel in (("plist", "eds/AndroidHigh.plist"),
                      ("feats", "feats/AndroidHigh.feats")):
        item = gfx_written.get(kind)
        if not item:
            continue
        out.append((item["path"], f".depot/{rel}", False))
    return out


def plan_manifests(root: str, name: str) -> list:
    """The manifest files that must follow any content change."""
    out = [
        (os.path.join(root, ".depot", "asset_list_base.txtCache.txt"),
         ".depot/asset_list_base.txtCache.txt", False),
        (os.path.join(root, "apk", "res", "asset_list_vehicle_data.txt"),
         "apk/res/asset_list_vehicle_data.txt", True),
    ]
    car = os.path.join(root, "apk", "res", f"asset_list_vehicle_{name}.txt")
    if os.path.isfile(car):
        out.append((car, f"apk/res/asset_list_vehicle_{name}.txt", True))
    return out


#: Files the engine treats as a whole-table database.  Pushing a stale copy of
#: one of these silently reverts every row it holds - a car installed on the
#: device disappears from ``cardesc`` and nothing in the log says so.
TABLES = ("cardesc.list.nct", "suspensionbehaviour.suspensiondata.nct",
          "cardamagethresholds.damage.nct", "carappearances.appearances.nct",
          "carupgrade.upgrades.nct", "carparts.parts.nct",
          "carrepairs.repairs.nct", "default.liveries.bin.nct",
          "liveryStringTable.bin.nct")

#: Tables whose rows are keyed by car id, so the rows themselves can be
#: compared instead of guessing from the file size.
_ID_TABLES = ("cardesc.list.nct", "carappearances.appearances.nct")

_REMOTE_CACHE: dict = {}


def _remote_bytes(dev: Device, remote_rel: str) -> bytes:
    """Pull a device file once per run; empty when it is not there."""
    key = (getattr(dev, "serial", ""), remote_rel)
    if key in _REMOTE_CACHE:
        return _REMOTE_CACHE[key]
    folder = os.path.join(tempfile.gettempdir(), "rrmod_check")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, os.path.basename(remote_rel))
    if os.path.isfile(path):
        os.remove(path)
    r = dev.run("pull", f"{DEV}/{remote_rel}", path)
    blob = b""
    if r.returncode == 0 and os.path.isfile(path):
        with open(path, "rb") as fh:
            blob = fh.read()
    _REMOTE_CACHE[key] = blob
    return blob


def _table_ids(name: str, blob: bytes):
    """The car ids a table holds, or ``None`` when we cannot read it."""
    if not blob:
        return None
    try:
        plain = nctlib.crypt(blob) if nctlib.looks_encrypted(blob) else blob
        if name == "cardesc.list.nct":
            return set(speclib.parse_cardesc(plain).ids())
        if name == "carappearances.appearances.nct":
            _count, recs = applib.parse(plain)
            return {r.id for r in recs}
    except Exception:
        return None
    return None


def check_table(local: str, remote_rel: str, dev: Device, *,
                allow_shrink: bool = False) -> None:
    """Refuse to push a table that would lose rows the device already has.

    Size alone is not enough: a working copy built from the *local* depot had a
    bigger ``cardesc.list.nct`` than the device's yet still lacked the car that
    had been installed on the device, because one row was longer.  So for the
    id-keyed tables both sides are parsed and the id sets compared; the size test
    stays as the fallback for the tables we cannot decode here.
    """
    name = os.path.basename(local)
    if name not in TABLES:
        return
    remote = _remote_bytes(dev, remote_rel)
    if not remote:
        return                      # not on the device yet - nothing to lose
    if name in _ID_TABLES and not allow_shrink:
        theirs = _table_ids(name, remote)
        with open(local, "rb") as fh:
            ours = _table_ids(name, fh.read())
        if theirs and ours is not None:
            lost = sorted(theirs - ours)
            if lost:
                raise DeployError(
                    f"refusing to push {name}: it is missing {len(lost)} id(s) the "
                    f"device has ({', '.join(str(i) for i in lost[:8])}"
                    f"{'...' if len(lost) > 8 else ''}). The local copy is older "
                    f"than the device, so pushing it would drop those rows and the "
                    f"cars would vanish from the game. Rebuild the working copy "
                    f"from the device's own tables before editing them.")
            return
    if len(remote) > os.path.getsize(local) and not allow_shrink:
        raise DeployError(
            f"refusing to push {name}: local copy is {os.path.getsize(local)} "
            f"bytes but the device has {len(remote)}. The local copy is older than "
            f"the device, so pushing it would drop rows. Rebuild the working copy "
            f"from the device's own tables before editing them.")


#: The text tables are parallel arrays: line *n* of ``gametext.txt`` is a key and
#: line *n* of every ``text_<lang>.txt`` is that key's translation.  Pushing a
#: copy with fewer lines than the device has therefore does not delete a name -
#: it shifts every name below the gap onto the wrong key, and the showroom shows
#: one car's name on another.  The manager only ever edits a line in place, so a
#: device copy with *more* lines means another tool added keys here first.
def check_texts(local: str, remote_rel: str, dev: Device) -> None:
    """Refuse to push a text table that has fewer lines than the device's."""
    leaf = os.path.basename(remote_rel)
    if leaf != textlib.GAMETEXT and not re.fullmatch(r"text_[\w\-]+\.txt", leaf):
        return
    r = dev.su(f"wc -l {_quote(f'{DEV}/{remote_rel}')}")
    bits = (r.stdout or "").split()
    if not bits or not bits[0].isdigit():
        return                      # not on the device yet, or unreadable
    theirs = int(bits[0])
    with open(local, "rb") as fh:
        # ``wc -l`` counts newline characters, and the files use CRLF, so the
        # number of ``\n`` is the number ``wc -l`` reports.
        ours = fh.read().count(b"\n")
    if theirs > ours:
        raise DeployError(
            f"refusing to push {leaf}: the device has {theirs} lines and the local "
            f"copy has {ours}. The text tables are parallel arrays, so a shorter "
            f"copy moves every later name onto the wrong key. Load the text tables "
            f"from the device before editing them.")


#: The career file is not one of the small tables above - it is a 14 MB tree with
#: every series, tier and event in the game.  Pushing a copy built from the local
#: depot would silently delete any series added on the device, which is exactly
#: how a working copy built offline loses other people's work.
CAREER_REL = ".depot/data/events.dat.nct"


def _career_ids(blob: bytes):
    """``(series ids, event ids)`` in a career file, or ``None``."""
    if not blob:
        return None
    try:
        plain = nctlib.crypt(blob) if nctlib.looks_encrypted(blob) else blob
        career = careerlib.parse(plain)
        events = {e.id for t in career.tiers for e in t.events}
        return {s.id for s in career.series}, events
    except Exception:
        return None


def check_career(local: str, remote_rel: str, dev: Device, *,
                 allow_shrink: bool = False) -> None:
    """Refuse to push a career file that would lose series or events.

    The career file cannot be merged row by row the way the car tables can - the
    menu pages, the tier list and the text keys all have to agree - so the only
    safe rule is: whatever the device has, the new file must still have.
    """
    if not remote_rel.endswith("events.dat.nct"):
        return
    remote = _remote_bytes(dev, remote_rel)
    if not remote:
        return                      # not on the device yet - nothing to lose
    if allow_shrink:
        return
    theirs = _career_ids(remote)
    if not theirs:
        return
    with open(local, "rb") as fh:
        ours = _career_ids(fh.read())
    if not ours:
        raise DeployError(
            "refusing to push events.dat.nct: the local copy could not be read "
            "back, so there is no way to tell what it would drop.")
    lost_series = sorted(theirs[0] - ours[0])
    lost_events = sorted(theirs[1] - ours[1])
    if lost_series or lost_events:
        bits = []
        if lost_series:
            bits.append(f"{len(lost_series)} series ({', '.join(str(i) for i in lost_series[:8])}"
                        f"{'...' if len(lost_series) > 8 else ''})")
        if lost_events:
            bits.append(f"{len(lost_events)} event(s)")
        raise DeployError(
            f"refusing to push events.dat.nct: it is missing {' and '.join(bits)} "
            f"that the device has. The local copy is older than the device, so "
            f"pushing it would delete those series and the career screen would "
            f"change. Load the career from the device before editing it.")


def deploy_files(dev: Device, items, *, log=print,
                 allow_shrink: bool = False) -> dict:
    """Push ``[(local, remote_rel, lock)]`` in order, stopping on the first error.

    ``allow_shrink`` is for a *deliberate* rollback: the size guard exists to
    catch a working copy that is older than the device, and a revert looks
    exactly like that from the outside.  Only a caller that knows it is undoing
    an edit should set it.
    """
    done = []
    for local, remote, lock in items:
        if not os.path.isfile(local):
            raise DeployError(f"missing local file: {local}")
        check_table(local, remote, dev, allow_shrink=allow_shrink)
        check_career(local, remote, dev)
        check_texts(local, remote, dev)
        # relpath would raise across drives - the depot can sit on E: while the
        # merged manifests are staged under the workspace on C:
        log(f"  push {os.path.basename(local)} -> {remote}")
        done.append(dev.push(local, remote, lock=lock))
    return {"pushed": len(done), "items": done}


# ------------------------------------------------------------ manifest merge
REGISTRY_REL = ".depot/asset_list_base.txtCache.txt"
DATA_LIST_REL = "apk/res/asset_list_vehicle_data.txt"


def _pull_bytes(dev: Device, remote_rel: str, local: str) -> bytes:
    """Read a device file into ``local``; empty bytes when it is not there."""
    # os.devnull is not a regular file on Windows, so pulling into it would fail
    # the isfile() test below and look exactly like "the device has no such
    # file".  That silently disabled the whole manifest merge once, so refuse it.
    if os.path.abspath(local) == os.path.abspath(os.devnull):
        raise ValueError("_pull_bytes needs a real file target, not os.devnull")
    os.makedirs(os.path.dirname(os.path.abspath(local)), exist_ok=True)
    # A copy left over from an earlier pull would pass the isfile() test below
    # and be mistaken for what the device holds, so clear it first.
    if os.path.isfile(local):
        os.remove(local)
    r = dev.run("pull", f"{DEV}/{remote_rel}", local)
    if r.returncode != 0 or not os.path.isfile(local):
        return b""
    with open(local, "rb") as fh:
        return fh.read()


def _touched_names(items) -> set:
    """Car folders the plan writes into, ignoring the shared folders."""
    out = set()
    for _local, remote, _lock in items:
        if not remote.startswith(".depot/vehicles/"):
            continue
        rest = remote[len(".depot/vehicles/"):]
        if "/" not in rest:
            continue
        name = rest.split("/", 1)[0]
        if name not in ("data", "common", "decals", "shaders", "wheels"):
            out.add(name)
    return out


def _writable(path: str) -> bool:
    """True when we can actually create and delete a folder under ``path``."""
    probe = os.path.join(path, "_write_test")
    try:
        os.makedirs(probe, exist_ok=True)
    except OSError:
        return False
    try:
        os.rmdir(probe)
    except OSError:
        pass
    return True


def staging_dir(root: str) -> str:
    """A writable place to build merged manifests for this install.

    The depot is often read only on purpose - it is the pristine copy the user
    keeps for reference - so the merge output cannot live inside it.  Prefer the
    backup folder beside it, then the system temp folder, then ``./work``.
    """
    tag = hashlib.md5(os.path.abspath(root).encode("utf-8")).hexdigest()[:10]
    candidates = [
        os.path.join(root, "_rrmod_backup", "_merge"),
        os.path.join(tempfile.gettempdir(), "rrmod_merge", tag),
        os.path.join(os.getcwd(), "work", "rrmod_merge", tag),
    ]
    for cand in candidates:
        if _writable(os.path.dirname(cand)) or _writable(cand):
            return cand
    raise DeployError("no writable folder for the merged manifests; tried "
                      + ", ".join(candidates))


def merge_manifests(dev: Device, root: str, items, *, dest: str = "", log=print) -> dict:
    """Fold this plan into the *device's* manifests instead of overwriting them.

    The depot on the device can be newer than the copy on disk - another tool may
    have installed a car, or the game may have refreshed a table - so the manifest
    on disk is not authoritative and pushing it over the top silently deletes
    whatever the device knew that the disk does not.  The device copy is the base;
    only the paths in ``items`` get their hashes rewritten, and paths it does not
    have yet are appended.

    Returns ``{"items": [...], "report": {...}}`` where the manifest entries of
    ``items`` have been replaced by the merged files in ``dest``.
    """
    from rr3lib import manifest as manifestlib

    dest = dest or staging_dir(root)
    os.makedirs(dest, exist_ok=True)
    content = [(l, r, k) for l, r, k in items if not _is_manifest(r)]
    report = {"registry": {}, "data_list": {}, "car_lists": {}, "dest": dest}

    # ---- registry ----------------------------------------------------
    base = _pull_bytes(dev, REGISTRY_REL, os.path.join(dest, "device_registry.txt"))
    if base:
        reg = manifestlib.parse_registry(base)
        before = len(reg)
        changed = added = 0
        for local, remote, _lock in content:
            if not remote.startswith(".depot/"):
                continue
            path = "/" + remote[len(".depot/"):]
            md5 = manifestlib.md5_file(local)
            if path not in reg.entries:
                added += 1
            if reg.set(path, md5):
                changed += 1
        out = os.path.join(dest, "asset_list_base.txtCache.txt")
        manifestlib.save_registry(reg, out)
        report["registry"] = {"base": before, "changed": changed,
                              "added": added, "rows": len(reg), "merged": out}
        log(f"  registry: device had {before}, {changed} rewritten "
            f"({added} new), merged {len(reg)}")
    else:
        # No device copy to merge with - fall back to the disk manifest and say so.
        disk = os.path.join(root, ".depot", "asset_list_base.txtCache.txt")
        if os.path.isfile(disk):
            out = os.path.join(dest, "asset_list_base.txtCache.txt")
            with open(disk, "rb") as fh:
                blob = fh.read()
            with open(out, "wb") as fh:
                fh.write(blob)
            report["registry"] = {"base": 0, "changed": 0, "added": 0,
                                  "merged": out, "warning": "device had no registry"}
            log("  registry: device had none, using the disk copy")
        else:
            out = ""

    # ---- vehicle data list -------------------------------------------
    data_items = [(l, r) for l, r, _k in content
                  if r.startswith(".depot/vehicles/data/")]
    out_data = ""
    if data_items:
        base = _pull_bytes(dev, DATA_LIST_REL, os.path.join(dest, "device_data_list.txt"))
        if base:
            rows = manifestlib.parse_data_list(base).rows
            index = {r[0]: i for i, r in enumerate(rows)}
            changed = added = 0
            for local, remote in data_items:
                path = "/" + remote[len(".depot/"):]
                n = os.path.getsize(local)
                row = (path, manifestlib.md5_file(local), n, n)
                if path in index:
                    if rows[index[path]] != row:
                        rows[index[path]] = row
                        changed += 1
                else:
                    rows.append(row)
                    index[path] = len(rows) - 1
                    added += 1
            out_data = os.path.join(dest, "asset_list_vehicle_data.txt")
            blob = ("\n".join(f"{p}\t{m}\t{pk}\t{r}" for p, m, pk, r in rows) + "\n")
            with open(out_data, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(blob)
            report["data_list"] = {"base": len(index) - added, "changed": changed,
                                   "added": added, "rows": len(rows), "merged": out_data}
            log(f"  data list: {changed} rewritten, {added} new")
        else:
            disk = os.path.join(root, "apk", "res", "asset_list_vehicle_data.txt")
            if os.path.isfile(disk):
                out_data = os.path.join(dest, "asset_list_vehicle_data.txt")
                with open(disk, "rb") as fh:
                    blob = fh.read()
                with open(out_data, "wb") as fh:
                    fh.write(blob)
                report["data_list"] = {"base": 0, "changed": 0, "added": 0,
                                       "merged": out_data,
                                       "warning": "device had no data list"}
                log("  data list: device had none, using the disk copy")

    # ---- per car manifests -------------------------------------------
    # Rows are only rewritten for files this plan pushes.  Everything else keeps
    # whatever the device already says: the device copy knows about cars this
    # depot has never seen, and the disk copy must not overwrite that.
    car_out = []
    for name in sorted(_touched_names(content)):
        rel = f"apk/res/asset_list_vehicle_{name}.txt"
        base = _pull_bytes(dev, rel, os.path.join(dest, f"device_car_{name}.txt"))
        disk = os.path.join(root, "apk", "res", f"asset_list_vehicle_{name}.txt")
        pushed = {"/" + r[len(".depot/"):]: l for l, r, _k in content
                  if r.startswith(f".depot/vehicles/{name}/")}
        if not pushed:
            continue
        if base:
            rows = manifestlib.parse_data_list(base).rows
            index = {r[0]: i for i, r in enumerate(rows)}
        else:
            rows, index = [], {}
        # A row whose packed size differs from its raw size refers to the
        # compressed form of the file, which we cannot reproduce (the packer is
        # unknown).  Declaring the file as stored raw - packed == raw == size,
        # md5 of the bytes on disk - is what the game already accepts for the
        # .banim/.xml rows it was given, so use that form for what we push.
        changed = added = 0
        for path, local in pushed.items():
            n = os.path.getsize(local)
            row = (path, manifestlib.md5_file(local), n, n)
            if path in index:
                if rows[index[path]] != row:
                    rows[index[path]] = row
                    changed += 1
            else:
                rows.append(row)
                index[path] = len(rows) - 1
                added += 1
        for path, md5, packed, raw in manifestlib.read_car_manifest(disk):
            if path in pushed or path in index:
                continue
            rows.append((path, md5, packed, raw))
            index[path] = len(rows) - 1
            added += 1
        out_car = os.path.join(dest, f"asset_list_vehicle_{name}.txt")
        with open(out_car, "w", encoding="utf-8", newline="\n") as fh:
            for p, m, pk, r in rows:
                fh.write(f"{p}\t{m}\t{pk}\t{r}\n")
        car_out.append((out_car, rel, True))
        report["car_lists"][name] = {"changed": changed, "added": added, "rows": len(rows)}
        log(f"  {name}: {changed} rows rewritten, {added} new")

    merged = list(content)
    if out:
        merged.append((out, REGISTRY_REL, False))
    if out_data:
        merged.append((out_data, DATA_LIST_REL, True))
    merged.extend(car_out)
    # ---- every other asset list ---------------------------------------
    # A logo page is claimed by ``asset_list_gui_assets_core.txt``, a common
    # texture by ``asset_list_vehicle_common.txt``, a shader by
    # ``asset_list_vehicle_shaders.txt``.  None of those is the registry or the
    # vehicle data list, so before this they were never rewritten and the engine
    # saw a file on disk that no list mentioned - which it answers with a
    # download.  Each one is merged from the device's own copy, exactly like the
    # two above: only the rows this plan pushes are rewritten.
    extra, extra_report = _other_lists(
        dev, root, content, dest,
        covered={REGISTRY_REL, DATA_LIST_REL} | {rel for _o, rel, _k in car_out},
        log=log)
    merged.extend(extra)
    report["other_lists"] = extra_report
    return {"items": merged, "report": report}


def _other_lists(dev: Device, root: str, content, dest: str, *, covered, log=print):
    """Merge the plan into every remaining asset list that claims a pushed path.

    Returns ``(items, report)``.  ``covered`` names the lists already handled by
    the caller so nothing is written twice.
    """
    from rr3lib import manifest as manifestlib

    # Which leaf owns each pushed path.  One index build covers the whole plan.
    wanted: dict[str, list] = {}
    try:
        index = manifestlib.asset_index(root)
    except manifestlib.ManifestError as exc:
        log(f"  other lists: {exc}")
        return [], {}
    for local, remote, lock in content:
        if not remote.startswith(".depot/"):
            continue
        path = "/" + remote[len(".depot/"):]
        # ``list_for`` and not ``owner_of``: a page this install *creates* has no
        # row anywhere yet, so ``owner_of`` answers "" and the file would be
        # pushed without a manifest row - which the engine answers with a
        # download error.  ``list_for`` files a new path where its neighbours
        # already live, which is what makes a brand-new ``vehicles/common`` page
        # land in ``asset_list_vehicle_common.txt``.
        leaf = index.list_for(path)
        if not leaf or f"apk/res/{leaf}" in covered:
            continue
        wanted.setdefault(leaf, []).append((path, local, lock))

    items, report = [], {}
    for leaf in sorted(wanted):
        rel = f"apk/res/{leaf}"
        rows = wanted[leaf]
        base = _pull_bytes(dev, rel, os.path.join(dest, f"device_{leaf}"))
        if base:
            al = manifestlib.parse_asset_list(leaf, base)
            before = len(al)
        else:
            disk = manifestlib.asset_list_path(root, leaf)
            if not os.path.isfile(disk):
                log(f"  {leaf}: neither the device nor the disk has it, skipped")
                continue
            al = manifestlib.load_asset_list(root, leaf)
            before = 0
            log(f"  {leaf}: device had none, using the disk copy")
        changed = added = 0
        for path, local, _lock in rows:
            n = os.path.getsize(local)
            row = (path, manifestlib.md5_file(local), n, n)
            got = al.get(path)
            if got is None:
                al.insert(path, row[1], n, n)
                added += 1
            elif got != row:
                al.update(path, row[1], n, n)
                changed += 1
        out = os.path.join(dest, leaf)
        manifestlib.save_asset_list(al, out)
        lock = any(k for _p, _l, k in rows)
        items.append((out, rel, lock))
        report[leaf] = {"base": before, "changed": changed, "added": added,
                        "rows": len(al)}
        log(f"  {leaf}: {changed} rewritten, {added} new, {len(al)} rows")
    return items, report


def _is_manifest(remote_rel: str) -> bool:
    return (remote_rel == REGISTRY_REL or remote_rel == DATA_LIST_REL
            or (remote_rel.startswith("apk/res/asset_list")
                and remote_rel.endswith(".txt")))


def following_manifests(items, *, root: str = "") -> list:
    """The asset lists a push of ``items`` will rewrite, as remote paths.

    Nothing is generated here - this answers "what else moves?" for the plan
    list.  :func:`merge_manifests` does the work during Push, onto the device's
    own copies; the point of naming them up front is that a plan of three model
    files looks like the lists were left behind when they were not.

    ``root`` is the install or working copy the asset index is read from.  Without
    it only the three lists this module names by hand can be reported, which is
    what the plan showed before a logo page turned out to need a fourth.
    """
    from rr3lib import manifest as manifestlib

    items = [(l, r, k) for l, r, k in items if not _is_manifest(r)]
    if not items:
        return []
    out = []
    if any(r.startswith(".depot/") for _l, r, _k in items):
        out.append(REGISTRY_REL)
    if any(r.startswith(".depot/vehicles/data/") for _l, r, _k in items):
        out.append(DATA_LIST_REL)
    covered = {REGISTRY_REL, DATA_LIST_REL}
    for name in sorted(_touched_names(items)):
        out.append(f"apk/res/asset_list_vehicle_{name}.txt")
        covered.add(f"apk/res/asset_list_vehicle_{name}.txt")
    if root:
        try:
            index = manifestlib.asset_index(root)
        except manifestlib.ManifestError:
            index = None
        if index is not None:
            extra = set()
            for _local, remote, _lock in items:
                if not remote.startswith(".depot/"):
                    continue
                leaf = index.owner_of("/" + remote[len(".depot/"):])
                if leaf and f"apk/res/{leaf}" not in covered:
                    extra.add(f"apk/res/{leaf}")
            out.extend(sorted(extra))
    return out


#: Lists whose rows are the engine's shopping list.  They live in ``apk/res`` and
#: are all named ``asset_list_*.txt``; the per-car ones are among them.
LIST_GLOB = "asset_list_*.txt"


def _device_paths(dev: Device, sub: str = ".depot") -> set:
    """Every file the device has under ``sub``, as ``/vehicles/...`` style paths."""
    r = dev.su(f"find {_quote(f'{DEV}/{sub}')} -type f")
    root = f"{DEV}/{sub}/"
    return {"/" + line[len(root):] for line in (r.stdout or "").splitlines()
            if line.startswith(root)}


def _device_lists(dev: Device, dest: str) -> dict:
    """``{list name: [(path, md5), ...]}`` for every list the device holds.

    Pulling ``apk/res`` whole is 50 MB for the sake of 13 MB of text, so the
    lists are copied to a scratch folder on the device and collected from there.
    ``adb pull`` has no glob and 1,237 round trips would be slower than the copy.

    What comes back is a **tar**, not a folder.  ``adb pull`` of a directory
    fails part way through when the destination path has non-ASCII characters
    (``cannot create 'E:/...数据包.../rrmod_lists/x.txt': Not a directory``),
    and a Chinese install path is the normal case here - so the device packs the
    lists and the archive is read on this side, where one file always arrives.
    Before this the whole reconcile step raised, the push reported it as a
    swallowed error, and the registry was never re-made after a deploy.
    """
    tmp = "/sdcard/rrmod_lists"
    os.makedirs(dest, exist_ok=True)
    archive = os.path.join(dest, "lists.tar")
    if os.path.isfile(archive):
        os.remove(archive)
    dev.sh(f"rm -rf {tmp}; mkdir -p {tmp}; "
           f"cp {DEV}/apk/res/{LIST_GLOB} {tmp}/ && "
           f"cd {tmp} && tar -cf {tmp}/lists.tar {LIST_GLOB}")
    r = dev.run("pull", f"{tmp}/lists.tar", archive)
    dev.sh(f"rm -rf {tmp}")
    if r.returncode != 0 or not os.path.isfile(archive):
        raise DeployError(
            f"could not read the device's asset lists\n{(r.stderr or '')[:400]}")
    out = {}
    with tarfile.open(archive) as tf:
        for member in tf.getmembers():
            leaf = os.path.basename(member.name)
            if not member.isfile() or not (leaf.startswith("asset_list_")
                                           and leaf.endswith(".txt")):
                continue
            handle = tf.extractfile(member)
            blob = handle.read() if handle else b""
            rows = []
            for line in blob.decode("utf-8", "replace").split("\n"):
                parts = line.split("\t")
                if len(parts) >= 2 and parts[0].startswith("/"):
                    rows.append((parts[0], parts[1]))
            out[leaf] = rows
    return out


def ensure_data_list(dev: Device, root: str, *, dest: str = "", log=print) -> dict:
    """Make sure the device's ``asset_list_vehicle_data.txt`` mentions every data
    file the local install owns.

    ``asset_list_vehicle_data.txt`` is the one manifest the engine rewrites
    behind our back: when it finds a row it cannot resolve it discards the list
    and re-extracts the bundled copy out of ``res.zip`` - which knows nothing
    about a car we added.  That is what happened on 2026-11-16: the list on the
    device went back to its 1,137 vanilla rows while the spec and livery of the
    new car stayed in the depot, unlisted.

    Rows the device already has are left exactly as they are.  Their md5 is the
    engine's own packer output, which cannot be recomputed, and the only rule the
    engine enforces is that this list and the registry agree - which
    :func:`reconcile_registry` then guarantees.  So the only safe edit is to
    append the rows for files that no row mentions yet.
    """
    from rr3lib import manifest as manifestlib

    dest = dest or staging_dir(root)
    os.makedirs(dest, exist_ok=True)
    local_path = os.path.join(root, "apk", "res", "asset_list_vehicle_data.txt")
    if not os.path.isfile(local_path):
        return {"error": "no local vehicle data list"}
    with open(local_path, "rb") as fh:
        local_rows = manifestlib.parse_data_list(fh.read()).rows

    base = _pull_bytes(dev, DATA_LIST_REL, os.path.join(dest, "device_data_list.txt"))
    if base:
        rows = manifestlib.parse_data_list(base).rows
    else:
        rows = []
    have = {r[0] for r in rows}

    files = _device_paths(dev)
    added = []
    for path, md5, packed, raw in local_rows:
        if path in have or path not in files:
            continue
        rows.append((path, md5, packed, raw))
        have.add(path)
        added.append(path)

    report = {"before": len(have) - len(added), "added": len(added),
              "rows": len(rows), "paths": added}
    for path in added:
        log(f"    + {path}")
    if not added:
        log("  data list: every data file we own is already listed")
        return report

    out = os.path.join(dest, "asset_list_vehicle_data.txt")
    with open(out, "w", encoding="utf-8", newline="\n") as fh:
        for p, m, pk, r in rows:
            fh.write(f"{p}\t{m}\t{pk}\t{r}\n")
    dev.push(out, DATA_LIST_REL, lock=True)
    log(f"  data list: {len(added)} row(s) added, {len(rows)} total, pushed")
    return report


def reconcile_registry(dev: Device, root: str, *, dest: str = "", log=print) -> dict:
    """Make the registry agree with the asset lists the device actually holds.

    The engine never hashes a file.  For every row of an ``asset_list_*.txt`` it
    looks the path up in ``.depot/asset_list_base.txtCache.txt`` and calls the
    asset *current* only when the two md5s are equal; anything else is queued for
    download, and with the service dead one queued byte is a fatal
    ``ASSET DOWNLOAD ERROR`` at the next launch.  So the registry is not a cache
    of what is on disk - it is a promise that must match the lists, row for row.

    Two things keep breaking that promise and neither is under our control:

    * ``apk/res/asset_list_vehicle_data.txt`` ships inside ``res.zip`` and the
      engine unpacks it over whatever we pushed **on every launch**.  Measured
      2026-11-16: after a restart the device copy's mtime is the boot time and
      its md5 is the one inside ``res.zip``.  ``chmod 444`` does not stop it -
      the app owns the folder, so it can unlink and recreate the file, which is
      why the doc's 444 recipe held on Android 12 but not here.
    * the engine prunes registry rows it decides are stale, so a disagreement
      erodes the registry instead of repairing itself.

    The net effect of one restart was five rows under ``/vehicles/data`` gone and
    the four tables we had edited queued for download on every boot.

    What is durable is "whatever the lists on the device say".  This walks all of
    them, rewrites the registry to the md5 each list demands for every file that
    really is present, and drops rows for files that are gone.
    """
    from rr3lib import manifest as manifestlib

    dest = dest or staging_dir(root)
    os.makedirs(dest, exist_ok=True)
    base = _pull_bytes(dev, REGISTRY_REL, os.path.join(dest, "device_registry.txt"))
    if not base:
        return {"error": "the device has no registry to reconcile"}
    reg = manifestlib.parse_registry(base)
    before = len(reg)

    files = _device_paths(dev)
    lists = _device_lists(dev, dest)
    log(f"  reconcile: {len(files)} files, {len(lists)} lists, {before} rows")

    fixed, absent = [], []
    for leaf, rows in lists.items():
        for path, want in rows:
            if path not in files:
                absent.append((leaf, path))
                continue
            have = reg.get(path)
            if have != want:
                fixed.append((leaf, path, want, have))
                reg.set(path, want)

    ghosts = [p for p in reg.entries if p not in files]
    for p in ghosts:
        reg.remove(p)

    out = os.path.join(dest, "asset_list_base.txtCache.txt")
    size = manifestlib.save_registry(reg, out)
    report = {"before": before, "rows": len(reg), "size": size, "path": out,
              "fixed": fixed, "ghosts": ghosts, "absent": len(absent)}
    for leaf, path, want, have in fixed:
        log(f"    {leaf}: {path}  {str(have)[:8]} -> {want[:8]}")
    for p in ghosts:
        log(f"    dropped ghost row {p}")
    log(f"  reconcile: {len(fixed)} rows corrected, {len(ghosts)} dropped, "
        f"{before} -> {len(reg)}")

    if fixed or ghosts:
        dev.push(out, REGISTRY_REL, lock=False)
        log("  reconcile: registry pushed")
    else:
        log("  reconcile: registry already agrees with the lists")
    return report


def verify_remote(dev: Device, root: str, name: str) -> list:
    """Compare every file of one car on the device against the local copy.

    Two things this used to get wrong, and both turned the report into noise
    nobody reads:

    * It listed the car folder **without recursing**, so everything under
      ``livery/`` - the paint pages - was reported missing on every deploy even
      though it had just been pushed.
    * It did not skip the profile variants.  A manifest lists one row per GPU
      family (``.dxt.dds.z`` here, ``.atc``/``.etc``/``.ptc`` for Adreno,
      PowerVR and the rest) while a depot only ships the one its build targets,
      so the donor itself looks "incomplete" by that measure - 84 rows against
      31 files.

    What is left is the only question worth asking: a file this build says it
    ships is not where the engine will look for it.
    """
    from rr3lib import manifest as manifestlib

    problems = []
    car_manifest = os.path.join(root, "apk", "res", f"asset_list_vehicle_{name}.txt")
    if not os.path.isfile(car_manifest):
        return [f"no local manifest for {name}"]
    rows = manifestlib.read_car_manifest(car_manifest)
    wanted = []
    for p, *_ in rows:
        if not p.startswith(f"/vehicles/{name}/"):
            continue
        if any(tag in p.lower() for tag in (".atc.", ".etc.", ".ptc.")):
            continue
        wanted.append(p)
    r = dev.su("ls -lR " + _quote(f"{DEV}/.depot/vehicles/{name}"))
    base = f"{DEV}/.depot/vehicles/{name}"
    remote = set()
    folder = ""
    for line in (r.stdout or "").splitlines():
        stripped = line.rstrip()
        if stripped.endswith(":"):
            folder = stripped[:-1]
            continue
        bits = stripped.split()
        if len(bits) < 5 or stripped.startswith("total"):
            continue
        # ``ls -lR`` prints a header line per directory; make the entry relative
        # to the car folder so ``livery/x.dxt.dds.z`` compares with the manifest.
        rel = os.path.relpath(os.path.join(folder or base, bits[-1]), base)
        remote.add(rel.replace(os.sep, "/"))
    for p in wanted:
        rel = p[len(f"/vehicles/{name}/"):]
        if rel not in remote:
            problems.append(f"missing on device: {p}")
    return problems


# ------------------------------------------------------------ comparing
def md5_local(path: str) -> str:
    import hashlib

    h = hashlib.md5()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


#: Longest ``su -c`` command worth sending.  The emulator's ``su`` refuses a
#: long argument outright - a 31-file ``md5sum`` batch (4.3 KB of quoted paths)
#: came back empty with exit code 255 while a 20-file one (2.7 KB) answered.
#: That empty answer used to be read as "the device has none of these files", so
#: a car's whole folder was reported missing on every compare however often it
#: had just been pushed: the two ends never agreed.  A batch is therefore bounded
#: by the length of the command, not by the number of paths.
MAX_CMD = 1500


def _md5_batch(dev: Device, rels) -> dict:
    """One ``md5sum`` call; the answer keyed by install-relative path."""
    cmd = "md5sum " + " ".join(_quote(f"{DEV}/{r}") for r in rels)
    r = dev.su(cmd)
    out = {}
    prefix = f"{DEV}/"
    for line in (r.stdout or "").splitlines():
        bits = line.split()
        if len(bits) < 2 or len(bits[0]) != 32:
            continue
        path = bits[-1]
        if path.startswith(prefix):
            path = path[len(prefix):]
        out[path.replace("\\", "/")] = bits[0].lower()
    return out


def remote_md5(dev: Device, rels, *, chunk: int = 40, log=print) -> dict:
    """``{install-relative path: md5}`` for what the device really holds.

    One ``md5sum`` call per batch instead of one per file: a car is a hundred
    files and a round trip each turns a two-second check into a minute of
    waiting.  A path the device does not have simply does not come back - which
    is the answer the caller needs anyway ("missing" is a difference).

    Two things are guarded against here, and both of them once made this
    function lie:

    * the batch is capped by :data:`MAX_CMD` as well as by ``chunk``, because a
      command the device refuses answers with nothing at all;
    * a batch of several paths that answers *nothing* is not believed - it is
      retried one path at a time.  Silence from a refused command and silence
      from a folder of missing files look identical from here, and the second is
      what the user saw as "the two ends never match".
    """
    out = {}
    batch, size = [], 0

    def flush() -> None:
        nonlocal batch, size
        if not batch:
            return
        got = _md5_batch(dev, batch)
        if not got and len(batch) > 1:
            log(f"  md5sum refused a batch of {len(batch)}, asking one by one")
            for one in batch:
                got.update(_md5_batch(dev, [one]))
        out.update(got)
        batch, size = [], 0

    for rel in rels:
        rel = str(rel).replace("\\", "/").lstrip("/")
        cost = len(rel) + len(DEV) + 4
        if batch and (size + cost > MAX_CMD or len(batch) >= chunk):
            flush()
        batch.append(rel)
        size += cost
    flush()
    return out


def compare_files(dev: Device, root: str, rels, *, log=print) -> list[dict]:
    """Compare install files against the device, one row per path.

    ``rels`` are install-relative (``.depot/vehicles/<car>/x``).  A row says
    ``state``: ``same``, ``differs``, ``missing`` (device has no such file) or
    ``gone`` (the install no longer has it - not something a push can fix, so it
    is reported and skipped).  Only files that exist locally are compared; a
    local file with no device counterpart is a new asset, and pushing it is
    exactly right.
    """
    rows = []
    wanted = []
    for rel in rels:
        rel = str(rel).replace("\\", "/").lstrip("/")
        local = os.path.join(root, *rel.split("/"))
        if not os.path.isfile(local):
            rows.append({"rel": rel, "local": local, "state": "gone",
                         "local_md5": "", "remote_md5": "",
                         "size": 0})
            continue
        wanted.append((rel, local))
    remote = remote_md5(dev, [rel for rel, _l in wanted], log=log)
    for rel, local in wanted:
        mine = md5_local(local)
        theirs = remote.get(rel, "")
        state = "same" if theirs == mine else ("missing" if not theirs else "differs")
        rows.append({"rel": rel, "local": local, "state": state,
                     "local_md5": mine, "remote_md5": theirs,
                     "size": os.path.getsize(local)})
        if state != "same":
            log(f"  {state}: {rel}")
    return rows


def compare_car(dev: Device, root: str, name: str, *, log=print) -> list[dict]:
    """Every file of one car, plus the tables a car edit can touch.

    The car folder is only half of it.  A **rename** writes nothing inside the
    folder at all: the spec holds a ``CAR_NAME_*`` key and the name itself lives
    in ``gametext.txt`` and the twelve ``text_<lang>.txt``, while the brand lives
    in the spec's make string and its ``CAR_MANUFACTURER_*`` key.  A **build**
    adds a row to ``cardesc`` and one to the appearance table.  Leaving those out
    is why a name changed here never reached the game: the compare listed the car
    as identical, so there was no row to tick and nothing was ever pushed, and
    the showroom kept the old name however many times the rename was repeated.
    """
    car_dir = os.path.join(root, ".depot", "vehicles", name)
    rels = []
    if os.path.isdir(car_dir):
        for base, _dirs, files in os.walk(car_dir):
            for leaf in files:
                rel = os.path.relpath(os.path.join(base, leaf), root)
                rels.append(rel.replace(os.sep, "/"))
    for extra in (f".depot/vehicles/data/liveries/{name}.liveries.bin.nct",
                  f".depot/{speclib.CARDESC}",
                  f".depot/{applib.APPEARANCES}"):
        rels.append(extra)
    # The thirteen text files: a rename rewrites one line in each of them.
    for leaf in (textlib.GAMETEXT,) + tuple(f"text_{lang}.txt"
                                            for lang in textlib.LANGUAGES):
        rels.append(f".depot/{leaf}")
    # The spec is ``<id>_<car>.bin.nct``; the id is not part of the folder name.
    import glob

    for hit in glob.glob(os.path.join(root, ".depot", "vehicles", "data",
                                      f"*_{name}.bin.nct")):
        rel = os.path.relpath(hit, root).replace(os.sep, "/")
        rels.append(rel)
    return compare_files(dev, root, rels, log=log)


def check_log(text: str) -> dict:
    """Summarise a logcat dump against :data:`MARKERS`."""
    hits = {}
    for line in text.splitlines():
        for m in MARKERS:
            if m in line:
                hits.setdefault(m, []).append(line.rstrip())
    return {
        "markers": hits,
        "start_list": len(hits.get("StartListDownload", [])),
        "download_errors": len(hits.get("ASSET DOWNLOAD ERROR", [])),
        "up_to_date": len(hits.get("all files up to date", [])),
        "fatal": len(hits.get("FATAL", [])) + len(hits.get("Fatal signal", [])),
        "ok": not hits.get("ASSET DOWNLOAD ERROR") and not hits.get("FATAL"),
    }


# ------------------------------------------------------------------- restore
def restore_from_reference(dev: Device, reference: str, name: str, *,
                           log=print) -> dict:
    """Put a car's files back from a pristine depot copy."""
    rel = f"vehicles/{name}"
    src = os.path.join(reference, *rel.split("/"))
    if not os.path.isdir(src):
        raise DeployError(f"reference has no {rel}")
    info = dev.push_tree(src, f".depot/{rel}")
    log(f"  restored {name} from {reference}")
    return info
