# HANDOFF 2026-10-28（第 9 份）：删 `all_lods` / LOD G·H 的轮子 / 驾驶员导入 / 相机壳与内饰独立导入

状态：**已完成**（`WHEEL SMOKE: PASS (107 ok, 0 failed)`、`DRIVER SMOKE: PASS (38 ok, 0 failed)`、
`MATERIAL SMOKE: PASS (113 ok, 0 failed)`、`SMOKE TEST: PASS`、`CARTEST: PASS`）

---

## 0. 一句话结论

| 用户说的 | 真正的根因 | 修法 |
|---|---|---|
| 一次导入所有 LOD 还是有点 bug，去掉它 | 它只是循环调单 LOD，本身没错，但**每个 LOD 都会重算一次材质与贴图**，慢且容易留下同名材质 | 整段删除（`import_vehicle_all_lods` + `_available_lods` + operator 的 `all_lods`） |
| LOD G 用的也是 LOD F 的轮子 | `_shared.m3g` 里**根本没有 G / H 字母的轮子网格**，`wheel_set(lod="G")` 返回空 | `WHEEL_LOD_FALLBACK = {"G": "F"}`、`NO_WHEEL_LODS = ("H",)` |
| LOD H 不需要轮子 | 同上 | 同上 |
| 要能导入驾驶员 | 资源在 `<depot>/driver/`，材质名 `driver` 在 `materials.bin` 里**不存在**，必须特判到 `vehicles/common/driver.dxt.dds.z` | 新建 `rr3lib/driver.py` + `import_driver()` + `import_scene.rr3_driver` |
| shared 里的 bonnetcam 要单独放 | 它们和车身在同一文件、位置完全重合，叠在一起 z-fighting | `separate_camera` + `BONNETCAM` / `LIT_` 判定 |
| 单独导入 shared 要完整导入 | `car_from_path()` 把 `_shared`/`_int_a`/`_int_b` 的 lod 认成 `None`，随后被当成"缺 LOD 的车身"处理 | `lod = "shared"/"int_a"/"int_b"` + `standalone` 分支 |
| `int_a`/`int_b` 是独立 LOD | 同上 | 同上，集合名 `<car>_int_a` |

---

## 1. 用户原话（2026-10-28）

> 一次导入所有lod功能还是有点bug...去掉它吧。然后修一个bug，就是车辆的lod_g用的也是lod_f的轮子（已经预组装了的，直接放在世界原点就行），lod_h的话就不需要轮子，因为已经是最低质量的Lod了
> 然后加入一个导入驾驶员的功能，驾驶员的模型和动画在driver文件夹里，贴图在common文件夹里。给驾驶员绑定好动画后再加个根空物体用于整体移动。
> 还有个问题，导入车辆时也会导入shared模型中的bonnetcam前缀的车头视角模型。请给它们单独放在一个集合内。然后当导入器发现用户单独选择导入shared模型时，请直接完整导入，不要导入附属lod。int_a和int_b是第一人称车内视角模型，请将它们视作独立lod导入，不要当作附属lod导入。

---

## 2. LOD G / H 的轮子

### 2.1 实测：`_shared.m3g` 的轮子只到 F

463 台有 `_shared.m3g` 的车，按 LOD 字母统计"有轮子网格的车数"：

| LOD | 有轮子的车 | 构成 |
|---|---|---|
| A | 463 | TYRE+WHEEL 314、再加 WHEEL_REAR 149 |
| B | 463 | 同上 |
| C | 463 | TYRE+WHEEL 315、再加 WHEEL_REAR 148 |
| D | 463 | TYRE+WHEEL 281、+WHEEL_REAR 148、只有 WHEEL 32、只有 TYRE 1、TYRE+WHEEL_REAR 1 |
| E | 463 | TYRE+WHEEL 274、+WHEEL_REAR 147、只有 WHEEL 41、TYRE+WHEEL_REAR 1 |
| F | 463 | 只有 WHEEL 462、TYRE+WHEEL 1 —— **预装配（跨左右）** |
| **G** | **0** | — |
| **H** | **0** | — |

⇒ 用户说的"lod_g 用的也是 lod_f 的轮子"完全正确：游戏在 G 级复用 F 的预装配轮子。
`wheel_set(lod="G")` 之前严格按字母过滤，所以返回空 `WheelSet`，LOD G 导出来没有轮子。

### 2.2 修法

