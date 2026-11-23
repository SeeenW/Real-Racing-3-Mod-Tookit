"""Where the suspension numbers sit, car class by car class, and whether any
other float in the record is ever non-zero."""

from __future__ import annotations

import os
import statistics
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rr3lib import spec as speclib

ROOT = r"E:\DXT_480x320+960x640+2048x1536数据包-Build260716\files\.depot"


def main() -> int:
    table = speclib.load_suspension(ROOT)
    desc = speclib.load_cardesc(ROOT)

    classes: dict[str, list[tuple[str, float, float]]] = {}
    for entry in desc.entries:
        text = entry.decode("ascii", "replace")
        cid, _, leaf = text.partition("_")
        name = leaf.rsplit(".bin", 1)[0]
        try:
            spec = speclib.load_spec(ROOT, int(cid))
            cls = spec.stats().get("car_class") or "?"
        except Exception:                       # noqa: BLE001
            cls = "?"
        rec = table.get(int(cid))
        f = struct.unpack_from("<34f", rec, 4)
        classes.setdefault(cls, []).append((name, f[23], f[24]))

    print(f"{'class':12s} {'cars':>5s}  {'f23 front (m)':^28s}  {'f24 rear (m)':^28s}")
    print(f"{'':12s} {'':>5s}  {'min':>8s}{'med':>10s}{'max':>10s}  "
          f"{'min':>8s}{'med':>10s}{'max':>10s}")
    print("-" * 84)
    for cls, rows in sorted(classes.items(), key=lambda kv: -len(kv[1])):
        a = [r[1] for r in rows]
        b = [r[2] for r in rows]
        print(f"{cls:12s} {len(rows):5d}  {min(a):8.3f}{statistics.median(a):10.3f}"
              f"{max(a):10.3f}  {min(b):8.3f}{statistics.median(b):10.3f}{max(b):10.3f}")

    print()
    prod = classes.get("Prod", [])
    print(f"road cars (Prod), first 18 of {len(prod)}:")
    for name, f23, f24 in prod[:18]:
        print(f"   {name:46s} {f23:.3f}  {f24:.3f}")

    print()
    always_zero, ever_used = [], []
    for idx in range(34):
        vals = {round(struct.unpack_from("<34f", r, 4)[idx], 6) for r in table.records}
        (ever_used if len(vals) > 1 or 0.0 not in vals else always_zero).append(idx)
    print("floats that never change:", always_zero)
    print("floats that carry data  :", ever_used)
    return 0


if __name__ == "__main__":
    sys.exit(main())
