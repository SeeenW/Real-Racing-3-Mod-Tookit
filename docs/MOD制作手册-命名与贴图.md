# RR3 自制车 MOD 手册：部件命名 / 贴图读取 / 轮毂缩放

> 面向"从 Blender 出一套 m3g 塞进真实赛车3"的实际操作。所有结论都在本项目里实测过，
> 不是推测。文中 `NL` = NFS No Limits（模型来源），`RR3` = 真实赛车3（目标游戏）。

---

## 0. 五条硬规则（背下来就够用）

1. **基名必须是引擎认识的，tag 可以自造。** 部件名拆成 `<基名>_mm_<tag>`，两半走两条
   不同的路：**基名**（`LOD_A_BRAKE_CALIPER_FRONT_LEFT`）必须出现在引擎里那份**编译期
   清单**上——`libRealRacing3.so` 里有 1327 个不带 tag 的 `LOD_<字母>_<基名>` 字符串，
   不在里面的基名（比如 `CARBON_SKIRT`）永远画不出来，logcat 只会说 `contains
   unreferenced mesh`。**tag** 却是开放的：新造一个 tag，只要在 `liveryStringTable` 里
   补上对应的**区域名** `ext_<tag>` 并给它一行页行，部件就能画（§3.5，已实测）。
2. **`_mm_<tag>` 后缀是强制的。** 引擎靠它决定这个部件用哪张贴图、哪套材质。
   少了它，名字照样在表里（比如 `LOD_A_BRAKE_CALIPER_FRONT_LEFT`），但解析不到 tag，
   于是没有贴图也没有材质 —— 表现就是"部件不见了"。卡钳整整丢了一轮就是这个原因。
3. **页由 `ext_<tag>` / `int_<tag>` 这个区域名决定，部件自己的 slot 行不决定页。**
   证据是出厂车：一台真车 200 多个 mesh，`liveries` 表里只有 **17 行贴图 + 21 行材质**，
   17 行恰好就是 `ext_ext`、`ext_lights`、`ext_misc`、`ext_badges`、`ext_cab`、
   `ext_wheel`、`ext_wheel_blur`、`ext_windows*`、`ext_rotor`、`int_ext`、`int_int`、
   `int_sw`、`int_mat02` 这些区域名——页是**按区域**给的，所以同一 tag 的部件共用一张
   图，那张图必须是**图集**。想让某个 tag 单独一张图，就补一个 `ext_<tag>` 区域名 +
   一行页行（§3.5）。材质才是逐部件查的（部件名一行，没有就走 tag 默认）。
4. **轮子的绝对尺寸由 `carappearances` 记录决定，但那个数是"缩放基准"不是半径。**
   实画半径 = `f1² / 网格轮胎半径`（轮辋同理 `f2² / 网格轮辋半径`）。网格等于 f1 时才
   看起来 1:1；网格缩过就必须开方补偿。**别手填，用工作台的 scale 框或
   `wheelsize_set.py --scale`**（§5.6）。`f2` 小于轮胎内孔会出现"轮辋小、胎厚"的
   一圈空隙。
5. **轮子在导出前先统一外径，前后轴用同一份网格。** 整只轮组等比缩到轮辋外径
   **0.465 m** / 轮胎外径 **0.599 m**（Blender 里看的是 N 面板的 Y/Z，即最大外径），
   然后在制作台里给前后轴各填一个 scale（§5.7）。前后轴同一份网格是游戏自己的做法，
   省的是模型文件；屏幕大小由 scale 决定，和缩到多少无关。

---

## 1. 部件命名

```
LOD_<LOD字母>_<基名>_mm_<tag>
```

| 段 | 取值 | 说明 |
|---|---|---|
| `LOD` | 固定 | 前缀 |
| `<LOD字母>` | `A`…`H` | RR3 有 8 级车身 LOD。A 最精细，H 最远。 |
| `<基名>` | 见 §1.2 | 部件语义，决定材质与损伤分组 |
| `_mm_` | 固定 | **分隔符，缺了就等于没有 tag** |
| `<tag>` | 见 §2 | 决定贴图页与渲染方式。**可以自定义**，见 §3.5 |

实例：`LOD_A_BODY_mm_ext`、`LOD_A_GLASS_LEFT_mm_windows`、`LOD_B_WHEEL_mm_wheel`、
`LOD_A_BODY_mm_carbon`（自定义 tag）。

### 1.1 LOD 阶梯怎么排

RR3 的 LOD 不是"同一模型逐级减面"，而是**八级各自独立的网格**，引擎按距离整级切换。
NL 那边 `lod00`…`lod08` 也不是一条均匀的阶梯：

* NL `lod00` 是**展车**：车门+座舱一圈，发动机舱敞着（裸露碳纤维 + 透明盖），**没有完整的
  后甲板**。直接当 A 用，就会看到"车身少一大块"。
* NL `lod01` 起才是整车封闭外壳。
* NL `lod07` 是**一整块密封外壳**（`paintdark`），天然的远 LOD。

所以本项目用的映射是 **NL 01→A、02→B … 07→G**，H 由 G 复制（见 `install.fill_last_lod`）。
换车时先数一遍 NL 各级的顶点数和包围盒，别假设 00 就是最好的。

### 1.2 常用基名

车身板件（这些名字同时是**损伤分组**的键，见 §1.3）：

```
BODY  CHASSIS  DOOR_LEFT  DOOR_RIGHT  HOOD  BOOT  FRONTBUMPER  REARBUMPER
WING  WING_REAR  WING_REAR_LEFT  WING_REAR_RIGHT  WING_STRUT  WING_STRUT_REAR
MIRROR_LEFT  MIRROR_RIGHT  MIRROR_GLASS_LEFT  MIRROR_GLASS_RIGHT
INTERIOR  GLASS_FRONT  GLASS_LEFT  GLASS_RIGHT  GLASS_REAR
HEADLIGHT_LENS_LEFT  HEADLIGHT_LENS_RIGHT
TAILLIGHT_LENS_LEFT  TAILLIGHT_LENS_RIGHT
EXHAUST  BRAKE_CALIPER_<角>  ROTOR  WHEEL  WHEEL_BLUR  TYRE
```

* **轮子/刹车件**（`WHEEL`/`WHEEL_BLUR`/`TYRE`/`ROTOR`/`BRAKE_CALIPER_*`）放在
  `_shared.m3g` 里，一份文件服务四个角。它们的名字**不带左右前后**（除了卡钳），
  位置由引擎按 `points` 摆。
* **卡钳**是例外，必须带角：`LOD_A_BRAKE_CALIPER_FRONT_LEFT_mm_misc`。
  全库只有 16 个合法卡钳名（A/B × 前/后 × 左/右 × `ext`/`misc`），
  即 `_mm_ext` 和 `_mm_misc` 两种，且**只有 A、B 两级**。

### 1.3 损伤模型

损伤件和完好件**在同一个车身文件里，位置完全重合**，引擎按损伤阈值切换，不需要单独文件。

```
LOD_A_DOOR_LEFT_DAMAGE_mm_ext        # 板件被撞
LOD_A_TAILLIGHT_LENS_BROKEN_LEFT_mm_lights   # 玻璃/灯罩碎
```

两种标记：`DAMAGE`（钣金）、`BROKEN`（玻璃与灯罩）。抽样 61 台车：`DAMAGE` 出现 1516 次、
`BROKEN` 493 次，21 种基名。阈值表在 `cardamagethresholds.damage.nct`。

在 Blender 里给插件用：把带 `DAMAGE`/`BROKEN` 的网格放进**单独的集合**，
插件会自动 `separate_damage`（默认开），不会和完好件抢同一个材质槽。

### 1.4 空物体 / 锚点（points）

`points` 文件是**引擎读的轮子与特效锚点表**，位置来自 Blender 里的空物体：

| 空物体名 | 用途 |
|---|---|
| `ANCHOR_POINT_<名字>` | 一般锚点（排气口、灯位、特效挂点） |
| `ANCHOR_HINGE_<名字>` | 铰链（车门、尾翼枢轴） |
| `AERO_<轨道号>_<零件名>` | 主动空力的枢轴；它的 location / rotation 就是引擎值 |

导出：插件面板 → `导出 points`，写到 `<车名>.points`。名字对不上就静默跳过，
所以导完一定回读一遍条目数。

---

## 2. tag 表：21 个原生 token + 1 个自定义
引擎按 `_mm_` 后面的 token 找槽位，**顺序敏感、大小写敏感**。
文件名里必须含 `_<token>_` 或 `_<token>.`。

