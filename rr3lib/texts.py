"""The localised strings: ``gametext.txt`` and the twelve ``text_<lang>.txt``.

Both are line files under a second RC4 key (``nct.KEY_GAMETEXT``).  They are
written as parallel arrays: line *n* of ``gametext.txt`` is the key
``GAMETEXT_<something>`` and line *n* of every ``text_<lang>.txt`` is that key's
translation.  All fourteen files in this depot hold exactly 38,388 lines, and a
new key must be inserted at the same index in all of them or the game pairs the
wrong text with the wrong key.

The line separator is ``\\r\\n``.  ``text_<lang>.txt`` starts with a UTF-8 BOM on
line 0; ``gametext.txt`` does not.  Both files end with an empty line, so new
keys go *before* that last line.

Reading is cheap - 1.8 MB and 2.9 MB per file - but writing must never lose a
line, so :func:`Texts.save` rebuilds every file and the caller keeps the bytes.
"""

from __future__ import annotations

import os

from rr3lib import nct

LANGUAGES = ("cn-Hans", "cn-Hant", "de", "en", "es", "fr", "it",
             "jp", "kr", "nl", "pt-br", "ru")
GAMETEXT = "gametext.txt"
PREFIX = "GAMETEXT_"
BOM = b"\xef\xbb\xbf"
SEP = b"\r\n"


class TextError(Exception):
    pass


def _key_of(line: bytes) -> str:
    return line.decode("utf-8", "replace")


class _File:
    """One line file: its leaf name, whether it was plain on disk, and its lines."""

    __slots__ = ("leaf", "plain", "lines", "changed")

    def __init__(self, leaf: str, plain: bool, lines: list[bytes]):
        self.leaf = leaf
        self.plain = plain
        self.lines = lines
        self.changed = False

    def to_bytes(self) -> bytes:
        return SEP.join(self.lines)

    def __repr__(self) -> str:
        return f"_File({self.leaf!r}, {len(self.lines)} lines)"


