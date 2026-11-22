# Real Racing 3 资源工具（Blender 插件 v2.0）

读写《真实赛车3》14.0.1 的车辆资源：`.m3g` 模型、`.points` 锚点、`.banim` 零件动画、
`<车>_animations.xml` 动画片段表，以及"克隆一台新车"所需的六张共享表。

> 本版（2.0）相对旧版（空物体版）的变化：
> **从只读变成可写**。新增 `.m3g` 导出、`.points` 导出、`.banim` 导出、动画 XML 导出、
> 添加整车、改涂装材质、材质/部件浏览器共 10 个新功能；并修好了旧版只注册了 6 个类、
> 导致"导入模型 / 导入整车"在菜单里根本看不见的 bug。

配套参考手册：[`docs/材质与部件清单.md`](../docs/材质与部件清单.md)（297 个材质、
1869 个部件名、79 个引擎锚点名、12 个动画片段名，全表）。

---

## 0. 一页速查

| 我想做什么 | 用哪个入口 |
| --- | --- |
| 看一台车长什么样 | Import ▸ **Whole car (folder)**，选车目录 |
| 只看车身模型 | Import ▸ **Model (.m3g)** |
| 做尾翼/主动空力动画 | Import ▸ **Whole car** → 改 `AERO_*` 关键帧 → Export ▸ **Part animation (.banim)** + **Animation clips (.xml)** |
| 给自己拆出来的尾翼做动画 | 零件命名成 `LOD_A_WING_REAR_mm_<tag>` → Export ▸ **Part animation (.banim)**，`tracks_from = NAME` |
| 做车门/引擎盖这类铰链动画 | Import ▸ **Anchors (.points)** → 改 `HINGE_*` → Export ▸ **Anchors (.points)** |
| 加一台自己的车 | Car ▸ **Build a new car** |
| 改某个零件的材质 | Car ▸ **Set part material** |
| 换涂装 | 导入时 `materials = Game materials`，然后选中车身 Car ▸ **Switch paint scheme** 填预设号 |
| 把游戏贴图导成 PNG | Textures ▸ **Export textures**（解 `.dxt.dds.z` / `.z.bin` / `.pvr.z`） |
| 导入驾驶员 | Import ▸ **Driver (posed)**，选 `Depot` + `Car`，得到 15 部件 + 根空物体 |
| 只看内饰 / 车头视角壳 | Import ▸ **Whole car**，`LOD` 选 `int_a` / `int_b` / `shared` |
| 查有哪些材质/部件名可用 | Reference ▸ **Material / part catalog** |

三条最容易踩的规则（细节见第 8 节）：

1. **动画基就是 Blender 基。** `AERO_*` 空物体的 location / rotation_euler
   就是引擎里的米和弧度，导出时不做任何换算。
2. **锚点基不是。** 锚点导入时做了 `Rot180Z`，所以导出时再乘一次
   `Rot180Z`（180° 绕 Z 自逆）就回到引擎值。
3. **主动空力要三件套**：spec 里的行为串 + `<车>_wing.banim` + `<车>_animations.xml`。
   缺任何一件，模型在游戏里就是块死铁。
4. **会动的零件，顶点留在自己原点周围。** 游戏按 `pivot + R @ vertex` 摆零件，
   所以导出时不能把物体变换烘进顶点。插件会自己认出动画零件并强制局部坐标。

---

## 1. 安装

