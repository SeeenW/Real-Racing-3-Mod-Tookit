# 内饰：`_int.points` 与 `.dashplanes` 怎么自制

驾驶舱视角能不能看，取决于三样东西：**内饰模型**（`_int_a/b.m3g`）、
**内饰锚点**（`<car>_int.points`）、**仪表文字面**（`<car>.dashplanes`）。
本文只讲后两个文件，以及它们和模型/贴图怎么对上。

数据全部来自官方包
`E:\DXT_480x320+960x640+2048x1536数据包-Build260716\files`（960 个 `.points`、356 个 `.dashplanes`），
实测样本：`2012_lexus_lfa`（LHD、三表、带 `_int.points` 40 条里的大部分）。

---

## 1. 三个文件的分工

| 文件 | 位置 | 管什么 |
|---|---|---|
| `<car>_int_a.m3g` / `_int_b.m3g` | `vehicles/<car>/` | 内饰网格。Lexus 的 `int_a` 有 **44 个网格**（`LOD_A_INT_*`） |
| `<car>_int.points` | `vehicles/<car>/` | 内饰锚点：表针轴心、挡杆手、内后视镜、方向盘 |
| `<car>.dashplanes` | `vehicles/<car>/` | 仪表/HUD 上的**文字面**：档位、时速、圈速、转速 |

车身锚点 `<car>.points` 里也有 `POINT_DRIVER`，但**表针、挡杆、内后视镜的锚点只在 `_int.points` 里**：
40 个名字里有 34 个只在 `_int` 出现（完整表见 `锚点名清单.md`）。

---

## 2. 内饰模型用的贴图槽

内饰不是一张贴图搞定，是按材质槽分页的：

| 槽 | 贴图页 | 用途 |
|---|---|---|
| `int_mat00` … `int_mat07` | `<car>_int.dxt.dds.z` | 碳纤 / 皮革 / 缝线（带 alpha）/ 乙烯基 / 麂皮 … |
| `sw` | `<car>_sw.dxt.dds.z` | 方向盘 |
| `cab` | `<car>_cab.dxt.dds.z` | 从车外透过玻璃看到的座舱壳 |
| `misc` | `<car>_misc.dxt.dds.z` | 杂项（卡钳、内饰小件） |

材质槽名就是网格名末尾那一段：`LOD_A_INT_STEERING_WHEEL_mm_mat00` 用 `mat00` 槽，
`LOD_A_INT_DOOR_LEFT_mm_mat02` 用 `mat02`。改名就等于换材质，**槽位名不能自造**。

---

## 3. ★ 哪些网格是"锚点驱动"的

这是自制内饰最容易踩的坑：**一部分内饰网格被建模在原点，靠锚点摆到位置上；另一部分是就地建模的。**
实测（Lexus `int_a`，模型单位米、Y 朝上）：

| 网格 | 包围盒 | 结论 |
|---|---|---|
| `LOD_A_INT_NEEDLE_RPM_mm_int` | x ±0.002，y 0→0.046，z 0 | **建在原点**：一根 4 mm × 46 mm 的针，指向本地 +Y。位置由 `POINT_NEEDLE_RPM_*` 给，零位朝向由 `HINGE_NEEDLE_RPM` 给 |
| `LOD_A_INT_NEEDLE_RPM_EMISSIVE_mm_int` | 同上 | 夜光版，同一套锚点 |
| `LOD_A_INT_STEERING_WHEEL_mm_mat00` | x ±0.174，y ±0.176，z ±0.014 | **建在原点**：一个半径 17 cm 的圆盘，法线是本地 +Z。位置/朝向由 `POINT_STEERING_WHEEL` + `HINGE_STEERING_WHEEL` 给 |
| `LOD_A_INT_MIRROR_GLASS_mm_int` | x ±0.11，y 1.06→1.12，z −0.14 | **就地建模**：内后视镜玻璃直接放在车顶前缘，不靠锚点 |
| `LOD_A_INT_MIRROR_GLASS_LEFT/RIGHT_mm_int` | x ±0.9~1.0，y 0.88→0.99 | 就地建模（外后视镜镜面） |
| `LOD_A_INT_BODY_mm_ext` | x ±0.93，y 0.12→0.88，z −2.10→0.44 | 就地建模（整个座舱壳） |

⇒ **自己做内饰时**：指针、方向盘这类"会动/会转"的件，**模型建在原点、朝向 +Y/+Z**，
再用锚点摆；车身、门板、座椅、后视镜这些不动的件直接按真实位置建。

---