class Texts:
    """``gametext.txt`` plus every ``text_<lang>.txt``, kept in step."""

    __slots__ = ("files", "_index", "_english")

    def __init__(self):
        self.files: list[_File] = []
        self._index: dict[str, int] = {}
        self._english = -1

    # ------------------------------------------------------------ reading
    @classmethod
    def from_blobs(cls, blobs: dict[str, bytes]) -> "Texts":
        """Build from ``{leaf: raw bytes}``.  Missing languages are skipped."""
        t = cls()
        order = [GAMETEXT] + [f"text_{lang}.txt" for lang in LANGUAGES]
        for leaf in order:
            raw = blobs.get(leaf)
            if not raw:
                continue
            plain = not nct.looks_encrypted(raw)
            data = raw if plain else nct.crypt(raw, nct.KEY_GAMETEXT, nct.DROP_GAMETEXT)
            t.files.append(_File(leaf, plain, data.split(SEP)))
        if not t.files:
            raise TextError("no gametext.txt or text_<lang>.txt was given")
        if t.files[0].leaf != GAMETEXT:
            raise TextError("gametext.txt is required: it holds the keys")
        n = len(t.files[0].lines)
        for f in t.files[1:]:
            if len(f.lines) != n:
                raise TextError(
                    f"{f.leaf} has {len(f.lines)} lines but gametext.txt has {n} - "
                    f"the files are not a matched pair")
        t._index = {_key_of(line): k for k, line in enumerate(t.files[0].lines)}
        for k, f in enumerate(t.files):
            if f.leaf == "text_en.txt":
                t._english = k
        return t

    @classmethod
    def load(cls, folder: str) -> "Texts":
        """Read the fourteen files out of a directory (``depot`` or a pack)."""
        blobs = {}
        for leaf in [GAMETEXT] + [f"text_{lang}.txt" for lang in LANGUAGES]:
            p = os.path.join(folder, leaf)
            if os.path.isfile(p):
                with open(p, "rb") as fh:
                    blobs[leaf] = fh.read()
        return cls.from_blobs(blobs)

    # ------------------------------------------------------------ queries
    def __len__(self) -> int:
        return len(self.files[0].lines) if self.files else 0

    def keys(self) -> list[str]:
        return [_key_of(line) for line in self.files[0].lines]

    def has(self, key: str) -> bool:
        return self._full(key) in self._index

    def get(self, key: str) -> str:
        """The English text for ``key`` (``GAMETEXT_`` optional)."""
        k = self._full(key)
        at = self._index.get(k)
        if at is None or self._english < 0:
            return ""
        f = self.files[self._english]
        if at >= len(f.lines):
            return ""
        v = f.lines[at]
        if v[:3] == BOM:
            v = v[3:]
        return v.decode("utf-8", "replace")

    def get_all(self, key: str) -> dict[str, str]:
        """Every language's text for ``key``, ``{leaf: text}``."""
        k = self._full(key)
        at = self._index.get(k)
        if at is None:
            return {}
        out = {}
        for f in self.files:
            if f.leaf == GAMETEXT or at >= len(f.lines):
                continue
            v = f.lines[at]
            if v[:3] == BOM:
                v = v[3:]
            out[f.leaf] = v.decode("utf-8", "replace")
        return out

    def _full(self, key: str) -> str:
        return key if key.startswith(PREFIX) else PREFIX + key

    # ------------------------------------------------------------ writing
    def set(self, key: str, text: str, *, only_language: str = "") -> bool:
        """Set ``key`` to ``text`` in every language.

        A key that does not exist yet is appended in one new line at the same
        index in every file, just before the closing empty line - that is what
        the game's own writer does, and the only insertion point that cannot
        shift an existing pairing.

        ``only_language`` limits the change to one ``text_<lang>.txt``; the key
        still has to exist.
        """
        k = self._full(key)
        at = self._index.get(k)
        value = text.encode("utf-8")
        if at is None:
            at = self._insert_point()
            self.files[0].lines.insert(at, k.encode("utf-8"))
            self.files[0].changed = True
            for f in self.files[1:]:
                while len(f.lines) < at:
                    f.lines.append(b"")
                f.lines.insert(at, value)
                f.changed = True
            self._index[k] = at
            return True
        changed = False
        for f in self.files[1:]:
            if only_language and f.leaf != f"text_{only_language}.txt":
                continue
            while len(f.lines) <= at:
                f.lines.append(b"")
            v = (BOM + value) if (at == 0 and f.lines[0][:3] == BOM) else value
            if f.lines[at] != v:
                f.lines[at] = v
                f.changed = True
                changed = True
        return changed

    def remove(self, key: str) -> bool:
        """Drop a key from every file.  Only safe for keys we added ourselves."""
        k = self._full(key)
        at = self._index.pop(k, None)
        if at is None:
            return False
        for f in self.files:
            if at < len(f.lines):
                del f.lines[at]
                f.changed = True
        self._index = {_key_of(line): n for n, line in enumerate(self.files[0].lines)}
        return True

    def _insert_point(self) -> int:
        lines = self.files[0].lines
        if lines and lines[-1] == b"":
            return len(lines) - 1
        return len(lines)

    # ------------------------------------------------------------ saving
    def changed(self) -> list[str]:
        return [f.leaf for f in self.files if f.changed]

    def blobs(self, *, only_changed: bool = True) -> dict[str, bytes]:
        """``{leaf: raw bytes}``, re-encrypted for any file that was plain on disk."""
        out = {}
        for f in self.files:
            if only_changed and not f.changed:
                continue
            plain = f.to_bytes()
            out[f.leaf] = plain if f.plain else nct.crypt(
                plain, nct.KEY_GAMETEXT, nct.DROP_GAMETEXT)
        return out

    def save(self, folder: str, *, only_changed: bool = True) -> list[str]:
        """Write the changed files into ``folder``; returns their leaf names."""
        written = []
        for leaf, blob in self.blobs(only_changed=only_changed).items():
            with open(os.path.join(folder, leaf), "wb") as fh:
                fh.write(blob)
            written.append(leaf)
        return written

    def summary(self) -> dict:
        return {
            "files": len(self.files),
            "lines": len(self),
            "languages": [f.leaf for f in self.files[1:]],
            "changed": self.changed(),
        }


def read_key(folder: str, key: str) -> str:
    """Convenience: the English text of one key, or ``""``."""
    return Texts.load(folder).get(key)