1. 把整个 `rr3_blender_addon/` 目录拷到
   `%APPDATA%\Blender Foundation\Blender\<版本>\scripts\addons\`
   （或打包成 zip 用 *Edit ▸ Preferences ▸ Add-ons ▸ Install from Disk*）。
2. *Edit ▸ Preferences ▸ Add-ons* 里搜索 `Real Racing 3`，勾选启用。
3. 3D 视图按 `N`，右侧会出现 **RR3** 标签页。

支持 Blender **4.2 – 4.5**（4.4/5.0 的 slotted action 也兼容：取关键帧的代码同时走
`action.fcurves` 和 `layers[*].strips[*].channelbags[*].fcurves` 两条路）。

插件不依赖游戏安装位置。所有路径都在操作符的弹窗里手填。

---

## 2. 入口一览

### 2.1 菜单

- *File ▸ Import ▸ Real Racing 3*：7 项（整车文件夹 / 模型 / 动画片段 / 动画空物体 / 动画挂模型 / 锚点 / 驾驶员）
- *File ▸ Export ▸ Real Racing 3*：4 项（`.m3g` / `.points` / `.banim` / `.xml`）

### 2.2 N 面板（RR3 标签页）

| 分组 | 按钮 | `bl_idname` |
| --- | --- | --- |
| Import | Whole car (folder) | `import_scene.rr3_vehicle` |
| | Model (.m3g) | `import_scene.rr3_m3g` |
| | Driver (posed) | `import_scene.rr3_driver` |
| | Animation clips (.banim + XML) | `import_scene.rr3_banim_clips` |
| | Animation as empties (.banim) | `import_scene.rr3_banim_empties` |
| | Anchors (.points) | `import_scene.rr3_points` |
| Export | Model (.m3g) | `export_scene.rr3_m3g` |
| | Anchors (.points) | `export_scene.rr3_points` |
| | Part animation (.banim) | `export_scene.rr3_banim` |
| | Animation clips (.xml) | `export_scene.rr3_animxml` |
| Textures | Export textures | `rr3.export_textures` |
| | Load car textures | `rr3.load_textures` |
| Car | Build a new car | `rr3.build_car` |
| | Set part material | `rr3.set_part_material` |
| | Switch paint scheme | `rr3.switch_paint` |
| | Audit part materials | `rr3.audit_paint` |
| Reference | Material / part catalog | `rr3.catalog` |
| | File report | `rr3.report_to_text` |

所有"生成文本"的功能（catalog、audit、build car 日志、文件报告）都写进
**Text Editor 的数据块**（`rr3_catalog` / `rr3_audit` / `rr3_build_car` / 文件名），
不弹窗、不刷屏。

---

## 3. 导入

### 3.1 导入整车（推荐起点）

*Import ▸ Whole car (folder)*，选中车目录（例如 `.../vehicles/2012_lexus_lfa/`），
不用选文件 —— 插件自己从路径解析出车名和 LOD。

它会建一个集合，里面包含：

- **车身**：`<车>_a.m3g`（LOD A）
- **轮子**：4 个 `WHEEL_FL/FR/BL/BR` 空物体做枢轴，轮网格 parent 到枢轴下；
  右轮的 `rotation_euler.z` 预置 π（镜像）。枢轴带自定义属性
  `rr3_corner` / `rr3_steers` / `rr3_point`。
- **方向盘**：`STEERING_WHEEL` 枢轴，位置来自 `POINT_DRIVER` 锚点。
- **主动空力部件**：每个会动的零件一个 `AERO_<序号>_<短名>` 空物体
  （CUBE 显示），带 `rr3_track` / `rr3_part` 属性；它下面挂着对应的网格。
  勾了 `hinge_pivot` 时，枢轴点会自动放在"贴合车身那一侧 10% 顶点的质心"，
  这样转动看起来像铰链而不是像绕原点转。
- **锚点**：`ANCHOR_` 前缀的空物体（来自 `.points`）。

关键参数：

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `lod` | A | A..H，A 最精细；另有 `shared` / `int_a` / `int_b` 三项导入完整模型（见下） |
| `convert_axes` | 开 | 把引擎的 Y-up 转成 Blender 的 Z-up。关掉会得到躺倒的车 |
| `textures` | 开 | 自动解出 `.dxt.dds.z` 贴图并建材质 |
| `animate` | 开 | 自动读 `<车>_wing.banim` 建关键帧 |
| `fps` | 30 | 关键帧换算用 |
| `import_anchors` | 开 | 同时导入 `.points` |
| `height_adjust` | 0.0 | 车身升降（米），±0.3 |
| `rot_mode` | DELTA | `DELTA` 把首帧角度归零，方便手调；`ABS` 保留引擎原值 |
| `delta_axes` | 全关 | 逐轴做差（X/Y/Z 各自独立），勾上哪个轴就只把那个轴的首帧归零；**优先于 `rot_mode`** |
| `hinge_pivot` | 关 | 用铰链质心代替原点做枢轴 |
| `pos_scale` | 1.0 | 位置倍率 |
| `pos_factor` | 1.0 | 锚点位置倍率（`pos_scale` 之外再乘一次，作用在锚点/轮子/尾翼/动画上） |
| `facing` | +Y | `+Y` 与 `.m3g` 一致（恒等）；`-Y` 整车绕 Z 转 180°（拿 FBX 对位置时用） |
| `mirror_x` | 关 | 整车在 X 上镜像（拿到的 FBX 是镜像的时候用） |
| `wheel_size` | engine | 轮子缩放依据：`engine` 与游戏一致 / `ground` 轮胎正好落地 / `none` 保持模板 |
| `wheel_scale` | 1.0 | 在 `wheel_size` 之上再乘的手动倍率（0.2–4.0） |
| `rear_tyre_width` | 开 | 后轮只有更宽轮辋、没有独立后轮胎时，按轮辋宽度比拉宽后轮胎 |
| `brakes` | 开 | 一起装刹车盘和卡钳（只有 LOD A / B 有这两个网格） |
| `materials` | simple | `simple` = 按名字生成的假色 + 图集贴图；`game` = 读 `materials.bin` + 涂装表，**一个材质槽、每涂装一套预设** |
| `paint` | -1 | 默认把哪个预设连到 Material Output（-1 = 第 0 套）；只对 `materials=game` 有效 |
| `material_depot` | 空 | 装 `materials/materials.bin` 的目录。留空则从车目录向上找 8 层；车被拷出 depot 时填这里 |
| `separate_damage` | 开 | 把 `*_DAMAGE` / `*_BROKEN_*` 损伤件放进 `<车名>_LOD<X>_damaged` 子集合 |
| `separate_camera` | 开 | 把 `BONNETCAM_*` 车头视角壳和 `LIT_*_GLOW` 发光片放进 `<车名>_LOD<X>_camera` 子集合 |

> **装配顺序**：整车导入是"**先导 points，再按 points 位置装轮子**"。
> `WHEEL_*` 枢轴直接取对应 `ANCHOR_POINT_WHEEL_*` 的位置，轮网格挂在枢轴下、
> **不做任何居中**——轮子局部坐标系里 `x = 0` 就是外侧面，正好落在
> `POINT_WHEEL_*` 上。右轮是**绕竖轴转半圈**（`x=-x, z=-z`），不是镜像。
> 模型原点在地面（轮心高 ≈ 一个轮胎半径），所以**没有 Y 方向的偏移**。
>
> **朝向 / 镜像**由**一个根空物体**（`<车名>_ROOT`）承担：车身、轮子枢轴、尾翼枢轴、
> 锚点全部挂在它下面整体转/镜像，不会出现"车身转了轮子没转"。

> **刹车盘和卡钳**：引擎用**和轮胎一样的径向系数**缩放它们，所以插件也是
> `scale = (1.0, k, k)`、枢轴同样落在 `POINT_WHEEL_*` 上。区别只有一条：
> **卡钳不跟轮子转**——四个卡钳各自建模在自己那个角落、盘的后方
> （`BRAKE_CALIPER_FRONT_LEFT` 在 `+x`、`_FRONT_RIGHT` 在 `-x`），所以右轮的
> 半圈旋转只作用在轮辋、轮胎和刹车盘上。卡钳对象带 `rr3_brake_fixed = True`。
> 只有 **LOD A 和 LOD B** 有这两个网格（全库 398–401 台）；LOD C 及以下本来就只有
> 轮辋和轮胎，这不是缺件。关掉 `brakes` 就只导轮辋和轮胎。

> **LOD F 的轮子已经是装好的**：全库 463 台车的 `LOD_F` 轮网格都**跨越车身左右两侧**
> （`x` 从 −0.95 到 +0.95 这种），是四个轮子已经按真实尺寸摆好的整车网格。
> 再缩放或再按 points 平移就会做两遍。所以这种 LOD 走单独的路径：挂在一个位于
> 世界原点的 `WHEEL_LODF_ASSEMBLED` 空物体下，`scale` 保持 1、位置保持 0，
> 网格顶点原样。对象带 `rr3_pre_assembled = True`。

> **LOD G / H 的轮子**：`_shared.m3g` 里的轮子网格**只到 F 级**（463 台车的 G、H 两级
> 轮子网格数都是 0）。游戏的做法是 **G 级复用 F 级那套预装配网格、H 级不要轮子**
> （已经是最低质量）。插件照做：`WHEEL_LOD_FALLBACK = {"G": "F"}`、`NO_WHEEL_LODS = ("H",)`。
> 所以 LOD G 里会看到一个 `LOD_F_WHEEL_mm_wheel`，LOD H 没有轮子，两者都不是缺件。

> **`shared` / `int_a` / `int_b` 是完整模型**：`lod` 下拉里这三项不是 LOD 等级，而是
> `<车>_shared.m3g`（车头视角壳，43 个网格，含轮子）、`<车>_int_a.m3g` /
> `<车>_int_b.m3g`（第一人称内饰，各 43–44 个网格）。选它们时**整份导入**：不装轮子、
> 不装空力、不建 `_camera` / `_damaged` 子集合、不报"缺 shared / 缺 wing"，
> 集合名就是 `<车名>_shared` / `<车名>_int_a` / `<车名>_int_b`。

> **相机壳和发光片**（`separate_camera`）：`_shared.m3g` 里除了轮子还有
> `LOD_A_BONNETCAM_BODY/HOOD_*`（车头视角用的第二个车身，和引擎盖完全重合、会 z-fighting）
> 和 `LOD_A_LIT_*_GLOW`（面向相机的发光片）。它们进 `<车名>_LOD<X>_camera`，
> 对象带 `rr3_camera = True`。注意车身文件里 375/463 台也有 `BONNETCAM`，但都是
> `BONNETCAM_HOOD_DAMAGE_*`，已经被损伤集合收走了。

> **为什么需要 `wheel_size`**：游戏里的轮子网格是**一个 0.60 m 的通用模板**，每台车加载时
> 按自己的轮胎直径径向拉伸（只拉 y/z，宽度不动）。全库 463 台车的模板半径变异系数只有
> 0.46%，所以不缩放的话"所有车轮子都一样大"。`engine` 复现游戏算的那个系数（中位前轮
> ×1.153、后轮 ×1.196），`ground` 用加载半径让轮胎正好贴地（约小 5%）。
> 细节见 `docs/轮毂与轮胎缩放.md`。

> **前后轮不一样的车**：88 台有独立的 `TYRE_REAR`、149 台有独立的 `WHEEL_REAR`。
> 有专用网格就用专用的；只有更宽后轮辋、没有后轮胎的 62 台（其中 9 台轮辋比例偏离 1.0
> 超过 2%）按轮辋宽度比拉宽后轮胎（实测 87 台两种网格都有的车，两个比值中位偏差 0.6%）。

> **游戏材质与涂装**（`materials=game`）：不再用假颜色，而是走游戏自己的链路
> `网格名 → liveryStringTable 部件槽 → 材质槽（涂装覆盖 → 车表 → default）→ 材质名 → materials.bin 的着色器与 LUT`。
> **每个网格仍然只有一个材质槽**（和游戏一致），涂装是槽内材质的**预设**：每个预设一套
> `bsdf_<n>` + `atlas_<n>` + 两条色带，**只有当前预设连到 Material Output**。
> 选中网格、用 **Car ▸ Switch paint scheme** 填预设号就换涂装，槽数不变。
>
> - 材质名形如 `<车名>_<游戏材质名>`；各涂装参数不同的加 `_paint` 后缀。
> - **只有涂装表真的覆盖到的部件才有多预设**。轮胎、轮毂、刹车盘、底盘这些槽在任何
>   涂装下都不变（P1 的 `LOD_A_TYRE` / `LOD_A_WHEEL` 的 `overridden_by` 是空的），
>   只给 1 套预设、`rr3_paint_slots = 1`。实测 P1 83 个网格里 20 个有 6 套、63 个只有 1 套。
> - Base Color = 该涂装的 `_ext_<颜色>` 贴图（其它 tag 用对应图集）；Roughness / Metallic 由
>   `mu_MaterialSpecularPower_Base` 和 fresnel LUT 均值换算；**Specular Tint = 游戏值 / 255**
>   （游戏存 0–255 字节，直接写会让高光放大 255 倍、整车像镀铬）；**清漆层**（Coat）在
>   `mu_MaterialSpecularPower_Top ≥ 200` 时打开（金属漆 base 宽 8 / top 锐 1000，光漆反过来）。
> - 两条 LUT（`ramp_fresnel_<n>` / `ramp_specular_<n>`）以**未连线**的贴图节点存在预设里，想自己接就接。
> - 网格对象带 `rr3_paint_slots`（有几套涂装）、`rr3_paint_slot`（当前是第几套）、
>   `rr3_paint_presets`（名字表）。
> - 贴图**打包进 .blend**（`img.pack()`），重启 Blender 不会变粉色。
> - **贴图会垂直翻转**：游戏把每张图都存成 bottom-up，MonkeyTool 解码时翻一次再告诉模型
>   读取器不要翻 V，所以正确组合是"翻图、不翻 UV"。`texport.export_png` 默认就翻。
> - 有些 tag 在涂装表里本来就没有槽（`chassis`、`dash`、`taillight_glow` 等），这些网格没有贴图，
>   只按材质参数上色。细节见 `docs/游戏材质与涂装.md`。
> - **材质表要在 depot 里找得到**。插件从车目录向上最多找 8 层 `materials/materials.bin`；
>   把车目录单独拷出来就找不到了，这时导入会报一条
>   `game materials: cannot find the depot's materials/materials.bin above …` 并保留占位材质。
>   把 `material_depot` 指到 `.depot` 文件夹即可（以前这里是静默退回，看起来就像"材质没导入"）。

