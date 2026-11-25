# RR3 `.points` 锚点表：完整格式与全库实测

> 本文基于 **927 个 `.points` 文件**（546 台车，463 个 `<car>.points` + 464 个 `<car>_int.points`）
> 逐字节走完、零 warning、零 trailing 得出，全部可复现。
> 解析器：`rr3lib/points.py`；导出器：`rr3dump.py --format txt|json`。

---

## 1. 容器布局

全部小端，无对齐填充：

```
u16  version            ; 全库 927/927 = 2
u16  recordCount
recordCount x record:
    u16  type           ; 0=point 1=spline 2=hinge 3=transform
    u16  size           ; 后面的载荷长度（name + extra 一起算）
    cstr name           ; NUL 结尾 ASCII，长度计入 size
    ...  extra          ; size - len(name) - 1 字节
u16  overrideCount
overrideCount x override:
    cstr name
    cstr value          ; 自由文本，如 b"SCALE 0.7\r\n"
```

`rr3lib/points.py` 的 `PointRecord.size` 是**载荷**长度（不含 4 字节记录头），
所以 `offset + 4 + size` 就是下一条记录的起点。全库实测这条恒等式 12,719 次全部成立。

### 每类型的 extra 布局（全部精确吃到末尾，零 slack）

| type | 名称 | extra 长度 | 布局 |
|---|---|---|---|
| 0 | point | 12 | `3 × f32` 位置（引擎单位） |
| 1 | spline | 变长 | `u16 splineCount`，然后 splineCount × (`u16 pointCount` + pointCount × `3 × f32`) |
| 2 | hinge | 48 | `3 × f32` 位置 + `9 × f32` 行主序 3×3 朝向矩阵（行 = 局部轴） |
| 3 | transform | 64 | `16 × f32` 行主序 4×4；最后一列是平移且 w=1.0；左上 3×3 是纯旋转 |

**type 1 没有 flags 字段**——第一个 u16 就是 spline 条数。旧版 docstring 把它当 flags、
把第二个 u16 当点数，在"只有 1 条 spline"时结果相同所以一直没暴露；实测有 105 条记录
带多条 spline，其中 **68 条各 spline 点数不等**（如 `[10, 10, 13]`、`[19, 15]`、`[9, 2, 2]`），
旧解析在这些文件上必然错位。已在 2026-10-27 修正。

---

## 2. 单位与轴向

* **位置单位 = 1/32 米**（引擎世界单位）。`米 = 原始值 / 32`。
* 文件空间：`x = 右`，`y = 前`，`z = 上`；`z = 0` 是**地面**。
* 模型空间（m3g 网格）用的是 `x=右, y=上, z=沿车长`，换算：

```python
model.x =  points.x / 32
model.y =  points.z / 32      # 上
model.z = -points.y / 32      # 沿车长（前方为负）
```

`rr3lib/parts.py` 的 `anim_to_model()` 就是这三行。

**精度验证**：FORMATS.md 给的 1979 Porsche 935 例子里，
`POINT_BRAKELIGHT_LEFT` 算出 (-0.459, 0.473, 1.849)，网格实际 (-0.459, 0.471, 1.841)，
误差 **8 mm / 4.7 m 车长**。我们自己在 611 上做的尾翼/轮子对位也是同量级。

---

## 3. 全库统计（927 文件 / 12,719 条记录）

| | `.points`（463 个） | `_int.points`（464 个） | 合计 |
|---|---|---|---|
| type 0 point | 6,543 | 1,791 | 8,334 |
| type 1 spline | 328 | 0 | 328 |
| type 2 hinge | 3,486 | 552 | 4,038 |
| type 3 transform | 16 | 3 | 19 |
| **合计** | 10,373 | 2,346 | **12,719** |

* 每文件记录数 1..37。
* **927/927 文件零 warning、零 trailing bytes**——解析器完全正确。
* hinge 的 3×3 矩阵：**4,038 条行范数全部 = 1.000000（误差 <1e-3），行列式 0.999999..1.000001**
  ⇒ 纯旋转、右手系、无缩放无镜像。
* spline 名字只有 4 种：`SPLINE_SPECULAR`(163)、`SPLINE_SPECULAR_REVERSE`(163)、
  `SPLINE_REVERSE`(1)、`SPLINE_REVERSE_SPECULAR`(1)。161 对同名成对出现，仅 26 对字节相同。