```python
#: The shared file stops at LOD F, which is already assembled across the car.
#: The game reuses it for LOD G, and drops the wheels altogether at LOD H.
WHEEL_LOD_FALLBACK = {"G": "F"}
NO_WHEEL_LODS = ("H",)


def wheel_lod_for(lod):
    """Which ``_shared.m3g`` level holds the wheels of body LOD ``lod``."""
    return WHEEL_LOD_FALLBACK.get((lod or "A").upper(), lod)
```

`wheel_set()` 开头：

```python
if (lod or "A").upper() in NO_WHEEL_LODS:
    return WheelSet()
lod = wheel_lod_for(lod)
```

`build_plan()` 里 `no LOD_H wheel mesh` 这条警告也按 `NO_WHEEL_LODS` 跳过 —— H 级没有轮子
是**设计如此**，不是数据缺失。

### 2.3 实测（`2012_lexus_lfa`）

```
F  meshes=25 wheels=1 pre=True  fit=None            LOD_F_WHEEL_mm_wheel
G  meshes=2  wheels=1 pre=True  fit=None            LOD_F_WHEEL_mm_wheel   ← 复用 F
H  meshes=1  wheels=0 pre=False fit=(1.189,1.188)   ← 无轮子
```

G 的轮子与 F 完全一样：`x -0.95 .. 0.95`（跨整车）、站在地面上，`pre_assembled=True`
所以不做尺寸拟合、不缩放、不平移。

---

## 3. 驾驶员导入

### 3.1 资源在哪

`<depot>/driver/`：

| 文件 | 内容 |
|---|---|
| `driver_lod_a.m3g` | **15 个部件**，每个绕自己的关节建模 |
| `driver_lod_b.m3g` | 15 个部件，同一姿势的低模 |
| `driver_lod_c.m3g` / `driver_lod_d.m3g` | **各 1 个网格**（`02_legs_source_LOD_C/D`），腿已在座位里 |
| `driver_lod_c_<car>.m3g` / `driver_lod_d_<car>.m3g` | 12 台车的定制版（`mclaren_mp4x`、`porsche_909`、`f1_mp44`…） |
| `driver.banim` | 通用坐姿动画 |
| `driver_<car>.banim` | 35 个按车定制（`caterham`、`countach`、`atom`、`formula_e`…） |

15 个部件名（`driver_lod_a`，顶点数为 LOD A）：

```
00_helmet 263  01_body 573  02_groin 68
03_leftarm 94  04_leftforearm 83  05_lefthand 174
06_rightarm 94 07_rightforearm 83 08_righthand 168
09_leftleg_upper 65 10_leftleg_lower 86 11_leftleg_foot 59
12_rightleg_upper 65 13_rightleg_lower 86 14_rightleg_foot 59
```

全部 `material_name = 'driver'`、`material_id = 0`、UV 齐全、**`_unparsed = 0`（没有 keyframe 表）**
⇒ 部件按**序号**绑轨道（`track i` ↔ 网格名前两位 `%02d`），这一点与尾翼相反。

### 3.2 贴图：必须特判

`materials.bin` 里**没有** `driver` 材质，`liveryStringTable` 里**没有** `driver` 槽
⇒ 材质名 `driver` 只存在于 `.m3g` 自己的 `T_MATERIAL_LIST`。
贴图固定取 `vehicles/common/driver.dxt.dds.z`（512×512），另有 8 个皮肤：

```
driver.dxt.dds.z（默认） driver_alesi  driver_alonso  driver_berger
driver_brad_keselowski  driver_ferrari  driver_joe_logano  driver_raikkonen
driver_yellow_helmet_red_suit
```

### 3.3 位置单位：**所有 `.banim` 都是 1/65536 m**

`rr3lib/rig.py` 的 `POS_SCALE` 原来写 `1.0/32768.0`（当时以为只有 wing 用 1/65536），
这次改正为 `1.0/65536.0`。三路证据：

1. **MonkeyTool `nodeMatrix()`**（`re\mt\Monkey-Tool-main\src\nfsnl_rr3.cpp:614-634`）对**每个**
   banim 统一 `/ 65536.0f`，旋转 `kTurn = 6.28318530718f / 65536.0f`
   （65536 counts = 360° ⇒ `ROT_SCALE = π/32768`，与我们的一致）。
2. **身高**：`driver_lod_a` 按 t=0 装配，1/65536 → `size = [0.573, 1.089, 1.320]`（身高 1.089 m，
   坐姿合理）；1/32768 → `[0.981, 1.692, 2.324]`（宽 0.98 m、纵深 2.32 m，明显错）。
3. **手到方向盘**：以 `POINT_DRIVER` 为驾驶员原点，量左右手到方向盘中心的距离。
   1951 F1 F375 的轮缘 r = 0.201 m：1/65536 → 左手 0.205 / 右手 0.187 m（在轮缘上）；
   1/32768 → 0.376 / 0.352 m（在轮外一倍半径处）。

