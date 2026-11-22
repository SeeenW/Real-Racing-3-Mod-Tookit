# livery 配置表：槽位 id / 名字表 / 材质名池

数据源：`E:\DXT_480x320+960x640+2048x1536数据包-Build260716\files\.depot\vehicles\data\liveries\`
（全部 `.nct`，用 `analysis/nct_dec.py` 的 keystream 解密）

> **2026-10-27 重要修订**：本文早期版本（以及当时所有工具）只解了 liveries 文件里的
> **第 1 张贴图表**就停了，因此得出了"livery 只能换贴图、不能换材质"的错误结论。
> 完整的 4 张表结构来自 MonkeyTool `docs/FORMATS.md` §"A liveries list"，见下面第 2 节。
> **第 2 张表（网格→材质）就是"零件 → 材质"的官方映射**，尾翼跟随车漆正是靠它实现的。

## 1. `liveryStringTable.bin.nct`（70,134 B）= id → 名字表

```
[u32 count = 2068] + count × ( [u32 len][name ASCII] )
```
解析 2068 条正好吃到文件末尾，**索引就是 slot id**。完整导出见 `re/livery_slot_table.txt`。

区段：

| id | 内容 |
|---|---|
| 0..21 | tag 级槽名：`ext_chassis`、`ext_windows_cracked`、`ext_windows_shattered`、`ext_windows`、`ext_tyre`、`ext_rotor`、`ext_cloak`、`ext_banner`、`ext_scratches`、`ext_headlight_glow`、`int_windows_cracked`、`int_windows_shattered`、`int_windows`、`int_mat00..int_mat07`、`int_banner` |
| 22..约1931 | **具体零件名**（`LOD_?_..._mm_<tag>`）与 70 个 `car_*` 材质名混排（ASCII 升序） |
| 1932..1944 | 外观区域槽：`ext_ext`(1932)、`ext_lights`、`ext_misc`、`ext_badges`、`ext_cab`、`ext_wheel_blur`、`ext_wheel`、`int_ext`、`int_int`、`int_sw`、`REAR_VIEW`、`SIDE_LEFT`、`SIDE_RIGHT` |
| 1945..2067 | 漆种材质名（`car_paint_*` 与 `car_bumper_paint_*` 成对） |

关键的零件级 id：

| 名字 | id |
|---|---|
| `LOD_A_BODY_mm_ext` | 30 |
| `LOD_A_WING_REAR_LEFT_mm_ext` | 738 |
| `LOD_A_WING_REAR_RIGHT_mm_ext` | 742 |
| `LOD_A_WING_REAR_mm_ext` | **745** |
| `LOD_A_WING_REAR_mm_misc` | **747** |
| `LOD_A_WING_STRUT_REAR_mm_ext` | 750 |
| `LOD_A_WING_STRUT_mm_ext` | 753 |
| `LOD_A_WING_mm_chassis` | 756 |
| `LOD_A_WING_mm_ext` | 757 |
| `ext_ext`（车身漆面槽） | 1932 |

漆种材质 id（可作"目标材质"）：`car_paint_metallic_white`=1945、`_warm`=1958、`_cool`=1956、
`_blue`=1947、`_orange`=1951、`_red`=1953、`_bloodorange`=1949、`_green_light`=1960、
`_green`=1968、`_yellow`=1973、`_darkblue`=1977、`_purple`=1997、`_bloodred`=1963、
`_cool_light`=1976、`car_paint_pearl_blue`=1965、`car_paint_carbon_fibre`=1970、
`car_paint_matte`=23、`car_paint_matte_high`=1980、`car_paint_gloss`=31、`car_paint_chrome`=287、
`car_gloss`=2002、`car_flat`=28、`car_matte`=35。

## 2. `liveries/<车>.liveries.bin.nct` = 4 张表（完整结构）

```
str  车名
u32  n1, n1 × (u32 slot, str path)          # ① 贴图表
u32  n2, n2 × (u32 meshSlot, u32 matSlot)   # ② 网格 → 材质表   ★关键
u32  n3, n3 × (u32, u32, u32)               # ③ 第三张表
u32  n4                                      # ④ 涂装列表
n4 × {
    str 文件名, str 显示名, 8B, str swatch, str logo,
    u8 flag, str arms, str driver, 4B, 3B RGB,
    u32 m, m × (u32 slot, str path)          #    贴图覆盖
    u32 k, k × (u32 meshSlot, u32 matSlot)   #    材质覆盖   ★关键
}
```
所有 slot / 材质 id 都是 `liveryStringTable.bin.nct` 的下标。

实测尺寸：`2012_lexus_lfa` 4700 B（16/30/3/6 条）、`2014_mclaren_p1` 3814 B（20/9/3/6 条）。
用 `analysis/livery_full.py` 可以逐条打印（`parse()` + `nm()` 反查名字）。

### 2.1 表② 全局网格→材质（原厂写法）

`2012_lexus_lfa` 的 30 条：`100 LOD_A_CHASSIS_mm_misc -> 28 car_flat`、
`376 LOD_A_INT_LED_EMISSIVE_mm_int -> 476 add`、其余 28 条都是
`LOD_?_{TAILLIGHT,BRAKELIGHT}_LENS*_mm_windows -> 37 car_glass`。

全库 541 个 liveries 文件里，**只有 10 台车**在表②里写了 WING 条目：

| 车 | 条目 |
|---|---|
| `2007_lamborghini_reventon` | `LOD_?_WING_REAR[_LEFT/_RIGHT]_mm_ext -> car_paint_matte`（A~F 全 LOD） |
| `2013_bugatti_veyron_gsv` | `LOD_A/B_WING_REAR_mm_ext -> car_matte` |
| `2014_mclaren_p1` | `LOD_A_WING_STRUT_REAR_mm_ext -> car_matte`（注意是 STRUT，不是 REAR） |
| `2015_koenigsegg_regera` | `LOD_A_WING_STRUT_REAR_mm_ext -> car_flat` |
| `2016_ferrari_f12tdf` | `LOD_?_WING_REAR_mm_ext -> car_paint_matte` |
| `2019_volkswagen_idr` | `LOD_?_WING_REAR_mm_ext -> car_matte` |
| `2020_porsche_911_turbo_s` | `LOD_A_WING_STRUT_mm_ext -> car_matte` |
| `2021_pagani_huayra_r` | `LOD_?_WING_REAR_LEFT/RIGHT_mm_ext -> car_paint_matte` |
| `2022_koenigsegg_cc850` | `LOD_?_WING_REAR_mm_ext -> car_paint_matte_high` |
| `2023_rimac_nevera` | `LOD_?_WING_REAR_mm_ext -> car_bumper_paint_metallic_cool_light` |

### 2.2 涂装的材质覆盖（真正让尾翼跟随车漆的地方）

原厂绝大多数车**不在表②里写尾翼**，而是在每个涂装的材质覆盖表里按零件覆盖：

- `2014_mclaren_p1`：涂装 03 → `745 LOD_A_WING_REAR_mm_ext -> car_paint_metallic_cool`；
  04 → `_spec_orange`；05 → `_metallic_white`；01/02/06 无覆盖（用默认）。
  73 条覆盖里 745 排在第 18 位（**按 slot 升序**，插入后必须重新排序）。
- 全库统计：livery 里出现 745 的共 **25 台车 / 59 个涂装**；有 `_wing.banim` 的 53 台车里
  只有 20 台带 745（其余是静态尾翼或走 STRUT/LEFT/RIGHT 槽）。
- **745 的映射目标永远等于同一涂装里 30（`LOD_A_BODY_mm_ext`）的目标**——16 组配对无例外。
  也就是说：尾翼漆 = 车身漆，是 livery 表显式写出来的，不是引擎自动继承。
- **747 `LOD_A_WING_REAR_mm_misc` 全库 0 命中** ⇒ 原厂从不给尾翼的 `_mm_misc` 部分做材质覆盖
  （那部分本来就是黑塑料/内饰件）。

### 2.3 为什么我们的尾翼原本发暗

我们的 `_a.m3g` 里新增了 `LOD_A_WING_REAR_mm_ext` / `_mm_misc` 两个网格，但
`611` 的 liveries 文件是从 LFA 原样克隆的——LFA 原厂车身根本没有 WING 网格，所以
livery 表里一条 745/747 都没有。引擎找不到映射 ⇒ 退回默认材质 `car_flat`
（`materials.bin` 里它的 `mu_MaterialSpecularColour_Base = 0,0,0`、`Power = 1`，
对应 `fresnel_flat` 这张全库唯一纯黑的渐变图）⇒ 尾翼发暗、不随漆种变化。

这与着色器取证完全吻合：尾翼和车身用**同一个像素着色器**，唯一差别是引擎绑定了不同的
LUT 贴图（`set=2,binding=2` vs `binding=4`）——binding 的选择就来自 part 的材质集，
而材质集来自这张 livery 表。

## 3. `default.liveries.bin.nct`（15,904 B）= 全车通用的**兜底**网格→材质总表

**注意：这个文件不是只有一张贴图表。** 它有两张表，第 2 张才是关键：

```
[u32 n1 = 22]  + 22 × ( [u32 slotId][u32 len][路径] )        # ① 通用贴图，964 B 结束
[u32 n2 = 1867] + 1867 × ( [u32 meshSlot][u32 matSlot] )      # ② 兜底网格→材质，吃到 15904
```

`used == total == 15904`，无尾巴。

### 3.1 表① 通用贴图（22 条）

`common/car_chassis.ptc.pvr.z`、`car_windows_cracked_01`、`car_windows_shattered`、`car_windows`、
`car_tyre_tread`、`car_rotor_00`、`car_cloak_silver`、`car_windows_banner`、`car_scratches_01`、
`car_headlight_glow_white`，以及内饰 `carbon_fibre_dark_grey_mat00`、`leather_black_mat01`、
`stitching_white_a_mat02`、`plastic_leather_black_mat03`、`suede_black_mat04`、
`speaker_mesh_mat05`、`carpet_bluegrey_mat06`、`aluminium_foil_mat07`。
（这个文件的字符串是本地化的，解析时字符串要按原始字节处理，不能假设 ASCII。）

### 3.2 表② 兜底网格→材质（1867 条）

- 覆盖 slot **22..1931**（名字表里"具体零件名"那一整段），**严格升序**，
  中间缺 43 个——缺的全是**材质名槽**本身（23/26/28/31/33/35/37/39/79/102/152/161/165/167/170 …），
  因为材质名不是网格。
- 43 种目标材质，Top 20：`car_glass` 274、`car_paint_gloss` 229、`car_lights` 190、
  `car_wheels_alloy` 180、`car_matte` 157、`car_flat` 143、`car_tail_light` 135、
  `car_wheels_alloy_blurred` 97、`car_badge_matte` 50、`car_dash_flat` 36、`car_led_lights` 31、
  `car_wheels_gloss` 31、`car_dash_matte` 26、`car_mirror` 26、`car_wheels_chrome` 23、
  `projected_lights` 23、`car_wheels_dark_chrome` 22、`car_dash_matte_dull` 17、
  `car_tires` 17、`car_glass_trim` 14。
- **尾翼的默认值全在这里**（这就是"没覆盖时尾翼是暗的、但仍有一点漆色"的原因——
  默认给的是 `car_paint_gloss` 而不是 `car_flat`，真正绑 LUT 失败的是别的路径）：

  | slot | 网格 | 默认材质 |
  |---|---|---|
  | 30 | `LOD_A_BODY_mm_ext` | `car_paint_gloss` (31) |
  | **745** | **`LOD_A_WING_REAR_mm_ext`** | **`car_paint_gloss` (31)** |
  | **747** | **`LOD_A_WING_REAR_mm_misc`** | **`car_matte` (35)** |
  | 738 / 742 | `LOD_A_WING_REAR_LEFT/RIGHT_mm_ext` | `car_paint_gloss` (31) |
  | 750 / 753 | `LOD_A_WING_STRUT_REAR/_STRUT_mm_ext` | `car_paint_gloss` (31) |
  | 757 | `LOD_A_WING_mm_ext` | `car_paint_gloss` (31) |
  | 744 | `LOD_A_WING_REAR_mm_badges` | `car_badge_matte` (39) |
  | 746 | `LOD_A_WING_REAR_mm_lights` | `car_light_housing` (33) |
  | 748 | `LOD_A_WING_REAR_mm_windows` | `car_glass` (37) |
  | 756 | `LOD_A_WING_mm_chassis` | `car_flat` (28) |
  | 731 / 732 | `LOD_A_WING_BOOT_mm_ext/_mm_misc` | `car_paint_gloss` (31) |
  | 53–56 | `LOD_A_BONNETCAM_HOOD_WING_*_mm_ext` | `car_paint_gloss` (31) |
  | 257–266 | `LOD_A_HOOD_WING_*` | ext→31 / badges→39 / chassis→28 / misc→35 |
  | 1927 / 1931 | `LOD_G/H_BODY_mm_ext` | `car_paint_gloss` (31) |

  LOD_B~F 完全同构（`B_WING_STRUT_*_mm_ext` 例外，是 `car_matte` 35）。

### 3.3 材质解析：三级来源，第 3 级（default 表②）**几乎肯定参与**，但无法与"代码硬编码"区分

引擎按**网格名**查 `liveryStringTable` 得到 slot，然后按具体度回退：

1. **当前涂装的「材质覆盖」**（最具体，原厂把尾翼漆写在这里）— 已实测生效
2. **本车 liveries 的表②**（全车通用网格→材质）— 已实测生效
3. **`default.liveries.bin.nct` 表②**（1867 条全局兜底）**或**代码里同值的硬编码 — 见下

数据覆盖度统计（三种车、205 个网格，按上述 3 级都算上时"无来源"为 0）：

| 车 | 网格数 | 涂装覆盖 | 本车表② | default 表② |
|---|---|---|---|---|
| `2012_lexus_lfa` 原厂 | 68 | 13 | 7 | 48 |
| `2014_mclaren_p1` | 67 | 0 | 6 | 61 |
| `2012_lexus_lfa_animtest` (611) | 70 | 14 | 7 | 49 |

611 的尾翼解析结果：

```
LOD_A_WING_REAR_mm_ext   slot=745  → livery: car_paint_metallic_white   ← 我们补的
LOD_A_WING_REAR_mm_misc  slot=747  → default 表②: car_matte             ← 原厂行为，不补
```

#### 为什么说第 3 级"几乎肯定参与"

`2013_koenigsegg_agerar`（79 网格）和 `2013_ferrari_laferrari` 是**关键样本**：

| 车 | 表② 有 `30 LOD_A_BODY_mm_ext` 吗 | 涂装里有材质覆盖吗 | 游戏里车身上漆吗 |
|---|---|---|---|
| `2013_koenigsegg_agerar` | **没有**（表② 19 条，只有 `_mm_badges/_mm_misc/_mm_ext` 里的 chassis 等） | **6 个涂装全是 0 条** | **上漆** |
| `2013_ferrari_laferrari` | **没有**（表② 22 条，同样无 30） | **3 个涂装全是 0 条** | **上漆** |

车身网格 `LOD_A_BODY_mm_ext`（slot 30）在这台车**自己的数据里任何地方都查不到材质**，
但游戏里车身当然上漆 ⇒ 这个材质只能来自**本车之外**。来源只有两种可能：

* (a) `default.liveries.bin.nct` 表② 的 `30 -> 31 car_paint_gloss`（**运行时读表**）
* (b) 引擎代码里硬编码 `LOD_A_BODY_mm_ext -> car_paint_gloss`

**现有数据无法区分 (a) 和 (b)**——两者给出的值完全一样。
Agera R 这类老车的车漆**颜色**来自涂装的**贴图覆盖**（`texOv=2`，换 albedo 图集），
材质本身是通用的 `car_paint_gloss`，所以"换涂装车漆变色"不需要材质覆盖。

#### 这对我们意味着什么

* 修复前 611 尾翼（涂装覆盖无 745、本车表②无 745）落到第 3 级，拿到的是
  **`car_paint_gloss`（通用光泽漆）**——有光泽，但**不跟随车漆的漆种/颜色**。
* 修复后（涂装覆盖里写 `745 -> 同 30`）才拿到**和车身完全相同的漆种材质**
  （`car_paint_metallic_white` / `_warm`…）⇒ 实机确认"和车身同色同光泽"。
* ⇒ **结论不变：想让新部件跟随车漆，必须写进涂装的材质覆盖。**
  依赖第 3 级只能拿到通用光泽漆。

> **⚠ 一处仍待解释的旧观测**：`docs/尾翼发暗-着色器取证.md` 记录修复前尾翼 LUT
> 对应 `car_flat`（`mu_MaterialSpecularColour_Base = 0,0,0`、`Power = 1`、
> `fresnel_flat` 全库唯一纯黑渐变）。若第 3 级给的是 `car_paint_gloss`，这与观测矛盾。
> 可能原因：那次抓帧对象是 `re\lfa\2012_lexus_lfa_a_v37.m3g`（2026-10-24 构建），
> 当时部署路径/材质表与现在不同（经历过 `LOD_A_BODY_REAR_mm_ext` 等改名实验，
> 而 `LOD_A_BODY_REAR_mm_ext` **不在** slot 表里 ⇒ 查不到 slot ⇒ 更可能落到硬编码兜底）。
> **这一条没有被证实，别当结论用。**

#### 一锤定音的实验（**改 default 表②，看尾翼变不变**）

上表 (a)/(b) 两种可能，用一个实验就能分开：把 `default.liveries.bin.nct` 表② 里的
`745 -> 31 car_paint_gloss` 改成某个显眼的漆（如 `745 -> 1951 car_paint_metallic_orange`），
推上设备重启，看 Agera R（或 611 的 6 号涂装）的尾翼颜色。

* 尾翼变橙 ⇒ **(a) 运行时真的读 default 表②**，那么给新部件加材质有第三条路
* 尾翼不变 ⇒ **(b) 代码硬编码**，default 表② 只是工具链参考表

注意：改 `default.liveries.bin.nct` 后必须同步更新 `asset_list_base.txtCache.txt` 里它的
md5（`3cb4937f176b1c181b24b3b73a9872cc`），否则清单校验不过。

同理可看 `2013_ferrari_laferrari`（也是 0 条涂装覆盖 + 表② 无 745）。

> 补充：`default.liveries.bin.nct` 在 `asset_list_base.txtCache.txt` 里有注册条目
> （md5 `3cb4937f176b1c181b24b3b73a9872cc`），但**不在** `apk/res/asset_list_base.txt` 里
> ——后者只列 `apk/res/` 下的文件，`.depot/` 下的走前者。它表①的 22 条通用贴图
> （`common/car_chassis.ptc.pvr.z` 等）几乎肯定是运行时在用的默认贴图集。

### 3.4 三种"给部件上漆"的写法对比

| 写法 | 位置 | 效果 | 原厂用吗 |
|---|---|---|---|
| 涂装材质覆盖 `745 -> 漆种` | 每个涂装内 | **跟随每个涂装的车漆**（最佳） | **是**，25 台车 / 59 涂装 |
| 本车表② `745 -> 漆种` | liveries 文件第 2 张表 | 全车固定一种材质，不随涂装变 | 是，10 台车（多给 `car_paint_matte`/`car_matte`） |
| 都不写（落 default 表②） | — | 通用 `car_paint_gloss`，有光泽但颜色不随车漆 | 是，29 台车（含 Agera R / LaFerrari） |

⇒ **想让新部件"跟随车漆"，必须写涂装覆盖。** 只写表② 会固定一种材质；什么都不写会拿到通用光泽漆。

## 4. 70 个可被指派的车辆材质名（名字表里的 `car_*`，去掉 `car_bumper_*`）

漆面类：
`car_paint_gloss`、`car_paint_matte`、`car_paint_matte_high`、`car_paint_metallic_{white,blue,bloodorange,orange,red,cool,warm,green_light,bloodred,green,yellow,darkblue,purple}`、`car_paint_metallic_spec_{orange,red,yellow,white}`、`car_paint_pearl_blue`、`car_paint_chrome`、`car_paint_carbon_fibre`、`car_gloss`、`car_flat`、`car_alpha`

非漆类：
`car_body_plastic`、`car_badge_{plastic,matte,flat,chrome}`、`car_glass`、`car_glass_trim`、`car_glass_tint`、`car_glass_convex`、`car_light_housing`、`car_lights`、`car_led_lights`、`car_led_lights_no_alpha`、`car_tail_light`、`car_grill`、`car_grill_non_transparent`、`car_matte`、`car_matte_doublesided`、`car_cloth`、`car_stitching`、`car_arms`、`car_arms_gen2`、`car_mirror`、`car_mirror_blur`、`car_rotor`、`car_rotor_low`、`car_tires`、`car_tires_standard`、`car_wheels_{chrome,alloy,gloss,dark_chrome}` 及其 `_blurred` 版本、`car_dash_{flat,matte,matte_dull,gloss,chrome,exterior}`、`car_windscreen_cracks`、`car_nascar_net`

## 5. 工具

- `analysis/livery_full.py <车名>` / `--all`：完整解析 4 张表，slot id 反查成名字。
  `parse(data)` 返回 `{car, textures, materials, extra, liveries, used, total}`；`nm(idx)` 反查。
- `analysis/livery_write.py`：**读写往返 + 材质覆盖注入**。
  - `--selftest`：对全部 541 个 liveries 做 parse→serialize 往返，逐字节比对（540/541 通过，
    `default.liveries.bin.nct` 因结构不同需排除）。
  - `--add-wing <in> <out>`：给每个涂装补 `745 -> 同 30`。
  - `add_wing(L)` / `serialize(L)` / `parse_raw(data)` 可被流水线直接 import。
- `analysis/zc_container.py <file.dxt.dds.z>`：打印 z 容器头 + 内层 DDS 头（`.z` = 4 字节原长 + zlib，内层是标准 DDS，无私有参数；`.dds.z.bin` 才有 24 字节头）。
- `analysis/livery_slots.py`：解析 `liveries/<车>.liveries.bin.nct` 的第 1 张表（早期版本）。
- `analysis/zcbin_scan.py`：扫 `.dds.z.bin` 的 24 字节头。

## 6. 落地结论（已验证）

`analysis/newcar_build.py` 的 `build_livery()` 现在会在写出前自动调用
`livery_write.add_wing()`，给每个涂装的材质覆盖表插入
`(745 LOD_A_WING_REAR_mm_ext -> 该涂装 30 的目标材质)` 并保持 slot 升序。

实测（2026-10-27）：611 的 liveries 4709 → 4749 B（5 条涂装各 +1 条），部署后
**尾翼已经和车身同色同光泽，跟随车漆类型变化**。`_mm_misc` 不补（原厂也不补）。