### 3.2 导入单个模型

*Import ▸ Model (.m3g)*，参数：`scale`（位置倍率）、`convert_axes`、`import_anchors`。
每个网格对象会带自定义属性 `rr3_material`（材质名）和 `rr3_material_id`（材质槽号）。

### 3.3 导入锚点

*Import ▸ Anchors (.points)*。参数 `facing`（`-Y` / `+Y`）和 `mirror_x`。
空物体带属性 `rr3_point_type` / `rr3_point_type_name` / `rr3_point_raw` /
`rr3_orientation` / `rr3_spline_count`。

### 3.4 导入动画

两种方式：

- **Animation clips (.banim + XML)** —— 把每个动画片段做成独立的 NLA 轨道，
  片段名和帧范围来自 XML。做"看得见的动画"用这个。
- **Animation as empties (.banim)** —— 只建空物体和关键帧，不绑骨骼。
  看数据、改数值用这个。

都支持 `delta_x/y/z` 微调、`convert_axes`、`pos_scale`、`facing` / `mirror_x`、
`flip_mode`（`ROOT` / `BAKE`）。

### 3.5 导入驾驶员

*Import ▸ Driver (posed)*（`import_scene.rr3_driver`）。资源不在车目录里，在
`<depot>/driver/`：`driver_lod_a.m3g`（15 个部件）、`driver_lod_b.m3g`（同姿势低模）、
`driver_lod_c/d.m3g`（各 1 个网格，腿已在座位里），另有 12 台车的定制版。
动画是 `driver.banim`（通用坐姿）或 `driver_<车>.banim`（36 个按车定制）。

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `depot` | 空 | `.depot` 文件夹；留空则从当前 .blend 位置向上找 |
| `car` | 空 | 车目录名。用它找 `driver_lod_c_<车>` 变体，并自动查出该车的 `.bin.nct` 记录 |
| `car_record` | 空 | **推荐**。该车的 `vehicles/data/<id>_<车>.bin.nct`，里面写着这台车用哪个 `driver_<x>.banim` |
| `banim_file` | 空 | 手选 `.banim`，优先级最高 |
| `lod` | a | `a` 15 部件 / `b` 同姿势低模 / `c`·`d` 只有腿 |
| `skin` | 空 | `alesi`、`alonso`、`ferrari`、`raikkonen`… 留空用 `driver.dxt.dds.z` |
| `fps` | 30 | 关键帧换算 |
| `max_frames` | 0 | 0 = 全部帧（`driver.banim` 是 60 帧） |
| `placement` | NODE | `NODE` 每个部件绕自己的关节转（游戏就是这么做的）/ `BONE` / `JOINT` |
| `root_turn` | 开 | `.banim` 里人偶朝 −Y、车头朝 +Y，最后给根空物体绕 Z 转 180° |
| `flip_driver` | **关** | 逐部件镜像（会换手、把旋转共轭）。一般不要用，改用 `root_turn` |
| `with_root` | 开 | 建 `<车名>_DRIVER_ROOT`，所有部件挂上去，移动它整体搬动 |
| `textures` | 开 | 加载 `vehicles/common/driver*.dxt.dds.z` |

**装配顺序**：先按 `.banim` 在它自己的空间摆好每个部件 → 部件挂到 `<车名>_DRIVER_ROOT`
→ 由这个根空物体转 180° 对齐车头。部件保留游戏原始变换，只有根在转向。

**动画怎么选**（优先级从高到低）：`banim_file` 手选 → `car_record` 里写的 →
按车名猜（`driver_<x>.banim` 的 `<x>` 出现在车名里，最长者胜）→ `driver.banim`。

> 猜名字经常猜错，所以要读记录：`2014_toyota_ts040` → `driver_919_lmp1.banim`、
> `2014_ferrari_f1_f14t` → `driver_laferrari.banim`、
> `2015_ferrari_fxx-k` / `2017_lamborghini_centenario` / `2019_mclaren_senna` →
> `driver_renault_dezirconcept.banim`。540 条记录里 224 条带这个字段，引用 34 个 `.banim`。

结果是**一个集合 + 一个根空物体 + 15 个带 action 的部件**（LOD C/D 是 1 个网格、不摆姿态）。

