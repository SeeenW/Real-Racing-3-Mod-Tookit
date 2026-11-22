"""Generate docs/动画片段与行为对照.md from the shipped car data.

Usage:
    python tools/gen_anim_doc.py [depot] [out.md]

Reads the ``_animations.xml`` of every car, joins it to the car's spec through
the appearance table, and prints one row per car with the clip set, the clip
frame ranges and the active-aero behaviour string.  Needs the game files; the
material/part catalogue generator (``gen_catalog_doc.py``) does not.
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from rr3lib import animxml, appearance as appearlib, nct, spec as speclib

DEFAULT_DEPOT = r"E:\DXT_480x320+960x640+2048x1536数据包-Build260716\files\.depot"
DEFAULT_OUT = os.path.join(ROOT, "docs", "动画片段与行为对照.md")

BEHAVIOUR_DOC = {
    "DeployWhenBraking": "刹车时展开",
    "NascarAirBrake": "NASCAR 专用空气刹车",
    "DeployAtSpeed": "到达某个速度时展开/收回，两个参数是速度阈值",
    "BrakeAndSpeedCombo": "刹车 + 速度组合触发，两个参数是速度阈值",
    "EngineFan": "引擎风扇（Porsche 917K / 909 Bergspyder）",
    "PaganiHuarya": "Huayra 的活动襟翼（官方拼写就是 Huarya）",
    "None": "行为名是 None，但参数在",
    "": "空 token —— 没有行为",
}


def behaviour_of(spec) -> str:
    """The string token that sits just before ``generic_race``.

    Returns "" when the car has no ``generic_race`` token or when the slot is
    empty (the shipped files leave a zero token there for 225 of 540 cars).
    """
    for i, t in enumerate(spec.tokens):
        if t[0] == "s" and t[3] == b"generic_race":
            if i == 0:
                return ""
            prev = spec.tokens[i - 1]
            if prev[0] == "s":
                return prev[3].decode("latin-1").strip()
            return ""
    return ""


def behaviour_kind(text: str) -> str:
    if text in ("", "(empty)"):
        return ""
    return text.split(",")[0].strip()


def collect(depot: str) -> list[dict]:
    """One row per car that has a spec, whether or not it has animation files."""
    vehicles = os.path.join(depot, "vehicles")
    data = os.path.join(vehicles, "data")

    count, recs = appearlib.load(depot)
    folder_of: dict[int, str] = {}
    for r in recs:
        name = r.name.decode("latin-1") if isinstance(r.name, (bytes, bytearray)) else r.name
        folder_of[r.id] = name

    rows = []
    for f in sorted(os.listdir(data)):
        if not f.endswith(".bin.nct") or not f.split("_")[0].isdigit():
            continue
        s = speclib.parse_spec(nct.read(os.path.join(data, f)))
        aid = s.appearance_id()
        folder = folder_of.get(aid) if aid else None
        path = os.path.join(vehicles, folder) if folder else ""
        exists = bool(folder) and os.path.isdir(path)
        xmls = [x for x in os.listdir(path) if x.endswith("_animations.xml")] if exists else []
        clips = animxml.load(os.path.join(path, xmls[0])) if xmls else []
        rows.append({
            "folder": folder or "",
            "car_id": s.car_id,
            "behaviour": behaviour_of(s),
            "clips": [(c.name, c.start, c.end) for c in clips],
            "xml": bool(xmls),
            "banim": bool(exists) and os.path.exists(os.path.join(path, folder + "_wing.banim")),
            "exists": exists,
        })
    return rows


def render(rows: list[dict]) -> str:
    animated = [r for r in rows if r["clips"]]
    out = []
    w = out.append

    w("# 动画片段与行为对照（14.0.1 全库实测）")
    w("")
    w("本文由 `tools/gen_anim_doc.py` 从游戏文件生成：扫描全部 **%d** 台有 spec 的车，"
      "其中 **%d** 台带 `<车>_animations.xml`（即真正会动的车）。" % (len(rows), len(animated)))
    w("")
    w("配套阅读：")
    w("")
    w("- [`插件使用手册`](插件使用手册.md) —— 三种动画载体怎么配合")
    w("- [`材质与部件清单`](材质与部件清单.md) —— 材质名 / 部件名 / 锚点名全表")
    w("")
    w("---")
    w("")

    # ---------------------------------------------------------------- clips
    w("## 1. 12 个官方片段名")
    w("")
    w("| 片段 | 含义 | 用到的车数 |")
    w("| --- | --- | --- |")
    counts: dict[str, int] = {}
    for r in animated:
        for name, _s, _e in r["clips"]:
            counts[name] = counts.get(name, 0) + 1
    for name in animxml.CLIP_ORDER:
        w("| `%s` | %s | %d |" % (name, animxml.CLIP_DOC.get(name, ""), counts.get(name, 0)))
    w("")
    unknown = sorted(set(counts) - set(animxml.CLIP_ORDER))
    if unknown:
        w("不在官方名单里的片段名：%s" % "、".join("`%s`" % u for u in unknown))
        w("")

    # ------------------------------------------------------------- combos
    w("## 2. 片段组合分布")
    w("")
    w("| 片段组合 | 台数 |")
    w("| --- | --- |")
    combos: dict[tuple, int] = {}
    for r in animated:
        key = tuple(sorted(c[0] for c in r["clips"]))
        combos[key] = combos.get(key, 0) + 1
    for key, n in sorted(combos.items(), key=lambda kv: -kv[1]):
        w("| %s | %d |" % (" + ".join("`%s`" % k for k in key), n))
    w("")
    w("**最小可用组合是 `wing_initial` + `wing_up` + `wing_down`。**")
    w("只做 `pivot_up` / `pivot_down` 的车也有 %d 台，说明引擎对缺片段是宽容的。"
      % sum(1 for r in animated if [c[0] for c in r["clips"]] ==
            ["wing_initial", "pivot_up", "pivot_down"]))
    w("")

    # --------------------------------------------------------- behaviours
    w("## 3. 行为串分布（全部 %d 台车）" % len(rows))
    w("")
    w("行为串是 spec 里 `generic_race` 字符串**前一个** token，格式是"
      "**自由文本 + 逗号参数**，引擎按前缀认：`<行为名>[, <参数1>, <参数2>]`。")
    w("")
    w("| 行为串 | 含义 | 台数 |")
    w("| --- | --- | --- |")
    beh: dict[str, int] = {}
    for r in rows:
        beh[r["behaviour"]] = beh.get(r["behaviour"], 0) + 1
    for text, n in sorted(beh.items(), key=lambda kv: -kv[1]):
        kind = behaviour_kind(text)
        doc = BEHAVIOUR_DOC.get(kind, "（未知行为名）")
        label = "`%s`" % text if text else "（空 token / 无 `generic_race`）"
        w("| %s | %s | %d |" % (label, doc, n))
    w("")

    # -------------------------------------------------- behaviour x clips
    w("## 4. 行为串 × 动画文件（全部 %d 台车）" % len(rows))
    w("")
    w("| 行为串 | 有 xml | 有 banim | 无动画文件 |")
    w("| --- | --- | --- | --- |")
    grid: dict[str, list[int]] = {}
    for r in rows:
        slot = grid.setdefault(r["behaviour"], [0, 0, 0])
        if r["xml"]:
            slot[0] += 1
        if r["banim"]:
            slot[1] += 1
        if not r["xml"] and not r["banim"]:
            slot[2] += 1
    for text, (x, b, none) in sorted(grid.items(), key=lambda kv: -sum(kv[1])):
        label = "`%s`" % text if text else "（空 token）"
        w("| %s | %d | %d | %d |" % (label, x, b, none))
    w("")
    nobeh = sum(1 for r in animated if not r["behaviour"])
    w("**注意：%d 台车完全没有行为串（空 token）却照样有完整动画。**" % nobeh)
    w("所以 `DeployWhenBraking` 不是「有尾翼动画」的必要条件 ——")
    w("`.banim` + `.xml` 决定**能不能动**，行为串只决定**什么时候动**。")
    w("")

    # ------------------------------------------------------------ per car
    w("## 5. 逐车对照表（%d 台会动的车）" % len(animated))
    w("")
    w("| id | 车目录 | 行为串 | 片段（起→止 帧） |")
    w("| --- | --- | --- | --- |")
    for r in animated:
        clips = "、".join("%s %d→%d" % (c[0], c[1], c[2]) for c in r["clips"])
        beh = ("`%s`" % r["behaviour"]) if r["behaviour"] else "—"
        w("| %s | `%s` | %s | %s |" % (r["car_id"], r["folder"], beh, clips))
    w("")
    return "\n".join(out) + "\n"


def main(argv: list[str]) -> int:
    depot = argv[1] if len(argv) > 1 else DEFAULT_DEPOT
    out = argv[2] if len(argv) > 2 else DEFAULT_OUT
    if not os.path.isdir(depot):
        print("depot not found: %s" % depot)
        return 2
    rows = collect(depot)
    if not rows:
        print("no _animations.xml found under %s" % depot)
        return 2
    text = render(rows)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    print("wrote %s: %d chars, %d lines, %d cars"
          % (out, len(text), text.count("\n"), len(rows)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
