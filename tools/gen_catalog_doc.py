"""Generate ``docs/材质与部件清单.md`` from :mod:`rr3lib.catalog`.

The catalog tables are already embedded in the addon, so this script needs no
game data.  Run it after ``tools/build_catalog.py`` to refresh the reference
document::

    python tools/gen_catalog_doc.py

The output is a plain markdown reference: every material instance the shipped
cars use, every part name with its livery slot, the ``_mm_`` tags and the
engine anchor names.  Keep it generated - do not hand edit.
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from rr3lib import animxml, catalog, points_write  # noqa: E402

OUT = os.path.join(ROOT, "docs", "材质与部件清单.md")

#: The order the applications are documented in: car relevant first.
APP_ORDER = [
    "appCarPaint", "appCarBumperPaint", "appCarWheels", "appCarDash",
    "appCarMirror", "appCarDecoration", "appDefault", "appDepthSort",
    "appOverlays", "appProjectedLights", "appShadows", "appSkids",
    "appGhostCar", "appGhostCarBrakeLights", "appTree", "appTreeLines",
    "appTreeLinesOuter", "appBuildingalpha", "appFence", "appCrowd",
    "appSkyBack", "appSkyFront", "appDepthWriteOnly", "appFlareBlocker",
]

#: Part bases worth calling out in the hand written section.
KEY_PARTS = [
    ("LOD_A_BODY_mm_ext", "车身外壳（漆面）", "上漆的目标"),
    ("LOD_A_WING_REAR_mm_ext", "尾翼主翼片（漆面）", "尾翼上漆的目标"),
    ("LOD_A_WING_REAR_mm_misc", "尾翼支架 / 端板（黑塑料）", "原厂从不覆盖"),
    ("LOD_A_WING_REAR_LEFT_mm_ext", "尾翼左活动片", ""),
    ("LOD_A_WING_REAR_RIGHT_mm_ext", "尾翼右活动片", ""),
    ("LOD_A_WING_STRUT_mm_ext", "尾翼立柱", ""),
    ("LOD_A_WING_STRUT_REAR_mm_ext", "尾翼后立柱", ""),
    ("LOD_A_WING_mm_ext", "尾翼（单件式）", ""),
    ("LOD_A_FRONTBUMPER_mm_ext", "前保险杠", ""),
    ("LOD_A_REARBUMPER_mm_ext", "后保险杠", ""),
    ("LOD_A_HOOD_mm_ext", "引擎盖", ""),
    ("LOD_A_BOOT_mm_ext", "后备箱盖", ""),
    ("LOD_A_DOOR_LEFT_mm_ext", "左车门", ""),
    ("LOD_A_DOOR_RIGHT_mm_ext", "右车门", ""),
    ("LOD_A_CHASSIS_mm_chassis", "底盘 / 悬挂", ""),
    ("LOD_A_WHEEL_mm_wheel", "轮辋", "在 _shared.m3g 里"),
    ("LOD_A_TYRE_mm_tyre", "轮胎", "在 _shared.m3g 里"),
    ("LOD_A_BRAKE_CALIPER_FRONT_LEFT_mm_misc", "前左卡钳", ""),
    ("LOD_A_BRAKES_mm_rotor", "刹车盘", ""),
    ("LOD_A_GLASS_FRONT_mm_windows", "前挡玻璃", ""),
    ("LOD_A_INT_INTERIOR_mm_int", "内饰", "在 _int_*.m3g 里"),
    ("LOD_A_INT_STEERING_WHEEL_mm_sw", "方向盘", "在 _int_*.m3g 里"),
]


def esc(s: str) -> str:
    return s.replace("|", "\\|")


def main() -> int:
    rows = catalog.materials()
    parts = catalog.parts()
    tags = catalog.tags()
    by_app: dict[str, list] = {}
    for r in rows:
        by_app.setdefault(r[2], []).append(r)
    templates = sorted({r[1] for r in rows})

    L: list[str] = []
    A = L.append

    A("# 材质与部件清单（游戏原厂全集）")
    A("")
    A("> 本文由 `tools/gen_catalog_doc.py` 从 `rr3lib/catalog_data.py` 生成，**不要手改**。")
    A("> 数据来自 14.0.1 的 `materials.bin` 与 `liveryStringTable.bin.nct`，")
    A("> 也就是**引擎认识的全部名字**。表里没有的名字，写进 liveries 也不会生效。")
    A("")
    A("## 0. 一页速查")
    A("")
    A("| 项 | 数量 | 说明 |")
    A("|---|---|---|")
    A(f"| 材质实例 | **{len(rows)}** | 写进 liveries 的是这个 |")
    A(f"| 材质模板 | **{len(templates)}** | 实例的父模板，决定着色器 |")
    A(f"| `appCarPaint` 材质 | **{len(by_app.get('appCarPaint', []))}** | 能当车漆用的那些（含 36 个 `car_paint_*`） |")
    A(f"| 部件名 | **{len(parts)}** | 网格名，也是 liveries 槽位名 |")
    A(f"| 部件基名 | **{len(catalog.bases())}** | 去掉 `_mm_<tag>` 后的名字 |")
    A(f"| `_mm_` 标签 | **{len(tags)}** | 决定图集页与渲染组 |")
    A(f"| 引擎锚点名 | **{len(points_write.ENGINE_POINTS)}** | `.points` 里唯一有效的名字 |")
    A(f"| 动画片段名 | **{len(animxml.CLIP_ORDER)}** | `_animations.xml` 里唯一有效的名字 |")
    A(f"| liveries 槽位 | **{max(s for _n, s in parts)}** | 下标范围 22..{max(s for _n, s in parts)} |")
    A("")

    # ---------------------------------------------------------------- tags
    A("## 1. `_mm_` 标签（30 个）")
    A("")
    A("部件名 `LOD_A_WING_REAR_mm_ext` 拆成三段：`LOD_A_` = LOD，`WING_REAR` = 基名，")
    A("`ext` = 标签。**标签决定引擎取哪张图集、走哪个渲染组**；")
    A("基名决定 liveries 表里的槽位（也就是能不能单独上漆）。")
    A("")
    A("| 标签 | 部件数 | 含义 |")
    A("|---|---:|---|")
    from collections import Counter
    cnt = Counter(catalog.split_part(n)[2] for n, _s in parts)
    for t in sorted(tags):
        A(f"| `{t}` | {cnt.get(t, 0)} | {esc(catalog.TAG_DOC.get(t, ''))} |")
    A("")
    odd = sorted(t for t in {catalog.split_part(n)[2] for n, _s in parts}
                 if t and t not in catalog.TAG_DOC)
    if odd:
        A("另有未归档的标签：%s。" % ", ".join("`%s`" % x for x in odd))
        A("")
    untagged = sorted(n for n, _s in parts if not catalog.split_part(n)[2])
    if untagged:
        A("**不带 `_mm_` 标签的名字**（%d 个，`catalog.split_part()` 的 tag 为空，"
          "liveries 里查不到，无法上漆）：" % len(untagged))
        A("")
        for n in untagged:
            slot = catalog.part_slot(n)
            A("- `%s` (slot %s)" % (n, slot if slot is not None else "—"))
        A("")

    # ------------------------------------------------------------ paints
    A("## 2. 车漆材质（`appCarPaint`，41 个）")
    A("")
    A("**给部件上漆就从这张表里挑。** 这是按 `application == appCarPaint` 筛出来的全集，")
    A("里面除了 36 个 `car_paint_*`，还有 5 个非漆材质（`car_body_plastic`、`car_gloss`、")
    A("`car_matte`、`car_matte_doublesided`、`car_rotor_low`）——它们的 application 也是")
    A("`appCarPaint`，所以引擎允许把它们挂在车身件上，但观感不是车漆。")
    A("")
    A("| 材质名 | 模板 | flags |")
    A("|---|---|---|")
    for name, tmpl, _app, flags in by_app.get("appCarPaint", []):
        mark = "" if name in catalog.PAINT_MATERIALS else " ⚠"
        A(f"| `{name}`{mark} | `{tmpl}` | {esc(flags) or '—'} |")
    A("")
    A("⚠ = 不是 `car_paint_*` 家族，挂到车身件上通常不是你要的效果。")
    A("")
    A("### 2.1 flags 含义")
    A("")
    A("| flag | 含义 |")
    A("|---|---|")
    A("| `FOG` | 参与雾计算 |")
    A("| `SPEC_TEXTURE` | 用镜面贴图（车漆的高光形状就靠它） |")
    A("| `SPEC_MASK_TEXTURE` | 镜面遮罩，按 UV 决定哪里亮 |")
    A("| `REF_TEXTURE_MASK` | 用反射贴图的 alpha 当遮罩 |")
    A("| `COLOURED_FRESNEL` | 菲涅尔带色（糖果漆 / 珍珠漆的边缘色） |")
    A("| `SPEC_FLAKES` | 金属闪片（`metallic_spec_*`） |")
    A("| `ROTOR_GLOW` | 刹车盘余热发光 |")
    A("| `ALPHA_MODULATE` | 半透明 |")
    A("")
    A("### 2.2 保险杠漆（`appCarBumperPaint`）")
    A("")
    A("保险杠是**单独一套**材质名：`car_bumper_paint_*` 对应 `car_paint_*`，")
    A("flags 略少（多数没有 `REF_TEXTURE_MASK`）。给保险杠上漆要用 `car_bumper_paint_*`，")
    A("不要用 `car_paint_*`——虽然引擎不报错，但保险杠的 UV 是按保险杠那套烘的。")
    A("")
    A("| 保险杠材质 | 模板 |")
    A("|---|---|")
    for name, tmpl, _app, _flags in by_app.get("appCarBumperPaint", []):
        A(f"| `{name}` | `{tmpl}` |")
    A("")

    # ------------------------------------------------------------ materials
    A("## 3. 全部材质（297 个，按 application 分组）")
    A("")
    A("`application` 决定引擎绑哪个着色器与 LUT，比模板更能说明用途。")
    A("")
    apps = [a for a in APP_ORDER if a in by_app] + \
           sorted(a for a in by_app if a not in APP_ORDER)
    for app in apps:
        group = by_app[app]
        A(f"### `{app}` ({len(group)})")
        A("")
        A(esc(catalog.APPLICATION_DOC.get(app, "")) or "（无说明）")
        A("")
        A("| 材质名 | 模板 | flags |")
        A("|---|---|---|")
        for name, tmpl, _a, flags in group:
            A(f"| `{name}` | `{tmpl}` | {esc(flags) or '—'} |")
        A("")

    # --------------------------------------------------------------- parts
    A("## 4. 部件名（1869 个）")
    A("")
    A("### 4.1 命名规则")
    A("")
    A("```")
    A("LOD_A_WING_REAR_LEFT_mm_ext")
    A("^^^^^ ^^^^^^^^^^^^^^^ ^^ ^^^")
    A("LOD  基名             _mm_ 标签")
    A("```")
    A("")
    A("- `LOD_A` .. `LOD_H`：细节级别，A 最精细。老车常常只有 A–D。")
    A("- 基名：引擎按它查 liveries 槽位，**所以同名不同 LOD 是不同槽位**。")
    A("- 标签：见 §1。没有 `_mm_` 的名字（8 个）是历史遗留，不能单独上漆。")
    A("")
    A("### 4.2 常用部件与槽位")
    A("")
    A("| 部件名 | 槽位 | 说明 | 备注 |")
    A("|---|---:|---|---|")
    for name, note, extra in KEY_PARTS:
        slot = catalog.part_slot(name)
        A(f"| `{name}` | {slot if slot is not None else '—'} | {note} | {extra} |")
    A("")
    A("### 4.3 尾翼相关槽位（上漆最容易踩坑的一组）")
    A("")
    A("| 部件名 | 槽位 |")
    A("|---|---:|")
    for name in ("LOD_A_WING_REAR_mm_ext", "LOD_A_WING_REAR_mm_misc",
                 "LOD_A_WING_REAR_LEFT_mm_ext", "LOD_A_WING_REAR_RIGHT_mm_ext",
                 "LOD_A_WING_STRUT_REAR_mm_ext", "LOD_A_WING_STRUT_mm_ext",
                 "LOD_A_WING_mm_ext", "LOD_A_WING_mm_misc"):
        slot = catalog.part_slot(name)
        A(f"| `{name}` | {slot if slot is not None else '—'} |")
    A("")
    A("`745` 与 `30` 的对应关系是原厂的硬规律：**全库 16 组尾翼覆盖里，745 的目标材质")
    A("永远等于同一涂装里 30 的目标**。所以“尾翼跟随车漆”要写成")
    A("“把 745 设成和 30 一样”，而不是“把 745 设成某个漆”。")
    A("")
    A("### 4.4 按 LOD 统计的基名")
    A("")
    A("| LOD | 部件名 | 基名 |")
    A("|---|---:|---:|")
    per: dict[str, list[str]] = {}
    for name, _s in parts:
        lod, base, _t = catalog.split_part(name)
        per.setdefault(lod, []).append(base)
    for lod in sorted(per):
        A(f"| `{lod or '(无)'}` | {len(per[lod])} | {len(set(per[lod]))} |")
    A("")
    A("### 4.5 全部 LOD_A 基名（268 个）")
    A("")
    A("车身 LOD 里能出现的全部基名。改车时**只应该用这些名字**，")
    A("否则 liveries 里没有槽位，部件会拿到硬编码的 `car_flat`（发暗、不跟随车漆）。")
    A("")
    lod_a = sorted({catalog.split_part(n)[1] for n, _s in parts
                    if catalog.split_part(n)[0] == "A"})
    for i in range(0, len(lod_a), 3):
        chunk = lod_a[i:i + 3]
        A("| " + " | ".join(f"`{x}`" for x in chunk) + " |")
    A("")
    A(f"共 {len(lod_a)} 个。其余 LOD（B–H）的基名是它的子集，用 "
      "`rr3lib.catalog.parts_for_base()` 查一个基名在各 LOD 下的全部变体。")
    A("")

    # -------------------------------------------------------------- anchors
    A("## 5. 引擎认识的锚点名（79 个）")
    A("")
    A("`.points` 里只有这些名字会被引擎读取，其余**静默忽略**。")
    A("表来自 `libRealRacing3.so` 的 `0x01EEB458..0x01EEB6C8`（79 × 8 字节连续槽），")
    A("索引就是引擎内部 id。")
    A("")
    A("| # | 名字 | 类型 |")
    A("|---:|---|---|")
    for i, name in enumerate(points_write.ENGINE_POINTS):
        kind = "HINGE（铰链，带 3×3 朝向）" if name.startswith("HINGE_") else "POINT（点）"
        A(f"| {i} | `{name}` | {kind} |")
    A("")
    A("**带数字后缀的名字也认**：引擎先精确匹配，再剥掉末尾的数字与下划线重试，")
    A("所以 `POINT_HEADLIGHT_LEFT_01` .. `_09` 都会落到 `POINT_HEADLIGHT_LEFT`。")
    A("这一条只对末尾数字生效，`POINT_MY_THING` 这种新名字不行。")
    A("")
    A("几个常用索引：`6 = POINT_STEERING_WHEEL`、`57 = HINGE_STEERING_WHEEL`、")
    A("`7 = POINT_DRIVER`、`0..3 = POINT_WHEEL_FL/FR/BL/BR`。")
    A("")

    # ---------------------------------------------------------------- clips
    A("## 6. 动画片段名（12 个）")
    A("")
    A("`<car>_animations.xml` 里只有这些 `<anim name=...>` 会被引擎查询。")
    A("**1 帧 = 33.0 ms（30.303 fps）**，`end < start` 表示倒放。")
    A("")
    A("| 片段名 | 含义 |")
    A("|---|---|")
    for name in animxml.CLIP_ORDER:
        A(f"| `{name}` | {esc(animxml.CLIP_DOC.get(name, ''))} |")
    A("")
    A("行为设置（`DeployWhenBraking` 等）写在车的 spec 里，不在 XML 里，见")
    A("`docs/插件使用手册.md` §7。")
    A("")

    # ------------------------------------------------------------ templates
    A("## 7. 材质模板（137 个）")
    A("")
    A("模板是着色器配置，实例是名字。改材质时只用实例名；想换观感就换实例。")
    A("")
    A("| 模板 | 实例数 |")
    A("|---|---:|")
    from collections import Counter as C2
    tc = C2(r[1] for r in rows)
    for tmpl, n in sorted(tc.items(), key=lambda kv: (-kv[1], kv[0])):
        A(f"| `{tmpl}` | {n} |")
    A("")

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    text = "\n".join(L) + "\n"
    with open(OUT, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    print(f"wrote {OUT}: {len(text)} chars, {len(L)} lines")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