> **位置单位是 1/65536 米**，不是 1/32768。这条对**所有** `.banim` 都成立
> （MonkeyTool 的 `nodeMatrix()` 对每个 banim 都 `/65536`）。早期版本把驾驶员按
> 1/32768 算，人会大一倍（1.69 m 高、0.98 m 宽）。
>
> **`placement = NODE` 不能换成 `BONE`**：部件是绕自己的关节建模的，用包围盒中心
> 做支点会把关节拉散，整体高度从 0.93 m 变成 1.40 m。
>
> **材质名 `driver` 在 `materials.bin` 里不存在**，也没有对应的涂装槽 —— 贴图固定取
> `vehicles/common/driver.dxt.dds.z`，这是特判的。
>
> **贴图一定要接到 Base Color 上**。`.m3g` 的材质表里那 15 个部件的材质就叫 `driver`，
> 所以 `_build_mesh_object()` 会先建一个同名、按名字哈希出假色、**没有贴图**的材质；
> `_driver_material()` 必须**修**它而不是以为它是新的。检查的是"成品状态"：贴图节点存在、
> 图片正确、且 `Color` 真的连到了某个 Principled BSDF 的 `Base Color`。不满足就整棵树重建，
> 满足就原样保留（重复导入是幂等的，用户改过的参数也不会被冲掉）。
> 材质槽 `link` 强制设成 `DATA`、所有 polygon 的 `material_index` 归 0，
> 否则槽挂在对象上或索引指偏，节点树里有贴图但人偶上仍然看不见。

---

## 4. 导出

### 4.1 导出 `.m3g`

*Export ▸ Model (.m3g)*。把选中的网格（没选就是全部网格）写成 m3g。

| 参数 | 说明 |
| --- | --- |
| `template` | **强烈建议填**。从这台车的原版 `_a.m3g` 里抄 81 字节头部块、材质列表和 author 串。不填会生成"干净但和引擎期望不同"的文件。 |
| `all_objects` | 导出全部网格而不是选中项 |
| `use_world` | 应用对象变换（默认开） |
| `flip_v` | V 轴翻转（默认开） |
| `pos_scale` | 每个原始单位多少米，0 = 用模板值，否则自动拟合到 ±1024 原始单位 |

> **不要把 `pos_scale` 设成 1.0。** 文件本身合法，但引擎会走慢速顶点路径
> （扫描线卡顿、高光丢失）。原厂车的值是 **0.0021973606199026108**。
> 导出后如果值接近 1.0，插件会额外报一条 WARNING 提醒。

材质列表只写真正被网格引用的材质 —— 引擎碰到没人引用的材质项会崩。

### 4.2 导出 `.points`

*Export ▸ Anchors (.points)*。识别 `POINT_*` / `HINGE_*` / `TRANSFORM_*` 命名的空物体
（或带 `rr3_point_type` 属性的）。导出前会跑一遍校验，问题以 WARNING 逐条报出。

覆盖值（override 表）从场景自定义属性 `rr3_overrides` 读，格式是每行 `名字<TAB>数值`。

### 4.3 导出 `.banim`

*Export ▸ Part animation (.banim)*。

| 参数 | 说明 |
| --- | --- |
| `tracks_from` | `AERO`（`AERO_*` 空物体，默认）/ `NAME`（按零件名，见下）/ `TAGGED`（带 `rr3_track` 属性）/ `SELECTED`（当前选中）/ `PARTS`（带 `rr3_track` 的网格，驾驶员那种一部件一轨道） |
| `part_filter` | 只在 `NAME` 用：网格名里必须含的词，默认 `WING` |
| `fps` | 0 = 用场景帧率 |
| `duration_ms` | 0 = 按最后一帧算 |

一个轨道 = 一个零件，6 个通道（位置 XYZ 米 + Euler XYZ 度），存的是相对静止姿态的增量。

> 关键帧取值必须**逐帧求值**（`frame_set` 后读），不能直接读对象当前姿态 ——
> 否则每条曲线写的都是同一个数。插件已经这么做了。

#### `NAME` 模式：手工拆出来的尾翼怎么排轨道

给车身里拆出来的零件做动画时，不用建空物体、不用打标签 —— 只要**按游戏的命名
习惯给物体起名**，轨道号由名字算出来：

| 网格名 | 零件基名 | 轨道 |
| --- | --- | --- |
| `LOD_A_WING_REAR_mm_ext` | `WING_REAR` | 0 |
| `LOD_A_WING_REAR_mm_misc` | `WING_REAR` | 0（同一个零件，只写一条） |
| `LOD_A_WING_STRUT_mm_misc` | `WING_STRUT` | 1 |
| `LOD_A_WING_STRUT_REAR_mm_misc` | `WING_STRUT_REAR` | 2 |

规则有三条，都是从原厂文件反推出来的（52 台有尾翼 `banim` 的车，52/52 吻合）：

1. **基名 = 去掉 `LOD_<字母>_` 前缀和 `_mm_<tag>` 后缀**。同一零件的不同材质后缀
   （`_mm_ext` / `_mm_misc` / `_mm_chassis`）是**一个零件**，只写一条轨道 ——
   写两条会让后面每个轨道号都错位。
2. **轨道号 = 基名字母序**。不是 m3g 里的网格顺序（实测 3 台车里有 2 台不一致），
   也不是物体在 Blender 里的顺序。`WING_REAR` < `WING_STRUT` < `WING_STRUT_REAR`。
3. **`*_BRAKES` 不单独占轨道**。尾翼刹车灯是独立网格但跟着尾翼动，原厂 52 台里
   一台都没有它的轨道。

`AERO_*` 空物体和它们的子网格会被跳过（导入器建的空物体名字里也含零件名，
但它是**承载者**不是零件）。如果零件挂在 `AERO_*` 空物体下、动画打在空物体上，
`NAME` 模式会自动去空物体上取姿态。

#### 动画零件的顶点必须留在自己的原点周围

游戏把零件放在 `pivot + R @ vertex`。所以**会动的零件，顶点要相对自己的原点**
（也就是物体 origin 在零件中心，顶点是它周围的局部坐标），导出时**不能**把
物体变换烘进顶点 —— 否则游戏叠加 pivot 之后零件会飞到两倍距离外。

插件现在会自动判断：网格自己有 action、或者挂在带 action 的 `AERO_*` 空物体下，
就**强制按局部坐标导出**，不管面板上 `use_world` 勾没勾。静态零件不受影响
（它们的 origin 本来就是 0，两种算法结果一样）。

实测（用户 LFA 工程）：`LOD_A_WING_REAR_mm_ext` origin `(0, −1.823, 0.933)`，
局部包围盒 `(−0.511,−0.257,−0.104)..(0.511,0.109,0.029)`；旧行为会导出成
`(−0.511, 0.829, 1.715)..(0.511, 0.962, 2.08)`，新行为导出
`(−0.511,−0.104,−0.109)..(0.511,0.029,0.257)`（已换轴）。

### 4.4 导出动画片段表

*Export ▸ Animation clips (.xml)*，写 `<车>_animations.xml`。

- `preset = WING`：生成 `wing_initial` + `wing_up` + `wing_down` 三段（尾翼标准三件套）
- `preset = PIVOT`：生成 `wing_initial` + `pivot_up` + `pivot_down`（`down` 是倒放）

`start_frame` / `end_frame` 指定帧范围。

---

## 5. 添加一台新车

*Car ▸ Build a new car*。这是把 `analysis/newcar_build.py` 那一整套流程搬进插件。

### 5.1 参数