### 铰链矩阵里到底存了什么（2026-11-25 复扫 929 文件 / 4,048 条 hinge）

§3 那次算的是 927 文件 4,038 条；这里把范围放到全部 929 个 `.points` 文件，多出的两个文件带来 10 条。
矩阵本身的性质和当时一致（行范数 1、行列式 1.000000），下面这些是那次没看的**含义**：

* **只有 453 种不同的矩阵**，前 7 种就占了约 2,700 条 —— 全是轴置换 + 符号翻转（元素只有 0 / ±1）。
  说明这是**离散的约定**，不是逐车量出来的微调。
* **左右成对的车，两侧矩阵差 180°**（绕局部某轴半圈）：`MIRROR` 332 对、`FRONTBUMPER` 226 对、
  `BOOT` 142 对、`DOOR` 61 对。例外是 `HOOD`：234 对全部**完全相同**（0°）。
  少数 `MIRROR` 是 0°（21 对）或 120°/90°（共 7 对），那几台车大概用了不同代的导出工具。
* **表针是唯一非轴对齐的一族**：`HINGE_NEEDLE_RPM` 中位 **14.5°**、`HINGE_NEEDLE_SPEED`
  **15.7°**（绕车体 X 轴的倾角，即仪表盘面在座舱里的俯仰），范围 0–107.9°；
  方向盘上的表针（`HINGE_STEERING_WHEEL_NEEDLE_*`）是 **90°**。
* 名字上的小坑：`HINGE_BOOD_LEFT/RIGHT`（各 1 台）是官方数据里的**拼写错误**，和 `BOOT` 并存。

**推论**：这 9 个数是**零件自己的局部坐标系**（三行 = 局部 X/Y/Z 在车体坐标里的方向），
引擎用它决定"这个铰链开合的方向"。左右车差 180° 正是为了让**同一个局部旋转值**在两侧
都朝外开；`HOOD` 两侧相同则是因为引擎盖绕的是横向轴，左右对称不用翻。

**还没证实的一条**：引擎具体绕**局部哪个轴**转。观察支持"局部 X"——引擎盖矩阵里局部 X 就是车体 X
（两侧都是 `(1,0,0)`），表针的局部 X 又正好是表盘法线；但这只是拟合得好，没有直接证据。
要钉死：把某台车门 hinge 的矩阵改一笔（绕某轴转 90°）推上屏，看门往哪个方向开。

**插件怎么处理**（已经是对的，不用改）：导入时把这 9 个数写到空物体的
`rotation_euler` 上（所以能在视口里看见、能直接拖），同时原值另存在 `rr3_orientation`；
导出时用空物体的实际旋转反算矩阵，若和原值一致就**原样写回那 9 个 float**——
避免"打开再保存就变一位"的文件，那种文件没法 diff。

### `.points` vs `_int.points` 分工

`_int.points` 是**座舱内部**锚点，只出现 40 种名字，且和 `.points` 几乎不重叠：

* 只在 `_int.points` 里出现：所有 `POINT_NEEDLE_*`（表针）、`HINGE_NEEDLE_*`、
  `POINT_STEERING_WHEEL_NEEDLE_*`、`POINT_GEARSTICK` / `_HAND`、`POINT_NET_CENTER`、
  `TRANSFORM_DRAG_RACE_VIEW`。
* `POINT_STEERING_WHEEL` 在 `_int.points` 里出现 365 次（`.points` 里 0 次）。
* 546 个车目录里 **83 个完全没有 `.points`**（只有 `livery/`，多为未使用的占位/别名车），
  1 个（`2019_astonmartin_gte`）只有 `_int.points`。

---

## 4. ★ 引擎侧权威名单：79 条硬点名

`.so` 里有一张**连续的 79 个 8 字节槽**的表，索引就是引擎内部 id：

**地址 `0x01EEB458` .. `0x01EEB6C8`**（`re/lib/libRealRacing3.so`，imageBase 0x100000）

