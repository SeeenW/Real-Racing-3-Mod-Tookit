"""What the 34 floats in a suspension record actually look like, road car by
road car, with a couple of extremes for contrast."""

from __future__ import annotations

import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rr3lib import spec as speclib

ROOT = r"E:\DXT_480x320+960x640+2048x1536数据包-Build260716\files\.depot"

WANT = [
    "2000_nissan_silvia_(s15)",
    "2006_nissan_350z_(z33)",
    "1999_nissan_skyline_gt-r_v-spec_(r34)",
    "2010_bmw_z4_sdrive35is",
    "2010_bmw_m3_coupe",
    "2013_toyota_86",            # may not exist
    "2014_lexus_is_f_sport",
    "2012_lexus_lfa",
    "1969_dodge_charger_rt",
    "2013_bugatti_veyron_16.4_grand_sport_vitesse",
]


def main() -> int:
    table = speclib.load_suspension(ROOT)
    desc = speclib.load_cardesc(ROOT)
    by_id = {}
    for entry in desc.entries:
        text = entry.decode("ascii", "replace")
        cid, _, name = text.partition("_")
        by_id[name.rsplit(".bin", 1)[0]] = int(cid)

    print(f"records: {len(table)}, cars in cardesc: {len(by_id)}")
    print()
    head = "  ".join(f"f{i:02d}" for i in range(21, 27))
    print(f"{'car':46s} id    {head}   (f23/f24 are the travel pair)")
    print("-" * 110)
    for name in WANT:
        cid = by_id.get(name)
        if cid is None:
            print(f"{name:46s} -- not in cardesc")
            continue
        rec = table.get(cid)
        vals = struct.unpack_from("<34f", rec, 4)
        cells = "  ".join(f"{vals[i]:.3f}" for i in range(21, 27))
        print(f"{name:46s} {cid:4d}  {cells}")

    print()
    # how many distinct (f23, f24) pairs the whole table has
    from collections import Counter
    pairs = Counter()
    for rec in table.records:
        v = struct.unpack_from("<34f", rec, 4)
        pairs[(round(v[23], 3), round(v[24], 3))] += 1
    print(f"distinct (f23, f24) pairs: {len(pairs)}")
    for pair, n in pairs.most_common(15):
        print(f"   {pair}  x{n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