| # | token | 谁用它 | 槽位 |
|---|---|---|---|
| 1 | `ext` | 车漆本体（车身、引擎盖、翼子板、尾翼） | 区域槽 **1932** |
| 2 | `lights` | 灯罩、灯内胆、灯光叠加片 | 区域槽 **1933** |
| 3 | `misc` | 碳纤、镀铬、塑料、钛、格栅、发动机舱照片、卡钳 | 区域槽 **1934** |
| 4 | `badges` | 徽标、牌照（**带 alpha 的透贴**） | 区域槽 **1935** |
| 5 | `cab` | 座舱内饰壳 | 区域槽 **1936** |
| 6 | `chassis` | 底盘、悬挂、排气外皮 | 编号槽 **0** `ext_chassis` |
| 7 | `windows_cracked` | 裂纹玻璃（损伤） | 编号槽 **1** |
| 8 | `windows_shattered` | 碎裂玻璃（损伤） | 编号槽 **2** |
| 9 | `windows` | 玻璃与窗框 | 编号槽 **3** `ext_windows` |
| 10 | `tyre` | 轮胎 | 编号槽 **4** `ext_tyre` |
| 11 | `wheel_blur` | 轮毂运动模糊版 | 区域槽 **1937** |
| 12 | `wheel` | 轮毂 | 区域槽 **1938** |
| 13 | `rotor` | 刹车盘 | 编号槽 **5** `ext_rotor` |
| 14 | `cloak` | 隐身/护罩 | 编号槽 **6** |
| 15 | `banner` | 挡风横幅 | 编号槽 **7** |
| 16 | `tyre_flipped` | **镜像侧轮胎** | 编号槽 **1986**（在零件名区段里，容易漏） |
| 17 | `scratches` | 划痕叠加 | 编号槽 **8** |
| 18 | `headlight_glow` | 大灯光晕 | 编号槽 **9** |
| 19 | `sidelight_glow` | 侧灯光晕 | 无独立槽 |
| 20 | `taillight_glow` | 尾灯光晕 | 无独立槽 |
| 21 | `wheel_flipped` | 镜像侧轮毂 | 无独立槽 |
| 22 | `carbon` | **本项目自定义**：裸碳纤（`convert.CARBON_TAG`） | 无区域槽；**每个部件一行**指到 `common/rrmod_carbon` |

两条要点：

* **编号槽 0..9 有 `common/` 兜底**（`default.liveries` 表① 给的通用页）。
  本车不写这一行，引擎就拿通用页 —— 这不会报错，但**左右两侧可能拿到不同的页**
  （`tyre` 与 `tyre_flipped` 是两个槽）。"轮胎贴图贴错"有一半是这个原因。
* **区域槽 1932..1941 没有兜底**，必须自己写。
* 第 22 行不是游戏自带的，表里原来没有 `carbon` 这个 token，`convert.APPENDED_TAGS`
  允许这么做。**但它没有区域槽**：一开始想给它追加一个 `ext_carbon`，实测会让游戏
  启动即崩（§3.5）。所以它的页是**每个部件一行**写上去的，靠"部件行压过 tag"生效。
  自造 tag 的收益因此变成"把这组部件跟 `_mm_misc` 分开"，而不是"多一个区域"。

---

## 3. 贴图是怎么被找到的（两条独立的链）

一条链找**材质**（决定着色器、混合模式、光泽），另一条链找**贴图页**。两条的键不一样，
而且**不能互相顶替**：

```
材质 : 部件名（mesh 全名）        -> 那一行材质
页   : tag 的区域名 ext_/int_<tag> -> 那一行贴图
```

部件自己槽位上的**贴图行不参与选页**（它只是历史遗留，写了也不生效）。想让一个 tag
单独一张图，唯一的路是给它一个区域名 —— 见 §3.5。这是本手册里最容易搞错的一点。

### 3.1 材质链（决定"看起来像什么"）

```
网格名 ──liveryStringTable──► slot
                              │
      ① 当前涂装的材质覆盖 ────┤ 最具体
      ② 本车 liveries 表② ─────┤
      ③ default.liveries 表② ──┤ 全局兜底（≈代码硬编码）
```

材质名只有那 70 个 `car_*` 可选（slot 只到 2067）。每个名字背后是
`实例 → 模板 + application + cull/blend + flags + uniform + LUT` 一整套，全在
`materials.bin`（297 块 + 186 条着色器绑定）。

**注意这条链只按部件槽位查，不按区域查。** `default.liveries` 里 1867 条材质行全是
部件名，`ext_misc` 这类区域名一条材质行都没有 —— 所以新造的部件名如果不补一行材质，
就只能落到引擎的硬编码兜底上。这是"自定义 tag"唯一真正要多做一步的地方（§3.5）。

**想给新部件一个特殊外观（比如纯黑不透明窗框），改的就是这条链** —— 在 livery 表②
里写一行 `网格slot → 材质slot`。

### 3.2 贴图链（决定"上面画了什么"）

```
网格名 ──liveryStringTable──► 部件 slot（表②/表① 可以直接按它查）
        └─ 取出 _mm_ 后面的 tag
              └─ 区域名 = "ext_" + tag  ──liveryStringTable──► 区域 slot
                                                            │
                            ① 当前涂装的贴图覆盖 ───────────┤
                            ② 本车 liveries 表①（部件 slot 优先）┤
                            ③ default.liveries 表①（common/…）┘
```

**关键：页是挂在"区域"上的，不是挂在部件上的。** 表里有一组 `ext_<tag>` 名字，
一个 tag 一个，和部件名放在同一张字符串表里：

| 区域名 | slot | 谁用 |
|---|---|---|
| `ext_chassis` | 0 | 所有 `_mm_chassis` |
| `ext_windows` | 3 | 所有 `_mm_windows` |
| `ext_tyre` | 4 | 所有 `_mm_tyre` |
| `ext_ext` | 1932 | 所有 `_mm_ext`（车漆页） |
| `ext_lights` | 1933 | 所有 `_mm_lights` |
| `ext_misc` | 1934 | 所有 `_mm_misc` |
| `ext_badges` | 1935 | 所有 `_mm_badges` |
| `ext_cab` | 1936 | 所有 `_mm_cab` |
| … | | `int_ext` / `int_int` / `int_sw` 是同一批的"内饰视角"版本 |

所以 `LOD_A_BODY_mm_misc`、`LOD_A_FRONTBUMPER_mm_misc`、`LOD_B_BODY_mm_misc` 三个部件
**在自己的槽位上根本没有贴图行**，它们全落到 `ext_misc` = 1934 那一行。
`default.liveries` 里的 22 张贴图行也全是区域名（`ext_chassis` / `ext_misc` / `int_mat00`…），
不是部件名 —— 这条链的兜底同样按区域走。

**部件自己槽位上的贴图行不改变页**（§4.6 有反证）：本车给卡钳的 88/90/92/94 都写了
指向 `rrmod_misc_caliper_01` 的行，卡钳照样读整车的 misc 页 —— 因为 `_mm_misc` 先解析
到 `ext_misc`（1934）。想让某个 tag 单独一张图，只能给它一个区域名。

> **修正：区域名可以自造。** 早一版这里写着"区域名是闭集，自造会 abort"，那是误判：
> 那次 abort 的批次同时把 16 个部件的基名改成了 `CARBON_SKIRT`（引擎清单里没有），
> 跟区域名无关。后来 `ext_calipers` / `ext_calipers_rear` 两个自造区域名实测通过，
> `unreferenced mesh` 从 16 条降到 0 条。做法见 §3.5。

文件名写 PVR 名（`xxx.ptc.pvr.z`），引擎按当前 GPU 家族换成 `.dxt.dds.z` /
`.etc.dds.z` / `.atc.dds.z`。**模拟器上的 RR3 吃 DXT**，所以只出 `.dxt.dds.z` 就够。

### 3.3 为什么必须做图集

NL 的 UV 是"每个材质在自己的小图里 0..1 归一"。RR3 的 UV 是"整个 tag 共用一张大图"。
把 NL 的图直接当 RR3 的页用，UV 仍然 0..1 —— 但落到的是**整张大图**，于是
"发动机舱照片被贴满整块碳纤"。

正确做法（本项目 `atlas.py` 的做法）：给每个源图在大图上划一个矩形，把该材质的
**整个 UV 包围盒**线性映射进那个矩形。映射前后共用同一张布局表，两边才不会漂移。

#### 图集的代价：重复次数只能变少，不能变多

NL 的 UV 常常**超出 0..1**：碳纤的 UV 跨度是 **162**，也就是同一块 64×64 的织纹在
车身上铺 162 遍。图集把"跨度 162"压进一个 512×673 的矩形，只能放 51×67 份，
于是织纹被放大成 **3.2 倍粗**（`atlas.report()` 会直接打印这个数）：

```
carbon_opaque  fit  cell 0,0 512x1024  content 512x673  x51x67  texture_carbon.png  3.2x coarser than source
```

这不是参数没调好，是**算术上限**：要按 NL 的密度显示 162 遍 64 px 的织纹，需要
`162 × 64 = 10368 px` 的唯一细节，一张 1024² 的页放不下。页越大只能缓解，不能解决。

**唯一能拿到原生密度的办法是让采样器自己 wrap**：页 = 原图，UV 保留 0..162，
引擎按周期 1 重复 —— 轮胎就是这么做的（`TYRE_REPS`，`fixuv` 故意把 v 写到 1 以外）。
代价是**这张页只能属于一个部件**：矩形边缘会互相渗色，所以 wrap 只能整页生效，
而"整页一个材质"要求这个部件不和别的材质合并。见 §3.4。

#### 还有第二道上限：`.m3g` 的 UV 是 int16

就算给了独立页，UV 也不能原样写进去。`m3g` 的 texcoord 是 int16，**512 单位 = 1 个
模型 tile，4 个 tile = 1 个页面 tile**，所以能写的最大值是 `32767 / 2048 ≈ 16 个页面 tile`
（模型空间 ±64）。碳纤的 v 从 **-148** 跑到 0 —— 超了 9 倍。`m3gwrite` 是**静默饱和**的，
超了会直接钉在页角，不报错。