| # | 名字 | # | 名字 |
|---|---|---|---|
| 0 | POINT_WHEEL_FL | 40 | HINGE_FRONTBUMPER_RIGHT |
| 1 | POINT_WHEEL_FR | 41 | HINGE_MIRROR_LEFT |
| 2 | POINT_WHEEL_BL | 42 | HINGE_MIRROR_RIGHT |
| 3 | POINT_WHEEL_BR | 43 | HINGE_HOOD_LEFT |
| 4 | POINT_WHEEL_FL_PIVOT | 44 | HINGE_HOOD_RIGHT |
| 5 | POINT_WHEEL_FR_PIVOT | 45 | HINGE_BOOT_LEFT |
| 6 | POINT_STEERING_WHEEL | 46 | HINGE_BOOT_RIGHT |
| 7 | POINT_DRIVER | 47 | HINGE_DOOR_LEFT |
| 8 | POINT_NEEDLE_SPEED | 48 | HINGE_DOOR_RIGHT |
| 9 | POINT_NEEDLE_RPM | 49 | HINGE_GULLDOOR_LEFT |
| 10 | POINT_STEERING_WHEEL_NEEDLE_SPEED | 50 | HINGE_GULLDOOR_RIGHT |
| 11 | POINT_STEERING_WHEEL_NEEDLE_RPM | 51 | HINGE_DOOR_LEFT_REAR |
| 12 | POINT_BRAKELIGHT_LEFT | 52 | HINGE_DOOR_RIGHT_REAR |
| 13 | POINT_BRAKELIGHT_RIGHT | 53 | HINGE_NEEDLE_SPEED |
| 14 | POINT_BRAKELIGHT_CENTER | 54 | HINGE_NEEDLE_RPM |
| 15 | POINT_HEADLIGHT_LEFT | 55 | HINGE_STEERING_WHEEL_NEEDLE_SPEED |
| 16 | POINT_HEADLIGHT_RIGHT | 56 | HINGE_STEERING_WHEEL_NEEDLE_RPM |
| 17 | POINT_GEARSTICK | 57 | HINGE_STEERING_WHEEL |
| 18 | POINT_GEARSTICK_HAND | 58 | HINGE_STRUT_LOWER_FRONT_LEFT |
| 19 | POINT_INTERIOR_HUD | 59 | HINGE_STRUT_UPPER_FRONT_LEFT |
| 20 | POINT_EXHAUST | 60 | HINGE_STRUT_LOWER_FRONT_RIGHT |
| 21 | POINT_STEERING_ARM_ANCHOR_PIVOT_LEFT | 61 | HINGE_STRUT_UPPER_FRONT_RIGHT |
| 22 | POINT_STEERING_ARM_ANCHOR_PIVOT_RIGHT | 62 | HINGE_STRUT_LOWER_REAR_RIGHT |
| 23 | POINT_STEERING_STRUT_LEFT_END | 63 | HINGE_STRUT_UPPER_REAR_RIGHT |
| 24 | POINT_STEERING_STRUT_RIGHT_END | 64 | HINGE_STRUT_LOWER_REAR_LEFT |
| 25 | POINT_NET_CENTER | 65 | HINGE_STRUT_UPPER_REAR_LEFT |
| 26 | POINT_UNDERBODY_SPARKS | 66 | HINGE_AXEL_REAR_RIGHT |
| 27 | POINT_NEEDLE_LINEAR_SPEED | 67 | HINGE_AXEL_REAR_LEFT |
| 28 | POINT_NEEDLE_LINEAR_RPM | 68 | HINGE_STEERING_ARM_LEFT |
| 29 | POINT_STEERING_WHEEL_NEEDLE_LINEAR_SPEED | 69 | HINGE_STEERING_ARM_RIGHT |
| 30 | POINT_STEERING_WHEEL_NEEDLE_LINEAR_RPM | 70 | HINGE_STEERING_ARM_ANCHOR_LEFT |
| 31 | POINT_LIGHTBAR_FRONT | 71 | HINGE_STEERING_ARM_ANCHOR_RIGHT |
| 32 | POINT_LIGHTBAR_REAR | 72 | HINGE_HOOD_WING_LEFT |
| 33 | POINT_LIGHTBAR_LEFT | 73 | HINGE_HOOD_WING_RIGHT |
| 34 | POINT_LIGHTBAR_RIGHT | 74 | HINGE_WING_REAR_LEFT |
| 35 | POINT_LIGHTBAR_CENTER_FRONT | 75 | HINGE_WING_REAR_RIGHT |
| 36 | POINT_LIGHTBAR_CENTER_REAR | 76 | HINGE_WING_REAR |
| 37 | HINGE_REARBUMPER_LEFT | 77 | HINGE_DRIVER |
| 38 | HINGE_REARBUMPER_RIGHT | 78 | HINGE_FAN |
| 39 | HINGE_FRONTBUMPER_LEFT | | |