| 参数 | 说明 |
| --- | --- |
| `depot` | 原版 `.depot` 目录（读六张表） |
| `pkg` | `files` 目录（读 `apk/res/` 下的清单） |
| `out_dir` | 输出目录，会生成一个 `files/` 镜像 |
| `donor_name` | 克隆哪台车（**必须有 appearance 记录**，见下） |
| `new_name` | 新名字，必须 `<年份>_<厂牌>_<型号>` 形式 |
| `new_id` | 0 = 自动取下一个空闲 id |
| `body_m3g` | 用自己的车身模型替换 donor 的 `_a.m3g`（可选） |
| `aero` | 是否打开主动空力（原地替换空 token） |
| `aliases` | 是否生成 donor 命名别名副本（**保持开启**） |

### 5.2 它写了什么

一次写全 10 个产物：

1. `vehicles/data/<id>_<name>.bin.nct` —— spec（id / 型号 / 显示名 / appearance id / 空力开关）
2. `cardesc.list.nct` —— 加一行
3. `suspensionbehaviour.suspensiondata.nct` —— 克隆 140 字节记录改 id
4. `cardamagethresholds.damage.nct` —— 克隆 116 字节记录改 id
5. `carappearances.appearances.nct` —— 克隆外观块改 id 和名字
6. `vehicles/data/liveries/<name>.liveries.bin.nct` —— 6 套涂装 + 尾翼跟随车漆
7. `vehicles/<name>/` —— 整个车目录（模型 + 贴图 + 锚点）
8. `apk/res/asset_list_vehicle_<name>.txt` —— 车辆清单
9. `.depot/asset_list_base.txtCache.txt` —— 注册表
10. `apk/res/asset_list_vehicle_data.txt` —— 数据清单

### 5.3 三条血泪教训（代码里已经处理，但你改代码时要知道）

**① donor 命名别名副本不能省。**
贴图名是烘进 `.m3g` 里的。如果只把文件重命名成新名字，m3g 里写的还是
`2012_lexus_lfa_ext.dxt.dds.z`，引擎找不到 → 全车洋红。
所以每个含新名字的文件都要在**同一目录**再放一份 donor 原名的副本。
`livery/` 子目录里的 `_ext_*.dxt.dds.z` 特别容易漏（旧版就漏了）。

**② 空力开关必须原地替换。**
spec 里 `generic_race` 前面有个空 token（`00 00 00 00 0c 00 00 00 generic_race`）。
打开空力是把这 12 字节原地换成 `DeployWhenBraking` 的 token 序列。
**不能插入** —— 插入会让后面所有字段错位，引擎在 `+0x18` 读空指针直接崩。

**③ 尾翼材质是 donor 克隆唯一继承不到的东西。**
donor 本身没有尾翼零件，它的 livery 表里没有 `LOD_A_WING_REAR_mm_ext` 这一行。
不补的话引擎退回 `car_flat`（纯黑高光），尾翼发暗。
插件会自动把 `745`（尾翼）指向和 `30`（车身）相同的材质，跟随每个涂装的车漆。

### 5.4 donor 怎么选

**必须选一个有 appearance 记录的车。** 540 个 spec 里有 63 个没有
（F1 系列、NASCAR 涂装车、少数概念车 —— 它们复用别的车体），
它们的车目录也不存在。插件遇到 `appearance_id == 0` 会失败。

另外注意：spec 文件名里的 `<年份>_<厂牌>_<型号>` **不等于**车目录名
（例：spec 叫 `2012_aston_martin_one77`，目录叫 `2012_astonmartin_one77`）。
插件内部走 appearance 表的 `record.name` 做 join，不要自己按文件名猜。

---

## 6. 涂装材质

*Car ▸ Set part material*：改一个零件在某台车上的材质，直接落盘。

| 参数 | 说明 |
| --- | --- |
| `depot` / `car` | 目标 |
| `part` | 部件名，例如 `LOD_A_WING_REAR_mm_ext`（完整名单见参考手册） |
| `material` | 材质名，例如 `car_paint_matte` |
| `copy_body` | 勾上 = 直接抄车身的材质（最省事） |

*Car ▸ Audit part materials*：反过来查 —— 给定网格列表，报出每个网格最终用的材质
和它的来源层级：

| 层级 | 含义 |
| --- | --- |
| `paint` | 涂装级覆盖（跟随每个涂装，**最佳**） |
| `car` | 本车表②（全车固定） |
| `default` | `default.liveries.bin.nct` 兜底（通用光泽漆，不跟车漆） |
| `none` | 该车没有这条涂装 |
| `no-slot` | 部件名在 `liveryStringTable` 里查不到（**无法上漆**） |

上漆的三级回退顺序就是上表从上往下。只落到 `default` 时，尾翼是"通用光泽漆"，
不跟随车漆 —— 这就是旧版尾翼发暗的根因。

> `LOD_A_INT_GLASS_CRACKED_FRONT_01..04`、`LOD_A_INT_HAND_GEAR`、
> `LOD_A_INT_HAND_STEER`、`add`、`projected_lights` 这 8 个名字**没有 `_mm_` 标签**，
> 在槽位表里查不到，因此永远无法上漆。别白费力气。

### 6.1 把游戏材质整套导进 Blender（`materials = game`）

上面两个 operator 都是**改数据**（写回 `.liveries.bin.nct`，进游戏才生效）。
如果只是想在 Blender 里看到每套涂装长什么样，导入时把 `materials` 改成 `game`：

| 项 | 内容 |
| --- | --- |
| 数据源 | `.depot/materials/materials.bin`（297 个材质实例 + 186 条着色器绑定） |
| 材质名 | `<车名>_<游戏材质名>`；各涂装参数不同的加 `_paint` 后缀；同一台车同一个游戏材质名配了不同图集时再加 tag 后缀（`<车>_car_flat_cab`） |
| 材质槽 | **每个网格仍然只有一个槽**（和游戏一致）；涂装是槽内材质的**预设** |
| 预设结构 | 每个涂装一套 `bsdf_<n>` + `atlas_<n>`（贴图）+ `ramp_fresnel_<n>` / `ramp_specular_<n>`，各自装在一个 `NodeFrame`（`preset_<n>`）里 |
| 哪些部件有多预设 | **只有涂装表覆盖到的**。轮胎 / 轮毂 / 刹车盘 / 底盘在任何涂装下都不变，只给 1 套预设（P1：20 个网格 6 套、63 个 1 套）；`_mm_cab` 内饰面板有时也跟着涂装变（Veyron GSV 的 `cab` 有 `cab.png` / `cab_chrome.png` / `cab_orange.png`） |
| 贴图来源 | **涂装覆盖 → 车自己的表 → `default.liveries.bin.nct`**。窗户 / 轮胎 / 刹车盘 / 底盘的图在 `vehicles/common`，车表里通常没有那一行（全库 `ext_tyre` 缺 153 台、`ext_rotor` 155、`ext_windows` 90、`ext_chassis` 540 全部） |
| 连线 | **只有当前预设的 BSDF 连到 Material Output**，其余预设不连 |
| Base Color | 该涂装的 `<车名>_ext_<颜色>.dxt.dds.z`（其它 tag 用对应图集，`extension="REPEAT"`）；无贴图时用涂装色的纯色 |
| Roughness | `sqrt(2 / (mu_MaterialSpecularPower_Base + 2))` |
| Metallic | fresnel 色带均值 → `clamp((mean-0.35)/0.40, 0, 1)` |
| Specular Tint | `mu_MaterialSpecularColour_Base / 255`，夹到 0..1（**不除 255 会整车像镀铬**） |
| Coat | 仅当 `mu_MaterialSpecularPower_Top >= 200`，`Coat Roughness = sqrt(2/(top+2))` |
| 色带 | `ramp_fresnel_<n>` / `ramp_specular_<n>` 是**未连线**的贴图节点，想接就接 |
| 贴图朝向 | **垂直翻转**（游戏存 bottom-up，UV 按文件原样） |
| 网格属性 | `rr3_paint_slots`（共几套）、`rr3_paint_slot`（当前第几套）、`rr3_paint_presets`（名字表）、`rr3_damaged`（损伤件） |
| 材质属性 | `rr3_presets`、`rr3_preset_names`、`rr3_preset_active`、`rr3_textures`、`rr3_material`、`rr3_fresnel`、`rr3_specular` |