绕法只有一个：**让页里装 N×N 份同一块织纹，UV 除以 N**。1 个页面 tile 就代表 N 次重复，
需要的坐标立刻小 N 倍，屏幕上的织纹尺寸不变（分母和分子一起变）。本项目取 N = 8
（512² 页 = 8×8 份 64² 织纹，零重采样），UV 再整体平移到以 0 为中心，最大坐标 10 tile，
安全落在 16 以内。

平移必须是**整 tile** 的：整 tile 平移落在重复图案的同一个点上，相邻板件的织纹才不会错位。

#### 顺带一个坑：导出器不要折 UV

`m3gexport.collect_parts` 原来无条件把 UV 折进 0..1（`u %= 1`）。理由是 int16 装不下，
而"采样器周期是 1，折了看起来一样"——**这句话只在三角形不跨整数边界时成立**。
跨边界的三角形被折之后是从 0.9 反向插值到 0.1，会在整个 tile 上反向铺一遍，表现为一道
拉丝。本车碳纤 **92.5% 的三角形**都跨边界。

现在改成**装得下就原样写**（`_uv_overflows` 先整网格测一次，超了才折），
所以碳纤的 162 遍织纹才能原样进文件。

### 3.4 一个部件只有一张页，所以要先让它独立成部件

`convert.py` 会把**同名部件**合并成一个网格（`join_all`）：No Limits 把一块前保险杠
拆成 paint / carbon / grill / plastic 四个网格，它们落到 `LOD_A_FRONTBUMPER_mm_ext`
和 `LOD_A_FRONTBUMPER_mm_misc` 两个名字上，于是 misc 那一堆（碳纤唇 + 格栅 + 塑料）
**合并成一个网格**。一个网格 = 一个材质槽 = 一张页，所以它们只能共用图集。

这就是为什么碳纤以前拿不到 wrap：它从来不是独立部件。要给它独立页，必须先让它有
**自己的 tag** —— 于是就有 §3.5 那个问题：能不能用表里没有的后缀？

答案是**能**，本车的碳纤已经这么做了：

| 部件 | 旧 tag | 新 tag |
|---|---|---|
| `LOD_A_BODY_mm_carbon` | `misc`（和格栅/塑料/镀铬合并） | `carbon` |
| `LOD_A_CHASSIS_mm_carbon` | `misc` | `carbon` |
| `LOD_A_FRONTBUMPER_mm_carbon` | `misc` | `carbon` |
| `LOD_A_REARBUMPER_mm_carbon` | `misc` | `carbon` |
| `LOD_B_BODY_mm_carbon` | `misc` | `carbon` |
| `LOD_B_CHASSIS_mm_carbon` | `misc` | `carbon` |
| `LOD_B_FRONTBUMPER_mm_carbon` | `misc` | `carbon` |
| `LOD_B_REARBUMPER_mm_carbon` | `misc` | `carbon` |

`mesh_carbon_body` 例外：它是车身后甲板和两个后翼子板的**喷漆**面板（NL 也把它挂在
`carbon_opaque` 上），所以 `convert.MESH_TAGS` 把它单独送到 `ext`。见 `convert.py`
里 `MESH_TAGS` 的注释。

### 3.5 自定义后缀：`_mm_calipers` 这种名字能不能用

**能，但条件在基名上，不在 tag 上。**（本节 2026-11-17 第二次重写，前两版都错了一半。）

一句话：

| 部件名的部分 | 谁说了算 | 能不能自造 |
|---|---|---|
| `<基名>` | 引擎里的**编译期清单**（`libRealRacing3.so`，1327 条） | **不能** |
| `_mm_<tag>` | `liveryStringTable` 里的**区域名** `ext_<tag>` + 一行页行 | **能** |
| 材质 | `liveries` 表的逐部件材质行，没有就按 tag 默认 | 能 |

#### 先看引擎里到底有什么

把 `libRealRacing3.so`（33 283 886 字节，从 `base.apk` 的 `lib/arm64-v8a/` 里解出来）
拆开数一遍：

- **1327 个不带 tag 的 `LOD_<字母>_<基名>` 字符串**，按 LOD 字母分布：
  `A=209, B=206, C..H=152`（每级一套，正是"每级一份部件表"的形状）；
- `CARBON` 出现 **0** 次，`SKIRT` 出现 **0** 次 —— `LOD_A_CARBON_SKIRT` 这个名字
  在引擎里根本不存在；
- 带 `_mm_` 的只有 3 条（`LOD_A_BODY_mm_ext` 和两条镜子玻璃），也就是说**引擎不存
  全名，只存基名**，tag 是运行时拼上去的；
- 整个文件里没有任何指向这些名字的指针数组（`R_AARCH64_RELATIVE` 重定位里只有 2 条
  指向 `LOD_*`），说明它们不是数据表，而是**代码里逐个字面量**。

所以 `LOD_A_CARBON_SKIRT_mm_misc` 被跳过，原因不在 tag，在**基名压根不在清单上**。
换成长度相同的出厂基名 `LOD_A_MIRROR_RIGHT_mm_misc`，部件立刻出现、日志行消失 ——
这就是当年那次对照实验真正的含义。

#### 再看 tag 这一侧：页是 `ext_<tag>` 给的

出厂车的数据把规则写得很清楚。取捐赠车
`2018_bugatti_chiron_sport.liveries.bin.nct`：

```
17 行贴图 / 21 行材质，而它的 m3g 里有 200 多个 mesh
17 行贴图的 slot 全是区域名：
  1932 ext_ext      1933 ext_lights    1934 ext_misc    1935 ext_badges
  1936 ext_cab      1937 ext_wheel_blur 1938 ext_wheel  1939 int_ext
  1940 int_int      1941 int_sw         1/2/3 ext_windows*  5 ext_rotor
  15 int_mat02
21 行材质全是**部件名**（`LOD_A_EXHAUST_mm_ext -> car_matte` 之类）
```

**200 多个 mesh、17 行页行**，所以页不可能按部件给；而材质行是逐部件给的。
这就是两条链的分工：

```
页   : mesh 的 _mm_<tag>  ->  区域名 ext_<tag>（外饰）/ int_<tag>（内饰）  ->  那一行贴图
材质 : mesh 的全名        ->  部件名材质行，没有就按 tag 的默认
```

**部件自己的 slot 写贴图行，不改变页。** 卡钳是反证：本车给 slot 88/90/92/94 都写了
指向 `common/rrmod_misc_caliper_01` / `_13` 的行，卡钳照样读整车的 misc 页 —— 因为
`_mm_misc` 先解析到 `ext_misc`（slot 1934 → `<car>_misc`）。

#### 所以自造 tag 的正确做法（已实测通过）

`_mm_calipers` 第一次试的时候只做了"把部件名追加进字符串表 + 逐部件页行/材质行"，
结果 16 条 `contains unreferenced mesh '..._mm_calipers'`，卡钳直接消失。补上一步就通了：

```
1. liveryStringTable 追加区域名   ext_calipers        (= slot 2088)
2. 车自己的 livery 表给 2088 写一行贴图 -> common/rrmod_misc_caliper_01
3. 部件名 LOD_*_BRAKE_CALIPER_*_mm_calipers 留在表里（材质行也照写）
```

实测结果：同样的 8 个 mesh，**`unreferenced mesh` 从 16 条变成 0 条**，卡钳正常画出。
`install.py` 里这段叫 `REGION_PAGES` / `add_region_pages()`。

> 早一版手册写"自造区域名会让游戏 abort"，那次 abort 与区域名无关：那批 mesh 的基名
> 是 `CARBON_SKIRT`，本来就不在引擎清单上，而且同时改了 16 个部件名。

#### 但基名还是只能借

字符串表里有大量**这台车没用到的**出厂名。实测本车 `LOD_A_*` 还剩 **649** 个，
全部 LOD 加起来 1739 个。要加一个引擎清单里没有的**基名**（比如一块自制的碳纤维侧裙），
只能借一个出厂基名，再靠 tag 和页行把它画成想要的样子：

- **Parts 页**：`From` 列显示 `no slot - the engine skips this mesh`，底部汇总会点数；
- **Parts 页 → Borrow a shipped name...**：按当前部件的 LOD 字母和 tag 找最接近的空闲
  名，选中即复制到剪贴板，回 Blender 改物体名再导出；
- **构建时**：`rrmod/edit.py` 会在日志里逐条打 `! <mesh> has no livery slot`。

#### 顺手记一下字符串表的格式

`liveryStringTable.bin.nct` 是 RC4（key `a5 35 b3 b1 e8 43 e7 cf`，drop 133），明文是

```
u32 count
count × ( u32 len + len 字节 )
```

没有排序、没有索引、没有哈希表 —— **slot 就是下标**，所以只能往后追加，不能插中间。
三种名字共用一个命名空间：区域名（`ext_*` / `int_*`）、部件名（`LOD_*_mm_*`）、
材质名（`car_*`）。现在表里 2084 条（其中最后 8 条是卡钳改名实验留下的孤儿，无害）。

#### 想给卡钳上漆？不用改名，表里有现成的孪生槽

每只卡钳在字符串表里都有 `_mm_ext` 和 `_mm_misc` **两个**出厂名：

```
87 LOD_A_BRAKE_CALIPER_FRONT_LEFT_mm_ext    88 ..._mm_misc
89 ...FRONT_RIGHT_mm_ext                    90 ...FRONT_RIGHT_mm_misc
91 ...REAR_LEFT_mm_ext                      92 ...REAR_LEFT_mm_misc
93 ...REAR_RIGHT_mm_ext                     94 ...REAR_RIGHT_mm_misc
```

