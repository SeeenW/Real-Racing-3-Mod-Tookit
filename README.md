# Real Racing 3 资源解析 / Blender 导入导出工具

> **English** — A toolkit for the Real Racing 3 asset format. Readers and
> writers for `.m3g` models, `.points` anchors, `.banim` animations and the six
> shared `.nct` tables; a Blender add-on (20 operators, `N` panel) that imports
> and exports a whole car; and a desktop manager that builds a car into a
> playable installation and deploys it over adb. Written against Build 260716,
> Python 3.12 + PySide6, Blender 4.5.
>
> **No game data is included** — you need your own installation. Not affiliated
> with the game's publisher; see [NOTICE.md](NOTICE.md). MIT licensed.
>
> Download the packaged builds from the
> [releases page](https://github.com/SeeenW/Real-Racing-3-Mod-Tookit/releases).
> 中文说明从这里往下看。

针对 Build 260716 数据包（`E:\DXT_480x320+960x640+2048x1536数据包-Build260716\files\.depot`）编写。
可读可写：解析 `.m3g` / `.points` / `.banim` / `.nct` 六张共享表，也能反向写出模型、锚点、动画片段，
并一次性造出一台能装进游戏的整车（spec + 四张共享表 + 涂装表 + 车目录 + 资源清单）。

Blender 插件现在注册 **20 个 operator**（7 个导入、4 个导出、2 个贴图、4 个车辆/材质、1 个目录、1 个报告、1 个法向修复）
加 1 个面板，面板在 3D 视图的 `N` → `RR3` 页（18 个按钮），菜单在 `File → Import / Export`。
读写全在内存里完成，不改源文件；只有主动执行导出/造车才会写出新文件。

> **新手从这里开始**：`docs/插件使用手册.md` —— 按“我要做成一件事”组织的 6 个任务
> （导入整车 / 换车身模型 / 做会动的尾翼 / 加一台全新车 / 改零件材质 / 做静态铰链）
> 加一节驾驶员导入。插件本身的参数表在 `rr3_blender_addon/README.md`。

## 交付物

```
rr3_blender_addon.zip      ← Blender 插件包（直接“安装…”用，不要解压）
rr3_blender_addon/         ← 插件源码目录
  __init__.py              ← 20 个 operator + N 面板
  rr3_export.py            ← Blender → .points / .banim / _animations.xml
  m3gexport.py             ← Blender → .m3g（模板继承 + 定点顶点）
  README.md                ← ★ 插件参数手册（11 章，全部参数表 + 格式速查）
  rr3lib/                  ← 与根目录 rr3lib/ 同步的 28 个模块
rr3lib/                    ← 解析 / 写出库，28 个模块：
  m3g.py m3gwrite.py geometry.py texture.py   ← 模型读 / 写 / 网格 / DDS
  ddsdecode.py texport.py                     ← DXT1/3/5 解码 / 私有贴图容器导出
  points.py points_write.py                   ← 锚点读 / 写
  banim.py banim_write.py rig.py driver.py    ← 动画读 / 写 / 骨骼解算 / 驾驶员资源
  parts.py animxml.py wheelsize.py            ← 整车装配 / 动画片段 XML / 轮子缩放系数
  livery.py appearance.py spec.py             ← 涂装表 / 外观表 / 车辆规格
  gamematerial.py carmaterial.py pvr.py       ← 游戏材质库 / 每涂装材质 / PVR 色带
  catalog.py catalog_data.py                  ← 材质与部件名目录（内置，不需游戏数据）
  manifest.py car.py nct.py dashplanes.py     ← 资源清单 / 一站式造车 / 加密 / 仪表盘
rr3dump.py / .bat / _json.bat ← 命令行解析器：拖文件即导出 .txt / .json
dump/                      ← 已对指定文件生成的示例输出
tools/                     ← 生成器与测试（都可直接 python 跑）
  gen_catalog_doc.py       ← 生成 docs/材质与部件清单.md
  gen_anim_doc.py          ← 生成 docs/动画片段与行为对照.md
  test_car.py              ← 造车端到端测试（13 步，不需 Blender）
  smoke_addon.py           ← Blender headless 冒烟测试（16 项）
  smoke_wheels.py          ← 轮子装配/缩放测试（4 台车 × 3 模式 + 刹车 + LOD G/H，107 项）
  smoke_driver.py          ← 驾驶员导入测试（记录配动画 + 坐姿 + 根空物体 + 皮肤接线，50 项）
  smoke_materials.py       ← 游戏材质/涂装/贴图测试（3 台车，113 项）
  sync_rr3lib.py           ← 根 rr3lib/ → 插件 rr3lib/ 同步（--check 只检查）
analysis/                  ← 逆向过程中的探针与测试脚本
  series_tool.py           ← ★ 自定义赛事（生成/编辑/部署/校验）
  music_tool.py            ← ★ 赛事音乐 / 菜单音乐编辑
  gfx_profile.py           ← ★ 画质档位 plist/feats 生成与部署
  gui_tool.py              ← .gui 布局解码 / 改控件 / 加按钮
  so_patch.py              ← .so 原地补丁（apk 内 STORED，不重签）
  dev.py / armxref.py      ← adb 封装 / ARM64 xref 扫描
docs/插件使用手册.md       ← ★ 任务导向使用手册（6 个任务 + 排查表）
docs/材质与部件清单.md     ← ★ 297 材质 / 1869 部件 / 79 锚点 / 12 片段全表
docs/动画片段与行为对照.md ← ★ 540 台车的片段与行为串逐车对照
docs/轮毂与轮胎缩放.md     ← ★ 轮子为什么都一样大：0.60 m 模板 + 径向拉伸系数
docs/RE-载入-拼装-动画-着色器.md ← 引擎侧逻辑逆向报告
docs/HANDOFF-20261027.md   ← 尾翼发暗根因与修复（已实机验证）
docs/HANDOFF-20261027-3-轮子装配修复.md ← ★ 整车导入"先导 points 再装轮子"的改造记录
docs/HANDOFF-20261027-3-赛事音乐画质工具.md ← ★ 游戏内改造三件套的工具用法与实机状态
reference/                 ← 参考实现 M3G2FBX 的源码摘录（可忽略）
preview_*.png              ← 导入 Blender 后的渲染验证图
```

## 快速开始

### 1. Blender 里导入模型

1. Blender 4.2+（实测 4.5 LTS / 5.0）→ `编辑 → 偏好设置 → 插件 → 安装…` → 选 `rr3_blender_addon.zip` → 勾选启用。
2. `文件 → 导入 → Real Racing 3 Vehicle Folder`（推荐，整台车一次装好），
   或 `Real Racing 3 Model (.m3g)` 只导一个模型；右侧 `N` 面板也有 **RR3** 标签页。
3. 同一目录有同名 `.points` 时会自动把锚点导成空物体（选项可关）。

**整车导入**（`Real Racing 3 Vehicle Folder`）会一次性搭出：车身网格、四个轮子枢轴（`WHEEL_FL/FR/BL/BR`，
已按 `.points` 定位）、方向盘枢轴（`STEERING_WHEEL`）、主动空力枢轴（`AERO_<序号>_<部件名>`，
带关键帧动画）、以及全部锚点空物体。参数 `lod`（A–H，另有 `shared`/`int_a`/`int_b`）、
`height_adjust`、`wheel_scale`、`rot_mode`、`brakes`、`separate_damage`、`separate_camera` 等
23 项说明见 `rr3_blender_addon/README.md`「导入」。

**驾驶员导入**（`Real Racing 3 Driver`）从 `<depot>/driver/` 取 15 部件的人偶，
按 `driver[_<车>].banim` 摆好坐姿，贴 `vehicles/common/driver.dxt.dds.z`，
最后挂到一个 `<车名>_DRIVER_ROOT` 空物体下便于整体搬动。
该用哪个动画不用猜：车的 `vehicles/data/<id>_<车>.bin.nct` 记录里直接写着
（540 条记录里 224 条有这个字段，引用 34 个 `.banim`），也可以用文件选择器手选 `.banim`。
朝向靠根空物体整体绕 Z 转 180°（动画朝 −Y、车头朝 +Y），部件保留游戏原始变换。

Reventon 实测：91 个网格、47 487 顶点、45 177 三角面，包围盒 **2.218 × 1.438 × 4.696 m**（与真车尺寸完全一致），UV 与顶点色齐全。

导入时会自动解码同目录的 `<车名>_<tag>.dxt.dds.z` 贴图集（`textures` 选项，默认开），
按材质名里的 `_mm_<tag>` 后缀绑定；实测一辆车会加载 8 张图集
（badges / cab / int / lights / misc / sw / wheel / wheel_blur）。

UV 与法向都在导入时做了换算（2026-10-21 修正）：

- **UV**：文件里是 4×4 的 tile 空间（u 0–4、v −3–1），着色器按 `u/4`、`(1−v)/4` 取样。
  以前直接取原值，所以贴图会以 4 倍密度平铺并且上下镜像；现在按同一条换算，贴图正常。
- **法向**：以 4096 为单位的定点数（`|n| ≈ 4096`），导入时归一化。
  以前直接当单位向量用，会出现“一边亮一边暗”。

反向导出（Blender → 游戏）：`文件 → 导出 → Real Racing 3 Model (.m3g)`，`Template .m3g` 选一辆原厂车的
`_a.m3g`（部件名与模板一致才能继承材质表和那些不透明字节块），`Position scale` 留 0 让它自动用模板的原厂系数。
**别填 1.0**：几何虽然一样，但实机会扫描线卡顿并丢高光（见下面格式要点）。整节说明与实测系数表在
`rr3_blender_addon/README.md`「导出 .m3g」。回归测试：`blender -b --factory-startup -P analysis\test_fixedpos_export.py`。
导出完成后信息栏会报出实际写入的 `positionScale`（万一算成 1.0 会附带警告）。

### 1b. 造一台全新的车（不建模也能先跑通）

`N` 面板 → `RR3` → **Build a new car**，填两个路径 + donor 名 + 新车名即可。
一次写出 10 个产物：spec、cardesc、suspension、damage、appearances、涂装表、车目录（55 个文件）、
资源清单、注册表、数据列表 —— 全部落在 `<输出目录>/.depot/...` 的 `files/` 镜像里，可直接整目录推设备。

选 donor 的三条规则、10 个产物的作用、以及三个必踩的坑（贴图别名 / 空力 flag 原地替换 / 尾翼材质 745→30），
见 `docs/插件使用手册.md` 任务 D。命令行等价：

```
python -c "import sys; sys.path.insert(0,'.'); from rr3lib import car; car.build_car(DEPOT, PKG, OUT, new_id=611, new_name='2026_test_clone', donor_name='2012_lexus_lfa')"
```

端到端测试（13 步，不用 Blender）：`python tools\test_car.py`。

### 1c. 改某个零件的涂装材质

`N` 面板 → **Set part material**：填车名 + 部件名 + 材质名；勾 `Copy body paint` 就让它跟随车漆
（这是最省事、也是修尾翼发暗的那一招）。想知道某个部件当前到底用了哪张表里的哪个材质，
用 **Audit paint**，它会逐网格报出 `paint / car / default / none / no-slot` 五个来源层级。

可用的 297 个材质名、1869 个部件名、槽位号，全在 `docs/材质与部件清单.md`；
机制说明（为什么尾翼会退回 `car_flat` 而发暗）见 `docs/插件使用手册.md` 任务 E。

### 2. 导出动画/锚点的原始可读信息

把 `driver.banim`、`2007_lamborghini_reventon_wing.banim`、`2007_lamborghini_reventon.points`
（或任意数量的这三类文件、甚至整个文件夹）**拖到 `rr3dump.bat` 上**，
结果出现在 `dump\` 里，如 `driver.banim.txt`。

命令行等价写法：

```
python rr3dump.py -o D:\out --format both --max-keys 0 "path\to\file.banim"
```

`.banim` 默认把**每帧**都解出来（`driver.banim` 有 16290 个关键帧 × 15 个部件，文本约 1 MB）。
只想看前 N 帧就加 `--frames 120`；加 `--no-anim` 则只导原始曲线、不做逐帧解码。
`.points` / `.m3g` 不受这两个开关影响。

**单位约定（2026-10 修正，实机校准）**：旋转一律用**角度**表示，换算是
`角度 = 原始值 × 180 / 32768` —— 即 **32768 个原始单位 = 180°**（不是 2π 弧度）。
校准依据：Reventon 尾翼刀片 `LOD_A_WING_REAR` 的 ch3 原始值 `-2730` → **14.996°**，
而在 Blender 里手动旋转到 **14.888°** 才与游戏截图吻合（差 0.1°）；若按"÷32768 = 弧度"
解读只有 4.77°，肉眼明显不符。位置在所有 `.banim` 里都是 **`raw / 65536` 米**
（2026-10-28 更正：早期以为驾驶员用 1/32768，实测按 1/65536 才是 1.09 m 高、手正好落在
方向盘轮缘上）。`.points` 的坐标先印原始工程单位，再印 `raw / 32` 的米值
（游戏内 32 倍缩放已验证这条换算）。

每次拖放结束后窗口底部会列出刚刚写出的文件名与大小，方便确认导出了什么。

#### 组合报告 `<车名>_report.txt`

拖一个**车辆文件夹**（或 `driver` 文件夹）时，除了每个文件各自的 txt，还会额外写出
一份组合报告，章节顺序固定为：

1. **首末两帧** —— 每个部件三行：起始 `xyz` / `rot`、末帧 `xyz` / `rot`、变化 `Δxyz` / `Δrot`；
2. **锚点位置** —— `.points` 全部记录，只给 `名称 + x / y / z`（原始值 / 32，单位米）；
3. **banim 全部帧** —— 每个部件逐帧一行：`t / x / y / z / rx° / ry° / rz°`。

位置是模型坐标（x 右、y 上、z 车头），单位米；角度单位度、欧拉 XYZ。
**要套到网格上的是"增量"**（末帧 − 首帧）：网格本身已经按静止姿态建模，
把绝对角直接贴上去会重复旋转一次（左右进气翻板会明显穿模）。

同时还会写两份便于筛查的文件：

- `<车名>_frames.csv` —— 每帧一行（`file, part, t_ms, x, y, z, rx, ry, rz`），
  带 BOM，Excel 直接双击打开就能按部件筛选/排序，适合轨道很多的文件（如 `driver.banim` 的 15 条轨）；
- `<车名>_assembly.txt` —— 轮子安装点、轮胎半径、空力枢轴与行程。

## 已解析格式（要点）

- **.m3g**：JSR-184 容器，12 字节魔数 + 分段（`u8 压缩标志 / i32 段长 / i32 未压缩长 / 对象 / i32 校验和`），
  对象引用是**全局对象表 1 基下标**；网格 → 顶点缓冲 → 顶点数组/索引缓冲链全部还原，
  位置 = `分量 × positionScale + positionBias`，UV 缩放原始值 1/512。
  原厂 `positionScale` **从来不是 1.0**：它约等于「整车峰值坐标 / 1024」，同一文件所有网格共用一个值
  （LFA 0.0021973606199026108、Reventon 0.0022958945482969284、P1 0.0023481915704905987、
  F1 0.0019114369060844183；峰值都是 ±1023）。导入只看乘积，所以两种写法几何等价，
  但引擎按这个系数选顶点处理路径：写 1.0 实机会**扫描线卡顿 + 丢高光**。
  导出器已按原厂规则写（`raw = 米 / scale`，模板优先，否则 `峰值/1024`），见
  `rr3_blender_addon/README.md` 的「导出 .m3g」。
  材质索引是**0 基**（不是规范里说的 1 基）——按 0 基读，91/91 个网格的材质名后缀才与自身网格名
  `_mm_<tag>` 一致；按 1 基读会整体错位一格（这也是旧版本贴图看起来对不上的原因）。
- **.dxt.dds.z**：`u32 原始长度 + zlib(DDS)`，解压后是标准 DDS（DXT1/DXT5）。一辆车的 10 张图集是
  `badges cab int lights mask misc sha sw wheel wheel_blur`，其中 `mask`（红/蓝涂装区域遮罩）
  与 `sha`（白色阴影/AO 图）不对应任何材质 tag，是着色器固定取用的辅助图。
- **.points**：`u16 版本(=2) / u16 记录数`，记录 = `u16 类型 / u16 长度 / 名字\0 / 额外数据`，
  尾部 `u16 覆盖项数` + `名字\0值\0`。类型 0 点、1 样条、2 铰链（含 3×3 矩阵）、3 未知。
  全库 958 个文件零解析错误。
- **.banim**：魔数 `0x7F7F00xx`，`[变体&0x10 → u32 版本] / fieldA / 轨道数 / 时长毫秒 / 数据偏移`，
  每轨道 116 字节记录（轨道号 + 14 组 `关键帧数/起始帧号`，帧号**全局**），
  关键帧 8 字节 `(f32 时间毫秒, f32 值)`，之后是每轨道 4 字节尾部、可选属性表和事件名表。
  全库 496 个文件全部解析到底。
- **.dashplanes**：`u32 版本标志(4 或 5)` + 若干「HUD 文本面片」，每个面片 =
  `名字\0 + 列主序 4×4 变换 + 字号/旗标等尾部字段 + 字体名\0 + RGB`（版本 4 的尾部更短，
  两种版本都不做对齐填充，所以只能按名字定位）。位置 ÷32 得米，模型空间（Y 上、Z 前），
  与 `.points` 同约定。全库 355 个文件 / 930 个面片零告警，名字只有 `dash_lcd_*` 与
  `wheel_lcd_*`（后者是方向盘轮毂上的小屏）。
  **这个文件只有 HUD 文字排版信息，不含任何部件枢轴或动画轨道** —— 方向盘的安装位置在
  `_int.points` 的 `POINT_STEERING_WHEEL` 里，详见下文「方向盘」小节。

详细字段与限制见 `rr3_blender_addon/README.md`。

### 3. 导入 .banim 动画（每帧位置 / 变换）

`文件 → 导入 → Real Racing 3 Animation (.banim)`，选 `.banim` 即可：
插件会在同目录自动找轨道数匹配的 `.m3g`（`driver.banim` → `driver_lod_a.m3g`），
把 15 个部件按索引一一绑定，并逐帧写入 `location` / `rotation_euler` 关键帧（线性插值）。

- `Placement = Bone (aligned)`：部件挂在解码出的关节上，并沿骨轴对齐（观感更接近人体）。
- `Placement = Joint only`：只按解码出的关节位置摆放，不做任何对齐，**与数据 1:1 对应**。
- 同时也会把轨道号/角色写进物体的自定义属性 `rr3_track` / `rr3_role`，方便脚本继续处理。

如果只想拿运动、自己搭装配，用 **`Real Racing 3 Animation as Empties (.banim)`**：
不导网格，每轨一个空物体，关键帧直接打在空物体上（可 parent 自己的网格或用约束跟随）。
这个入口对**所有** `.banim` 都用 `raw/65536` 的位置刻度（`*_wing.banim` 与
`driver/*.banim` 一致；2026-10-28 更正：早期以为驾驶员是 1/32768，会让整具人偶大一倍）。

同样的数据在文本 dump 里更直接（`dump\driver.banim.txt` 的 `PART ANIMATION (decoded)` 段）：

```
track -> part binding
trk  part / mesh                        role
  0  00_helmet_source_LOD_A             helmet (head)
  1  01_body_source_LOD_A               chest (torso)
  ...
per-frame values (30 fps)
   t(ms)  trk         x        y        z       rx°      ry°      rz°
     0.0    0   -0.0335  -1.1318   0.5273      0.23    -1.05     7.75
```

### 4. 导入整台车（轮子 + 主动空力部件）

`文件 → 导入 → Real Racing 3 Vehicle (wheels + aero)`，**选车里任意一个文件**（例如 `<车名>_a.m3g` 或 `<车名>.points`）即可。
插件会自动找齐同目录的 `_shared.m3g`（轮子/轮胎网格）、`.points`（轮心坐标）、`_wing.banim`（空力部件动画），然后：

- 车身 LOD 照常导入；
- **装配顺序是先 `.points` 后轮子**：`WHEEL_FL/FR/BL/BR` 枢轴直接取对应
  `ANCHOR_POINT_WHEEL_*` 的位置（实测偏差 0.000 mm），轮辋 + 轮胎网格挂在枢轴下、
  **不做任何居中**（轮子局部坐标系里 `x = 0` 就是外侧面，正好落在 `POINT_WHEEL_*` 上）。
  右轮是**绕竖轴转半圈**（`x=-x, z=-z`），不是镜像——这样轮辋上的字还正着读。
  模型原点在地面（轮心高 ≈ 一个轮胎半径），所以没有任何 Y 方向偏移；
- **轮子按车的真实轮胎尺寸径向拉伸**（`wheel_size` 参数，默认 `engine` = 与游戏一致）。共享网格是
  一个 0.60 m 的通用模板（463 台车变异系数 0.46%），引擎加载时按 `suspensionbehaviour` 的轮胎直径
  只缩放 y/z、宽度不动；中位系数前轮 ×1.153、后轮 ×1.196。见 `docs/轮毂与轮胎缩放.md`；
- **前后轮分开处理**：88 台有独立 `TYRE_REAR`、149 台有独立 `WHEEL_REAR`；只有更宽后轮辋
  而没有后轮胎的 62 台按轮辋宽度比拉宽后轮胎（`rear_tyre_width`，默认开）；
- **刹车盘和卡钳也一起装**（`brakes`，默认开）：用**和轮胎同一个径向系数**，枢轴同样落在
  `POINT_WHEEL_*` 上；但**卡钳不跟轮子转**——四个卡钳各自建模在自己角落、盘的后方，
  右轮那半圈旋转只作用在轮辋、轮胎和刹车盘上。只有 LOD A / B 有这两个网格；
- **LOD F 是例外**：它的轮网格是四个轮子已经按真实尺寸装好的整车网格（全库 463 台都跨
  车身左右），所以这一级**放世界原点、不缩放、不平移**，否则装配会做两遍；
- **LOD G / H 的轮子**：`_shared.m3g` 的轮子网格只到 F 级，游戏在 G 级**复用 F 那套预装配网格**、
  H 级**不要轮子**（`WHEEL_LOD_FALLBACK = {"G": "F"}`、`NO_WHEEL_LODS = ("H",)`）；
- **`shared` / `int_a` / `int_b` 是完整模型**（车头视角壳 / 两份第一人称内饰），`lod` 下拉里
  选它们会**整份导入**：不装轮子、不装空力、不建相机/损伤子集合；
- **相机壳和发光片**（`separate_camera`，默认开）：`BONNETCAM_*` 和 `LIT_*_GLOW` 进
  `<车名>_LOD<X>_camera`，否则它们和引擎盖完全重合、会 z-fighting；
- **损伤件**（`separate_damage`，默认开）：`*_DAMAGE` / `*_BROKEN_*` 进 `<车名>_LOD<X>_damaged`；
- **朝向 / 镜像**（`facing` / `mirror_x`）由**一个根空物体**（`<车名>_ROOT`）承担，
  车身、轮子枢轴、尾翼枢轴、锚点全部挂在它下面整体转，不会出现"车身转了轮子没转"；
- 每个 `*_WING*` 部件挂到 `AERO_<i>_<部件名>` 空物体上，并把 `.banim` 里**位置 + 旋转**都写成关键帧；
  **部件和轨道的配对靠网格自带的 keyframe 表**（`.m3g` 网格对象尾部：`u32 count` + 每键 14 字节），
  不是靠名字顺序——全库 106,399 个网格里 93 个带这张表，带表的就是会动的部件。这一条修好了
  P1 尾翼和支架动画对调的问题（全库 53 台有 `_wing.banim` 的车，改前 48 台干净、改后 52 台）；
  `delta_axes` 可以逐轴把首帧角度归零，`pos_factor` 对锚点/轮子/尾翼/动画一起生效；
- **材质可以换成游戏自己的**（`materials = Game materials`）：走
  `网格名 → 涂装表部件槽 → 材质槽 → materials.bin 着色器` 这条链。**每个网格仍然只有一个材质槽**
  （与游戏一致），槽内材质按涂装分**预设**——每个预设一套 `bsdf_<n>` + 自己的贴图 + 两条色带，
  **只有当前预设连到 Material Output**，选中后用 Car ▸ **Switch paint scheme** 填预设号换涂装，
  槽数不变。Roughness/Metallic/Coat 由游戏的双镜面叶瓣（`SpecularPower_Base/Top`）和 fresnel
  色带换算，两条色带以未连线节点保留在预设里。贴图会 `pack()` 进 .blend，重启不变粉色。
  见 `docs/游戏材质与涂装.md`；
- **私有贴图容器能单独导出**：*Textures ▸ Export textures* 把 `.dxt.dds.z` /
  `.dxt.dds.z.bin`（多帧阴影图）/ `.dxt.dds.bin` / `.rgb.pvr.z` 解成 PNG 或 DDS，
  DXT1/3/5 由 `rr3lib/ddsdecode.py` 自己解（与 Blender 自带解码逐像素一致）；
- **窗户/轮胎/刹车盘的贴图来自 `vehicles/common`**：这些共享图集由
  `default.liveries.bin.nct` 指定，车自己的涂装表里往往没有那一行（全库 `ext_tyre` 缺 153 台、
  `ext_rotor` 155 台、`ext_windows` 90 台、`ext_chassis` 540 台全部）。取贴图按
  **涂装覆盖 → 车表 → default 表**三级回退，所以这些部件现在都有图；
- **损伤件单独成组**（`separate_damage`，默认开）：车身文件里每个板件都有完好版和
  `*_DAMAGE` 版，玻璃与灯罩另有 `*_BROKEN_*`，两者叠在同一位置会看着像穿模。损伤件放进
  `<车名>_LOD<X>_damaged` 子集合（对象带 `rr3_damaged` 标记），完好件留在主集合；
- **一个 Blender 材质名只对应一张图集**：`car_flat` / `car_matte` / `car_glass` 一台车会用在
  好几个网格上、各配不同图集（P1 有 3 处、Veyron GSV 有 4 处），撞名时自动加 tag 后缀
  （`<车>_car_flat_cab`），否则先建的赢、其余全穿错贴图；
- `.points` 里的锚点导成 `ANCHOR_*` 空物体。

实测（Reventon / Chiron）：轮子底面正好落在车身最低点（−0.298 m），轮距/轴距与真车一致；
Chiron 的尾翼在 100 帧里**升高 0.143 m、后移 0.064 m、下压 16.41°**，与真车空气刹车一致。

拖车目录到 `rr3dump.bat` 时，除逐文件报告外还会多出一份 `<车名>_assembly.txt`（轮心、轮半径、空力部件行程、运动规则）。

## 动画通道是怎么解出来的（`.banim` → 每帧变换）

每条轨道 12 条曲线 = **6 个通道 × 2 种采样率**（33 ms/30 fps 与 ~16.5 ms/60 fps 存的是同一条信号，
互相对插误差中位数 < 1 个原始单位）。6 个通道按 `ch0..ch2 / ch3..ch5` 分组：

| 通道 | 含义 | 单位 | 依据 |
|---|---|---|---|
| ch0 ch1 ch2 | 该部件**关节点的位置** (x 右 / y 前 / z 上) | 米 = 原始值 ÷ **65536** | 头盔在躯干正上方 0.69 m、双手落在方向盘原点、左右部件仅 x 镜像；按 ÷65536 时整具人偶高 1.09 m |
| ch3 ch4 ch5 | 该部件**旋转**（Euler XYZ） | 角度 = 原始值 × 180/32768 | 幅度多为 5°–60°；`0`（原始 0）为哨兵值（未使用通道） |

15 条轨道与 15 个部件的绑定是**按索引**的，验证方式：髋→膝 0.681 m、膝→踝 0.601 m、胸→头 0.693 m、
肩→肘 0.461 m、肘→手 0.460 m，全部左右严格镜像，且与网格自身长度（如大腿网格 0.666 m）吻合。
`driver.banim` 中腿（t09–t14）位置与旋转全为常数——是坐姿模板，只有上半身动。

## 轮子与主动空力部件：装配与运动（`.points` + `_wing.banim`）

**结论：静止件直接烘在车体坐标里，运动件则存成“绕自己枢轴”的局部坐标——枢轴位置只在 `.points` / `_wing.banim` 里。**
车身网格的包围盒覆盖整台车（±1.11 × ±2.35 m），而每个 `*WHEEL*` / `*TYRE*` / `*WING*` 网格都围绕原点建模
（例如 `LOD_A_WHEEL_mm_wheel` 中心 (0.113, 0, 0)、半径 0.2265 m；`LOD_A_TYRE_mm_tyre` 半径 0.2985 m）。

| 数据 | 含义 | 单位/空间 | 依据 |
|---|---|---|---|
| `POINT_WHEEL_FL/FR/BL/BR` | 4 个轮心 | **1/32 米**，(x 右 / y 前 / z 上) | Reventon 轴距 (40.582+44.841)/32 = **2.669 m**（真车 2.66）；轮心高 9.919/32 = 0.310 m ≈ 轮胎半径 0.2985 |
| `_wing.banim` ch0..2 | 空力部件**枢轴**位置 | **1/65536 米**，同一空间 | 96/96 条轨道按 ÷65536 都落在车体包围盒内；÷32768 会全部飞到车尾外几米 |
| `_wing.banim` ch3..5 | 枢轴**旋转**（Euler XYZ） | 角度 = 原始值 × 180/32768 | Reventon 刀片 14.996°（实机对照 14.888°）；Chiron 51.6°、MP4-12C 59°、AMG GT Black 105° 均为空气刹车量级 |
| `<车名>_animations.xml` | 片段名 → 帧区间 | 30 fps 时间轴 | `wing_up 0→45`、`wing_down 45→0`；Chiron 还有 `wing_race_initial 0→75`、`pivot_up 80→90` |

坐标换算：动画空间 (x 右, y 前, z 上) → 模型空间 (x, z, −y)。**竖直基准只对 `.points` 生效**：
`.points` 与轮子的高度是从地面算的，要减去 4 个轮心的平均高度（≈0.309 m）；
而 `_wing.banim` 枢轴的高度**已经是模型坐标**（例如 Reventon 刀片 0.854 m、翻板 1.018 m），
再减就会整体下沉 0.31 m——这一点在实机对照时确认过。
在 Blender 里车头朝 **+Y**，空力部件在 **−Y**。

运动规则（游戏里是程序驱动的，没有任何文件存轮子的转动曲线）：

- **转向**：前轮（`POINT_WHEEL_FL/FR`）绕底盘竖轴转动；
- **滚动**：绕轮子自身 **局部 X 轴**，角速度 = 车速 ÷ 轮胎半径；
- **轮辐模糊**：`*_WHEEL_BLUR*` 是第二个轮辋网格（半径与轮辋相同），高速时替换显示；
- **主动空力**：枢轴自身会**平移 + 旋转**，各通道的关键帧时间互不相同（Chiron 的旋转通道从 1485 ms 才开始），
  插件按各通道并集的时间点逐点插值写入关键帧。

## 方向盘（数据里没有，靠锚点＋几何反推）

游戏里方向盘是**程序摆上去**的：958 个 `.points` 里没有控制它的轨道，`driver.banim` 与
`_wing.banim` 也没有对应通道，`_a.m3g` 里 `LOD_A_STEERING_WHEEL_mm_cab` 只是绕自身原点建模的局部网格
（0.345 × 0.333 × 0.135 m ⇒ 盘径 0.345 m，**自转轴 = 网格自身 Z**，也就是最薄的那一维）。

能用的只有三条线索：

| 线索 | 数值 | 来源 |
|---|---|---|
| 盘心位置 | `POINT_STEERING_WHEEL = (-0.352, 0.508, 0.672) m` | `_int.points`（与 `POINT_DRIVER` 同 x/y，低 1.4 cm） |
| 指针轴心 | `HINGE_NEEDLE_RPM (-0.452, 0.837, 0.687)`、`HINGE_NEEDLE_SPEED (-0.255, 0.837, 0.688)` + `POINT_NEEDLE_*` | `_int.points` |
| 转角曲线 | 0 → **82.3°**（1980 ms），旋转轴 anim (0.001, 0.960, −0.281) ≈ 模型 (0, −0.28, −0.96) | 由 `driver.banim` 的双手位置反推（`analysis/steer_fit.py`） |

双手连线的长度在整段动画里是**刚性**的 0.649–0.710 m，只有把驾驶员位置也按 ÷65536（而不是 ÷32768）缩放后，
手到盘心的距离 0.169 m 才与网格半径 0.172 m 吻合（误差 1 cm）——这也印证了“动画坐标看起来放大一倍”。
反推出的转角轴不是纯 Z，说明**方向盘是绕倾斜的转向柱转的**，而不是绕车身坐标轴。

## 已知限制

1. ~~**贴图只能靠命名约定**~~ → **已解出（2026-10-28）**：材质名不是从 `.m3g` 来的
   （`T_MATERIAL_LIST` 里只有 15 条笼统名），而是走 `网格名 → liveryStringTable 部件槽
   → 涂装表材质槽 → materials.bin`。所以 `ext`（车漆）现在按涂装取
   `<车>_ext_<颜色>.dxt.dds.z`，其余 tag 取同名图集。仍有 5 个 tag 全库 0 覆盖
   （`chassis`/`dash`/`dashplanes`/`taillight_glow`/`sidelight_glow`），那些网格只有材质参数。
   细节见 `docs/游戏材质与涂装.md`。
2. **驾驶员模型是骨骼局部坐标**，骨架不在任何文件里（`driver\` 只有 banim 和 m3g）；导入模型后 15 个部件重叠在原点，
   请用插件的 “Spread bone-local parts” 排开查看，或改用 `.banim` 导入——那样部件会被放到每帧解码出的关节位置上。
3. `.banim` 轨道与节点的对应是**按位置**的（轨道 i ↔ 第 i 个节点）；用网格名做哈希匹配尾部 15 个 0x… 字已全部试过，不成立。
4. 动画里的部件朝向是**重建**的：位置和旋转来自数据，但网格原点在部件中心而非关节，因此“怎么把网格挂到骨轴上”
   只能推断（插件提供 Bone / Joint 两种摆法），做不到与原作像素级一致。
5. `0x10` 变体（如 `2007_lamborghini_reventon_wing.banim`）多一个 u32 版本字段，已能逐字节校验通过并解出
   每帧位置与枢轴（左/右翻板 ±0.548 m、后 1.160 m、高 1.018 m；刀片高 0.854 m），与几何完全吻合；但文件里没有
   部件名，工具只给轨道号。少数过场动画尾部仍有未解码字节，原样十六进制输出。
6. `.points` 类型 3 记录（64 字节）结构未知，原样十六进制输出。
7. `_mm_<tag>` → 图集 的那张表**不在数据里**：引擎 `.so` 的 `.data.rel.ro` 里只有 tag 名数组
   （外观 21 项、内饰 15 项，见 `re\tag_table.txt`），没有任何并行的图集名数组，
   所以映射是代码分支。已定位到描述符区 `0x1F703F0`–`0x1F70530`，但尚未把具体分支读完。
8. **导出 `.m3g` 的顶点不焊接**：按 loop 全展开，一辆 LFA 是 69 435 顶点（原厂 17 942，共享顶点），
   三角数一致但文件大一倍多（2.11 MB vs 0.73 MB）。若实机仍有卡顿，下一步是加焊接。
9. ~~自制尾翼发暗仍未定位~~ → **已定位并修复（2026-10-27 实机验证）**：根因不在模型，
   而在 `vehicles/data/liveries/<车>.liveries.bin.nct` 的「网格→材质」表里**没有 `LOD_A_WING_REAR_mm_ext` 这一行**，
   引擎查不到就退回 `car_flat`（全库唯一 `mu_MaterialSpecularColour_Base = 0,0,0`、`Power = 1`、
   `fresnel_flat` 的材质）⇒ 纯黑、不吃光。修法是给每个涂装补一条「尾翼 → 与车身同材质」的覆盖
   （`745 -> 与 30 相同`），插件里就是 **Set part material → 勾 `Copy body paint`**。
   取证过程见 `docs/HANDOFF-20261027.md`，操作见 `docs/插件使用手册.md` 任务 E。
10. **`.spec` 里没有固定字段偏移**：字符串在文件里补零到 4 字节边界，token 流里就多出数量不等的零 token，
   于是外观 id 的索引在 84–112 之间浮动（硬编码 86 只对 30/188 正确）。现在按字节形状定位
   （`spec.locate_appearance`），188/188 正确、540/540 no-op 重写字节不变。
   显示名同理：33 台车没有 `CAR_NAME_*`，115 台有两个；5 台（Koenigsegg Regera / Alfa 4C / Shelby GT500 /
   Jesko Absolut / Battista Furiosa）的厂商串被拆成数字 token，改名后读不回来（文件里的值是对的）。
11. **63 个 spec 没有 appearance 记录**（F1 涂装车、`1968_porsche_909_bergspyder` 等，它们复用别的车体）。
   造车时**必须选一个有 appearance 记录的 donor**，否则 `build_spec` 会失败。
12. **`appearances.link.nct`（12,685 B）格式未完全解出**：已知 `u32 version=1 + u32 count=82`，
   后接长度前缀的车目录名，但每条记录尾部的 u32 数量不定。目前不使用这个文件。
13. **`gametext.txt` 用另一套密钥**：`nct.KEY_GAMETEXT`（`b1 75 a5 23 f3 c2 b6 15`，丢 211 字节），
   用默认 `nct.read()` 读会得到乱码。
14. 原厂涂装洋红 / 无高光属于 DXT 数据包缺 `.ptc.pvr.z` 的环境问题，与工具无关。
15. **轮子模板的系数在极少数车上会反直觉**：`wheel_size="ground"` 用加载半径，一般比 `engine`
    小 5%–8%，但轮心高大于自由半径的车（Caterham 620R +4.7%）会更大。这是数据本身如此
    （MonkeyTool 注释里提到的 Zenvo 情形），不是 bug。见 `docs/轮毂与轮胎缩放.md`。
16. **后胎宽度在没有 `TYRE_REAR` 的车上是推断的**：62 台车只有更宽的后轮辋、没有独立后轮胎，
    插件按 `WHEEL_REAR / WHEEL` 的宽度比拉宽前轮胎。实测 87 台两种网格都有的车，这个代理的
    中位偏差只有 0.6%，但不是引擎的原值。想让某台车回到原样就关掉 `rear_tyre_width`。
17. **低 LOD 没有刹车**：全库只有 LOD A / B 带刹车盘和卡钳（398–401 台），LOD C 及以下是 0。
    这是游戏自己的取舍，不是导入漏了。想确认就对比一下 LOD A 和 LOD D 的对象数。
18. **LOD F 的轮子不能动**：它的轮网格是四个轮子已经按真实尺寸摆好的整车网格（463 台全部
    跨车身左右），插件会跳过 `wheel_size` 并把网格放在世界原点。手动缩放它就会变形。
19. **游戏材质是"换算"出来的，不是引擎原式**：`materials.bin` 里给的是 Blinn-Phong 的
    `SpecularPower` 和两条 fresnel/specular 色带，插件把它们换算成 Principled BSDF 的
    Roughness / Metallic / Coat（`roughness = sqrt(2/(n+2))`，`metallic` 由 fresnel 均值线性映射），
    两条色带本身以未连线节点保留。所以观感接近但不等于游戏内截帧。见 `docs/游戏材质与涂装.md`。
20. **有些 tag 在涂装表里没有槽**：`chassis` / `dash` / `dashplanes` / `taillight_glow` /
    `sidelight_glow` 全库 0 覆盖，这些网格拿不到贴图，只有材质参数。`tyre`/`rotor` 覆盖率
    387/385 台，个别老车也没有。
21. **723 条涂装贴图引用指向未随包发布的文件**：540 台车 9971 条引用，双路回退后 9248 命中。
    缺失集中在 `2017_renault_formula_e_*`、`2016_chevrolet_ss_nascar_*` 等车。
22. **`.ptc.pvr.z` / `.atc.dds.z` / `.etc.dds.z` 不解码**：它们是 PVRTC / ATC / ETC 块压缩，
    全库各 9 个、全在 `gui_assets\2048x1536\events\super_groups\`，车辆从不用。
    `rr3lib/texport.selftest()` 会明确跳过它们而不是报错（"4/4 container kinds decoded (2 skipped)"）。
23. **贴图默认打包进 .blend**：解码产物落在临时目录，不 `pack()` 的话重启 Blender 后全部变粉色。
    代价是 .blend 体积变大（一台 6 涂装的车约 15–20 MB 贴图）。想省空间就在导入后
    手动 *File ▸ External Data ▸ Unpack*，并把临时目录设成持久路径。
24. **游戏材质要求车还在 depot 里**：材质表（`materials/materials.bin`、livery 表）在 depot
    根下，插件从车目录向上最多找 8 层。把车目录单独拷出来再用 `materials = Game materials`
    就找不到表了 —— 这时导入会**明确报一条 warning**（以前是静默退回占位材质，看起来就像
    "材质没导入"）。把 **Depot** 参数指到 `.depot` 文件夹即可。
25. **`Load car textures` 会清掉旧解码**：解码产物按 `v<n>` 分目录存（当前 `v2`），加载前会把
    更早版本的目录/散落 PNG 和引用它们的 Blender 图像一并删掉。所以它不只是"加载"，
    也会**移除**上一版解码出来的贴图 —— 这是故意的，否则同一张图会同时存在正反两份。
26. **窗户/轮胎/刹车盘的贴图不在车目录里**：这些是 `vehicles/common` 下的共享图集，由
    `default.liveries.bin.nct` 指定。全库 540 台车里 `ext_tyre` 缺自己那行的是 153 台、
    `ext_rotor` 155 台、`ext_windows` 90 台、`ext_chassis` 540 台（全部）。插件现在按
    「涂装覆盖 → 车表 → default 表」三级取贴图，所以这些部件也能拿到图。
27. **损伤件默认单独成组**：车身文件里每个板件都有完好版和 `*_DAMAGE` 版，玻璃和灯罩另有
    `*_BROKEN_*`。默认放进 `<车名>_LOD<X>_damaged` 子集合（`separate_damage` 可关），
    否则两个版本叠在同一位置，看上去像模型穿模。
28. **一个 Blender 材质名只对应一张图集**：同一台车的 `car_flat` / `car_matte` / `car_glass`
    会用在多个网格上，各配不同图集（P1 有 3 处、Veyron GSV 有 4 处）。材质名冲突时自动
    加 tag 后缀（`<车>_car_flat_cab`），否则先建的赢、其余全穿错图。
29. **`_shared.m3g` 的轮子只到 LOD F**：G 级复用 F 级那套预装配网格，H 级没有轮子
    （`WHEEL_LOD_FALLBACK = {"G": "F"}`、`NO_WHEEL_LODS = ("H",)`）。两者都不是缺件。
30. **`shared` / `int_a` / `int_b` 不是 LOD 等级**，是完整模型（车头视角壳 / 两份第一人称内饰）。
    `lod` 选它们会整份导入：不装轮子、不装空力、不建相机/损伤子集合。
31. **没有"一次导入全部 LOD"了**：那个入口已删除（每级都会重算材质与贴图，慢且容易留下
    同名材质）。需要多级就分几次导入。
32. **驾驶员不在车目录里**：在 `<depot>/driver/`；材质名 `driver` 不在 `materials.bin` 里，
    贴图固定取 `vehicles/common/driver.dxt.dds.z`；位置单位是 **1/65536 米**（不是 1/32768）。
33. **相机壳要单独放**：`_shared.m3g` 里的 `BONNETCAM_*` 是车头视角用的第二个车身，和引擎盖
    完全重合；`LIT_*_GLOW` 是面向相机的发光片。默认进 `<车名>_LOD<X>_camera`（`separate_camera` 可关）。
34. **驾驶员根空物体不再转 180°**：`.banim` 里的人偶本来就朝 +Y（车头方向），早期版本给
    `<车名>_DRIVER_ROOT` 绕 Z 转 180° 想"对齐车头"，结果把人偶转反了。那个开关已删除，
    根空物体保留（用来整体搬动驾驶员）。驾驶员导入的 `FPS` 默认改成 **90**，因为源
    `.banim` 的键间隔是 11/10/12 ms（约 91 键/秒），按 30 采样会丢掉三分之二。
35. **专属驾驶员网格跟着动画走**：12 个车型有 `driver_lod_c_<x>.m3g` / `driver_lod_d_<x>.m3g`，
    导入时**先定 `.banim`、再按它的名字找网格**，所以引用 `driver_919_lmp1.banim` 的
    16 台 LMP1 都会拿到 `driver_lod_c_919_lmp1.m3g`，而不是通用模型。
36. **同名材质不再互相删**：每个 LOD 各建一次 `GameMaterials`，旧版的名字表是实例级的，
    导入 LOD B 时不知道 LOD A 已经建过 `<车>_Vehicle Exterior_car_chassis`，名字撞上、
    预设不匹配就 `remove()` 掉，而 LOD A 的网格还挂着它。现在名字表是全会话共享的，
    且只在 `mat.users == 0` 时才删（有人在用就改名新建）。
37. **有通用模型入口了**：`Import ▸ Real Racing 3 Generic Model`（不带锚点/贴图/模板，
    可关 `Convert axes` 看文件原始坐标，`Report sizes` 打印每个网格的尺寸与半径）；
    `Export ▸ Real Racing 3 Generic Model`（`AUTO` / `METRES` / `FIXED` 三档 `positionScale`）。
    驾驶员、赛道模型是 **1.0**，车零件是 **0.0021973**，别混用。
38. **`Load textures (pick files)` 可以只选文件**：整台车扫描找不到的图（专属轮胎贴图、
    没写进涂装表的图集）用这个入口直接选一个或多个 `.z/.dds/.pvr/.etc/.atc/.ptc` 加载。

---

## 5. 动画片段导出（`.banim` + `<car>_animations.xml`）

`.banim` 里只有一整条时间轴；哪些帧属于哪个动作，写在同目录的 `<car>_animations.xml` 里：

```xml
<anims>
  <anim name="wing_up"><frames start="0"  end="45" /></anim>
  <anim name="wing_down"><frames start="45" end="0"  /></anim>
</anims>
```

- 帧号 = banim 的帧，**1 帧 = 33.0 ms**（30.303 fps）：Reventón 的 `wing_up 0→45` 正好是 1485 ms，P1 的 `0→60` 是 1980 ms，都精确对得上。
- `end < start` 表示**倒放**（`wing_down` 45→0）。

### 用法

`File > Import > Real Racing 3 Animation Clips (.banim + XML)`，选 `_wing.banim` 即可（XML 自动找同目录的）。

导入结果：

- 每条轨道一个空物体（和“Animation as Empties”一样）；
- **每个片段一份 Action**（`<车>_<片段>_<轨道>`）与**每个片段一条同名 NLA 轨道**；
- 场景帧率设为 1000/33，帧号与 XML 完全一致（`wing_up` 落在第 1–46 帧）。

三个“Difference X/Y/Z”勾选框控制旋转是否相对片段起点做差（不同车的作者姿态基准不同，见上一节）。

### 导出 glTF / FBX（每段一个动画）

Blender 里 `File > Export > glTF 2.0`，把 **Animation Mode 设为 `NLA Tracks`**，就会得到“每个片段一条动画”：

```bash
blender -b --factory-startup -P analysis\test_clips_gltf.py -- \
    "<car>_wing.banim" "re\clips.glb"
```

实测（Reventón 尾翼、Blender 4.5）：5 个片段 → 15 个 Action / 5 条 NLA 轨道；第 1 帧刀片 0°、第 46 帧 −15.00°，与游戏内角度一致；导出的 GLB 里 `wing_up` / `wing_down` 各含 translation+rotation 通道（0 长度的 `wing_initial` / `pivot_up` / `pivot_down` 是纯姿态片段，没有运动，导出器会略过）。

### 常见车的片段数

| 车 | 片段 |
|---|---|
| 大多数带尾翼的车 | `wing_initial` / `wing_up` / `wing_down` / `pivot_up` / `pivot_down` |
| Mercedes SLR McLaren 722 | 六态：`neutral↔speed` / `speed↔brake` / `neutral↔brake` |
| Ford GT | `wing_up 0→34`、`pivot_up 36→56`（同一 banim 的不同时间段） |

全库 53 台有 `_animations.xml` 的车的逐车对照（片段组合 + 帧范围 + 行为串）在
`docs/动画片段与行为对照.md`。

---

## 6. 从 Blender 反向导出锚点与动画

`File → Export` 下有三个写侧入口，都从当前场景读数据：

| 入口 | 输出 | 数据来源 |
|---|---|---|
| `Real Racing 3 Points (.points)` | `.points` | 场景里 `POINT_*` / `HINGE_*` / `TRANSFORM_*` 空物体（或带 `rr3_point_type` 属性的） |
| `Real Racing 3 Animation (.banim)` | `.banim` | `AERO_*` 空物体的关键帧（`tracks_from` 可改成带 `rr3_track` 属性的或当前选中的） |
| `Real Racing 3 Animation Clips (.xml)` | `<车>_animations.xml` | 手工填片段名 + 起止帧（`preset=WING` 自动出 `wing_initial`/`wing_up`/`wing_down`） |

三条**坐标系事实**（`rr3_export.py` 顶部 docstring 也写了，弄错就会飞）：

1. **动画基就是 Blender 基** —— 导入时 `cm @ ANIM_TO_MODEL == 单位阵`，所以 `AERO_*` 空物体的
   `location` / `rotation_euler` **就是**引擎值（米 / 弧度），导出时原样读，不做换算。
2. **锚点不在这个基里** —— 导入是 `Rot180Z @ engine`，导出就是 `engine = Rot180Z @ blender`（180° 绕 Z 自逆）。
3. **一轨 = 一个零件，6 个通道** —— `pos xyz`（米）+ 欧拉 `xyz`（度），存的是**相对静止姿态的增量**。

导出 `.banim` 时关键帧时间是 `(帧号 − 1) / fps × 1000` ms，`fps` 留 0 就用场景帧率。
**必须求值关键帧**（插件里 `_pose_at` 会 `frame_set` 再读），直接读对象只会把所有帧写成同一个当前姿态。

`.points` 导出会跑 `points_write.validate`，非引擎标准名的锚点会以 WARNING 报出来；
79 条引擎硬点名（37 个 `POINT_` + 42 个 `HINGE_`）列在 `docs/材质与部件清单.md` 第 5 章，
`points_write.engine_name()` 按前缀匹配，所以 `POINT_HEADLIGHT_LEFT_01..09` 都归到 `POINT_HEADLIGHT_LEFT`。

---

## 7. 动画行为：什么时候动（spec 里的行为串）

`.banim` + `.xml` 决定**能不能动、动哪一段**；spec 里的**部署条件串**决定**什么时候动**。
它是自由文本 + 逗号参数，引擎按前缀认，格式 `<Behaviour>[, <arg1>, <arg2>]`，位置在
`generic_race`（或 `bf_race` 等模式串）**前一个 token**。全库 540 台车实测：

| 行为串 | 台数 | 含义 |
|---|---|---|
| （空 / 无） | 476 | 不主动动作 |
| `NascarAirBrake` | 40 | NASCAR 专用刹车挡板，全部无 `_wing.banim` |
| `DeployWhenBraking` | 13 | 刹车时展开 |
| `PaganiHuarya` | 2 | 官方拼写就是 `Huarya`，不是 `Huayra` |
| `DeployAtSpeed, 120, 60` | 2 | 时速 120 展开 / 60 收回 |
| `EngineFan` | 2 | 引擎风扇 |
| `BrakeAndSpeedCombo, 180, 170` | 2 | 刹车 + 时速组合 |
| `DeployAtSpeed, 275, 220` | 1 | 40_2013_koenigsegg_agera_r |
| `BrakeAndSpeedCombo, 120, 80` | 1 | 340_2006_mercedes_slr_mclaren_722 |
| `BrakeAndSpeedCombo, 100, 60` | 1 | 2023_rimac_nevera |
| `DeployAtSpeed, 100, 60` | 1 | 2020_porsche_taycan_turbo_s |
| `None, 180, 170` | 1 | 562_2022_koenigsegg_jesko_absolut |

**关键反例**：53 台有 `_wing.banim` 的车里只有 7 台用 `DeployWhenBraking`，
**16 台完全没有行为串却有尾翼动画**。所以 `DeployWhenBraking` 不是"有尾翼动画"的必要条件。

写 spec 里的这个 token 时**只能原地替换，不能插入**：`generic_race` 前必须正好是一个空 token
（`\x00\x00\x00\x00\x0c\x00\x00\x00generic_race`），插入会移动后面所有字段，
引擎在 `+0x18` 读到空指针直接崩。插件 `spec.set_aero()` 会先断言这个空 token 全文件只出现 1 次。

**静态尾翼 vs 主动空力互斥**：有 `HINGE_WING_REAR_LEFT/RIGHT` 的 17 台全是 NASCAR 且全无 `_wing.banim`；
有 `_wing.banim` 的 53 台车全部 0 条 WING 铰链（`HINGE_WING_REAR` 全库 0 命中）。
⇒ 想让尾翼动，走 banim；想让它固定在一个角度，走 `.points` 铰链。

---

## 8. 游戏内改造：自定义赛事 / 赛事音乐 / 画质开关

除模型侧工具外，`analysis/` 下还有一套**直接改游戏运行时数据**的工具（都实测通过，详见
`docs/HANDOFF-20261027-3-赛事音乐画质工具.md`）：

| 工具 | 作用 | 现状 |
|---|---|---|
| `analysis/series_tool.py` | 自定义赛事：`rr3series add/edit` 生成 14 个文件，部署并同步两处清单 md5 | 已注入 10000 LFA-AnimTest，`verify` 14/14 |
| `analysis/music_tool.py` | 赛事音乐：改 `Tracks/data/*.bin.nct` 里的 `Music_Track_1/2/3` 记录 | 已改 4 条 Bathurst，`verify` 4/0 |
| `analysis/gfx_profile.py` | 画质开关：生成 `AndroidHigh.plist` / `.feats`，五档 low→insane | **ultra 已在设备生效** |
| `analysis/gui_tool.py` | `.gui` 布局解码 / 改控件 / 加按钮 | 可用（2380 条界面） |
| `analysis/so_patch.py` | `.so` 原地补丁（apk 内 STORED，不重签） | 可用 |
| `analysis/dev.py` | adb 封装，避开 PowerShell 引号地狱 | 可用 |
| `analysis/armxref.py` | ARM64 xref 扫描（numpy）；`GhidraVA = ELF vaddr + 0x100000` | 可用 |
| `analysis/rr3adb.py` | adb 路径/序列号/端口运行时自动探测（MuMu 升级后 15.0→12.0） | 全部工具共用 |
| `analysis/addr.py` | AArch64 迷你反汇编 + vaddr↔文件偏移 + .rela.dyn 查询 | 可用 |
| `analysis/mem.py` | 活进程内存读写（按 ELF vaddr 寻址） | 可用 |
| `analysis/screen.py` | 截图 / 像素变化率 / 角落三击 | 可用 |
| `analysis/ascii.py` | 截图转 ASCII（模型读不了图时的替代） | 可用 |
| `analysis/patch_debug_menu.py` | 调试菜单 8 点补丁：verify / build / push | **已部署** |
| `analysis/debug_menu.py` | 补丁与运行时标志状态检查、三击触发、强制开闸 | 可用 |
| `analysis/debug_cfg.py` | `doc/DebugRaceSelect.2.cfg` 逐字段解码 | 可用 |

**地基**（`docs/清单校验与补丁.md`）：清单 md5 == 注册表 md5 且文件存在 ⇒ 引擎永不下载；
Android 引擎从不现场算 md5。所以不动清单就直接改 `.depot/` 里的文件即可生效。

---

## 9. 游戏内调试菜单（已打通）

屏幕**任意角落连点三次**呼出调试菜单，打开 `DebugRaceSelector` 后主菜单出现 **Σ 图标按钮**，
点进去就是原厂的 `DebugRaceSelectScreen`：自选赛道 / 模式 / 圈数 / 对手数 → PLAY 开赛。
**已实机验证可玩，参数正确。**

原理：角落三击 → `StartAcceptingPassword` 被打成直接以 `"Ironmint"` 调 `EnterPassword`
→ 作弊标志置 1 → `AreCheatsAllowed` 恒真 → Σ 按钮出现。共 8 个补丁点，
详见 `docs/HANDOFF-20261028-6-调试菜单.md`。

```powershell
python analysis\patch_debug_menu.py verify   # 校验源 apk 10 个点的原始字节
python analysis\patch_debug_menu.py build    # 重新构建 base_patched.apk
python analysis\patch_debug_menu.py push     # 推上去并重启游戏
python analysis\debug_menu.py status         # 补丁 + 运行时标志体检
python analysis\debug_cfg.py show            # 解出上次开赛的赛道索引等字段
```

> 最容易踩的坑：`.so` 的第 2/3 个 PT_LOAD 文件偏移与 vaddr **差 0x1000**，
> 且 ADRP 的 PC 必须用 **ELF vaddr**（不是 Ghidra VA，后者高 0x100000）。
> 搞混了不会报错，只会读到一堆看似合理的垃圾。

---

### 常用命令

```powershell
$env:PYTHONIOENCODING = 'utf-8'; $env:ANDROID_ADB_SERVER_PORT = '5038'
& $adb connect 127.0.0.1:16384      # 模拟器重启后必须重连，否则 verify 会假报 MISMATCH

python analysis\series_tool.py list                    # 看现有 1603 个系列
python analysis\series_tool.py add --title "MY CUP" --cars 114 `
  --event "Bathurst" --event "Spa" --group STREAM_GROUP_AMATEUR --deploy
python analysis\music_tool.py set --track Bathurst --song Ryan_Kurt_Time.mp3
python analysis\gfx_profile.py build insane work\gfx\insane ; python analysis\gfx_profile.py deploy work\gfx\insane
```

---

## 文档索引

| 文档 | 内容 |
|---|---|
| `docs/插件使用手册.md` | ★ 任务导向：6 个"怎么做成一件事" + 驾驶员导入 + 20 行排查表 + §2 的 30 行快速对照 |
| `docs/材质与部件清单.md` | ★ 297 材质（按 application 分组）/ 1869 部件名与槽位 / 30 个 `_mm_` tag / 79 锚点 / 12 片段 |
| `docs/动画片段与行为对照.md` | ★ 540 台车的片段组合、帧范围、行为串逐车表 |
| `docs/轮毂与轮胎缩放.md` | ★ 0.60 m 模板 + 径向拉伸：系数来源、两种模式、f0..f7 语义、全库分布、刹车与预装配 LOD |
| `docs/游戏材质与涂装.md` | ★ 游戏材质按参数+贴图导入：materials.bin 的 297 块 / 186 条着色器、LUT 色带、单槽多预设结构、私有贴图容器 |
| `rr3_blender_addon/README.md` | 插件全部参数表 + 格式速查 |
| `docs/HANDOFF-20261027.md` | 尾翼发暗根因取证（liveries 表缺行 → `car_flat`） |
| `docs/HANDOFF-20261027-2-插件与文档.md` | 插件 v2 的全部改动、19 个 operator、spec 定位器修复、三条坐标系事实 |
| `docs/HANDOFF-20261027-3-赛事音乐画质工具.md` | ★ 自定义赛事 / 赛事音乐 / 画质开关 三条主线的工具用法与实机状态 + 环境常量 + 踩坑 |
| `docs/HANDOFF-20261027-3-轮子装配修复.md` | ★ 整车导入"先导 points 再装轮子"的改造：4 个 bug、5 个新参数、107 项断言 |
| `docs/HANDOFF-20261027-4-尾翼轨道与材质.md` | ★ 尾翼-轨道配对（keyframe 表判据）与游戏材质/涂装导入的实施记录 |
| `docs/HANDOFF-20261028-5-单槽多预设与贴图.md` | ★ 材质改成单槽多预设、贴图打包、私有容器导出器（ddsdecode / texport） |
| `docs/HANDOFF-20261028-6-贴图翻转与着色参数.md` | ★ 贴图垂直翻转（图翻 UV 不动）、`Specular Tint` 除以 255（"像镀铬"根因）、按涂装表决定谁有多预设 |
| `docs/HANDOFF-20261028-7-材质表查找与贴图缓存.md` | ★ 材质表找不到时不再静默（`material_depot` 参数）、`Load car textures` 递归 `livery/`、解码缓存分版本并清旧的未翻转贴图 |
| `docs/HANDOFF-20261028-8-cab变体-common贴图-损伤分组.md` | ★ `_mm_cab` 内饰的涂装变体（材质名去重）、`vehicles/common` 三级贴图回退（153/155/90/540 台缺行）、损伤件 `separate_damage` 子集合 |
| `docs/HANDOFF-20261028-9-LODGH-驾驶员-相机壳.md` | ★ 删 `all_lods`、LOD G 复用 F 的预装配轮子 / H 无轮子、驾驶员导入（15 部件 + 根空物体 + 1/65536 单位）、`BONNETCAM` 独立集合、`shared`/`int_a`/`int_b` 完整导入 |
| `docs/HANDOFF-20261028-10-驾驶员朝向与动画选择.md` | ★ 驾驶员朝向改由根空物体转 180°（不再逐部件镜像）、动画变体改读车自己的 `.bin.nct` 记录（224/540 有字段）+ `.banim` 文件选择器 |
| `docs/HANDOFF-20261028-6-调试菜单.md` | ★ 游戏内调试菜单打通：8 点补丁、触发链路、地址链、DebugRaceSelectScreen 与 cfg 格式 |
| `docs/RE-载入-拼装-动画-着色器.md` | 引擎侧逻辑逆向（资源校验 / 载入 / 拼装 / 动画 / 着色器） |
| `docs/FORMATS.md` | MonkeyTool 的 m3g 格式文档（原始资料） |
| `docs/m3g自定义参数.md` | 81 字节块 / positionScale / 顶点格式实测 |
| `docs/points-格式.md` / `appearances-格式.md` / `materials-格式.md` | 各格式逐字段说明 |
| `docs/livery槽位表与材质名.md` | 涂装四张表 + 槽位表全量 |
| `docs/新车-共享表注册.md` / `清单校验与补丁.md` | 造车要改的六张表 + 不触发下载的机制 |

## 自检

```
python tools\sync_rr3lib.py --check          # 根 rr3lib/ 与插件副本是否一致（28 模块）
python tools\test_car.py                     # 造车端到端 13 步，普通 Python
python tools\gen_catalog_doc.py              # 重新生成 docs/材质与部件清单.md
python tools\gen_anim_doc.py                 # 重新生成 docs/动画片段与行为对照.md
& "C:\Program Files\Blender Foundation\Blender 4.5\blender.exe" -b --factory-startup --python tools\smoke_addon.py
                                             # 插件冒烟 16 项（日志会有大量 PermissionError 噪声，只 grep SMOKE/FAIL）
& "C:\Program Files\Blender Foundation\Blender 4.5\blender.exe" -b --factory-startup --python tools\smoke_wheels.py
                                             # 轮子装配/缩放 107 项（4 台车 × 3 模式 + 后胎宽度 + 朝向/镜像 + 刹车 + 预装配 LOD + LOD G/H + shared/int_a）
& "C:\Program Files\Blender Foundation\Blender 4.5\blender.exe" -b --factory-startup --python tools\smoke_driver.py
                                             # 驾驶员导入 50 项（记录配动画 + 15 部件 + 根空物体 + 坐姿手到轮缘 + 低模 + 换皮肤 + 材质接线）
& "C:\Program Files\Blender Foundation\Blender 4.5\blender.exe" -b --factory-startup --python tools\smoke_materials.py
                                             # 游戏材质/涂装/贴图 113 项（单槽多预设 + 切换 operator + 容器解码 + livery 子目录 + common 回退 + 损伤分组）
```

贴图容器自检（纯 Python，不需要 Blender）：

```python
from rr3lib import texport, ddsdecode
texport.selftest()        # 每种容器解一个样本，返回失败数（2 个块格式会明确跳过）
ddsdecode.backend()       # "numpy" 或 "pure"，两条路径逐像素一致
```