换涂装：选中网格 → *Car ▸ Switch paint scheme* → `Paint scheme` 填预设号（0 起）。
它只做一件事：把那个预设的 BSDF 重新连到 Material Output（并更新 `rr3_paint_slot`），
**不会增加材质槽**。

> **同一台车的不同涂装可以用不同材质模板**。P1 的黄色涂装是 `car_paint_gloss`
> （Roughness 0.045、无清漆层），蓝色是 `car_paint_metallic_cool`
> （Roughness 0.447、带清漆层）。所以换涂装不只是换贴图。
>
> **有些 tag 在涂装表里没有槽**（`chassis` / `dash` / `dashplanes` / `taillight_glow` /
> `sidelight_glow`，全库 0 覆盖），这些网格只有材质参数、没有贴图；但
> `tyre` / `rotor` / `windows` 现在能从 `vehicles/common` 拿到图。
>
> **贴图是打包进 .blend 的**（`img.pack()`）。解码产物原本落在临时目录，
> 不打包的话重启 Blender 后每张贴图都变粉色——那看起来就像"贴图从来没导入过"。
>
> 完整链路、297 块 / 186 绑定的字段语义、LUT 实测色带值见 `docs/游戏材质与涂装.md`。

### 6.2 贴图容器与导出（`rr3.export_textures` / `rr3.load_textures`）

游戏的贴图不是普通图片，`rr3lib/texport.py` 认得这几种容器：

| 后缀 | 布局 | 车辆用量 |
| --- | --- | --- |
| `.dxt.dds.z` | `u32 rawSize` + zlib → DDS | 21,446 |
| `.dxt.dds.z.bin` | `u32 0xFFFFFFFF, version, frames, flags` + 每帧 `[u32 comp][u32 rawSize]` + zlib | 924（阴影图，实测 19–43 帧） |
| `.dxt.dds.bin` | 重复的 `[u32 rawSize][raw DDS]`，不压缩 | 2（实测 128 帧 × 32,900） |
| `.rgb.pvr.z` | `u32 rawSize` + zlib → PVR（8/16/24/32 bpp） | 3,229（车辆里 12 个） |
| `.atc.dds.z` / `.etc.dds.z` / `.ptc.pvr.z` | 块格式，**故意不解**（只在 `gui_assets`） | 0 |

DXT1/DXT3/DXT5 由 `rr3lib/ddsdecode.py` 自己解（numpy 可用时快 8 倍，两条路径字节级一致），
所以不依赖 Blender 的 DDS 支持。

**导出的 PNG 是垂直翻转过的**（`texport.FLIP_V = True`）。游戏把每张图都存成 bottom-up：
文件第 0 行是画面最下面一行。MonkeyTool 的解码器无条件 `flipImageVertically()`，然后
告诉模型读取器 **不要**翻 V（`loadM3g(..., flipV = false)` 是默认值）——"翻图、不翻 UV"
才是配套的正确组合。想要原始行序就传 `flip_v=False`：

```python
texport.export_png(src, dst)             # 翻转（默认，给 Blender 用）
texport.export_png(src, dst, flip_v=False)   # 原始顺序，和文件逐行对得上
```

| operator | 作用 |
| --- | --- |
| `rr3.export_textures` | `source` 车目录 / `target` 输出目录 / `fmt` `png` 或 `dds` / `frame` 多帧阴影图取第几帧 / `skip_existing`。结果写进 Text 块 `rr3_textures` |
| `rr3.load_textures` | `car_dir` 车目录（**递归**，含 `livery/`）；把该车所有图集 + 12 条着色器色带加载成 Blender 图像（色带设 `Non-Color`，全部 `pack()`）。加载前先清掉旧版本解码 |

`rr3.load_textures` 会**递归**扫车目录，所以 `<车>/livery/` 里的涂装图集也会进（平铺
`listdir` 会正好漏掉换涂装最需要的那几张）。它还会**先清掉旧解码**：产物按
`<临时目录>/rr3_dds/v<n>/` 分版本存（当前 `v2`），加载前把更早版本的目录、散落的
`.png/.dds`、以及引用它们的 Blender 图像一并删除 —— 否则同一张贴图会同时存在正反两份，
而 Blender 只按路径命中已加载的图像，不会重新读盘。

命令行等价：

```python
from rr3lib import texport
texport.export_tree(car_dir, out_dir, "png")
texport.selftest(depot)          # 每种容器解一个样本，返回失败数
texport.flip_rows(w, h, ch, px)  # 只翻行，不写文件
```

---

## 7. 参考数据

*Reference ▸ Material / part catalog*，`which` 选
`materials` / `paints` / `parts` / `tags` / `all`，结果写进 Text 块 `rr3_catalog`。

规模（14.0.1 全库实测）：

- 材质 **297** 个实例 / **137** 个模板
- `appCarPaint` 分类下 **41** 个（其中 `car_paint_*` 36 个，另 5 个是
  `car_body_plastic` / `car_gloss` / `car_matte` / `car_matte_doublesided` / `car_rotor_low`
  —— 它们的 application 也是 `appCarPaint`，所以按分类筛出来的 41 条 **不等于** 36 个漆种）
- 部件名 **1869** 个 / 基名 **948** 个 / `_mm_` 标签 **30** 种 / 槽位号 22..1931
- 引擎锚点名 **79** 个（37 个 `POINT_` + 42 个 `HINGE_`）
- 动画片段名 **12** 个

完整表格见 [`docs/材质与部件清单.md`](../docs/材质与部件清单.md)。

---

## 8. 动画类型与行为设置

这一节是整份文档最容易搞错的地方，请完整读一遍。

### 8.1 坐标系与单位（必读）

| 内容 | 换算 |
| --- | --- |
| **动画基**（`.banim`） | **就是 Blender 基**。`cm @ ANIM_TO_MODEL == 单位矩阵`，所以 `AERO_*` 空物体的 location（米）和 rotation_euler（弧度）**就是**引擎值，导出不做换算。 |
| **锚点基**（`.points`） | 不是。导入是 `Rot180Z @ engine`，导出即 `engine = Rot180Z @ blender`。 |
| 位置原始单位 | `.banim` 用 1/65536 米；`.points` 用 1/32；`rig` 用 1/32768 |
| 角度原始单位 | 180/32768 度（≈0.0055°/单位） |
| 通道 | 每轨 6 个：`pos_x/y/z`（米）+ `rot_x/y/z`（度，Euler XYZ，Rz@Ry@Rx） |
| 轨道 ↔ 零件 | 一轨一个零件，存相对静止姿态的增量 |

### 8.2 三种动画载体