`_mm_ext` 走车漆链（跟车身同色），`_mm_misc` 走杂项材质（`car_flat` / `car_matte`）。
换的是**同一个部件的两个出厂身份**，所以两个都能用，不需要造名字。


---

## 4. 把通用贴图放进 `common/`，多台车共用一份（已实现）

目标：轮胎、刹车盘、玻璃这类**跟具体车型无关**的贴图，在 `vehicles/common/` 里只放一份，
所有自制车都指向它 —— 加十台车也只占十台车的车身贴图，通用部分一份。

### 4.1 为什么这样就够，不用改 `default.liveries`

引擎解析车自己的 livery 表①时，**路径原样使用**，`common/…` 是合法路径。
证据就在原厂车上：这台车的表①里本来就有
`common/car_windows_02.ptc.pvr.z`、`common/car_rotor_07.ptc.pvr.z`、
`common/stitching_red_mat02.ptc.pvr.z` 三行，而且都能加载。

所以「让游戏去 common 找」不需要任何新机制，只要：

1. 把图放进 `vehicles/common/<名字>.dxt.dds.z`；
2. 在**每台车**的 livery 表① 里写 `slot → common/<名字>.ptc.pvr.z`。

`default.liveries` 是**全库兜底表**，改它会影响 500 多台原厂车，还要同步
`asset_list_base.txtCache.txt` 的 md5，风险远大于收益 —— **不要为了共享去动它**。

### 4.2 命名要带 token

引擎会把贴图文件按 `_<token>_` / `_<token>.` 匹配到槽位，所以文件名里必须留 token：

```
common/rrmod_tyre.dxt.dds.z        ← 含 "_tyre."
common/rrmod_rotor.dxt.dds.z       ← 含 "_rotor."
common/rrmod_windows.dxt.dds.z     ← 含 "_windows."
common/rrmod_carbon.dxt.dds.z      ← 含 "_carbon."
```

`rrmod_` 前缀只是标明来源，引擎不看它。

### 4.3 哪些能共享、哪些不能

判据只有一条：**这张页的 UV 是不是"我们自己定的约定"**。

| 能共享 | 为什么 |
|---|---|
| `tyre` | `fixuv` 规定 u 横向铺一次、v 绕周长 `TYRE_REPS` 次。任何轮胎网格都适用。 |
| `rotor` | `fixuv` 把盘面整页平面投影。 |
| `windows` | 三个色块在固定格子里，网格采样格子中心 —— 本质是一张 3 项查表。 |
| `caliper_front` / `caliper_rear` | NL 原图 1:1 贴、网格保留 NL 自己的 UV，所以谁用这套卡钳网格谁就对得上。 |
| `carbon` | 页是一张**可平铺**的 64² 织纹，网格保留 NL 的 UV（只除以 8）。织纹没有"布局"，平移整 tile 也看不出，所以任何车的碳纤都能用它。 |

| 不能共享 | 为什么 |
|---|---|
| `misc` `lights` `badges` `cab` `ext` | 是这台车自己的美术。 |
| `chassis` | 用的是 NL 原模型的底盘图集，UV 是**每台车自己的**。四台车共用一张底盘页，等于各自去采别人车底的一块。 |
| `wheel` `wheel_blur` | 轮毂造型因车而异。 |

### 4.4 工具链怎么做的

`work/cars/tourbillon/install.py`：

```python
SHARED_PAGES = {                       # tag -> (本地页, common 下的名字)
    "tyre":    ("tourbillon_tyre",    "rrmod_tyre"),
    "rotor":   ("tourbillon_rotor",   "rrmod_rotor"),
    "windows": ("tourbillon_windows", "rrmod_windows"),
    "carbon":  ("tourbillon_carbon",  "rrmod_carbon"),   # 8x8 可平铺织纹
}
```

* `PAGES` 里**不再包含**这三张 → 装车时不会复制进车目录；
* `publish_shared()` 把它们写进 `vehicles/common/`（已存在且字节相同就跳过）；
* `SLOT_PAGES` 的 3 / 4 / 5 / 1986 四个槽改成 `common/rrmod_*`；
* `DEAD_PAGES` 里加上 `_tyre` `_rotor` `_windows`，把以前留在车目录的旧副本
  连同它的清单行一起清掉；
* `deploy.py` 的 `plan()` 额外列出这三个 common 文件；
* `rrmod/deploy.py` 的 `_other_lists` 用 `list_for()` 而不是 `owner_of()` ——
  **新建**的文件在清单里还没有行，`owner_of` 会返回空、于是文件被推上去却没有任何
  清单登记，引擎就报下载错误。`list_for` 按"邻居在哪张清单"归档，
  新文件才能正确落进 `asset_list_vehicle_common.txt`。

加第二台车时：把它的 `SHARED_PAGES` 指到**同一批** `rrmod_*` 名字，
它就一份通用贴图都不用带。

### 4.5 验证

```
adb shell grep rrmod .../apk/res/asset_list_vehicle_common.txt   # 应有五行
```
再加上设备上 `vehicles/common/rrmod_*.dxt.dds.z` 五个文件、以及 livery 表①里
3/4/5/1986/88/90/92/94/789/791/793/795 这些行指向 `common/` —— 三样齐了就不会触发下载。

### 4.6 卡钳：结论改到第四版了

这一节问的是"能不能像 No Limits 那样给卡钳单独一张图"，结论改过四次：

| 版本 | 结论 | 为什么错 |
|---|---|---|
| v1 | 不能，名字是封闭的 | 混淆了"基名"和"tag" |
| v2 | 能造 tag，但页必须逐部件写行 | 页根本不看部件行 |
| v3 | 基名只能借，tag 可以造；页由 `ext_<tag>` 给 | 对，但把剩下的症状误判成 UV |
| **v4（现行）** | **页要对，而且那张页里必须真有这个部件的画** | — |

v3 的配方是有效的，也实测过（`unreferenced mesh` 16 → 0，卡钳画出来了）。真正卡住的是
最后一步：**我们这张 misc 页里根本没有卡钳**。

#### 为什么自带车的 `_mm_misc` 卡钳能画，我们的不能

出厂车把卡钳的画**打包进自己那张 misc 页**，所以 `_mm_misc` → `ext_misc` → 那一页，
正好命中卡钳。我们这台是从 No Limits 拼出来的，misc 页里放的是别的东西，卡钳采样到的
就是**别人家的像素** —— 不是 UV 跑偏，是页里没这张画。

卡钳网格的 UV 是**按"整页就是卡钳"展开的**（`_uv_probe.py`，`build/tourbillon_shared.m3g`）：

```
LOD_A_BRAKE_CALIPER_FRONT_LEFT_mm_misc   537 v   raw u 26..1749    v -2020..-33
LOD_A_BRAKE_CALIPER_REAR_LEFT_mm_misc    426 v   raw u 55..2035    v -2004..-66
```

raw 值铺满 `0..2048`，和轮胎/轮辋/刹车盘同一个量级 —— 因为 No Limits 的
`brake_caliper_exotic_opaque` / `brake_caliper_basic_opaque` 就是两张 **128×128、
整张只画一只卡钳**的图。UV 这样展开是**对的**，不是 bug。

> 所以：**UV 不用动。** 错的是页 —— 给了一张"整页是杂项"的图，而不是"整页是卡钳"的图。

#### 正确做法（v4，符合自带车规范）

按 §3.5 那四步，给卡钳单独一个 tag + 区域名 + 页行，页指向整张就是卡钳的那张图：

```
1. 网格改名      _mm_misc -> _mm_calipers / _mm_calipers_rear（8 个 mesh）
2. 字符串表追加  8 个部件名（每个 mesh 一条）
3. 字符串表追加  2 个区域名   ext_calipers / ext_calipers_rear
4. livery 表①    给这两个区域名各写一行页
       ext_calipers      -> common/rrmod_misc_caliper_01
       ext_calipers_rear -> common/rrmod_misc_caliper_13
```

两张页是 No Limits 原图 **1:1 贴上去的**（128×128，不缩放、不重排），UV 原样保留正好对得上。
`install.py` 里这段是 `REGION_PAGES` + `add_region_pages()`，`TAG_MATERIALS` 给这两个 tag
配 `car_flat`。

| 角 | No Limits 材质 | 贴图（`common/`） | 区域名 |
|---|---|---|---|
| 前左 / 前右 | `brake_caliper_exotic_opaque` | `rrmod_misc_caliper_01` | `ext_calipers` |
| 后左 / 后右 | `brake_caliper_basic_opaque` | `rrmod_misc_caliper_13` | `ext_calipers_rear` |

> `_mm_misc` 的槽位（88/90/92/94、789/791/793/795）**保留不动**，也别指望它选页：
> 它只影响材质，页永远是区域名那一条。

**判据（v4）：页 = 区域名 `ext_<tag>` / `int_<tag>` 在表①里那一行，而且那一页里得真有
这个部件的画。** 两件事都要成立 —— 前者管"读到哪张图"，后者管"图上有没有它"。

文件名里带 `_misc_` 是为了满足 §4.2 的 token 规则（引擎的兜底匹配靠它），
`01`/`13` 是 No Limits 自己的编号，一眼能对上源图。

#### 当前状态（2026-11-17 已回滚，等重导入）

