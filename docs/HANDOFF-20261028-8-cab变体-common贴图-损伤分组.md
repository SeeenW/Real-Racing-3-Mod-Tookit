# HANDOFF 2026-10-28（第 8 份）：`_mm_cab` 涂装变体 / `vehicles/common` 贴图 / 损伤件分组

状态：**已完成**（`MATERIAL SMOKE: PASS (113 ok, 0 failed)`，另三套回归全绿）

---

## 0. 一句话结论

三件事都做完了，根因都不是"解析不出"，而是**取用链路上的三个漏洞**：

| 用户说的 | 真正的根因 | 修法 |
|---|---|---|
| `cab` 内饰部件也有涂装变体 | 变体**解析是对的**（涂装表 texture override），但 Blender 材质名撞车 —— 先建的赢，其余全穿错贴图 | `GameMaterials._unique_name()`：撞名加 tag 后缀 |
| 窗户/轮胎/刹车盘的贴图在 `common` 里 | 取贴图只查「涂装覆盖 → 车表」，**没查 `default.liveries.bin.nct`** | `texture_path_for_tag()` 加第三级 default 回退 + `_common_texture_files()` 载入 |
| 损伤件要单独放 | 车身文件里完好版和撞毁版位置完全重合 | `separate_damage`（默认开）+ `DAMAGED_TOKENS` |

---

## 1. 用户原话（2026-10-28）

> 还有点问题。有些cab后缀的内饰部件也有不同的涂装变体，我猜livery nct文件上有配置。
> 有些部件，比如窗户，轮胎，刹车盘等，它们的贴图在common文件夹内，需要载入并连接。
> 还有就是如果导入的lod含有broken,damage后缀的损伤部件，请把他们放在一个新的子集合内。

三条都验证为真，其中第一条用户猜得完全正确（确实是 livery nct 里的配置）。

---

## 2. `_mm_cab` 的涂装变体

### 2.1 机制：涂装表的 texture override，不是材质 override

`liveryStringTable` 里 cab 相关 slot 79 个（`int_` 331、`window` 314、`wheel` 502、
`brake` 94、`tyre` 36、`rotor` 13）。`Paint.texture_of(slot)` 命中时，
`carmaterial.resolve()` 早就正确取到了那条贴图 —— **解析层从来没坏过**。

全库扫描（379 台 ≥2 涂装的车、1903 个 `_mm_cab` 网格）：
**49 个 cab 网格在不同涂装下解析出不同贴图**。

实测样例 `2013_bugatti_veyron_gsv`（6 涂装）：

```
LOD_A_BODY_mm_cab      part_slot=27
  paint1 cab_chrome / paint2 cab_orange / paint3 cab
  paint4 cab_chrome / paint5 cab / paint6 cab_orange
LOD_A_INTERIOR_mm_cab  part_slot=275   同上
```

`1999_nissan_skyline_r34_r3`：paint1 `_cab` / paint2 `_cab_blue` / paint3 `_cab`。

### 2.2 真正的问题：Blender 材质名撞车

`GameMaterials._build()` 原来用 `name = f"{self.car}_{first.material}"`。
而**同一个游戏材质名在一台车上会配不同图集**：

| 车 | 网格 | 不同材质名 | 撞名数 |
|---|---|---|---|
| `2014_mclaren_p1` | 67 | 15 | **3** |
| `2013_bugatti_veyron_gsv` | 84 | 14 | **4** |
| `2011_pagani_huayra` | 87 | 16 | **3** |
| `2012_lexus_lfa` | 68 | 14 | **4** |

P1 的 3 处冲突：

```
2014_mclaren_p1_car_flat    2 sigs: tex=_misc   / tex=_cab
2014_mclaren_p1_car_glass   2 sigs: tex=car_windows_04 / car_windows_shattered_04
2014_mclaren_p1_car_matte   3 sigs: tex=_misc / tex=_lights / tex=_ext_yellow
```

Veyron GSV 的 4 处：`car_badge_matte`(2)、`car_flat`(5，含 cab_chrome / misc /
ext_bluecarbon / None)、`car_glass`(2，misc vs car_windows_02)、`car_matte`(2)。

**改前的实际后果**（Blender 实测）：`LOD_A_DOOR_LEFT_mm_cab` 拿到
`2014_mclaren_p1_car_flat` 但 atlas 是 `_misc.png`（应该 `_cab.png`）；
`LOD_A_GLASS_FRONT_mm_windows` 拿到 `car_windows_shattered_04.png`
（应该 `car_windows_04.png`）—— **先建的赢，其余全穿错贴图**。

