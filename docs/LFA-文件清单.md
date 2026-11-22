# LFA 相关文件全清单

游戏根：`E:\DXT_480x320+960x640+2048x1536数据包-Build260716\files`
设备根：`/sdcard/Android/data/com.ea.games.r3_rra/files`

车辆名：`2012_lexus_lfa`，车辆 ID **88**

---

## 1. 车辆自己的目录（`vehicles/2012_lexus_lfa/`，31 个文件）

### 1.1 模型（12 个 `.m3g`）

| 文件 | 大小 | 用途 |
|---|---|---|
| `2012_lexus_lfa_a.m3g` | 728,986 | **LOD A 车身**（68 网格 / 546 对象 / 15 材质）——尾翼几何焊在 `LOD_A_BODY_mm_ext` / `_mm_misc` 里 |
| `2012_lexus_lfa_b.m3g` | 618,737 | LOD B |
| `2012_lexus_lfa_c.m3g` | 463,159 | LOD C |
| `2012_lexus_lfa_d.m3g` | 234,914 | LOD D |
| `2012_lexus_lfa_e.m3g` | 151,539 | LOD E |
| `2012_lexus_lfa_f.m3g` | 80,603 | LOD F |
| `2012_lexus_lfa_g.m3g` | 39,233 | LOD G（远景） |
| `2012_lexus_lfa_h.m3g` | 2,663 | LOD H（最远） |
| `2012_lexus_lfa_shared.m3g` | 314,582 | **轮子 / 轮胎 / 刹车盘**（所有 LOD 共用） |
| `2012_lexus_lfa_int_a.m3g` | 663,506 | 内饰（第一人称比赛视角） |
| `2012_lexus_lfa_int_b.m3g` | 548,353 | 内饰（备用） |
| `2012_lexus_lfa_frontend.m3g` | 790,796 | 前段/菜单展示模型 |

> 注：`_b`~`_h` 全部**没有**独立尾翼网格；只有 `_a` 有（而且焊在车身里）。

### 1.2 贴图（10 个 `.dxt.dds.z` + 2 个阴影 `.bin`）

| 文件 | 大小 | 内容 |
|---|---|---|
| `2012_lexus_lfa_ext_shadows_high.dxt.dds.z.bin` | 344,700 | 外部阴影贴图 |
| `2012_lexus_lfa_int_shadows.dxt.dds.z.bin` | 916,273 | 内部阴影贴图 |
| `2012_lexus_lfa_badges.dxt.dds.z` | 33,030 | 车标 |
| `2012_lexus_lfa_cab.dxt.dds.z` | 52,842 | 座舱 |
| `2012_lexus_lfa_int.dxt.dds.z` | 122,492 | 内饰 |
| `2012_lexus_lfa_lights.dxt.dds.z` | 90,597 | 灯组 |
| `2012_lexus_lfa_mask.dxt.dds.z` | 25,823 | **车漆分区掩码** |
| `2012_lexus_lfa_misc.dxt.dds.z` | 49,912 | 杂项 |
| `2012_lexus_lfa_sha.dxt.dds.z` | 10,858 | **阴影/AO（256×256）** |
| `2012_lexus_lfa_sw.dxt.dds.z` | 60,902 | 方向盘面 |
| `2012_lexus_lfa_wheel.dxt.dds.z` | 61,359 | 轮毂 |
| `2012_lexus_lfa_wheel_blur.dxt.dds.z` | 154,652 | 轮毂运动模糊 |

### 1.3 锚点 / HUD / 涂装（3 + 6 个）

| 文件 | 大小 | 内容 |
|---|---|---|
| `2012_lexus_lfa.points` | 1,175 | 22 条锚点，含 `SPLINE_SPECULAR` / `SPLINE_SPECULAR_REVERSE` 反射探针 |
| `2012_lexus_lfa_int.points` | 217 | 内饰锚点（`POINT_STEERING_WHEEL`、仪表指针铰链等） |
| `2012_lexus_lfa.dashplanes` | 236 | HUD 文字面片 |
| `livery/2012_lexus_lfa_ext_passionate_pink.dxt.dds.z` | 131,832 | 涂装：激情粉 |
| `livery/2012_lexus_lfa_ext_pearl_red.dxt.dds.z` | 129,786 | 涂装：珍珠红 |
| `livery/2012_lexus_lfa_ext_pearl_yellow.dxt.dds.z` | 142,447 | 涂装：珍珠黄 |
| `livery/2012_lexus_lfa_ext_steel_gray.dxt.dds.z` | 119,693 | 涂装：钢灰 |
| `livery/2012_lexus_lfa_ext_sunset_orange.dxt.dds.z` | 135,628 | 涂装：落日橙 |
| `livery/2012_lexus_lfa_ext_whitest_white.dxt.dds.z` | 145,220 | 涂装：极白 |