这一版配方跑通过一次（卡钳画出、`unreferenced mesh` 0 条），但同一批改动之后游戏开始在
加载资产清单时报 `signal 6`，无法归因到改名本身，所以整批回滚：

```
模型       _merge/shared_before_calipers.m3g  ->  恢复，卡钳回到 _mm_misc
字符串表   从 _rrmod_backup/20261117-131825 恢复（2084 条）
livery     删掉 ext_calipers / ext_calipers_rear 那两行
install.py REGION_PAGES = {}
```

回滚后游戏正常启动、车在车库里可见（PR 80.6）。字符串表里**留着 8 条孤儿**
`LOD_*_BRAKE_CALIPER_*_mm_calipers`（表只能追加、不能删），没有任何 mesh 引用它们，无害。

要重做这一版：`REGION_PAGES` 填回那两行 → `rename_mesh.py` 改名 → `apply_build.py` →
`deploy.py`。四步都在代码里，不用手改二进制。

> 旧判据（v2）写的是"页 = 部件槽位那一行"，**已作废**。卡钳的 slot 88/90/92/94 行
> 一直存在、一直指向卡钳图，而卡钳一直读的是整车 misc 页 —— 这就是反证。

### 4.7 工作台里怎么做（Parts / Textures 两处）

上面这些规则在工作台里已经按 v4 实现了，不用再手改二进制。

**Parts 页 → `Set page...`**（选中一个部件）

1. 目标永远是**区域槽**（`ext_<tag>`），不是部件自己的槽。部件槽上的贴图行只作为
   提示显示（"the part has its own texture row (...) and the engine ignores it"）。
2. 如果这个 tag 在字符串表里**还没有**区域名，会先问一句，然后追加 `ext_<tag>` ——
   这就是 §3.5 第 3 步，自造 tag 的入口。
3. 弹出的页选择器列出 `vehicles/common/` 和本车目录里的所有页，**同类排前面**
   （轮胎槽先给轮胎页），每行标 `shared` / `this car`。
4. 选完写的是那一行，标题栏会写清楚"这一页有 N 个 mesh 一起换"。

Parts 表新增 **Page 列**，显示的是区域名（`ext_misc`），鼠标悬停能看到它实际加载的
文件 —— 区域名是引擎解析的东西，文件是人要看的东西，两个都给。

**Textures 页 → `Add a page from a picture...`**

| 选项 | 作用 |
|---|---|
| Picture | 任意 PNG/JPG/BMP，**不缩放**（页的大小必须等于美术画的大小） |
| Name | 页名，自动折成 `[a-z0-9_]`（引擎的 token 匹配只认这个形状） |
| Format | DXT / ETC1 / ATC 可写，**PVRTC 灰掉并写明原因** |
| Where | `common/`（所有车都能引用）或本车目录（只有这台车） |

页放哪儿，行就写成什么样：

```
common/  -> common/<name>.dxt.dds.z
本车目录 -> <name>.dxt.dds.z              （相对车目录，和 <car>_misc 同一层）
```

导入完会问"要不要顺手指给刚才选中的那个槽"，点是就直接写行。只导入不指也行，
之后在 Parts 页的 `Set page...` 里选它。

> 三件都要对：**区域名存在**、**行指向的页存在**、**页里有这个部件的画**。
> 前两件工作台能替你检查（页不在工作区里会直接拒绝），第三件只有肉眼能看。

`rrmod/pages.py` 是这两处的数据层，`pages.selftest()` 会把三种可写格式各编码一次
再解码回来对照。顺手修掉的两个老 bug：`materials.MODELS` 被同名常量覆盖（模型下拉框
对每台车都会抛异常）、`materials.selftest` 的相对导入越界。


---

## 5. 轮毂缩放：游戏到底怎么定轮子大小

> **2026-11-16 已游戏内定案，2026-11-17 修正了一次。** 这一节以前写的是
> "`suspensionbehaviour` 的轮胎直径说了算"，那是照着 MonkeyTool 的**预览器**推的，
> 实测证明游戏不吃。改成 `carappearances` 之后又发现第二个错误：`f1` 不是"画出来的
> 半径"，而是"缩放基准"，中间差一个平方（见 §5.0.1）。

### 5.0 一句话规则

```
引擎绘制的轮胎半径 = f1² / 网格轮胎半径      （前 f1，后 f5）
引擎绘制的轮辋半径 = f2² / 网格轮辋半径      （前 f2，后 f6）
```

**网格多大是算进去的**，`suspensionbehaviour` 完全不参与。反过来说：只要网格没被
缩放过，`网格半径 == f`，公式退化成"1:1"，这也是 2026-11-16 那两次实验看起来
"填多少画多少"的原因——当时网格还是 No Limits 原尺寸。

### 5.0.1 为什么是平方（三次实测）

同一条外观记录，只改网格和 f，一次启动看一次：

| 网格轮胎半径 | f1 | 车库里的结果 |
|---|---|---|
| 0.3599（NL 原尺寸） | 0.3595 | **正常** |
| 0.2863（统一到模板后） | 0.3595 | **放大约 1.25 倍** |
| 0.2863（统一到模板后） | 0.2860 | **缩小约 0.8 倍** |

三组只有 `f1² / 网格` 能同时吻合（0.359、0.451、0.286）。所以引擎的实际做法是
"先按 `f1 / 网格半径` 缩一次，而这个系数又作用在已经被缩过一次的几何上"，
两次抵消成平方。

**实践含义：把轮子网格缩放到统一尺寸之后，外观记录必须开方补偿。**

```python
f1 = sqrt(目标轮胎半径 × 网格轮胎半径)
f2 = sqrt(目标轮辋半径 × 网格轮辋半径)
```

我们的 Tourbillon 统一到模板（网格胎 0.2863、辋 0.2325）后写入的就是
`f1=0.3208 f2=0.2605 f5=0.3240 f6=0.2631`，屏幕上回到 NL 的 0.3595/0.2919。
`wheelsize_set.py --fit` 已经按这条公式算，不要再手填"目标半径"。


两次对照实验（只改一个文件、只动 611 号车，其余不动，进游戏看）：

| 实验 | 改动 | 游戏内结果 |
|---|---|---|
| A | `suspensionbehaviour` `+4+21*4`/`+4+22*4`：前 0.740→**1.480**、后 0.780→**0.390** | **毫无变化** |
| B | `carappearances` 564 号记录 `f1`→**0.600**、`f5`→**0.150** | 前轮变巨型轮、后轮变备胎 |
| C | 同上记录 `f2`/`f6` 0.2400→**0.2919/0.2977** | **轮辋明显变大，尺寸正常了** |

所以 `suspensionbehaviour` 那两个直径**不要拿来调轮子**（它可能只喂物理）。

### 5.1 MonkeyTool 是怎么做的（对照，**不是**游戏规则）

MonkeyTool 的 `attachSharedCorners()` 取值顺序是：**先试 `suspensionbehaviour` 的直径 →
再试 `hubHeight / r` → 再试轮拱内切**，三个都失败才用 1.0。

它是**预览器**的逻辑，第一条分支（读 `suspensionbehaviour`）和游戏不一致 ——
所以 MonkeyTool 里看到的轮子大小不能当基准。它的第三条分支
`scale = 轮心高 / 网格半径` 反而和下面 §5.3 的做法是同一个思路。

### 5.2 "轮毂小、轮胎厚"的真因：轮辋比轮胎内孔还小

轮辋和轮胎是**两个独立的缩放**，所以两者之间会露出缝：

```
轮胎内孔实画半径 = 网格内孔 × (f1 / 网格轮胎半径)
缝 = f2 − 轮胎内孔实画半径           # 负数 = 轮辋缩在内孔里，一圈空隙
```

我们这台车（网格：轮胎 0.3501 / 内孔 0.2780 / 轮辋 0.2843）一开始抄的是 Chiron 的外观记录：

| | f1 胎 | f2 辋 | 内孔实画 | 缝 |
|---|---|---|---|---|
| 抄 Chiron 的块 | 0.3410 | 0.2400 | 0.2708 | **−31 mm** |
| `--fit` 之后 | 0.3595 | 0.2919 | 0.2854 | +6.5 mm ✓ |

`f1` 只差 5%（看不出来），`f2` 差了 16% —— 于是"轮子偏小、胎偏厚"的锅一直挂在 UV 上。
**判断顺序：先看 f2 有没有比内孔小，再看 UV，最后才怀疑几何。**

### 5.3 正确做法：一条命令

```bash
python work/cars/tourbillon/wheelsize_set.py --fit
```

`--fit` 做两件事：

1. `f1`/`f5` = **`POINT_WHEEL_*` 的 z ÷ 32**（轮心离地高；单位 1/32 m，见 `docs/points-格式.md`）。
   这样轮胎半径正好等于轮心高度，轮子填满轮拱、贴地。
2. `f2`/`f6` = **网格轮辋半径 × (f1 / 网格轮胎半径)**，保持模型自己的辋/胎比例 ——
   轮辋正好压住胎唇，既不留缝也不穿出胎壁。

`report()` 会为每条轴打印 **辋 − 内孔**，为负就报警。手工微调：`--rim F R` 写 f2/f6，
`--appearance F R` 写 f1/f5。

### 5.4 两个 nct，各管各的

| 文件 | 位置 | 管什么 |
|---|---|---|
| `vehicles/data/carappearances.appearances.nct` | 每车记录块 `+4`/`+20` = 轮胎半径，`+8`/`+24` = 轮辋半径 | **可视尺寸（唯一的旋钮）** |
| `vehicles/data/suspensionbehaviour.suspensiondata.nct` | 每车 140 B 记录 `+4+21*4`/`+4+22*4` | 轮胎直径，**游戏不用它画轮子**（大概只喂物理） |