### 2.3 修法

```python
def _unique_name(self, stem: str, tag: str) -> str:
    """``stem``, or ``stem_<tag>`` / ``stem_<tag>_2`` when that is taken."""
    if stem not in self._names:
        return stem
    if tag:
        candidate = f"{stem}_{tag}"
        if candidate not in self._names:
            return candidate
        n = 2
        while f"{candidate}_{n}" in self._names:
            n += 1
        return f"{candidate}_{n}"
    n = 2
    while f"{stem}_{n}" in self._names:
        n += 1
    return f"{stem}_{n}"
```

`_build()` 里 `stem = f"{self.car}_{first.material}"`，多签名时加 `_paint`，
然后 `name = self._unique_name(stem, first.tag)`。**tag 是区分它们的依据，所以后缀用 tag**。

顺带把材质复用校验也加强了（`_build_preset_material`）：

```python
mat = bpy.data.materials.get(name)
if mat is not None:
    same = (mat.get("rr3_presets") == len(presets) and mat.node_tree is not None)
    if same and presets:
        same = mat.get("rr3_textures") == [p[2].texture_file or "" for p in presets]
    if same:
        return mat
    bpy.data.materials.remove(mat)
```

新增属性 `mat["rr3_textures"]`（每预设的贴图文件名列表），供上面这个校验用。

### 2.4 实测

```
2014_mclaren_p1_car_tail_light_rotor   atlas=car_rotor_08.png          ← rotor 与尾灯撞名，去重生效
2014_mclaren_p1_car_glass              atlas=car_windows_04.png        ← 不再是 shattered
2014_mclaren_p1_car_flat_cab           atlas=2014_mclaren_p1_cab.png   ← 去重生效
2013_bugatti_veyron_gsv_car_glass_windows  atlas=car_windows_02.png
2013_bugatti_veyron_gsv_car_flat_paint atlas=..._cab_chrome.png        ← 6 预设
```

冒烟断言 `a material name never carries two atlases` → P1 **19 个名字、0 冲突**；
LFA **16 个名字、0 冲突**。
`a cab panel keeps one preset per scheme` → Veyron GSV `6 preset(s) of 6`，
`its atlas changes with the scheme` → `['cab.png', 'cab_chrome.png', 'cab_orange.png']`。

---

## 3. `vehicles/common` 的共享贴图

### 3.1 数据

`vehicles/common/` 有 **298 个文件**。`default.liveries.bin.nct` 的 22 条 texture 行
就是这批共享图集：

```
0  ext_chassis           -> common/car_chassis.ptc.pvr.z
1  ext_windows_cracked   -> common/car_windows_cracked_01.ptc.pvr.z
2  ext_windows_shattered -> common/car_windows_shattered.ptc.pvr.z
3  ext_windows           -> common/car_windows.ptc.pvr.z
4  ext_tyre              -> common/car_tyre_tread.ptc.pvr.z
5  ext_rotor             -> common/car_rotor_00.ptc.pvr.z
6  ext_cloak  7 ext_banner  8 ext_scratches  9 ext_headlight_glow
10-12 int_windows*        13-20 int_mat00..mat07        21 int_banner
```

### 3.2 缺行统计（540 台有 livery 文件的车）

| 槽名 | 车自己的表里缺这一行的台数 |
|---|---|
| `ext_tyre` | **153** |
| `ext_rotor` | **155** |
| `ext_windows` | **90** |
| `ext_chassis` | **540（全部）** |

⇒ 之前 `texture_path_for_tag()` 只查「涂装 override → 车 textures」，
这 153 / 155 / 90 台车的轮胎、刹车盘、玻璃**完全没有贴图**。
`common/` 路径本身能正确解析（实测 `common/car_tyre_tread.ptc.pvr.z` →
`...\vehicles\common/car_tyre_tread.dxt.dds.z`，5 个全部命中）。

### 3.3 修法

```python
def texture_path_for_tag(L, table, tag, paint_index=None, default=None):
    slot = texture_slot_for_tag(table, tag)
    if slot is None:
        return None
    if paint_index is not None and 0 <= paint_index < len(L.paints):
        hit = L.paints[paint_index].texture_of(slot)
        if hit is not None:
            return hit.decode("utf-8", "replace")
    for s, path in L.textures:
        if s == slot:
            return path.decode("utf-8", "replace")
    if default is not None:                       # ← 新增第三级
        for s, path in default.textures:
            if s == slot:
                return path.decode("utf-8", "replace")
    return None
```