| 载体 | 文件 | 作用 |
| --- | --- | --- |
| 零件关键帧 | `<车>_wing.banim` 等 | **能不能动** |
| 片段表 | `<车>_animations.xml` | **什么时候动哪一段** |
| 行为串 | spec 里 `generic_race` 前那个 token | **由什么条件触发** |

**三者互相独立。** 实测 53 台有 `_wing.banim` 的车里，只有 7 台写了
`DeployWhenBraking`，另有 **16 台完全没写行为串却有完整尾翼动画**。
所以"没有 `DeployWhenBraking` 就没有尾翼动画"是错的。

### 8.3 12 个官方片段名

| 片段 | 含义 |
| --- | --- |
| `wing_initial` | 静止姿态（收起 / 缩回）。**必须有** |
| `wing_race_initial` | 比赛中的静止姿态 |
| `wing_up` | 展开空力面（刹车襟翼抬起） |
| `wing_down` | 收回空力面 |
| `pivot_up` | 抬起活动枢轴 |
| `pivot_down` | 放下活动枢轴 |
| `neutral_to_speed` | 中性 → 高速位 |
| `speed_to_neutral` | 高速 → 中性 |
| `speed_to_brake` | 高速 → 空气刹车位 |
| `brake_to_speed` | 空气刹车 → 高速 |
| `neutral_to_brake` | 中性 → 空气刹车 |
| `brake_to_neutral` | 空气刹车 → 中性 |

实际用法（53 台车全库统计）：

| 片段组合 | 台数 |
| --- | --- |
| `wing_initial` + `wing_up` + `wing_down` + `pivot_up` + `pivot_down` | 17 |
| `wing_initial` + `pivot_up` + `pivot_down` | 14 |
| 上面两个再 + `wing_race_initial` | 8 |
| `wing_initial` + `neutral_to_speed` … `brake_to_neutral`（完整 7 段） | 6 |
| `wing_initial` + `wing_up` | 4 |
| 其它 | 4 |

**最小可用组合**：`wing_initial` + `wing_up` + `wing_down`。
只做 `pivot_up`/`pivot_down` 的车也有 14 台，说明引擎对缺片段是宽容的。

### 8.4 六种行为串

格式是**自由文本 + 逗号参数**，引擎按前缀认：
`<行为名>[, <参数1>, <参数2>]`

| 行为 | 参数 | 全库台数 | 含义 |
| --- | --- | --- | --- |
| `DeployWhenBraking` | 无 | 13 | 刹车时展开 |
| `NascarAirBrake` | 无 | 40 | NASCAR 专用空气刹车 |
| `DeployAtSpeed` | 速度, 速度 | 5 | 到某速度展开/收回 |
| `BrakeAndSpeedCombo` | 速度, 速度 | 4 | 刹车 + 速度组合触发 |
| `EngineFan` | 无 | 2 | 引擎风扇（917K、909 Bergspyder） |
| `PaganiHuarya` | 无 | 2 | Huayra 的活动襟翼（**官方拼写就是 Huarya**） |
| `None` | 速度, 速度 | 1 | Jesko Absolut，参数在但行为名是 None |

实测参数取值：`DeployAtSpeed, 120, 60` / `, 275, 220` / `, 100, 60`；
`BrakeAndSpeedCombo, 180, 170` / `, 120, 80` / `, 100, 60`。

另外 225 台车这个位置是空 token（`00 00 00 00`，无行为），250 台根本没有
`generic_race` 串（走 `generic_road` / `generic_carbon` / `bf_super` 等其它模式串）。

### 8.5 静态尾翼 vs 主动空力（互斥）

- 有 `HINGE_WING_REAR_LEFT` / `HINGE_WING_REAR_RIGHT` 的 **17 台全是 NASCAR**，
  且**全部没有** `_wing.banim`。
- 有 `_wing.banim` 的 **53 台全部 0 条 WING 铰链**。
- `HINGE_WING_REAR`（不带 L/R）全库 0 命中。

结论：**主动空力走 `.banim`，静态尾翼走 `.points` 铰链，两者不共存。**
做主动空力时不要给尾翼加铰链，反之亦然。

### 8.6 完整制作流程（做一套能动的尾翼）

1. *Import ▸ Whole car*，选车目录，勾 `animate`。
2. 场景里找到 `AERO_1_WING_REAR_mm_ext`（格式是 `AERO_<轨道号>_<零件名>`，`LOD_A_` 前缀被去掉）。
3. 在帧 1 摆"收起"，帧 N 摆"展开"，插关键帧。
4. *Export ▸ Part animation (.banim)*，`tracks_from = AERO`，存成 `<车>_wing.banim`。
   `Container from` 可以留空——尾块由部件名自动生成，带不带 donor 结果逐字节相同。
5. *Export ▸ Animation clips (.xml)*，`preset = WING`，存成 `<车>_animations.xml`。
6. 想让它自动动，还要打开 spec 的行为开关（*Build a new car* 时勾 `aero`，
   或手工把 spec 里 `generic_race` 前的空 token 换成 `DeployWhenBraking`）。
7. 想换模型就 *Export ▸ Model (.m3g)*，`template` 填原版 `_a.m3g`。

---

## 9. 已知限制

1. **`appearances.link.nct` 格式未解出。** 12,685 字节，头是
   `u32 version=1, u32 count=82`，后面是 `u32 len + 车目录名`，但每条记录后面的
   u32 数量不定，三种解析都失败。目前只当作"82 条外观链接"看待，不做读写。
2. **spec 的字段位置不能硬编码。** `tokenize` 读字符串是"u32 长度 + 精确长度字节"，
   但文件把每个字符串补零到 4 字节边界，补零在 token 流里变成额外零 token，
   数量随车而异。所以 appearance id 的 token 索引在 84..112 之间浮动
   （旧代码写死 86，只对 218/540 成立）。现在改成按字节形状定位，188/188 正确。
3. **33 个 spec 没有显示名 token，63 个没有 appearance 记录。** 这些是真实存在的
   情况（车复用别的车体），不是 bug。插件不会硬插字段 —— 插入会让引擎读到垃圾。
4. **`.m3g` 导出只写三角网格 + 材质 + 顶点色 + UV。** 不支持蒙皮、多材质单网格、
   骨骼。导出前后请用 *File report* 核对。
5. **轮子半径有三个不同定义**，别混用：
   自由半径（`suspensiondata` 浮点 21/22 ÷ 2，中位 0.349/0.363 米）、
   加载半径（`carappearances` 外观块 f1/f5，中位 0.328/0.336）、
   轮心高度（`.points` 的 `POINT_WHEEL_*` z，中位 0.319）。
   加载半径 = 自由半径 − 0.0165..0.0180 米（低 4.8~5.0%）。
6. **`gametext.txt` 是另一套密钥的密文**（key `b1 75 a5 23 f3 c2 b6 15`，
   丢 211 字节），不是 `.nct` 那套。要读它得用 `nct.crypt(data, KEY_GAMETEXT, 211)`。
7. **部分车的 `CAR_NAME_` 有两个**（`CAR_NAME_XX` + `CAR_NAME_XX_SHORT`），
   第一个才是显示名。
8. **游戏材质是换算出来的，不是引擎原式。** `roughness = sqrt(2/(power+2))`、
   `metallic = clamp((fresnel均值-0.35)/0.40, 0, 1)` 都是经验映射；两条 LUT 以未连线
   节点保留，观感接近但不等于游戏内截帧。着色器源码（`.depot/Shaders/*.xsh`）是
   加密二进制，暂时读不出原式。
