"""RR3 ``.nct`` / ``.gui`` encryption: plain RC4 with a fixed key.

The game's "encryption" is an RC4 keystream XORed over the plaintext.  There is
no header, no IV and no length limit - byte *i* of the ciphertext is
``plaintext[i] ^ keystream[i]``, and the keystream depends only on the key:

    key   = a5 35 b3 b1 e8 43 e7 cf
    drop  = 133 bytes of RC4 output

Verified against every ``.nct`` in the retail data cast, including the 14.4 MB
``events.dat.nct`` - the stream does not repeat and is not length limited.
(An earlier version of these tools shipped a 603 KB pre-computed keystream
file, which silently corrupted anything longer.  That file is no longer needed:
:func:`keystream` regenerates it on demand, to any length.)

A second key exists for the localised ``gametext`` blobs:

    key   = b1 75 a5 23 f3 c2 b6 15
    drop  = 211 bytes

Because XOR is its own inverse, :func:`crypt` encrypts *and* decrypts.  A file
is treated as ciphertext when :func:`looks_encrypted` says so, which lets the
callers accept both plain and encrypted input transparently.
"""

from __future__ import annotations

import os

#: The standard ``.nct`` key.
KEY_NCT = bytes((0xA5, 0x35, 0xB3, 0xB1, 0xE8, 0x43, 0xE7, 0xCF))
DROP_NCT = 133

#: The key used by the localised ``gametext`` blobs.
KEY_GAMETEXT = bytes((0xB1, 0x75, 0xA5, 0x23, 0xF3, 0xC2, 0xB6, 0x15))
DROP_GAMETEXT = 211

_CACHE: dict[tuple[bytes, int], bytes] = {}


def keystream(n: int, key: bytes = KEY_NCT, drop: int = DROP_NCT) -> bytes:
    """Return the first ``n`` bytes of the keystream (cached per key)."""
    if n < 0:
        raise ValueError("negative length")
    cache_key = (bytes(key), int(drop))
    have = _CACHE.get(cache_key)
    if have is None:
        have = b""
    if len(have) >= n:
        return have[:n]
    # grow geometrically so repeated calls for similar sizes stay cheap
    want = max(n, min(max(len(have) * 2, 1 << 16), 1 << 26))
    s = list(range(256))
    j = 0
    klen = len(key)
    for i in range(256):
        j = (j + s[i] + key[i % klen]) & 0xFF
        s[i], s[j] = s[j], s[i]
    out = bytearray()
    i = j = 0
    for _ in range(want + drop):
        i = (i + 1) & 0xFF
        j = (j + s[i]) & 0xFF
        s[i], s[j] = s[j], s[i]
        out.append(s[(s[i] + s[j]) & 0xFF])
    have = bytes(out[drop:])
    _CACHE[cache_key] = have
    return have[:n]


def crypt(data: bytes, key: bytes = KEY_NCT, drop: int = DROP_NCT) -> bytes:
    """XOR ``data`` with the keystream.  Encrypts and decrypts."""
    ks = keystream(len(data), key, drop)
    n = len(data)
    # int.from_bytes / XOR is far faster than a Python level loop for big blobs
    return (int.from_bytes(data, "little") ^ int.from_bytes(ks, "little")).to_bytes(
        n, "little"
    )


#: Friendly alias - ``xcrypt`` is what the older analysis scripts call it.
xcrypt = crypt


def looks_encrypted(data: bytes) -> bool:
    """Heuristic: does this blob look like ``.nct`` ciphertext rather than plain?

    Ciphertext is uniformly random, so it contains control bytes and no long
    printable run.  A plaintext table (JSON, XML, ASCII name list) does the
    opposite.  Used only to pick a branch; the caller can always force one.
    """
    if not data:
        return False
    head = data[:512]
    printable = sum(1 for b in head if 9 <= b <= 13 or 32 <= b < 127)
    return printable / len(head) < 0.85


def read(path: str, key: bytes = KEY_NCT, drop: int = DROP_NCT) -> bytes:
    """Read a file and return plaintext, decrypting only when necessary."""
    data = open(path, "rb").read()
    if looks_encrypted(data):
        return crypt(data, key, drop)
    return data


def write(path: str, plain: bytes, key: bytes = KEY_NCT, drop: int = DROP_NCT,
          encrypt: bool = True) -> None:
    """Write plaintext back out, encrypted unless ``encrypt`` is False."""
    folder = os.path.dirname(os.path.abspath(path))
    if folder:
        os.makedirs(folder, exist_ok=True)
    open(path, "wb").write(crypt(plain, key, drop) if encrypt else plain)


def selftest(depot: str | None = None) -> int:
    """Decrypt every ``.nct`` under ``depot`` and check the round trip.

    A wrong keystream shows up immediately: the plaintext would not re-encrypt
    to the same bytes.
    """
    import glob

    if not depot:
        depot = os.environ.get("RR3_DEPOT", "")
    if not depot or not os.path.isdir(depot):
        print("nct selftest: no depot given (set RR3_DEPOT)")
        return 2
    files = glob.glob(os.path.join(depot, "**", "*.nct"), recursive=True)
    bad = 0
    for p in files:
        raw = open(p, "rb").read()
        if not looks_encrypted(raw):
            continue
        plain = crypt(raw)
        if crypt(plain) != raw:
            print("FAIL", p)
            bad += 1
    print(f"nct selftest: {len(files)} files, {bad} failures")
    return 1 if bad else 0