37 个 `POINT_*` + 42 个 `HINGE_*` = 79，与 FORMATS.md §1372 的
"37 POINT_ names and 42 HINGE_ names" 完全吻合。
索引 6 = `POINT_STEERING_WHEEL`、57 = `HINGE_STEERING_WHEEL` 也逐条对上。

### 怎么找到的（关键方法论，之前一直踩坑）

`libRealRacing3.so` 是 PIE。`.data.rel.ro` 里这些字符串指针**在文件中是 0**，
真值存在 `.rela.dyn` 的 `R_AARCH64_RELATIVE` **addend** 里。
⇒ **朴素 8 字节指针扫描必然 0 命中**，这就是之前 `reloc_scan.py` 找
`liveryStringTable.bin.nct`、`car_paint_gloss` 全部失败的原因。

正确做法（`analysis/reloc_scan.py` 已实现）：

```
python analysis\reloc_scan.py re\lib\libRealRacing3.so point 0x0042B32B
```

原理：解析 ELF section header → 取 `.rela.dyn`（151,591 条）→ 每条 24 字节
`<QQQ offset, info, addend>`，只有 `(info & 0xFFFFFFFF) == 1027` 才是 RELATIVE →
把 `addend` 与目标字符串 vaddr 比对 → 命中的 `offset` 就是指针槽地址。

⚠ 两个误命中必须排除：`POINT_NAME` @0x00435B3D（上下文 `DIST_POINT_NAME`）、
`POINT_PERCENT` @0x004656F8（上下文 `TWEAKABLE_DRIFT_TURNING_POINT_PERCENT`）。
排除后正好 79 个连续槽。

### `.so` 里与 `.points` 相关的报错串

| 字符串 | file offset | vaddr |
|---|---|---|
| `Missing points file %s.` | 0x0042B32B | 0x0052B32B |
| `Wrong version of car points %s. Found %d, expected %d` | 0x003BD73E | 0x004BD73E |
| `Unused car transform data '%s' exists in points file '%s'.` | 0x003A3477 | 0x004A3477 |
| `WARNING: Unused car points data '%s' exists in points file '%s'.` | 0x00422C9D | 0x00522C9D |
| `WARNING: Unused car hinge data '%s' exists in points file '%s'.` | 0x00455D36 | 0x00555D36 |
| `WARNING: old spline data '%s' exists in points file '%s'.` | 0x0047F93E | 0x0057F93E |
| `Points file RGB parse error - expected RGB %f,%f,%f ` | 0x0044D071 | 0x0054D071 |
| `SPLINE_SPECULAR_REARBUMPER` / `SPLINE_SPECULAR_FRONTBUMPER` | 0x0045E3C1 / 0x0047F990 | |
| `.points` / `_int.points` | 0x004018B0 / 0x00465F12 | |

`TRANSFORM_DRAG_RACE_VIEW` 在 `.so` 里 **0 命中** ⇒ type 3 的名字是数据里的自由文本，
引擎只按 "Unused car transform data" 发警告，不按名字识别。

---

## 5. 命名匹配规则：**基名 + 可选数字后缀**

全库 176 个不同记录名（POINT 124 / HINGE 43 / SPLINE 4 / TRANSFORM 5）。
拿 79 条引擎表去匹配：

* verbatim 命中 **9,256** 条记录
* 基名 + 数字后缀命中 **3,072** 条记录
* 真正的孤儿 **18 条（3.1%）**

⇒ 引擎是按 **前缀匹配 + 编号后缀** 归组的。`POINT_BRAKELIGHT_LEFT_01..09`、
`POINT_HEADLIGHT_LEFT_1..06`、`POINT_EXHAUST_01..06`、`POINT_NEEDLE_RPM_1..4`、
`POINT_WHEEL_FL001` 全都是同一锚点的多实例（多灯泡 / 多排气管 / 多表针）。

### 18 个孤儿（数据里存在但引擎表里没有基名）