> **原厂没有** `2012_lexus_lfa_wing.banim`、也没有 `2012_lexus_lfa_animations.xml`——这两个是我们自己加的。

---

## 2. 车辆目录之外、但与 LFA 绑定的文件（7 类）

| 文件 | 大小 | 与 LFA 的关系 |
|---|---|---|
| `.depot/vehicles/data/88_2012_lexus_lfa.bin.nct` | 874 | **每车设定**：ID 88、性能数值、名称、音频路径、`generic_race` |
| `.depot/vehicles/data/liveries/2012_lexus_lfa.liveries.bin.nct` | 4,700 | 涂装清单（16 条 `.ptc.pvr.z` 路径） |
| `apk/res/asset_list_vehicle_2012_lexus_lfa.txt` | 9,264 | **每车资源清单**（87 行原厂；我们加了 2 条变 89 行） |
| `.depot/asset_list_base.txtCache.txt` | 4,909,607 | 全库清单，**含 35 条 LFA 条目**（13 字节头 + `path\tmd5` 行） |
| `.depot/vehicles/data/carappearances.appearances.nct` | 162,235 | 540 条外观记录之一 → LFA 记录号 476，含 266 B 外观块（**决定轮毂/轮胎尺寸**） |
| `.depot/vehicles/data/suspensionbehaviour.suspensiondata.nct` | 75,608 | 540×140 B，LFA 记录 #459（`+22/+23` 轮胎直径、`+43~45` 悬架行程） |
| `.depot/vehicles/data/cardamagethresholds.damage.nct` | 62,644 | 车损阈值（含 LFA 记录） |
| `.depot/vehicles/data/cardesc.list.nct` | 19,791 | 车辆列表/解锁信息（车库靠它枚举车辆） |
| `.depot/audio/Vehicles/v10_04/id_88_accel.decomp` | 4,508 | 引擎加速音 |
| `.depot/audio/Vehicles/v10_04/id_88_decel.decomp` | 3,783 | 引擎减速音 |

> `carparts.parts.nct` / `carupgrade.upgrades.nct` 也含 LFA 的改装项记录，但那是通用改装表。

---

## 3. 我们自己加/改过的文件（当前设备状态）

| 文件 | 来源 | 说明 |
|---|---|---|
| `vehicles/2012_lexus_lfa/2012_lexus_lfa_a.m3g` | `re/lfa/2012_lexus_lfa_a_v37.m3g` | 2,107,714 B，md5 `dd5d7740…`（自制尾翼 + 定点格式） |
| `vehicles/2012_lexus_lfa/2012_lexus_lfa_wing.banim` | `re/lfa/2012_lexus_lfa_wing_p1c.banim` | 17,640 B（P1 结构 + LFA 数值，两轨同动） |
| `vehicles/2012_lexus_lfa/2012_lexus_lfa_animations.xml` | `re/lfa/2012_lexus_lfa_animations_p1.xml` | 306 B（P1 的 4 段动画定义） |
| `vehicles/2012_lexus_lfa/2012_lexus_lfa_a.m3g.orig` | 设备备份 | 原厂 728,986 B 备份（应清理） |
| `apk/res/asset_list_vehicle_2012_lexus_lfa.txt` | `re/build/lfa_carlist_p1c.txt` | 89 行 |

**P1 已还原原厂**：`vehicles/2014_mclaren_p1/2014_mclaren_p1_a.m3g` = 1,216,273 B，md5 `872182d8c3782282e3d815ea418387c8`（与 E: 包一致）。

---

## 4. 一句话总结

LFA 的"模型"实际是 **12 个 `.m3g`**（`_a` 车身 / `_b`~`_h` 六级 LOD / `_shared` 轮组 / `_int_a`、`_int_b` 内饰 / `_frontend` 菜单），
加 **12 张 `.dxt.dds.z` 贴图** + **6 张涂装** + **2 个 `.points`** + **1 个 `.dashplanes`**，
外面再挂 **7 个共享数据表** 和 **2 个音频文件**。
尾翼在 `_a` 里，没有独立网格、没有 banim、没有动画 xml —— 全是我们后加的。