⚠️ 外观记录是**按外观 id** 索引的，不是车辆 id：我们 611 号车对应外观记录 **564** 号。
`spec.load_spec().appearance_id()` 才是正确的查法，直接拿车辆 id 去匹配会永远找不到。

工具：

```
python wheelsize_set.py                          # 报告：网格半径 / 悬挂 / 外观 8 个浮点 / 辋−内孔 / points 轮心高
python wheelsize_set.py --fit                    # ★ 推荐：一次算好 f1/f2/f5/f6
python wheelsize_set.py --fit 0.37 0.39          # 同上，但手工指定前后轮胎半径
python wheelsize_set.py --rim 0.2919 0.2977      # 只写轮辋半径
python wheelsize_set.py --appearance 0.3595 0.3667  # 只写轮胎半径
```

改完直接 `deploy.py`（这张表在推送清单里，registry 的 md5 会自动重写）。
**判断是否生效一定要 pull 设备文件再解析** —— deploy 日志里的
"already identical, skipped" 不可信。

### 5.5 和 `vehicles/wheels` 里那些自定义轮毂比一比

`vehicles/wheels/` 下是 30 套 `wheel_*` + 一套 `tyre_standard1`，每套是
`<名>_wheels.m3g` / `_tyres.m3g` + 贴图 + `.points`。它们是**装在标准轮胎上的替换轮辋**：

| | 轮胎外半径 | 轮胎内孔(bore) | bore/外 | 轮辋外半径 | 轮辋/轮胎 |
|---|---|---|---|---|---|
| `tyre_standard1` + `wheel_sports1` | 0.2996 | 0.2185 | 0.729 | 0.2367 | 0.790 |
| 本车 | 0.3501 | 0.2780 | 0.794 | 0.2843 | 0.812 |

两个结论：

1. **"把网格缩放成它们的尺寸"是白做。** 引擎画的绝对尺寸由 `f1`/`f2` 决定，
   把网格缩小之后 k 会自己变大补回来（§5.3 的预缩小实验：网格 0.3599→0.3501，
   k 从 1.028 变 1.057，屏幕上一模一样）。**唯一没被抵消的是宽度**（引擎只拉 y/z）。
2. **"可见轮辋半径"在 `f2 > 内孔` 时就是 `f2`。** 只有 `f2` 小于内孔时才会被轮胎侧壁
   盖住/露出空隙 —— 那正是我们之前 −31 mm 的状态。

真要再调比例，工具 `wheel_fit.py` 改**网格**（都可 `--restore` 撤销）：

```
python wheel_fit.py                       # 测量 + 比例报告
python wheel_fit.py --rim 1.06            # 轮辋网格径向放大 6%
python wheel_fit.py --bore 0.3000         # 把轮胎内孔推到 0.30 m（外径不变，胎壁变薄）
python wheel_fit.py --width 1.03          # 只改胎宽（唯一能活到屏幕上的整体缩放）
python wheel_fit.py --restore
```

改了网格之后记得重跑 `--fit`（因为 `f2` 是按网格轮辋半径算的）。

### 5.6 现成模型：轮子已经做好了，怎么缩放才能正确呈现

**答案：可以缩，但外观记录必须跟着开方。** 只缩网格不动记录，轮子会按缩小的倍数
**反过来放大**（§5.0.1 的实测）。

因为引擎画的是 `f1² / 网格半径`，所以：

```
屏幕上轮胎半径 = f1² / 网格轮胎半径
屏幕上轮辋半径 = f2² / 网格轮辋半径
屏幕上轮胎内孔 = 网格内孔 × (f1 / 网格轮胎半径)   ← 只有这个比例来自网格
```

于是有两条等价的路，**选一条，别混着来**：

| 做法 | 网格 | 外观记录 | 适用 |
|---|---|---|---|
| **A. 按真实尺寸建模**（推荐） | 不动，保留 NL 尺寸 | `f1 = 网格轮胎半径` | 一台车一个轮子，最省事 |
| **B. 统一到模板尺寸**（0.465 轮辋 / 0.572 轮胎） | 径向+宽度等比缩到模板 | `f1 = sqrt(目标半径 × 网格半径)` | 多台车共用一个轮子、前后轴共用网格 |

做法 B 的好处是缩放系数可预测（模板固定，`sqrt(0.3595 × 0.2863) = 0.3208` 这类数
可以提前算好），代价是记录里不再是"真实半径"，别人看表会以为填错了——所以
`wheelsize_set.py --fit` 统一按 B 的公式算，并在报告里同时打印"实画半径"。

**注意 `--fit` 的 `--rim` 必须一起写**：`f2` 小于轮胎内孔实画半径时，轮辋会缩进
胎里露出一圈空隙（§5.2）。统一到模板后正确的四个值是
`f1=0.3208 f2=0.2605 f5=0.3240 f6=0.2631`，报告里的"gap +5.8 mm"就是这个意思。

#### 落地步骤（每台新车一次）

```bash
# 1) 量网格（y/z 径向，不要用包围盒，要用顶点半径的最大/最小值）
#    轮胎外半径 R_t、轮胎内孔 R_b、轮辋外半径 R_r
# 2) 写外观记录：f1 = R_t, f2 = R_r（后轴同理 f5/f6）
python wheelsize_set.py --appearance R_t R_t_rear
python wheelsize_set.py --rim        R_r R_r_rear
```

`--fit` 是它的自动化版本，差别只在第一步取哪个数（见下）。

#### 唯一需要判断的一件事：`f1` 该取"网格半径"还是"轮心高度"

引擎把轮子摆在 `POINT_WHEEL_*` 上，同时轮胎要落地，所以 **`f1` 既决定轮子多大、
也决定轮心离地多高**。于是：

| 取法 | 结果 | 什么时候用 |
|---|---|---|
| `f1 = 网格轮胎半径` | 严格 1:1 复刻模型 | 模型的轮子相对车身已经正确（**推荐**） |
| `f1 = 轮心高度 H`（points 的 z ÷ 32） | 轮子居中于轮拱，直径按 H 重新定 | 轮拱对不齐，或模型轮子偏小 |

**在一个已经组装好的模型里这两个数本来就相等**——因为轮子本来就坐在地上，
轮心高度天然等于轮胎半径。所以直接填网格半径即可，两边自然对上。
我们的 Tourbillon 差 9.4 mm（轮心 0.3595 vs 网格 0.3501），`--fit` 取了 H，
结果比模型大 2.7%，用户确认好看——这点差异随便取哪个都行。

#### 定稿数值（Tourbillon，网格 0.3501 / 轮辋 0.2843）

| 项 | 值 | 反算实画半径 |
|---|---|---|
| `f1` 前胎 | 0.3548 | `0.3548² / 0.3501 = 0.3595` = 前轮心高 |
| `f2` 前辋 | 0.2881 | `0.2881² / 0.2843 = 0.2920` |
| `f5` 后胎 | 0.3583 | `0.3583² / 0.3501 = 0.3667` = 后轮心高 |
| `f6` 后辋 | 0.2910 | `0.2910² / 0.2843 = 0.2979` |

**别把这四个数当成"半径"直接抄**：网格一旦再变，四个数都要按 `sqrt(目标 × 网格)`
重算。上面之所以看起来像半径，只是因为网格已经缩到 0.3501，`sqrt(0.3595×0.3501)`
离 0.3595 只差 1.3 %。

另外 `wheelsize_set.py` 报告的 `gap +6.4 mm` **不是问题**：网格自己就是轮辋外缘
0.2843 比胎内孔 0.2780 大 6.3 mm（原模型用来压住接缝），实画时按 1.0268 一起放大，
所以永远是这个正数。只有当 gap 变成负数才是真的漏缝。

#### 工作台里怎么填（2026-11-17 起）

**只填"缩放倍数"，其余不用管。**

- 构建车辆对话框 **「3. Its wheels」**：`Front scale` / `Rear scale` 填倍数
  （相对导出的 shared 网格）。旁边两个按钮：
  - *From the wheel points*：倍数 = 轮心高度 ÷ 网格轮胎半径（让轮胎落地）；
  - *Match the mesh (1:1)*：倍数 = 1.0。
  下方实时显示"实画 xx m（record 0.xxxx）"，写进外观记录的是 `record` 那个数。
- 命令行等价物：`python wheelsize_set.py --scale 1.0268 1.0474`。

两者的换算都走 `rr3lib.wheelsize.record_values()` 一个函数：

```
f_tyre = 网格轮胎半径 × sqrt(倍数)      f_rim = 网格轮辋半径 × sqrt(倍数)
```

所以**倍数变 2 %，记录只变 1 %**——记录里那个数看起来"不像半径"是正常的。
工作台在这之前直接乘倍数，等于把轮子放大两次，这是"填了系数轮子反而更大"的根因。

#### 三个坑

1. **`f2` 必须大于轮胎内孔实画半径**，否则轮辋缩进胎里、露出一圈空隙（§5.2）。
   自己做的模型只要内孔 < 轮辋就没问题，别把 `f2` 填成"想要的轮辋大小"而不是"网格的轮辋大小"。