| 名字 | 条数 | 说明 |
|---|---|---|
| `SPLINE_SPECULAR` / `SPLINE_SPECULAR_REVERSE` | 各 163 | 引擎另有 spline 专用名字（见 .so 报错串） |
| `POINT_BRAKELIGHT` | 28 | 无左右后缀，可能落到 CENTER |
| `POINT_BRAKELIGHT_BOOT` | 9 | |
| `TRANSFORM_EXHAUST_01/02/03/004` | 7/7/1/1 | type 3 |
| `TRANSFORM_DRAG_RACE_VIEW` | 3 | type 3 |
| `SPLINE_REVERSE` / `SPLINE_REVERSE_SPECULAR` | 各 1 | |
| `POINT_BRAKELIGHT_BOOT_01/02` | 各 1 | |
| `POINT_NEEDLE_RPM_MIN` / `_MAX` | 各 1 | |
| `POINT_EXHAUST_S04` | 1 | |
| `HINGE_BOOD_LEFT` / `HINGE_BOOD_RIGHT` | 各 1 | **数据里的拼写错误：BOOD ≠ BOOT** |

### 引擎支持但本数据包从未使用（6 个，按基名匹配后仍为空）

`POINT_STEERING_WHEEL_NEEDLE_SPEED`、`POINT_INTERIOR_HUD`、`POINT_NEEDLE_LINEAR_SPEED`、
`POINT_STEERING_WHEEL_NEEDLE_LINEAR_SPEED`、`HINGE_STEERING_WHEEL_NEEDLE_SPEED`、
**`HINGE_WING_REAR`**。

（另有 10 个是"只用了带编号的版本"，如 `POINT_LIGHTBAR_*` 只有 `_01.._04`、
`POINT_UNDERBODY_SPARKS` 只有 `_01/_02`、`POINT_NEEDLE_LINEAR_RPM` 只有 `_1.._4`。）

---

## 6. 覆盖表（override）：语义已完全确定

145 / 927 个文件有 override，0 个 trailing。key 只出现在**灯光 / 轮子**锚点上：

| 值形态 | 含义 | 出现 |
|---|---|---|
| `SCALE 0.7` / `SCALE 0.4` / `SCALE 0.85` | 灯光精灵（billboard）尺寸 | 绝大多数 |
| `RGB 255,248,192` | 灯光颜色 | 部分 |
| `INTENSITY .4` | 灯光强度 | 部分 |
| `MapChannel:1 = UVChannel_1\r\n` | **轮子 UV 通道映射** | `POINT_WHEEL_FL/FR/BL/BR` **唯一取值**（17/17/16/16 个文件） |
| `LastPose = undefined` | 初始姿态 | 少数 |

`POINT_BRAKELIGHT_RIGHT` 用 `SCALE 0.4` 的有 17 个、`SCALE 0.5` 的 15 个、`SCALE 0.7` 的 10 个……
⇒ 同一辆车不同灯泡的精灵尺寸可以分别调，这就是"某车尾灯看起来比别人大"的数据来源。

---

## 7. type 3 transform：带朝向的挂点

19 条，只出现在 5 类地方：

| 名字 | 车 | 平移（米） |
|---|---|---|
| `TRANSFORM_EXHAUST_01..004` | `1993_alfa_romeo_155_v6_ti`（4 条，四出排气） | x ±0.30/±0.54, y −2.11, z 0.384 |
| `TRANSFORM_EXHAUST_01/02` | `2013_mercedes_sls_gt3` | x ±0.957, y +0.710, z 0.212 |
| 同上 | `2015_nissan_gtr_lm_lmp1` | x ±0.434, y +0.829, z 0.544 |
| 同上 | `2016_ford_gt_lm` / `2019_ford_gt_lm`（逐字节相同） | x ±0.995, y −0.914, z 0.140 |
| 同上 | `2020_bentley_gt3` | x ±1.019, y −0.420, z 0.176 |
| 同上 | `2020_porsche_911_rsr` | x ±1.02, y −0.80, z 0.21 |
| `TRANSFORM_DRAG_RACE_VIEW` | `2005_porsche_911_gt2` / `2010_porsche_gt3` / `2012_porsche_gt3`（**三条完全相同**） | (−0.353, +0.344, 0.854) |

`TRANSFORM_DRAG_RACE_VIEW` 在 `_int.points` 里（座舱视角机位），
其余全在 `.points`。上 3×3 都是纯旋转（行范数 1.000000）。

⇒ **type 3 是"位置 + 朝向"的完整变换**，type 0 只能给位置。
排气火焰要沿排气方向喷，所以这几台车必须用 type 3。

---

## 8. ★ 尾翼铰链：两条互斥路径

全库扫描的硬结论：