### 3.4 朝向：`flip_driver` 是必须的，`convert_axes` 几乎无影响

`_anim_matrix(convert, flip_driver)` 最终只做一件事：

```python
def _anim_matrix(convert: bool, flip_driver: bool):
    """The anim→Blender axis swap, when there is one to make.

    ``anim_to_model`` maps ``(x, y, z)`` to ``(x, z, -y)`` and the Blender
    conversion maps that to ``(x, -z, y)``; the pair cancels, so a joint
    offset needs no axis change at all.  What is left is the turn: the car
    model's nose ends up on -Y and the figure is modelled facing +Y, so the
    driver has to be turned round.
    """
    if flip_driver:
        return Matrix(((-1.0, 0.0, 0.0), (0.0, -1.0, 0.0), (0.0, 0.0, 1.0)))
    return Matrix.Identity(3)
```

四种组合实测（4 台车，`chest.y > wheel.y` 才算"胸在方向盘之后"）：

| `convert_axes` | `flip_driver` | 结果 |
|---|---|---|
| False | False | 胸在轮前 ✗ |
| False | True | 胸在轮后 ✓ |
| True | False | 胸在轮前 ✗ |
| True | True | 胸在轮后 ✓ |

`convert_axes` 只带来 0.4 mm 级差异（两次抵消），`flip_driver` 决定面朝哪边。

### 3.5 摆放模式：`NODE` 才是游戏的做法

旧代码用**包围盒中心**做旋转支点（`BONE`/`JOINT`），结果整体 bbox 高度 1.40 m（应 1.09 m）——
因为每个部件都绕"自己的 bbox 中心"转，关节就被拉散了。

```python
if placement == "NODE":
    # the part is modelled round its own joint, so the node matrix
    # applies about the origin: no bounding-box centre to undo
    ob.matrix_world = (
        Matrix.Translation(anim @ Vector(ps.position))
        @ rot_bl.to_4x4()
    )
    ob.keyframe_insert("location", frame=frame_no)
    ob.keyframe_insert("rotation_euler", frame=frame_no)
    continue
```

实测 bbox 高度：`NODE` 0.933 m、`BONE` 1.401 m、`JOINT` 1.333 m。默认改 `NODE`。

### 3.6 手落在轮缘上的实测

以 `ANCHOR_POINT_DRIVER` 为驾驶员原点：

| 车 | 方向盘轮缘 | 左手 | 右手 |
|---|---|---|---|
| `1951_ferrari_f1_f375` | 0.201 m | 0.205 m | 0.187 m |
| `1957_ferrari_500_trc` | 0.186 m | 0.213 m | 0.170 m |
| `1962_ferrari_250_gto` | 0.171 m | 0.207 m | 0.193 m |
| `2013_caterham_seven_620r` | 0.125 m | 0.136 m | 0.140 m |

四台车的手都在轮缘附近（±3 cm），且头盔 z 都高于脚 z。

### 3.7 动画：15 条轨道里只有 9 条真的动

`driver.banim`：`tracks = 15`、`duration_ms = 1980.0`、`names = 0`、`properties = 0`，
每个 track 14 条曲线但只有 ch0..ch5 有值。按通道唯一值个数（61 key）：

- **会动**：track0（头）、1（胸）、3/4/5（左臂/前臂/手）、6/7/8（右臂/前臂/手）
- **不动**：track2（骨盆）、track9..14（双腿）—— 全部 `uniq = 1`

`_c`/`_d` 是单网格、已在座位里，所以 `parts * 2 < num_tracks` 时**不摆姿态**（`posed = 0`）。

### 3.8 新增 API

`rr3lib/driver.py`（175 行，纯 Python）：

| 函数 | 作用 |
|---|---|
| `driver_dir(depot)` | `<depot>/driver` |
| `model_for(depot, lod="a", car=None)` | 先找 `driver_lod_<lod>_<car>.m3g`，剥掉年份前缀再找，最后 `driver_lod_<lod>.m3g` |
| `available_lods(depot)` | `['A','B','C','D']` |
| `banim_for(depot, car=None)` | `(path, matched)`，key 出现在车名里即命中，最长 key 胜 |
| `skins(depot)` | 9 个皮肤，`driver.dxt.dds.z` 排第一 |
| `texture_for(depot, skin="")` | `alesi` / `driver_alesi` / `driver_alesi.dxt.dds.z` 三种写法都认 |
| `selftest(depot)` | 全库配对自检 |