## 4. 指针锚点：`POINT_NEEDLE_*` 与 `HINGE_NEEDLE_*` 是一对

```
POINT_NEEDLE_RPM_1    type 0  轴心位置
HINGE_NEEDLE_RPM      type 2  同一位置的铰链（位置 + 3×3 朝向）
```

Lexus 实测：

```
HINGE_NEEDLE_RPM    (-11.225, 11.708, 24.716)   ← 1/32 m
POINT_NEEDLE_RPM_1  (-11.207, 11.024, 23.381)
POINT_NEEDLE_RPM_2  (-12.705, 11.024, 23.983)
POINT_NEEDLE_RPM_3  (-9.772,  11.774, 25.613)
```

- **位置**：`POINT_NEEDLE_*` 是针的转轴点；`HINGE_NEEDLE_*` 应该和它重合（上面差 0.7/1.3 单位
  = 2~4 cm，是原厂自己没对齐，别学）。
- **零位朝向**：由铰链的 3×3 决定。针的本地 +Y 会被转到这个 3×3 指向的方向，
  然后引擎按 `速度/转速` 绕铰链的**第三轴**旋转。写错 3×3，针会横着转或朝表盘背面转。
- **编号**：`_1` 到 `_4` 是四根针（双表/三表车才有 `_2` `_3` `_4`）。
- **线性表**：`POINT_NEEDLE_LINEAR_RPM_1..4` 是**条状**转速表的分段（不是旋转针），
  用 `_LINEAR_` 前缀，同样 1..4 段。
- **方向盘小表**：`POINT_STEERING_WHEEL_NEEDLE_RPM_1..3` + `HINGE_STEERING_WHEEL_NEEDLE_RPM`。

在 Blender 插件里：导入 `_int.points` 后，`HINGE_NEEDLE_*` 空物体的 `rotation_euler`
就是零位朝向，**转它就能改指针零位**，导出会写回铰链的 3×3（见 `points-格式.md` §10）。

---

## 5. 其他内饰锚点

| 名字 | 用途 | 实测（Lexus） |
|---|---|---|
| `POINT_GEARSTICK_HAND` | 手放挡杆的位置。驾驶员动画的手会伸到这里 | 178 台车有 |
| `POINT_NET_CENTER` | 内后视镜**镜面中心**（贴图里"后视"画面的锚点） | 17 台车有 |
| `POINT_STEERING_WHEEL` | 方向盘中心 | — |
| `HINGE_STEERING_WHEEL` | 方向盘转向轴 | — |
| `TRANSFORM_DRAG_RACE_VIEW` | 直线加速赛的机位（3 台 911 系，数值完全相同） | 3 台车有 |

`POINT_NET_CENTER` 只出现在 17 台车上，说明"车内后视镜画面"是可选功能；
没有它的话内后视镜就只是一块普通镜面贴图。

---

## 6. `.dashplanes`：仪表文字面

### 6.1 布局

```
u32 tag            4 或 5（全库：tag 5 = 259 个文件，tag 4 = 97 个）
每条：
  cstr name        "dash_lcd_speedo" / "wheel_lcd_gear" …
  16 f32           列主序 4×4：前三列是三个轴，第 4 列是位置
  tail             tag 5：3 f32 尺寸 + 2 u32 flags + f32 extra + cstr 字体 + 3 u8 RGB
                   tag 4：2~3 f32 尺寸 + 几个 flag 字节（没有字体、没有颜色）
```

记录**没有对齐填充**，所以步长不固定；解析器按名字定位再吃掉到下一个名字之间的字节。

### 6.2 坐标系：**模型系（Y 朝上）、单位 1/32 米**

这条是实测出来的，也是自制时最要紧的一条。Lexus：

```
dash_lcd_speedo  平移 (-11.66, 25.65, -11.87)
POINT_NEEDLE_RPM_1（引擎系，Z 朝上）  (-11.21, 11.02, 23.38)
```

两边一换轴就对上了：**模型系 = (x, z, −y) 之于引擎系**，
即 `dashplane (x, y, z) = point (x, z, −y)`。所以

- 单位同样是 **1/32 米**（25.65 → 0.80 m 高，正好是仪表台高度；按米算就是 25 米，显然不对）；
- 轴向是 **模型系**：x 向右、y 向上、**z 向后**（和 `.m3g` 顶点一致，内饰网格也是这个系）。

而 `.points` 用的是引擎系（z 朝上）。**两个文件不同系，换算就是一次 (x, z, −y)。**

### 6.3 10 个面名