* 有 `HINGE_WING_REAR_LEFT/RIGHT` + `HINGE_HOOD_WING_LEFT/RIGHT` 的**正好 17 台，全是 NASCAR**
  （2015–2022 Chevrolet SS / Ford Fusion / Toyota Camry / Camaro / Mustang），
  **这 17 台全部没有 `_wing.banim`**。
* 反之，**53 台有 `_wing.banim` 的车全部 0 条 WING 铰链**。

例（`2015_chevrolet_ss_nascar.points`）：

| 名字 | 模型坐标（米） |
|---|---|
| `HINGE_WING_REAR_RIGHT` | (0.112, 1.307, 0.623) |
| `HINGE_WING_REAR_LEFT` | (−0.419, 1.283, 0.727) |
| `HINGE_HOOD_WING_LEFT/RIGHT` | (±0.484, 0.830, −1.296)（前部） |

RIGHT 的 3×3 是绕竖轴约 90°（0.7074 / 0.7068…）。17 台位置几乎逐字节相同。

⇒ **主动空力走 `_wing.banim` 动画通道，静态尾翼（NASCAR）走 `.points` 铰链，两条路径互斥。**
这解释了 611 的自定义尾翼为什么不需要任何 `.points` 记录。
若将来要给静态尾翼做开合，得改用 `HINGE_WING_REAR_LEFT/RIGHT` 而不是 banim。

---

## 9. 轮子锚点：轮心高度与三个"半径"

`.points` 的 `POINT_WHEEL_*` 给的是**轮心高度**（z）。全库 463 台有四轮：

* 前轮 z ∈ 0.2740..0.3871 m，后轮 z ∈ 0.2677..0.3860 m
* 前 − 后 ∈ −0.0433..+0.0339 m，均值 −0.0023、**中位数 0.0000**；**150/463 台 |差| > 5 mm**
* 左右对称极好：FL − FR 的 |dz| 均值 **0.000069 m**

⚠ **重要发现：107 台车的四轮 z 完全相同 = 0.31903 m，这是占位值（不是实测值）。**
这一组的车型年份中位数 2012（全集是 2018），即偏老的资产没有单独标轮心高度。
对它们来说"四轮均值当 h"恰好等于占位值，反而没有误差；有误差的是其余 356 台。

### 三个"半径"的关系（188 台可三方对照）

| 定义 | 来源 | 中位数 |
|---|---|---|
| 自由半径 R_free | `suspensiondata` 的 floats **21/22** ÷ 2（前/后轮胎直径） | 0.349 / 0.363 |
| 加载半径 R_load | `carappearances` 外观块 `+4`/`+20`（f1 / f5） | 0.328 / 0.336 |
| 轮心高度 h | `.points` 的 `POINT_WHEEL_*` z | 0.319（占位组）/ 实测组随 R_load |

实测：**R_load = R_free − 0.0165..0.0180 m（约 4.8% ~ 5.0% 的压缩量），188 台全部为正**
（没有一台例外）⇒ 这就是**轮胎受载下沉（tyre deflection）**，不是数据噪声。

`_shared.m3g` 的 `LOD_A_TYRE_mm_tyre` 模板半径全库 **0.2940..0.3024（中位数 0.2990）**，
几乎不随车变化（标准差 0.0015），而 `R_load` 标准差 0.016
⇒ **模板网格是统一尺寸，实际大小靠运行时按外观块缩放**，`corr(模板半径, R_load) = −0.14`（无关）。
轮毂 `LOD_A_WHEEL_mm_wheel` 模板半径 0.2290、宽 0.2410；轮胎模板宽 0.2409。

### 对外观块 8 个 float 的实测解读

`carappearances` 外观块 `+0..+32` 是 8 个 f32（前 4 个前轮、后 4 个后轮）。
**只有 f1/f5 是确证的**，其余是实测值域 + 弱相关性，别当结论用：

| 槽 | 前轮 | 后轮 | 中位数 | 状态 |
|---|---|---|---|---|
| 1 | f1 | f5 | 0.328 / 0.336 | ✅ **加载轮胎半径**（与轮心高、与下沉量三方吻合，见上） |
| 0 | f0 | f4 | 0.293 / 0.314 | ⚠ 像"轮辋/轮毂半径"，但 `f0/f1` 中位数 0.871（= 23 英寸轮辋）明显偏大，**未确证** |
| 3 | f3 | f7 | 0.190 / 0.187 | ⚠ 像宽度，但与网格宽度的相关性只有 +0.16/+0.27，**未确证** |
| 2 | f2 | f6 | 0（233/540 非零） | ⚠ 未知；非零时多为 0.19..0.25 |