2. **宽度（x）引擎不动。** 想让后胎比前胎宽，必须在模型里做一条
   `LOD_A_TYRE_REAR_mm_tyre` / `LOD_A_WHEEL_REAR_mm_wheel`（只有 88/149 台原厂车有）；
   只改 `f5` 只会让后轮更高、不会更宽。我们这台车就没有 rear 变体，所以前后一样宽。
3. **想改直径永远改数据，想改比例/宽度才改网格。** 反过来做（缩网格改直径）是白做，
   而且会连累宽度——因为引擎只拉 y/z，网格的 x 会原样保留。

#### MonkeyTool 的缩放数是从哪读的（可对照的第三方实现）

`nfsnl_rr3.cpp` `attachSharedCorners()`（约 2581 行起），每个轮角一次：

```cpp
float scale = (radius > 1e-4f && h->pos[1] > 1e-3f) ? h->pos[1] / radius : 1.0f;
if (scale < 0.5f || scale > 2.0f) scale = 1.0f;          // 别的车的 shared 文件
float want = tyreDiameter ? tyreDiameter[rear ? 1 : 0] : 0.0f;
if (want > 0.2f && want < 2.0f && radius > 1e-4f) {
    scale = 0.5f * want / radius;                        // 主路径：游戏数据给的直径减半
} else {
    float arch = archRadius(car, h->pos);                // 兜底：贴轮拱
    if (radius > 1e-4f && arch > radius * 0.8f && arch < radius * 1.8f) {
        float byArch = (arch - 0.035f) / radius;
        if (byArch > scale) { scale = byArch; fitted = true; }
    }
}
...
copy.positions[i + 1] = y * scale + h->pos[1];           // 只缩 y/z
copy.positions[i + 2] = z * scale + h->pos[2];           // x（宽度）不动
```

`tyreDiameter` 来自 `vehicles/data/suspensionbehaviour.suspensiondata.nct`
（`rr3TyreDiameters()`，2778 行起）：头 `u32 1` + `u32 count`，然后每台车 140 字节，
`carId` 之后是 34 个 float，**第 22、23 个是前后轮直径（米）**，读作
`r + 4 + 21*4` / `r + 4 + 22*4`。本车 0.740 / 0.780 → 半径 0.370 / 0.390。

两个要点，别抄错：

1. **它是"直径减半"，不是半径。** `0.5f * want / radius` 算出来的 scale 直接乘在
   网格上，等于把网格**烘焙**成半径 `want/2`。烘焙完网格半径 == 期望半径，这时引擎的
   `f1²/mesh` 才恰好退化成 `f1`——所以 MonkeyTool 的预览永远是对的，它没走那条平方路。
   我们在游戏里改的是**记录**、网格是共用的，就必须自己开方。
2. **兜底用的是轮拱，且带 3.5 cm 余量**：`(arch - 0.035) / radius`。本车实测前拱
   0.3746 m、后拱 0.3967 m（`arch_radius.py`），代进网格 0.3501 是 0.970 / 1.033——
   等于让前胎比现在小 3 %、后胎大 3 %，前后还不一致。超跑轮拱本来就紧，所以这个兜底值
   只能当"量级参考"，不能当目标值。

#### 为什么原厂轮子在网格里都是"小"的

因为**原厂只做了唯一一份轮胎模板**。实测 80 台原厂车（`LOD_A`）：

| 部件 | 绝对半径 | 绝对半径 CV | 结论 |
|---|---|---|---|
| `_mm_tyre` | 0.2975 ~ 0.3016，中位 **0.2993** | **0.002** | **硬模板**，463 台车同一份 |
| `_mm_wheel` | 0.1859 ~ 0.2568，中位 0.2323 | 0.062 | 接近模板 |
| `_mm_rotor` | 0.1243 ~ 0.1868，中位 0.1654 | 0.095 | 按车各自画 |
| `_mm_misc`（卡钳） | 0.1385 ~ 0.2094，中位 0.1855 | 0.099 | 按车各自画 |

轮胎半径的变异系数只有 **0.2%**——这不是"每台车的轮子恰好一样大"，而是**同一份网格**。
0.5986 m 直径也正是全局轮子库 `vehicles/wheel.m3g` 的尺寸（0.5988），
每台车的 `_shared.m3g` 都从它派生。**省的是磁盘和显存，不是逻辑需要。**

所以"游戏组装时再放大一下"确实存在，但**它不是一次缩放，是两次同一个系数**：

```
放大系数 k = f1 / 网格轮胎半径
屏幕上半径 = k × (k × 网格半径) = f1² / 网格半径     ← 只有网格 == f1 时才等于 f1
```

原厂：网格 0.2993 + `f1` 0.34 → 实画 0.386（比 f1 大 13 %，原厂自己就这么干）
你也行：网格 0.3501 + `f1` 0.3548 → 实画 0.3595
**只要网格跟着 f1 走，屏幕尺寸就只由 f1 决定**——但公式是平方，不是正比（§5.0.1）。
模板只是流水线选择，不是引擎要求。

#### 但刹车盘和卡钳不参与这个缩放

`_mm_rotor` / `_mm_misc`（卡钳）的半径**不随 `f1` 收敛**（除以 f1 后 CV 反而更大），
实验里把后轮 `f5` 改成 0.150 时，**刹车盘仍是原尺寸、比轮胎还大一圈**——直接证据。

原厂车的盘/卡钳是按真车尺寸画进网格的，所以它们"看起来对"是因为**本来就画对了**，
不是因为被缩放。对我们的意义：

| 做法 | 胎/辋 | 盘/卡钳 | 屏幕结果 |
|---|---|---|---|
| **按最终尺寸做（推荐）** | 网格 = 最终尺寸，`f1`/`f2` 填它，k = 1.0 | 也按最终尺寸画 | 全部 1:1，最直观 |
| 走原厂惯例 | 胎缩到 0.2993 模板，`f1` 填最终半径 | **仍要按最终尺寸画** | 一样，但盘/卡钳不能跟着缩 |

两种都行，**但不能混**：如果胎/辋按模板缩、盘/卡钳也跟着缩，轮子放大后刹车就会缩在轮辋里。

#### 一句话总结

> 轮子的"大小"是数据里的两个数，轮子的"长相"是网格里的三个比例。
> 组装好的模型 = 长相已经对了，所以只要把它的真实半径抄进 `f1`/`f2`，
> **一个顶点都不用动**。

### 5.7 统一尺寸：导出前把轮子缩到多大

这一节回答"我到底把轮毂外径缩到几毫米"。

#### 先分清"统一"统一的是什么

统一尺寸统一的是**整只轮组的外径**，而且必须**等比**缩放（胎、辋、盘、卡钳一起选
中一起缩），比例一个都不许动。理由见 §5.6：屏幕尺寸来自 `f1`，比例来自网格。
等比缩放既不改变呈现、也不改变比例，只改变"制作台里要填的 scale 是几"。

**统一尺寸不会让轮子变大或变小。** 我们的 Tourbillon：轮辋外径 0.569 m、轮胎
0.700 m，缩到 0.465 / 0.572 之后 scale 从 1.027 变成 1.257，`f1` 仍然是 0.3595，
屏幕上**一模一样**。统一只买到两样东西：

1. 前后轴可以共用同一份网格（真车前后不同大时，只在数据里给后轴一个 scale）；
2. 制作台里那个 scale 有个可预期的基准，不用每次重新量。

#### 统一到几：原厂模板的两个数

| 部件 | 统一外径 | 来源（80 台原厂车实测） |
|---|---|---|
| 轮胎（最大外径） | **0.599 m** | `LOD_A_TYRE_mm_tyre` 半径中位 0.2993，CV **0.2%** |
| 轮辋（最大外径） | **0.465 m** | `LOD_A_WHEEL_mm_wheel` 半径中位 0.2323 |
| 两者比例 | 0.776 | 原厂"胎壁有多厚" |

轮辋 0.465 比轮胎内孔 0.437（`tyre_standard1` 实测内孔半径 0.2185）大 14 mm，
这 14 mm 就是**轮辋唇压在胎圈上的那一圈**，是正常的，不要拿内孔当轮辋外径。

#### Blender 里怎么量：最大外径，不是包围盒对角线

轮子是个圆环，Blender 的 Item / N 面板显示的是**包围盒的三个边长**：

```
X = 胎宽（轴向）
Y = Z = 最大外径   ← 就是这个
```

所以：

1. 选中轮辋对象，看 N 面板 Dimensions 的 **Y 或 Z**（两者相等），那就是"最大外径"；
2. **不要**取三个数的最大值再乘什么系数，也不要取对角线（√2 倍，必错）；
3. 要的是**轮辋**的 Y/Z，不是轮胎的——胎比辋大一圈。

#### 操作

```
① 选中整只轮组（胎 + 辋 + 盘 + 卡钳）
② S → 输入 0.465 ÷ 当前轮辋外径   （例如 0.465 / 0.569 = 0.8173）
③ 回到 N 面板确认轮辋 Y/Z = 0.465、轮胎 Y/Z = 0.572
④ 前后轴都这么做，最终两轴网格同尺寸
⑤ 导出，制作台 "3. Its wheels" 里填前后 scale（或点 From the wheel points）
```

制作台里的 scale 就是：

```
scale = 目标轮胎半径 ÷ 统一后的轮胎半径
```

统一到 0.599 的话，`scale = f1 / 0.2993`——正好是原厂引擎自己算的那个 k。

#### 代价：刹车盘和卡钳不跟着缩放