`rr3_blender_addon` 里：

```python
import_driver(depot, *, lod="a", car="", skin="", fps=30.0, max_frames=0,
              placement="NODE", convert_axes=True, flip_driver=True,
              with_root=True, textures=True, parent_collection=None)
```

返回 `{"model", "banim", "banim_matched", "objects", "root", "collection", "posed", "frames"}`。

Operator：`import_scene.rr3_driver`（10 个参数：`depot` / `car` / `lod` / `skin` / `fps` /
`max_frames` / `placement` / `flip_driver` / `with_root` / `textures`）。

根空物体：`<car>_DRIVER_ROOT`（`rr3_driver_root = True`），所有部件挂上去，
移动它就能整体搬动驾驶员。

`banim_for` 的匹配规则（27 台命中）：`driver_caterham` → `2013_caterham_seven_620r`、
`driver_countach` → `2021_lamborghini_countach_lpi`、`driver_atom` → `2013_ariel_atom_35`。
8 个匹配不上（`919_lmp1`、`f1_1951`、`f1_1995`、`f1_mp44`、`spyder_rs`、`toyota_gts_ae86`、
`vw_idr`、`xbow`），退回 `driver.banim`。

---

## 4. 相机壳与内饰独立导入

### 4.1 `BONNETCAM` / `LIT_`

`_shared.m3g` 里除了轮子还有：

```
LOD_A_BONNETCAM_BODY_mm_ext / _mm_lights / _mm_misc
LOD_A_BONNETCAM_HOOD_mm_badges / _mm_ext
LOD_A_LIT_EXHAUST_GLOW_mm_headlight_glow
LOD_A_LIT_HEADLIGHT_GLOW_LEFT/RIGHT_mm_headlight_glow
LOD_A_LIT_TAILLIGHT_GLOW_LEFT/RIGHT_mm_headlight_glow
```

463 台车的 `_shared.m3g` **全部**有 `BONNETCAM`，430 台还有 `LIT_*_GLOW`。
相机壳是"车身里的第二个车身"（和引擎盖 z-fighting），发光片是面向相机的精灵。

```python
BONNETCAM_TOKEN = "BONNETCAM"
GLOW_TOKEN = "LIT_"


def _is_camera_mesh(mesh_name: str) -> bool:
    """True for the bonnet-camera shell and the emissive glow quads."""
    base = (mesh_name or "").split("_mm_")[0].upper()
    return BONNETCAM_TOKEN in base or base.startswith("LOD_") and GLOW_TOKEN in base
```

`separate_camera`（默认开）时进 `<car>_LOD<lod>_camera`，对象带 `rr3_camera = True`。

注意：**车身文件里 375/463 台也有 `BONNETCAM`**，但都是 `LOD_A_BONNETCAM_HOOD_DAMAGE_*`
（带 `DAMAGE`），已经被损伤集合收走了。所以 `separate_camera` 对普通车身 LOD 影响很小，
主要作用于 `lod="shared"`。

### 4.2 `shared` / `int_a` / `int_b` 是完整模型

- `_shared.m3g`：43 个网格（轮子 + 相机壳 + 发光片）
- `_int_a.m3g`：44 个网格，`LOD_A_INT_BODY_mm_ext`、`LOD_A_INT_DOOR_LEFT_mm_mat00..05`…
- `_int_b.m3g`：43-44 个网格，**同时含 `LOD_A_*` 与 `LOD_B_*`**
- `int` 没有自己的 banim，但有 `_int.points`、`_int.dxt.dds.z`、`_int_shadows.dxt.dds.z.bin`
- `_frontend.m3g`：3 个网格（`LOD_A/B/C_CLOAK_mm_cloak`，车罩）

`car_from_path()` 原来对这三个只剥后缀、`lod` 返回 `None`，于是被当成"缺 LOD 的车身"。
现在返回 `lod = "shared" / "int_a" / "int_b"`，`build_plan()` 里 `standalone` 分支：

```python
standalone = (lod or "").lower() in ("shared", "int_a", "int_b")
a.shared_file = None if standalone else (...)
a.wing_banim = None if standalone else (...)
if standalone:
    a.points_file = None
    if lod.lower().startswith("int"):
        int_pts = os.path.join(car_dir, f"{car}_int.points")
        if os.path.exists(int_pts):
            a.points_file = int_pts
```

⇒ 不装轮子、不装空力、不报"缺 shared / 缺 wing.banim"，集合名 `<car>_shared` / `<car>_int_a`，
也不建 `_camera` / `_damaged` 子集合（它们本身就是完整模型）。

### 4.3 顺手修掉的重复集合