相关性全部很弱（|r| ≤ 0.27）的原因是 **`_shared.m3g` 的模板网格几乎是同一尺寸**
（轮胎半径标准差 0.0015 m），真正的大小靠运行时缩放，所以拿模板尺寸去对必然对不上。
要定这 4 个字段，得做"改外观块 → 看轮子变化"的实机二分实验（见 §11）。

### `suspensiondata` 34 个 float 的索引（**修正 FORMATS.md**）

FORMATS.md §1376 说"Floats 22 and 23 (21 and 22 counted from 0) 是前后轮胎直径"。
实测**前半句对、括号里的 0 基索引错了**：

| 0 基索引 | 含义 | 全库取值域 |
|---|---|---|
| **21** | **前轮胎直径（米）** | 0.543..0.770（77 个不同值） |
| **22** | **后轮胎直径（米）** | 0.590..0.800（79 个不同值） |
| 23 / 24 | 前/后轮**压缩量或行程**（米） | 0.003..0.632（中位 0.036/0.043） |
| 0..5 | 倾角/束角类，多为 0 或 −1/−0.75 | −3.5..0 |
| 6 | 前防倾杆/弹簧刚度档 | 0.2 / 0.3 / 0.4 |
| 7,8,9 | 阻尼三档（低速/中速/高速），组合只有 9 种 | 0.25..3.0 |
| 10..20, 25..31 | 全 0（保留） | 0 |
| 32, 33 | 后防倾杆/弹簧档 | 0.7..1.0 |

**验证**：`2018_porsche_911_gt3_rs` → 0.710 / 0.720（FORMATS.md 原文也是 0.710/0.720 ✔）；
`2015_renault_megane_trophy_r` → 0.670 / 0.670（原文 0.670 ✔）；
`2007_lamborghini_reventon` → 0.685 / 0.735 ✔；`2017_bugatti_chiron` → 0.740 / 0.780 ✔。
但按 **22/23** 取，`2010_ford_focus_rs` 会得到 0.686 / **0.024**（荒谬）——
这就是索引偏移 1 的直接证据。

⇒ **`rr3lib` 里凡是要用轮胎直径的地方，都该读 floats 21/22（0 基），不是 22/23。**

---

## 10. Blender 插件：导出到底读什么

插件里 `Import RR3 Anchors (.points)` / `Export RR3 Anchors (.points)` 一对算子，
2026-11-17 重做过一轮，现在的行为是：

### 10.1 导出范围：**整个场景**，不是选中

`rr3_export.points_from_scene()` 默认遍历 `scene.objects` 里的所有 **empty**，
挑"带 `rr3_point_type` 自定义属性"或"名字以 `POINT_` / `HINGE_` / `SPLINE_` / `TRANSFORM_` 开头"的。
之所以默认全场景：一台车的锚点散在四处，导出前先选 142 个空物体是纯体力活。

场景里同时有两台车的锚点时，用导出面板上新增的勾选框 **`Selected empties only`**
（`only_selected=True`，走 `bpy.context.selected_objects`）。这个开关是这次加的，
之前想只导一部分只能先把别的删掉。

### 10.2 每种记录读的是什么

| 类型 | 位置 | 朝向 | 说明 |
|---|---|---|---|
| `point` | 空物体的 `location` | — | 但**没动过的锚点写回文件里的原始数字**（`rr3_point_raw`），保证逐字节一致 |
| `hinge` | 同上 | 空物体的 `matrix_basis` 旋转部分，转回文件坐标系 | 导入时把 3×3 写到 `rotation_euler`，所以**旋转在视口里能看见、能拖**；绕哪个轴开门由这个旋转决定 |
| `spline` | 无（空物体放在质心） | — | 几何存在 `rr3_splines` 属性里（`list;point|list;point`，1/32 m），导出原样写回 |
| `transform` | 4×4 的**最后一行** | 左上 3×3 | 文件是"行主序 + 平移在最后一行"，Blender 是"平移在最后一列"，两边转换见 `_basis_to_file()` / `_file_to_basis()` |

"没动过就写原始数字"这套判断靠 `rr3_point_loc`（导入时记下空物体当时的位置）：
位置没变 → 用文件里的数字；变了 → 用你现在拖到的位置。所以**挪一个锚点会真的生效**，
这在旧版是不生效的（旧版无条件写原始数字）。