`_mm_rotor` / `_mm_misc` 不吃 `f1` 这个缩放（§5.6 已实测）。所以：

| 统一到 | 胎/辋 | 盘/卡钳 | 结果 |
|---|---|---|---|
| 最终尺寸（k=1，推荐） | 按真车画 | 按真车画 | 全部 1:1，最省心 |
| 0.599 / 0.465 模板 | 缩到模板 | 也跟着缩了 → 屏幕上是 k 倍偏小 | k≈1 看不出来；k 明显≠1 就会缩在轮辋里 |

**k 是同一台车两轴共用的**（因为两轴同一份网格），所以"盘/卡钳小 k 倍"在两轴上
是一致的，不会一边大一边小——这也是为什么统一尺寸只该在**一台车的前后轴之间**做，
不要拿一份网格去套不同车。

> 我们的车 k = 1.027，缩到模板后盘/卡钳只小 2.7%，肉眼无感；但如果哪天做一台
> k = 1.3 的车（大脚车），就必须走"按最终尺寸、k = 1"这条路，否则刹车会明显偏小。

---

## 6. 透明 / alpha：谁决定"透不透"

一个部件要透明，**两件事必须同时成立**：

1. **页面有 alpha 通道**（DXT5，`channels=4`）；
2. **材质是混合模式**（不是 `cmDefault`）。

材质对照（`materials.bin`）：

| 材质 | cull | 效果 | 适合 |
|---|---|---|---|
| `car_glass` | `cmAlphaNoZWrite` | 按贴图 alpha 混合、不写深度 | 车窗、灯罩 |
| `car_tail_light` | `cmAlphaNoZWrite` | 同上 | 尾灯罩 |
| `car_badge_matte` | `cmAlphaNoZWrite` | 同上 | 徽标、牌照透贴 |
| `car_led_lights` | `cmAlphaNoZWrite` | LED | 日行灯 |
| `add` | `cmAlphaAddNoZWrite` | **加法混合** | 灯光叠加片 |
| `car_alpha` | `cmAlpha` | alpha 测试/调制 | 需要镂空但保留深度 |
| `car_lights` / `car_matte` / `car_flat` / `car_light_housing` | `cmDefault` | **完全不透明** | 灯内胆、黑塑料、底盘 |

血泪教训两条：

* **窗框要纯黑不透明** ⇒ 它不能拿 `car_glass`。`car_glass` 是按贴图 alpha 混合的，
  而窗框和玻璃共用 `_mm_windows` 这个 tag、共用一张页。做法是让页面上窗框那块
  **alpha=255、颜色 (2,2,4)**，玻璃那块 alpha≈110 —— 同一张 DXT5 页上，靠 alpha 区分。
  如果窗框还是发灰透明，就是页面没绑上（槽位被 `common/car_windows_02` 抢了）。
* **透贴部分不透明** ⇒ 先查页面是不是 DXT1。DXT1 没有 alpha 通道，
  `badging_alpha` / `numberplate_alpha` 这类镂空贴图放上去就是**实心黑块**。
  本项目的 `atlas.compose` 曾经用 `convert("RGB")` 读源图，把 alpha 整条丢了，
  表现就是"该透明的地方没透明"。

---

## 7. Blender → 游戏 的完整流程

```
① 模型准备      NL 导出的 glb/fbx → Blender
② 命名          LOD_<字母>_<基名>_mm_<tag>（§1）
③ UV           每个 tag 的 UV 映射进该页的矩形（§3.3）；
               自带 wrap 的页（`mode="keep"`）不映射，只除以份数并整体平移
④ 合批          同名部件合并成一个网格、一个材质槽
⑤ 分集合        <车名>_LOD<字母> 一个集合一级；损伤件单独集合
⑥ 空物体        ANCHOR_POINT_* / ANCHOR_HINGE_* / AERO_*（§1.4）
⑦ 尾翼枢轴      给 LOD A 的 WING 建 pivot 并打关键帧
⑦.5 轮子统一    整只轮组等比缩到轮辋外径 0.465 / 轮胎 0.599（§5.7），前后轴同一份
⑧ 导出          m3g（每级一个）+ wing.banim + animations.xml + points
⑨ 贴图          build_textures：一个 tag 一张页，DXT1/DXT5 + 全 mip 链
⑩ 装车          install：写进 depot，改 livery 表①（贴图）和表②（材质）；
               自定义 tag 的名字在这里追加进字符串表，**不要**追加区域名（§3.5）
⑩.5 轮子缩放    制作台 "3. Its wheels" 填前后 scale（或 From the wheel points）
⑪ 部署          adb push + 合并 asset_list（**以设备上的清单为基准合并，不要覆盖**）
```

改完一轮要**重新落到已装好的车**上时，用 `apply_build.py`（`install.py` 只跑一次）：
它把 `build/*.m3g`、`PAGES`、`SHARED_PAGES` 覆盖过去，再把新名字/新行补进两张表。
幂等，跑几次都一样。

第 ②～⑦ 步的成品在 `work/cars/tourbillon/build/tourbillon_preexport.blend`：
打开就是"已经命好名、UV 已搬好、已合批、尾翼已绑定"的状态，改完直接导出即可。

⑩.5 那一步在制作台里长这样（`Build a car` 对话框第 3 段）：

```
3. Its wheels
  Front scale  [ 1.027 x ]     Rear scale  [ 1.047 x ]
  [From the wheel points]  [Match the mesh (1:1)]
  Mesh: tyre 0.700 m across, rim 0.569 m, so the rim laps the tyre's bore by
  +6.3 mm ... Drawn: front 0.719 m (rim 0.584 m), rear 0.733 m (rim 0.595 m).
```

- **scale 就是"比网格大多少倍"**，0.000 显示成 `donor's`（沿用供体的数）；
- 它同时写四个数：`f1 = 网格胎半径 × scale`、`f2 = 网格辋半径 × scale`，后轴 `f5`/`f6` 同理——
  所以轮辋/轮胎的比例永远等于你模型里的比例，不会出现一圈空隙；
- `From the wheel points` 用 `.points` 里 `POINT_WHEEL_*` 的高度当轮胎半径反算 scale，
  就是 §5.3 的 `--fit`；`Match the mesh (1:1)` 把两个 scale 设成 1.000；
- 下面那行读数会告诉你**画出来到底多大**（含轮辋直径和唇压量），先看一眼再点构建。

---

## 8. 排查清单（症状 → 先查什么）

| 症状 | 先查 |
|---|---|
| 某个部件完全不出现 | 名字在 `liveryStringTable` 里吗？`_mm_<tag>` 在吗？ |
| **启动即闪退**（logcat 里 `signal 6 (Aborted)`，最后一行是 `Assets are added asset_list_vehicle_<你的车>.txt`，无 Java 栈、无 tombstone） | 本车 `liveries` 表① 里有没有**挂在自造区域名上的贴图行**（`ext_carbon` 这种）？有就删掉，改成按部件逐行（§3.5）。这是唯一被证实会让引擎在加载期 abort 的表改动 |
| 用了自定义 tag，部件不出现 | 名字追加了吗？表①里**这个部件**有贴图行吗？（不是区域，是部件，§3.5） |
| 自定义 tag 的部件出现了但是纯色/发黑 | 表②缺这个部件名的材质行 ⇒ 落到硬编码兜底。补一行（`car_matte`） |
| 整个部件是纯色块 | 页面是不是没绑上（槽位被别人占了）？ |
| 图案被放大成几块色斑 | UV 没搬进矩形，或页面是整图不是图集 |
| 织纹/格栅出现"拉丝"或局部反向 | UV 被折进 0..1 了（跨 tile 的三角形反向插值）⇒ 页改成 N×N 份 + UV 除以 N（§3.3） |
| 贴图整体错位 / 贴到了别的图 | 槽位指到了 `common/` 的兜底页 |
| 该透明的没透明 | 页面是 DXT1（无 alpha）？材质是 `cmDefault`？ |
| 该不透明的透明了 | 材质是 `cmAlphaNoZWrite` 一类，换不透明材质 |
| 左右两侧不一样 | `tyre` / `tyre_flipped` 只写了一个 |
| 格栅/镀铬在 B、C 级上变成车身色 | 那个基名在原版表里没有 `misc` 槽，名字被降级成 `ext` 了 ⇒ 追加 `_mm_misc`（§3.5 末） |
| 轮子偏小 / 轮胎过厚 | **先算 `f2 − 轮胎内孔实画半径`**（负数 = 一圈空隙）；`wheelsize_set.py --fit` 修。再查 UV，最后才怀疑几何。`suspensionbehaviour` 与轮子大小**无关** |
| 改了 `suspensionbehaviour` 轮子没反应 | 正常，游戏不用它画轮子；改 `carappearances` 的 f1/f2/f5/f6 |
| 轮子整体偏大/偏小但比例正常 | 只改 `f1`/`f5`（`--appearance`） |
| 轮辋大但穿出胎壁 / 或缩在胎里 | 只改 `f2`/`f6`（`--rim`），别动 `f1`/`f5` |
| 制作台里 scale 填了没生效 | 分支选错：`modify` 走 `set_wheel_sizes` 写外观记录，`new` 走 `build_appearance`；两处都只认外观 id，外观 id 必须能从 spec 里查到 |
| 远处变成原厂车 | 最远 LOD 没填（H 要从 G 复制） |
| 进游戏前报资源错误 | `asset_list` 的 md5 没同步 |