`resolve()` 里传 `default`。另外新增 `_common_texture_files(car_dir)`：
**只载 `default` 表真正引用到的那些**，不是把 298 个文件全扫一遍
（否则会把每台车每个内饰色板都拖进来）。

### 3.4 实测

解析层（4 台车全部网格 `resolve()`）：

```
2014_mclaren_p1          meshes= 67  windows=12 cab=5  still missing=0
2013_bugatti_veyron_gsv  meshes= 84  windows=10 cab=7  still missing=0
2011_pagani_huayra       meshes= 87  windows=18 cab=5  still missing=0
2012_lexus_lfa           meshes= 68  windows=20 cab=3  still missing=0
```

改前 Veyron GSV 的轮胎/刹车盘全是 None。Blender 导入层：

```
LOD_A_TYRE_mm_tyre   mat=..._car_tires              atlas=car_tyre_tread.png
LOD_A_ROTOR_mm_rotor mat=..._car_rotor              atlas=car_rotor_01.png
```

冒烟断言 `the tyre falls back to vehicles/common` → `car_tyre_tread_pirelli_02.png`（P1）/
`car_tyre_tread.png`（LFA、Veyron）；`the rotor falls back to vehicles/common` →
`car_rotor_08.png` / `car_rotor_05.png` / `car_rotor_01.png`。

---

## 4. 损伤件分组

### 4.1 数据

车身文件里每个板件都同时有完好版和撞毁版，位置完全重合。
61 台车抽样：`DAMAGE` 出现 **1516** 次、`BROKEN` **493** 次，21 种基名：

```
LOD_A_DOOR_LEFT_DAMAGE 258 / DOOR_RIGHT_DAMAGE 258 / HOOD_DAMAGE 213 /
BONNETCAM_HOOD_DAMAGE 211 / REARBUMPER_DAMAGE 195 / BOOT_DAMAGE 193 /
FRONTBUMPER_DAMAGE 188 / TAILLIGHT_LENS_BROKEN_{A,B}_{LEFT,RIGHT} 57-59 /
HEADLIGHT_LENS_BROKEN_{A,B}_{LEFT,RIGHT} 52 / GLASS_BROKEN_REAR 36 /
TAILLIGHT_LENS_REARBUMPER_BROKEN_* 4 / TAILLIGHT_LENS_BOOT_BROKEN 1
```

两种标记：`DAMAGE`（车身板件）、`BROKEN`（玻璃与灯罩）。都在**同一个车身文件**里。

### 4.2 修法

```python
DAMAGED_TOKENS = ("DAMAGE", "BROKEN")

def _is_damaged(mesh_name: str) -> bool:
    """True when the mesh is the wrecked twin of a part."""
    base = (mesh_name or "").split("_mm_")[0].upper()
    return any(token in base for token in DAMAGED_TOKENS)
```

`import_vehicle_file()` 里 body 导入之后：

```python
damage_coll = None
if separate_damage:
    damage_coll = _collection(f"{car}_LOD{lod}_damaged", coll)

for ob in body["objects"]:
    for c in list(ob.users_collection):
        c.objects.unlink(ob)
    target = coll
    if damage_coll is not None and _is_damaged(ob.get("rr3_mesh_name") or ""):
        target = damage_coll
        ob["rr3_damaged"] = True
    target.objects.link(ob)
```

**配套改动（容易漏）**：材质应用要递归收集，否则子集合里的网格保留占位材质：

```python
def _all_objects(coll):
    """Every object in ``coll`` and in the sub-collections under it."""
    seen = []
    def walk(c):
        seen.extend(c.objects)
        for child in c.children:
            walk(child)
    walk(coll)
    return seen
```

`import_vehicle_file()` 末尾 `every = [ob for ob in _all_objects(coll) if ob.type == "MESH"]`。

### 4.3 实测

```
2014_mclaren_p1         damaged 24  objects    main 85 objects
2013_bugatti_veyron_gsv damaged 29  objects    main 104 objects
2012_lexus_lfa          damaged 22  objects
```

P1 的 24 个：`BONNETCAM_HOOD_DAMAGE_{badges,ext}`、`BOOT_DAMAGE_{lights,misc}`、
`DOOR_LEFT/RIGHT_DAMAGE_{cab,ext,misc}`、`FRONTBUMPER_DAMAGE_{ext,misc}`、
`GLASS_BROKEN_REAR`、`HEADLIGHT_LENS_BROKEN_{A,B}_{LEFT,RIGHT}`、
`HOOD_DAMAGE_{badges,ext}`、`REARBUMPER_DAMAGE_misc`、
`TAILLIGHT_LENS_BROKEN_{A,B}_{LEFT,RIGHT}`。