### 10.3 名字：一个都不改

旧版导入时会把不认识的记录改名（`SPLINE_SPECULAR` → `POINT_SPLINE_SPECULAR`），
理由是"让导出认得出来"。后果是**名字变了就等于那个锚点没了**：引擎按名字字面查表。
现在：

- 空物体名 = 文件里的名字（`rec.name`），原样；
- 再存一份 `rr3_point_name`，Blender 因为重名加了 `.001` 也还是按原名写回去
  （`2013_astonmartin_gte` 就有两组同名记录）；
- 记录顺序按 `rr3_point_index` 排，所以导入→导出顺序不变。

### 10.4 精度：`.6f` 曾经吃掉半毫米

自定义属性里存位置用的是 `f"{v:.6f}"`。位置是 f32、单位 1/32 m，2.28 m 处一个 ulp 是 2.4e-7，
六位**小数**四舍五入就把值改了 —— 每存一次漂一点点，往返不逐字节一致。
全部换成 `:.9g`（9 位有效数字足够唯一确定一个 f32）后，`raw → 文本 → raw` 无损。

### 10.5 覆盖表也跟着记录走

145 个文件的覆盖表（`SCALE 0.8` / `RGB 255,250,167`，管灯的亮度颜色）挂在对应记录的
`rr3_override` 属性上，导出时按记录顺序写回；找不到记录的名字落到场景属性 `rr3_overrides`。
同名记录可以各自带一条覆盖（4 台车有重复记录，两边都带覆盖），所以这里是 append 而不是
"按名字去重"。

### 10.6 实测：929/960 逐字节一致

`work/cars/tourbillon/_points_all.py`（Blender 里跑，全库 960 个文件）：

```
files 960  byte identical 929  mismatched 0  0-record 31
```

31 个 0 记录的文件（`wheel_*.points`）导出会拒绝写空文件，属预期。
`_points_rt.py` 另外验了"挪一个点只改一条记录"、"转一个铰链只改它的 3×3"、
"transform 记录平移正确"。

---

## 11. 工具

| 工具 | 用途 |
|---|---|
| `rr3lib/points.py` | 解析器（`load()` / `PointRecord` / `format_report()`） |
| `rr3lib/points_write.py` | 写入器（`Anchor` / `PointsDoc` / `build()` / `ENGINE_POINTS` / `engine_name()`） |
| `rr3dump.py --format txt\|json -o <dir> <f.points>` | 人读 / 机器读导出 |
| `analysis/reloc_scan.py <elf> point <hexaddr>` | 从 `.rela.dyn` 反查指针表（唯一可靠办法） |
| `analysis/scan_anchors.py` | 全库锚点普查 |
| `work/cars/tourbillon/_points_rt.py` | 4 个文件的往返 / 挪点 / 转铰链 / transform 自检（Blender headless） |
| `work/cars/tourbillon/_points_all.py` | 全库 960 文件逐字节往返自检（Blender headless） |

`rr3dump.py` 的 JSON 里 type 3 记录带两个键：
`"transform"`（16 个原始 float，行主序 4×4）和 `"transformMetres"`（平移的 3 个米制值）。

---

## 12. 还没做的事

1. **外观块 f0/f3/f2（f4/f7/f6）到底控制什么**：只有 f1/f5 = 加载轮胎半径是确证的。
   要定其余三个，得做"改一个 float → 看轮子变化"的实机二分实验。
2. **type 1 spline 的用途**：328 条全是 `SPLINE_SPECULAR*`，161 对成对出现且大多字节不同。
   猜是"车漆高光带的走向线"（车顶/腰线的高光带），但没在游戏里验证过。
3. **`POINT_NEEDLE_*` 的编号与表盘对应**：`_1.._4` 是四个表针，哪个是转速哪个是时速没实测。
4. **`TRANSFORM_DRAG_RACE_VIEW` 三个车完全相同**（都是 911 系）——是共用资产还是巧合，未查。
5. **83 台没有 `.points` 的车**：确认它们是否在游戏里根本不可选（多为别名/占位目录）。
6. **`rr3lib/parts.py` 的 `height_offset` 是否该用 f1/f5**：目前用四轮 z 均值，
   对 107 台占位车恰好正确、对其余 356 台有约 6~13 mm 偏差。改成 `appearance f1/f5`
   会更准，但需要 `build_plan()` 额外读 `carappearances`，尚未改。