| 名字 | 文件数 | 说明 |
|---|---|---|
| `dash_lcd_speedo` | 217 | 仪表台：时速数字 |
| `dash_lcd_gear` | 203 | 仪表台：档位 |
| `dash_lcd_kmhmph` | 115 | 仪表台：km/h / mph 单位字 |
| `dash_lcd_laptime` | 90 | 仪表台：圈速 |
| `dash_lcd_tacho` | 50 | 仪表台：转速数字 |
| `wheel_lcd_gear` | 101 | 方向盘上：档位 |
| `wheel_lcd_speedo` | 99 | 方向盘上：时速 |
| `wheel_lcd_laptime` | 34 | 方向盘上：圈速 |
| `wheel_lcd_tacho` | 17 | 方向盘上：转速 |
| `wheel_lcd_kmhmph` | 6 | 方向盘上：单位字 |

**名字是闭集**：`dash_lcd_*` / `wheel_lcd_*` 各 5 个，自造一个新名字引擎不会画。

### 6.4 朝向：第 4 列是位置，前三列是轴

Lexus 的 `dash_lcd_speedo` 三个轴：

```
X 列 ( 1.000,  0.000, -0.000)
Y 列 (-0.000, -0.972,  0.237)
Z 列 ( 0.000, -0.237, -0.972)
```

就是"绕 X 轴翻 180° 再倾 13.7°"——**面朝后（朝驾驶员）、略微仰起**。
文字面的法线是本地 +Z，所以这个 3×3 决定字朝哪边；写反了字会变成镜像/背面剔除。

### 6.5 尺寸与字体

- 尺寸是**两个 float**（宽、高），量级 `0.2~1.3 × 0.2~0.37`。单位没有实机验证过：
  按米算偏大（1.19 m 宽的字），按 1/32 m 算偏小（3.7 cm），更像是"相对单位 × 字号"。
  **实用做法**：抄一台同类型车的值，按比例放大缩小。
- 字体：`EuroFont`（408 次）、`EuroFont_Bold`（195）、`EuroFont_Demi`（154）、
  `LCD`（146）、`EuroFont_DemiOblique`（16）、`Minion_Italic`（9）。字体名必须在游戏字体表里。
- 颜色：tag 5 才有 RGB（Lexus 是 `168,168,168` 灰白）。tag 4 没有颜色字段，用材质默认色。

---

## 7. 自制一台"看得过去"的内饰：步骤

1. **模型**：`_int_a.m3g` 里放座舱壳、门板、座椅、仪表台（就地建模）；
   指针、方向盘**建在原点**、朝向 +Y / +Z。
2. **贴图**：内饰页 `<car>_int`，材质槽用 `int_mat00..07`；方向盘单独 `_sw` 页；
   透过玻璃看到的壳用 `_cab` 页。
3. **锚点**：在 `<car>_int.points` 里写
   - `POINT_NEEDLE_RPM_1` + `HINGE_NEEDLE_RPM`（位置重合，铰链给零位朝向）
   - 双表车再加 `_2` `_3`；条状表用 `_LINEAR_`
   - `POINT_STEERING_WHEEL` + `HINGE_STEERING_WHEEL`
   - `POINT_GEARSTICK_HAND`（手放的位置，别忘了）
   - 可选 `POINT_NET_CENTER`（内后视镜画面中心）
4. **文字面**：`<car>.dashplanes` 里给要显示的 5 个名字各写一条，
   位置从模型系换算（`dashplane = (x, z, −y)`，×32），朝向抄同类型车。
5. **部署**：工作台的部件页把 `dashplanes` 作为一个槽位一起部署（`rrmod/slots.py` 已登记）。

---

## 8. 还没确认的事

1. **驾驶舱相机在哪定义**：`_int.points`、`.dashplanes`、`int_a.m3g` 里都没有相机节点
   （`int_a` 的 211 个字符串里没有任何 `CAM*`）。所以机位是引擎侧按车型给的，
   改不了；能改的是"从这个机位看过去对不对"——也就是上面第 7 节的模型和锚点。
2. **`.dashplanes` 尺寸的真实单位**（见 6.5），需要实机改一个值看变化。
3. **`tag 4` 与 `tag 5` 的差别**是否只是"有没有字体/颜色"，还是对应不同的 HUD 渲染路径。
4. `POINT_NEEDLE_RPM_MIN` / `_MAX` 这两个名字引擎不认（`MIN`/`MAX` 不是数字后缀，剥不掉），
   但原厂还是写了——是不是留给工具的元数据，未查。