Veyron GSV 的 29 个多出 `DOOR_*_DAMAGE_mm_scratches`（该车有划痕图层）。

冒烟断言：`the damaged parts get their own collection`、`it holds the wrecked panels
and the smashed glass`、`everything in it is a damage or broken part`、
`the good panels stay in the main collection`、`the damaged meshes are flagged`。

---

## 5. 新增参数

`import_vehicle_file(..., separate_damage: bool = True)`；
operator `IMPORT_OT_rr3_vehicle` 加 `separate_damage: BoolProperty(name="Damaged parts
in their own folder", default=True)`。operator 参数现 **25 个**。

---

## 6. 测试

```
python tools\test_car.py                    → CARTEST: PASS（13 步）
tools\smoke_addon.py                        → SMOKE TEST: PASS（16 项）
tools\smoke_wheels.py                       → WHEEL SMOKE: PASS (96 ok, 0 failed)
tools\smoke_materials.py                    → MATERIAL SMOKE: PASS (113 ok, 0 failed)
python tools\sync_rr3lib.py --check          → already in sync（27 模块）
```

`smoke_materials.py` 从 62 项扩到 **113 项**，`CARS` 加了第三台 `2013_bugatti_veyron_gsv`
（唯一同时满足"有 cab 涂装变体 + 有大量损伤件 + 有 common 回退"的车）。
新增断言（每台车 9 项 + textures 组）：

- `the tyre falls back to vehicles/common`
- `the rotor falls back to vehicles/common`
- `a material name never carries two atlases`
- `a cab panel keeps one preset per scheme`
- `its atlas changes with the scheme`（仅当该车 cab 有多预设）
- `the damaged parts get their own collection`
- `it holds the wrecked panels and the smashed glass`
- `everything in it is a damage or broken part`
- `the good panels stay in the main collection`
- `the damaged meshes are flagged`

新增辅助函数 `atlas_of(mat)`（返回 `atlas_0` 节点指向的贴图文件名）。

---

## 7. 相关文档

| 文件 | 内容 |
|---|---|
| `docs/游戏材质与涂装.md` | 新增 §6.1 三级回退与缺行统计、§7.0.1 cab 变体、§7.0.2 材质名唯一、§7.0.3 损伤件分组 |
| `docs/插件使用手册.md` | §2 排查表加 4 行、§6.5 补 cab 变体与 common 回退、新增 §6.6 损伤件单独成组（原 §6.6 贴图顺延为 §6.7）、§9.4 脚本表改 113 项 |
| `rr3_blender_addon/README.md` | §3.1 参数表加 `separate_damage`、§6.1 表格补"材质名"与"贴图来源"两行、§9 已知限制加第 12–14 条 |
| `README.md` | 交付物树 `__init__.py` 138 KB、`smoke_materials.py` 113 项；§4 加 common 回退 / 损伤分组 / 材质名唯一三条；已知限制加第 26–28 条 |
| `docs/livery槽位表与材质名.md` | 涂装四张表的全量槽位（未改，仍是权威参考） |

---

## 8. 环境备忘

- depot 根：`E:\DXT_480x320+960x640+2048x1536数据包-Build260716\files\.depot`。
  **中文路径在 pwsh here-string 里写死会乱码**，用 `glob.glob(r"E:\DXT*Build260716")[0]`。
- `Paint.name` 是**方法不是属性**，`"%s" % p.name` 会
  `TypeError: unsupported format string passed to method.__format__`；用 `p.name()`。
- `DefaultTable` **没有 `.paints`**，只有 `.textures` / `.materials`；`load_default()` 返回它。
- `bpy.ops.import_scene.rr3_vehicle` 只认 `filepath=`，且必须指具体 `.m3g`
  （传文件夹会把 `car` 认成 `vehicles`，报 `no LOD A body found`）。
- 同进程连续导入多台车，每台前要 `bpy.ops.wm.read_factory_settings(use_empty=True)`
  + `addon_enable`，否则 `bpy.data.*` 保留上一台。
- Blender headless stderr 有几百行 `Failed to remove: ... PermissionError(13, '拒绝访问。')`
  （扩展清理噪音）；stdout 单独重定向到文件再读，`Select-String` 加 `-CaseSensitive`。