9. **`.ptc.pvr.z` / `.atc.dds.z` / `.etc.dds.z` 不解。** 它们是 PVRTC/ATC/ETC 块压缩，
   只出现在 `gui_assets`（各 9 个文件），车辆从不用；`texport` 会明确跳过而不是报错。
10. **游戏材质要求车还在 depot 里。** 材质表在 depot 根下（`materials/materials.bin`、
    `vehicles/data/liveries/`），插件从车目录向上最多找 8 层。把车目录单独拷出来就用
    `material_depot` 指到 `.depot`；不指的话导入会报一条 warning 并保留占位材质
    （早期版本这里是静默退回，看起来像"材质完全没导入"）。
11. **`rr3.load_textures` 会删旧解码。** 产物按 `<临时目录>/rr3_dds/v<n>/` 分版本存
    （当前 `v2`），加载前清掉更早版本的目录与引用它们的 Blender 图像。所以它不只"加载"，
    也会移除上一版解码 —— 故意的，否则同一张图会同时存在正反两份。
12. **窗户 / 轮胎 / 刹车盘 / 底盘的贴图在 `vehicles/common` 里。** 车自己的涂装表往往没有
    那一行（`ext_tyre` 缺 153 台、`ext_rotor` 155、`ext_windows` 90、`ext_chassis` 540 全部），
    只有 `default.liveries.bin.nct` 才有。取贴图按「涂装覆盖 → 车表 → default 表」三级回退。
13. **损伤件默认进子集合。** 车身文件同时带完好版和 `*_DAMAGE` / `*_BROKEN_*` 版，
    默认把后者放进 `<车名>_LOD<X>_damaged`（`separate_damage` 可关），对象带 `rr3_damaged`。
14. **一个材质名只对应一张图集。** `car_flat` / `car_matte` / `car_glass` 一台车会用在多个
    网格上、各配不同图集（P1 3 处、Veyron GSV 4 处）；撞名时自动加 tag 后缀，
    否则先建的赢、其余全穿错贴图。
15. **`_shared.m3g` 的轮子只到 LOD F。** G 级复用 F 级那套预装配网格，H 级没有轮子
    （`WHEEL_LOD_FALLBACK = {"G": "F"}`、`NO_WHEEL_LODS = ("H",)`），两者都不是缺件。
16. **`shared` / `int_a` / `int_b` 不是 LOD 等级**，是完整模型。选它们时整份导入，
    不装轮子、不装空力、不建相机/损伤子集合。
17. **驾驶员不在车目录里**，在 `<depot>/driver/`；材质名 `driver` 不在 `materials.bin` 里，
    贴图固定取 `vehicles/common/driver.dxt.dds.z`；位置单位 1/65536 米。
18. **没有"一次导入全部 LOD"了。** 那个入口已删除（每个 LOD 都会重算材质与贴图，慢且
    容易留下同名材质）；需要多级就分几次导入。

---

## 10. 命令行与测试

插件本体只能在 Blender 里跑，但底层 `rr3lib/` 是纯 Python，可以脱离 Blender 用：

```bash
# 端到端测"添加新车"全流程（不需要 Blender，输出到 %TEMP%\rr3_cartest）
python tools\test_car.py

# 把根目录的 rr3lib 同步进插件（插件里那份是拷贝）
python tools\sync_rr3lib.py
python tools\sync_rr3lib.py --check

# 重新生成参考手册
python tools\gen_catalog_doc.py
```

Blender 内部冒烟测试（16 项，覆盖注册 / 导入导出往返 / 面板）：

```bash
"C:\Program Files\Blender Foundation\Blender 4.5\blender.exe" -b --factory-startup --python tools\smoke_addon.py
```

另外三套（都需要游戏文件）：

```bash
# 轮子装配/缩放：107 项
"...\blender.exe" -b --factory-startup --python tools\smoke_wheels.py

# 驾驶员导入：38 项
"...\blender.exe" -b --factory-startup --python tools\smoke_driver.py

# 游戏材质/涂装/贴图：113 项
"...\blender.exe" -b --factory-startup --python tools\smoke_materials.py
```

> 测试脚本在仓库根的 `tools/`，不在插件目录里。

---

## 11. 格式速查（供核对）

### `.m3g`

JSR-184 容器的变体。文件头 12 字节 magic
`AB 4A 53 52 31 38 34 BB 0D 0A 1A 0A`，然后是一串对象段，每段
`u8 type + u32 size + 负载`。用到 9 种类型：
`0 FileInfo` / `3 Appearance` / `9 Group` / `11 TriStripArray` / `14 Mesh` /
`20 VertexArray` / `21 VertexBuffer` / `24 MaterialList`。

每个 mesh 对象里有 **81 字节**的引擎私有块（`obj.offset+12` 起），导出时从模板原样抄。

### `.points`

```
u32 version
u32 count
count × 记录（每条 u32 type, u32 nameOffset, u32 size, 负载）
```

4 种记录：`0 POINT`（3×f32×32）/ `1 SPLINE`（u16 段数 + 每段 u16 点数 + 点×3f×32）/
`2 HINGE`（3f×32 + 9f 方向）/ `3 TRANSFORM`（16f，平移部分 ×32）。

### `.banim`

```
u32 magic (0x7F7F7F00 | variant)
[u32 version，仅当 variant & 0x10]
u32 fieldA（30 = 30fps）
u32 trackCount
f32 durationMs
u32 dataOffset
trackCount × 116 字节记录（29 个 u32：14 对 (通道槽, 键数)，加索引）
键数据（每键 8 字节：u32 时间 + i32 值）
尾部原始数据（尾块）
名字表（u32 n + n × (u32 len, cstr)）
```

一个轨道固定 14 个槽，每槽两个通道（位置/旋转各 3 轴 = 6 通道，其余 8 槽未用）。
空槽写 `(0, 键数)`。

**尾块不能省。** 形状是 `u32 n` + `n × u32`，**`n` 永远等于轨道数**。全库 53 个
`_wing.banim` 无一例外都有它。缺了它引擎会**加载成功然后永不套用**这个 clip——
部件停在建模原点，尾翼看起来就是"消失了"。

那 `n` 个 word **是部件常量，不是哈希**。crc32 / crc32c / adler32 / fnv1 / fnv1a /
djb2 / sdbm / elf / oaat / java / murmur3 / xxh32 对名字的十种拼法（带不带 `LOD_A_`、
`AERO_`、`_mm_ext`，ascii 与 utf-16）**命中 0 次**。成立的是：轨道数与部件数相等的
52 台车里，word 的**多重集**与下表**每次都相等**（顺序不保证，有 5 台车与字母序不同）。

| 部件 | word |
| --- | --- |
| `WING` | `0x6C8C2CFD` |
| `WING_REAR` | `0xAD45C13F` |
| `WING_REAR_LEFT` | `0x4202CB14` |
| `WING_REAR_RIGHT` | `0x344991DE` |
| `WING_STRUT` | `0x89CEF5E4` |
| `WING_STRUT_REAR` | `0x57529DC8` |

导出器自己会写（`rr3_export.TRAILER_WORDS` / `trailer_words_for()`），所以
`Container from` 是可选的：**带 donor 与不带 donor 导出的结果逐字节相同**。

### `<车>_animations.xml`

```xml
<?xml version="1.0"?>

<anims>
	<anim name="wing_initial">
		<frames start="0" end="0" />
	</anim>
	<anim name="wing_up">
		<frames start="0" end="30" />
	</anim>
</anims>
```

帧号是 30fps 下的帧，不是毫秒。`frames_for(ms) = round(ms / 33)`。