`import_m3g_file()` 原来总是自己 `_collection(<文件名>)`，整车导入时于是出现
`<car>_shared` + `<car>_shared.001` 两个集合。现在多一个 `collection=None` 参数：

```python
coll = collection if collection is not None else _collection(stem)
```

整车导入与驾驶员导入都传自己的集合进去。

---

## 5. 删掉的功能

`all_lods`（"一次导入全部 LOD"）整段删除：

- `import_vehicle_all_lods(car_dir, car, *, lods=None, **kwargs)`
- `_available_lods(car_dir, car)`
- `IMPORT_OT_rr3_vehicle.all_lods` 属性与 `execute()` 里的分支
- `tools/smoke_wheels.py` 里的 `=== all LODs ===` 一段

理由：它只是循环调 `import_vehicle_file`，每个 LOD 都重算一次材质/贴图，慢，而且
单 LOD 导入已经够用。用户报的 bug 不值得修，删掉更干净。

---

## 6. 测试

```powershell
& "C:\Program Files\Blender Foundation\Blender 4.5\blender.exe" -b --factory-startup --python tools\smoke_wheels.py
& "C:\Program Files\Blender Foundation\Blender 4.5\blender.exe" -b --factory-startup --python tools\smoke_driver.py
& "C:\Program Files\Blender Foundation\Blender 4.5\blender.exe" -b --factory-startup --python tools\smoke_materials.py
& "C:\Program Files\Blender Foundation\Blender 4.5\blender.exe" -b --factory-startup --python tools\smoke_addon.py
python tools\test_car.py
python tools\sync_rr3lib.py --check
```

| 套件 | 结果 |
|---|---|
| `smoke_wheels.py` | `WHEEL SMOKE: PASS (107 ok, 0 failed)`（原 96，删 3 加 14） |
| `smoke_driver.py` | `DRIVER SMOKE: PASS (38 ok, 0 failed)`（新建） |
| `smoke_materials.py` | `MATERIAL SMOKE: PASS (113 ok, 0 failed)` |
| `smoke_addon.py` | `SMOKE TEST: PASS`（16 项） |
| `test_car.py` | `CARTEST: PASS`（13 步） |
| `sync_rr3lib.py --check` | `already in sync`（28 模块） |

`smoke_driver.py` 覆盖：

- 库：4 个 LOD、9 个皮肤、默认皮肤排第一、`driver_lod_c_mclaren_mp4x` 优先、
  `driver_caterham.banim` 命中、无定制动画退回 `driver.banim`
- 装配：15 个部件、单集合、60 帧、15/15 有 action、根空物体在原点、15/15 挂在根下、
  一个 `driver` 材质、贴图 512×512 且已 pack、贴图接在 Base Color 上
- 坐姿：5 台车"头高于脚"、4 台车"双手够到轮缘"（< 轮缘 ×1.30）、4 台车"胸在方向盘之后"
- 低模：LOD C 单网格不摆姿态、`with_root=False`、换皮肤 `driver_raikkonen`

---

## 7. 相关文档

| 文档 | 内容 |
|---|---|
| `docs/插件使用手册.md` | §6.8 驾驶员、§2 排查表新增行 |
| `docs/游戏材质与涂装.md` | 驾驶员贴图特判 |
| `rr3_blender_addon/README.md` | 参数表、§6.9 驾驶员 |
| `docs/动画与部件-格式.md` | banim 位置单位 1/65536（本节 3.3） |
| `docs/HANDOFF-20261028-8-cab变体-common贴图-损伤分组.md` | 上一轮 |

---

## 8. 环境备忘

- depot 根 `E:\DXT_480x320+960x640+2048x1536数据包-Build260716\files\.depot`。
  **中文路径在 pwsh here-string 里写死会变乱码**，用 `glob.glob(r"E:\DXT*Build260716")[0]`。
- Blender headless 的 stderr 有几百行 `Failed to remove: ... PermissionError(13, '拒绝访问。')`
  （扩展清理噪音）；stdout 单独重定向到文件再读，`Select-String` 加 `-CaseSensitive`。
- 同进程连续导入多台车，每台前要 `bpy.ops.wm.read_factory_settings(use_empty=True)`
  + `bpy.ops.preferences.addon_enable(module="rr3_blender_addon")`。
- `bpy.ops.import_scene.rr3_vehicle` 只认 `filepath=`，且必须指具体 `.m3g`。
- `bpy.data.images` 里加载过的图在 `read_factory_settings` 后不一定还在，验证贴图时
  要现查 `bpy.data.images.get(...)`，别缓存引用。
