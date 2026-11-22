# 拆成两个软件：开发路径

> 写作时间：2026-11-11。依据是 `rrmod` 现有 25 个模块、`rr3lib` 34 个模块的实测行为，
> 以及本文件末尾「取证」一节里那些跑出来的数字。凡是数字都量过，凡是判断都写了理由。

---

## 0. 一句话版本

用户的设想是对的，而且**地基已经有一半了**：`rrmod/workspace.py` 早就是"从不写安装、
只写工作副本"，`rrmod/edit.py` 早就是"每次编辑一个备份文件夹"。真正要做的不是重写，
是把这两件事**接上界面**、把"三本账"换成"按路径查账"、把 mod 包补上依赖声明。

分期建议：

| 期 | 内容 | 规模 |
|----|------|------|
| 第 0 期 | 修三个 bug，顺手把"按路径查账"做出来（**这是后面一切的地基**） | 2–3 天 |
| 第 1 期 | 历史步数 + 回滚页 + 部署前按文件备份 | 3–4 天 |
| 第 2 期 | 拆成两个程序 + 分区导航 | 4–5 天 |
| 第 3 期 | 依赖声明 + 发布页打包 + 自制材质 | 视情况，最难 |

---

## 1. 拆两个程序：同意，但边界要按「谁拥有真相」划

用户的原话是「一个软件就是 mod 制作，要求有游戏的完整备份」。**这一条我建议改一改**，
因为它会让软件多要求 10.4 GB 磁盘，而实际上并不需要。

现在的架构已经做到了这件事：

```
安装目录 E:\...\files         只读。任何代码都不写它。
        ↓ 按需取文件
工作副本 <state>\workspace\<md5[:10]>\   唯一写入点
        ↓ 用户按 Push
设备 / 用户选的目录            只在那里改
```

`rrmod/workspace.py:Workspace` 的 `ensure_car()` / `ensure_data()` / `ensure_livery()` 都是
"缺哪个拷哪个"。所以：

- **Mod 制作工具需要的是「一份干净的安装目录」当参考源，不是「一份完整备份」。**
  它从不写那个目录，所以那个目录被弄脏的风险是零。
- 用户真正担心的"回滚"发生在**部署之后**（设备/目标目录被改了），那才是需要备份的地方，
  而备份粒度应该是"被这个 mod 碰过的文件"，不是整盘。

所以两个程序的边界建议这样划：

### Mod 制作工具（暂名 RR3 Mod Studio）

拥有：**工作副本 + 编辑历史 + mod 包**。

- 输入：一份干净安装（只读参考）+ 用户的模型/贴图。
- 输出：`.rr3mod` 包（一个 zip，带 `mod.json` 和依赖声明）。
- 不需要：adb、设备、部署前备份。
- 需要：完整的历史/撤销、分区导航、发布页。

### Mod 管理器（RR3 Mod Manager）

拥有：**目标 + 已装 mod 清单 + 部署前备份**。

- 输入：`.rr3mod` 包 + 目标（adb 设备 或 用户选的目录）。
- 输出：改过的目标 + `<mods>/_backup/<mod-id>/` 里的回滚副本。
- 不需要：模型编辑、导出、历史步数。
- 需要：依赖解析、冲突检测、按 mod 卸载、音乐/画质（这两块本来就不打包）。

**中间那层是 `.rr3mod` 包**，两边都只认它。现在 `rrmod/share.py` 已经是这个形状了
（zip + `mod.json` + `files/<game path>`），扩展它比新造一套好。

---

## 2. 分区（车辆 / 地图 / 赛事 / 品牌）

同意，而且**这几乎不花时间**，因为代码已经是按资源域分开的：

| 分区 | 现有模块 |
|------|----------|
| 车辆 | `cars.py` `edit.py` `slots.py` `paints.py` `materials.py` `stats.py` `anim.py` `animcopy.py` `modpack.py` `share.py` |
| 地图 | `maps.py` `tracks.py` |
| 赛事 | `series.py` |
| 品牌 | `brands.py` `atlas.py` `thumbs.py` |
| 音乐 | `music.py` |
| 画质 | `gfx.py` |
| 通用 | `depot.py` `workspace.py` `deploy.py` `textures.py` `i18n.py` |

所以"分区"是**导航层的重排**，不是模块重构：加一个"我要做什么"的入口页，选完之后
决定哪些标签可见、哪些表被镜像。`rrmod/ui/app.py:112` 那个 `QTabWidget` 加个
`setTabVisible()` 就够了（Qt 6.5+ 有）。

一个附加好处：**分区能顺手解决"镜像太多"的问题**。现在 `ensure_data()` 会镜像 540 个
spec + 共享表，因为不确定用户要改哪台车。选了"车辆分区"之后可以只镜像用户打开的那台。

---

## 3. 历史步数：浮动面板 + 工程文件（两个不同时间尺度）

用户提的改法我全部同意，而且比我原来的「钉住」好，理由写在 3.2 和 3.3。

### 3.1 浮动历史面板

**地基已经有了，缺的是界面、信号和上限。** 实测 `rrmod/edit.py`：

```
BACKUP_DIR = "_rrmod_backup"
_begin()          -> 开一步，同一秒内重复自动加 -2/-3 后缀
_backup(root,p)   -> 把 p 拷到 <root>/_rrmod_backup/<stamp>/<rel>
backups(root)     -> 按名字倒序（新→旧）返回所有步
restore_backup()  -> 把某一步的文件逐个拷回
```

每个写操作都调 `_begin()`（`edit.py` 里 12 处、`share.py:239`、`textures.py:208`），
`sync_file()` 跟着外层那一步走。`workspace.py:824 _is_backup_rel()` 保证 `clear()`
不会删备份目录。所以**"撤销上一步"已经能工作了，只是没有按钮**。

浮动面板的实现成本几乎为零：Qt 6.11 的 `QDockWidget` 原生支持
`setFloating(True)` + `allowedAreas()` + `QMainWindow.setDockOptions(GroupedDragging)`
（已实测这三个 API 都在）。所以历史面板就做成一个 dock，默认停靠在右侧，
拖出去就是一个 Photoshop 那种悬浮窗，**和均衡器一样可以被用户摆在屏幕任意位置**。

要补的五件事：

1. **每步的元数据**。现在只有时间戳。加一个 `<stamp>/_step.json`：
   `{"stamp", "title", "files": [[rel, size]], "when", "mod", "pinned"}`。
   `title` 由调用方给（"装上 2012_lexus_lfa 的 LOD A"、"给尾翼补涂装行"），
   这样回滚页才能显示人话而不是 `20261111-001432-3`。
2. **上限 + 钉住**。默认 20 步，超过删最旧；`pinned: true` 的步永不删。
   工程文件（3.2）解决的是"大步骤"，钉住解决的是"中等步骤"，两者不冲突。
3. **历史缓存放哪由用户定**。`BACKUP_DIR` 现在是写死在 `<root>/_rrmod_backup`。
   改成可配置：`settings["history_dir"]`，空 = 默认（工作副本旁边），非空 = 用户指定。
   理由：有人希望历史跟工程走（可移动），有人希望它待在快的盘上（大 LOD 拷起来贵）。
   注意跨盘时 `shutil.copyfile` 会变成真拷贝，所以要在设置页标出"这个位置有多少空间"。
4. **重做**。Blender 那种 Ctrl+Z / Ctrl+Shift+Z 需要一份"撤销前再备份当前状态"的栈。
   建议先只做撤销（用户的原话也是"回滚页中选择要回滚的修改"），重做放后面。
5. **按对象过滤**。这是用户真正想要的——"撤销品牌时别把 LFA 的改动一起撤销"。
   现在 `undo_last()`（`rrmod/ui/app.py:652`）是 `ws.clear()` 全局清空。
   改成：历史面板列出每一步的 `title` + 文件清单，用户勾选要回滚的步（可以跨步选），
   只恢复被勾中那几步里出现过的文件。

### 3.2 工程文件：`.rr3proj`（用户提的，比我原来的方案好）

我原来的想法是「钉住某一步」，用户的想法是「另存一个工程」。**用户的更好**，理由是：

- 钉住只能保住"文件状态"，保不住"当时的参数"——而 mod 的参数（新车的 id、appearance、
  涂装槽位、aero 行为、价格…）是散在 8 个 nct 里的，不是"文件的某一版"。
- 另存工程可以**分支**：同一个 mod 两个方向，各自演化，互不干扰。钉住做不到。
- 工程可以**移动、分享、备份到别的盘**，历史步数不行（它绑定在工作副本上）。

实测压缩率（LFA 一台车 33 文件 7.37 MB）：

```
level 1 ->  4.90 MB (66%)  0.23 s
level 6 ->  4.84 MB (66%)  0.25 s
level 9 ->  4.84 MB (66%)  0.33 s
分项： .m3g      12 files  4.64 MB -> 2.13 MB (46%)
       .z        16 files  1.47 MB -> 1.46 MB (100%)   ← 已经是 zlib，压不动
       .bin       2 files  1.26 MB -> 1.25 MB (99%)    ← 同上
```

⇒ **用 level 1，0.23 s，和 level 9 只差 1.2%**。`.dds.z` 已经是压缩过的，再压是浪费 CPU。

工程文件格式建议（zip，和 `share.py` 的包同构，只是多一层）：

```
project.json           {
                         "format": 1, "name": "LFA wing", "made_by": ...,
                         "created": ..., "install_md5": "...",   ← 绑定的参考安装
                         "params": { ...BuildDialog.result_info() 的原样... },
                         "files": [["vehicles/2012_lexus_lfa/...", "replace"|"new"], ...]
                       }
files/<game path>      当时那些文件的内容
history/               可选：把当前的历史步一起带走（用户勾选）
```

关键一点：**`params` 直接存 `BuildDialog.result_info()` 的返回值**（实测它有 27 个键，
从 `pack`/`slots`/`new_id`/`aero` 到 `stats`/`tail`/`series` 全在里面）。这样"打开工程"
= 把对话框填回去，不需要第二套参数模型。现在这些参数**根本没有落盘**（
`Select-String result_info` 只在 `app.py:430` 出现一次，用完就丢），所以工程文件顺便
解决了"关掉程序就忘了上次怎么填的"。

`install_md5` 用来检测"参考安装变了"——如果用户换了游戏版本，打开工程时要提示
"这个工程是基于另一份安装做的"，而不是静默写错字节。

### 3.3 两个时间尺度别混在一起

- **历史步数** = 秒级，自动，有上限，绑在工作副本上。
- **工程文件** = 分钟/小时级，手动，无限，可以带走。

用户原来问的"钉住大步骤"其实是想用秒级机制表达小时级意图，工程文件正好填这个空。

> **注意**：第 4 条和第 1 期"部署前按文件备份"是同一个东西的两面。
> 工作副本里的历史负责"我还没部署，改错了"；部署前的备份负责"已经推上去了，要退回来"。
> 建议共用同一个 `_step.json` 格式，只是放在不同目录。

---

## 4. 部署前备份：按文件，不按整盘

用户自己已经想到这个了（"可能有些用户电脑没有那么多空间"），**这是对的**。实测：

| 东西 | 大小 |
|------|------|
| 整个安装 `files/` | **10.43 GB**（48,678 文件） |
| `.depot/` | **10.38 GB**（47,156 文件） |
| 一台车的目录（LFA，33 文件） | **7.37 MB** |
| LFA 的 spec + livery 表 | 874 B + 4,700 B |

所以一个典型的车辆 mod **< 30 MB**，而整盘备份 10.4 GB。差 350 倍。

而且备份清单是**免费的**：管理器在 Push 之前已经算出了"要推哪些文件"
（`DeployPage.prepare()` → `self._plan`），再加上 `deploylib.following_manifests()`
算出的那几本账，就是要备份的完整清单。

设计：

```
<mods>/                     用户选的 mod 包目录
<mods>/_backup/<mod-id>/    这个 mod 部署前的原始文件，按游戏路径存
<mods>/_backup/<mod-id>/_before.json   {files: [[path, md5, size]], when, target}
<mods>/_state.json          已装 mod 清单 + 每个 mod 提供/占用了什么
```

卸载一个 mod = 把 `_backup/<mod-id>/` 里的文件拷回去 + 从三本账里删掉**它新增的**行
（`_before.json` 里有"这个文件原本不存在"的标记）。

**边界情况要提前想好**：

- 两个 mod 改了同一个文件 → 第二个 mod 的 `_backup` 里存的是"第一个 mod 之后"的版本。
  卸载顺序必须**后进先出**，否则回滚到一半的中间态。这一点要在 `_state.json` 里记栈。
- 一个 mod 新增了文件，另一个 mod 也新增了同名文件 → 装第二个时拒绝，或者改名。
- 用户手动改了设备上的文件 → md5 对不上 `_state.json`，卸载前要提示"这个文件被别的
  东西改过了，回滚会覆盖它"。

---

## 5. 依赖项：游戏没有这个概念，所以只能做「文件级 + 槽位级」

这是整个设想里最容易做错的部分。先说清楚一件事：

> **游戏引擎不知道 mod 是什么。** 它只看「asset list 里有没有这一行」和「文件 md5 对不对」。
> 所以依赖不可能是引擎级的，只能是我们自己的元数据 + 部署时的检查。

### 5.1 文件级（简单，必须先做）

包里每个文件只有两种身份：

- **替换**：目标上已经存在 → 记下原 md5 和原文件，卸载时拷回。
- **新增**：目标上不存在 → 卸载时删掉，并从 asset list 里删行。

冲突判定：A 要替换 `x.m3g`，B 也要替换 `x.m3g`，且两个包给的 md5 不同 → 冲突，拒绝装 B
（或让用户选"覆盖"）。

### 5.2 槽位级（难，但绕不开）

新材质、新 livery 槽位、新 appearance id、新赛事 id —— 这些都是**全局编号**，
两个 mod 各自分配就会撞号。现在 `rr3mods.json` 已经记了 `vanilla`/`mods`/`series`/`brands`
四类，扩成"谁占了哪个号"就行：

```json
"claims": {
  "appearance_id": {"611": "2012_lexus_lfa_copy"},
  "livery_slot":   {"1942": "my_custom_material"},
  "series_id":     {"10001": "LFA Cup"}
}
```

分配号的时候查这张表；装包的时候检查包里声明的号有没有被别人占。

### 5.3 材质：用户提的两级模型是对的，而且第二级比我以为的便宜

用户把材质分成两级，我同意，而且实测下来**第二级的门槛比文档里原来写的低**：

#### 第一级：用游戏材质，只换贴图 —— **不需要任何依赖声明**

理由：贴图是**车自己的文件**（`<car>/livery/<car>_<slot><suffix>`），跟着车一起打包走。
`materials.bin` 一个字节都不用改，`liveryStringTable` 也不用改——槽位号本来就是游戏给的。
实测这条链是三级回退（`rr3lib/carmaterial.py:texture_path_for_tag`）：

```
① Paint.overrides[slot]      该涂装自己的覆盖
② LiveryFile.textures[slot]  车级行
③ default.liveries.bin.nct   兜底（22 行，全指向 vehicles/common/）
```

所以「材质名一样但轮胎贴图不同」本来就是游戏支持的：541 个 livery 文件里 387 台自带
`ext_tyre` 行，13 个涂装 per-scheme 覆盖 slot 4，71 个覆盖 slot 3。
`rrmod/edit.py:set_texture_slot(root, name, slot, source, *, paint=None)` 已经能写这一级了。

⇒ 用户说的"使用自定义贴图的材质在打包发布时必须带上，不需要依赖声明"**完全正确**。
打包时把 `<car>/livery/` 下被换掉的那几张一起塞进 zip 就行，它们天然属于这台车。

#### 第二级：自定义材质 —— 需要独立的包 + 标识 + 参数

这一级的可行性我重新验过了，**之前判"materials.bin 只读"判早了**：

```
materials.bin  135,065 B
  → load_records() 拆出 5,887 条记录（每条 = u32 key + u32 length + payload）
  → 重新拼回去，与原文件逐字节相同
  → 297 个 instance 块（296 个有名字），块长只有两种：14 条记录（69 个）/ 15 条（228 个）
  → 56 种 key，20 种已知（K_INSTANCE / K_TEMPLATE / K_SHADER / K_TEXTURE / K_UNIFORM ...）
```

**绑定关系已经搞清了**（这是之前不敢写的主因）：

```
实例名 --(K_TEMPLATE)--> 模板名 --(shaders 表)--> shader 块 --(K_VSH/K_FSH/K_TEXTURE)--> 着色器与贴图槽
```

实测 296 个实例里，**136 个不同模板、186 个 shader、0 个实例的模板不是 shader**
（`Library.shader_for()` 就是先查模板再查实例名）。例子：

```
car_paint_matte → shader car_paint_matte
  vsh car_rr3/car.vsh   fsh car_rr3/car.fsh
  uniforms: mu_MaterialSpecularColour_Base = 25, 25, 25
            mu_MaterialSpecularPower_Base  = 10.0
            mu_MaterialSpecularColour_Top  = 0, 0, 0
            mu_MaterialSpecularPower_Top   = 100.0
            s_cubeMap = s_carReflectionCubeMapBlur
  textures: [3] vehicles/shaders/fresnel_matte.pvr
            [4] vehicles/shaders/spec_matte.pvr
```

**新槽位号也是便宜的**：`liveryStringTable.bin.nct` 是纯位置表
（`u32 count` + 每项 `u32 len + bytes`，实测 2,068 项、70,134 B、往返逐字节一致），
**追加一个名字 = 70,153 B，新槽位号 = 2068**。所以「新材质需要一个全局唯一槽位号」
不是难题，是**纯 append**（只要所有 mod 都从"当前末尾"往后分配，天然不撞号——
但两个 mod 同时装就需要 5.2 的 claims 表来协调）。

一个新材质要动的东西，按依赖顺序：

| # | 文件 | 改动 | 谁负责记账 |
|---|------|------|-----------|
| 1 | `materials.bin` | 复制一个模板块，改 `K_INSTANCE` 的值 | `asset_list_startup.txt` |
| 2 | 它引用的 shader | **必须复用现成的**，不能新造（vsh/fsh 是编译过的） | 同上 |
| 3 | 贴图 `.dxt.dds.z` | `rr3lib/ddsencode.py` 已有写侧，1024² 平均差 0.84 | `asset_list_vehicle_common.txt` |
| 4 | `liveryStringTable.bin.nct` | 追加名字，拿新槽位号 | `asset_list_vehicle_data.txt` |
| 5 | `<car>.liveries.bin.nct` | 指向它的行 | `asset_list_vehicle_<car>.txt` |

⇒ **五本不同的账**。这正好说明 7.1 的 `owner_of(path)` 是必需的，不是优化。

**包的形态**（用户说的"单独打包发布，附上只有管理器能看懂的标识和参数"）：

```
material.json  {
                 "format": 1, "kind": "material",
                 "id": "my_carbon_weave",            ← 包自己的唯一标识
                 "name": "My Carbon Weave",          ← 给人看的
                 "based_on": "car_matte",            ← 复制的是哪个现成模板（必须存在）
                 "slot_name": "my_carbon_weave00",   ← 要追加进 liveryStringTable 的名字
                 "params": { "rgba": [255,255,255,255],
                             "flags": ["FOG","SPEC_TEXTURE","SPEC_MASK_TEXTURE"],
                             "uniforms": {"mu_MaterialSpecularPower_Base": "10.0"},
                             "textures": {"3": "my_carbon_fresnel.pvr",
                                          "4": "my_carbon_spec.pvr"} },
                 "requires": []                      ← 材质包自己也可以有依赖
               }
files/         贴图与（可选）改过的 materials.bin
```

一个材质可以带多张贴图（`textures` 是槽位映射），多个材质可以打成一个合集
（`kind: "material_pack"` + 一个 `members: [...]` 列表）——用户说的两点都覆盖了。

#### 车引用自定义材质时

车包里带一条依赖，管理器读得懂：

```
"requires": [
  {"kind": "material", "id": "my_carbon_weave", "version": 1,
   "author_note": "需要 My Carbon Weave 材质包",
   "url": "https://..."}          ← 作者可写，纯提示，管理器不自动下载
]
```

**关键行为（用户明确要求的）**：允许装进管理器，但**依赖没解决之前不允许启用**，
并说清缺什么。这条要写进 `_state.json` 的状态机：

```
installed, satisfied   → 可启用
installed, missing     → 列出缺的 id，Enable 按钮禁用，但 Uninstall 可用
```

作者写的 `author_note` / `url` 只显示，不自动访问网络（离线软件不该偷偷联网）。

#### 为什么建议这一级放最后

不是技术不可行，是**测试成本高**：改了 `materials.bin` 就是全局改动，任何一台车都可能
受影响，而验证要靠进游戏看。所以第一版只做「复制一个现成材质改名」，
不做「从零造新 shader」，也不做「改现有材质」（那会波及所有用它的车）。

### 5.4 驾驶员姿势（用户要加进待办的那条）

已写进 `docs/RRMOD-BACKLOG.md` 的 `### Drivers`。核心数字：

- 540 台车里 **131 台**匹配到专属姿势（33 个不同 `driver_<x>.banim`），**409 台**回落到
  通用 `driver.banim`，0 台缺失。
- 但低模只有 **12 个** `driver_lod_c_<x>.m3g`（`_d` 也是 12 个），而姿势用了 33 个
  ⇒ **24 个姿势没有配套低模**，那台车会静默拿到通用低模、摆一个它没被建模的姿势。
  只有 37/540 台刚好对得上。
- 反过来，`f1412t2` / `f1f14t` 两个低模**没有任何车记录引用**。

这就是用户说的"有依赖项问题"：**车声明了一个姿势，包就得带上它；带不上，管理器要拒绝装。**

---

## 6. 工具套件

- **贴图转换**：已有。`rr3lib/ddsdecode.py`（读 DXT1/3/5）+ `ddsencode.py`（写 DXT1/DXT5，
  实测 1024² 平均差 0.84，0.19–0.29 s）+ `texport.py`（容器读写，`.dxt.dds.z` 等四族）。
  **只差一个界面**。
- **nct → xml**：`tools/nct2xml/` 是外部工具（39 MB）。要做成内置的得先搞清它做什么；
  建议先做成"调外部工具"的按钮，别自己重写。
- **m3g 检查器**：`rr3lib/m3g.py` 已经能读全部结构。一个"打开 m3g 看网格/材质/顶点数"的
  只读窗口很便宜，而且调试时极有用。

---

## 7. 第 0 期必须先修的三个 bug（它们和上面全部相关）

### 7.1 加品牌后游戏触发下载 —— 根因已确认

**根因**：`.depot` 里的文件不是"三本账"管的，是 **1,236 个 asset_list** 管的。实测：

```
.apk/res/asset_list*              1,236 个文件
认领的路径总数                    114,307 个
同一个路径出现在两个列表里        0 个   ← 所以映射是唯一的
.depot 里被某本账认领的文件       47,089 / 47,156 = 99.9%
未被任何账认领的                  67 个（CC_Data、rra_logo.svg 等，本来就不参与校验）
```

`manufacturer_logos` 只被 `asset_list_gui_assets_core.txt`（365,312 B / 3,292 行）认领，
14 行。而 `rrmod/edit.py:sync_file()` **只更新三本账**（per-car 清单 / 注册表 /
`asset_list_vehicle_data.txt`），`gui_assets` 根本不在它的范围里，`workspace.capture()`
也不捕获 `gui_assets/`。所以新加的 `sprites_2.rgb.pvr.z` 和改过的 `.atlas` 没有登记
⇒ 引擎认为资源不完整 ⇒ 触发下载。

**修法（重要：做成通用的，别硬编码）**：既然"一个路径只属于一本账"，就做一个
`manifestlib.owner_of(path) -> asset_list 文件名` 的索引（扫一遍 `apk/res/asset_list*`，
1 秒以内，缓存到内存），然后 `sync_file()` 改成"查这本账、改这一行"。这样品牌、
地图、内饰、贴花、任何未来的路径都自动正确，而且顺手能发现"这个路径根本没有账认领"
（那就该拒绝写入并报警，而不是静默产生一个游戏看不见的文件）。

**注册表其实已经是全覆盖的**，这一点很容易看错：`asset_list_base.txtCache.txt` 47,090 行里
`/gui_assets/` 有 **14,694 行**、`/materials/` 1 行，`manufacturer_logos` 的那几个文件
（`.atlas` + `sprites_2.rgb.pvr.z`）**都在里面**。所以真正漏的只有 **asset_list 那一本**，
不是注册表。加品牌时 `add_logo` 走的是 `editor.for_gfx()` + `capture_paths()`，
连 `sync_file()` 都没经过 —— 所以两本都没更新。修的时候两处都要管。

另外发现一个**独立的坑**（不阻塞，但要知道）：`.depot/vehicles/data/` 下有 3 个
`.nct.hash` 伴生文件（`custom.paints.nct.hash` / `custom.decals.nct.hash` /
`carrepairs.repairs.nct.hash`），内容是纯文本：

```
File: \files\.depot\vehicles\data\custom.paints.nct
Size: 6215 bytes
MD5: E288AE987472C0DEB5A1F34195A2B71E
SHA1: 2A8798AB4A64D13B034B253888E563AB12B7F781
CRC32: D36AA341
Author: _depot_
Description: 巧克力漆面解锁
```

**它们不在注册表里，也不在任何 asset list 里**（所以游戏不校验它们，实测 3 个里 1 个
的 MD5 已经和真文件不符也没事）。但它们是 depot 作者留下的说明，**我们的工具改这三个
`.nct` 时应该顺手更新对应的 `.hash`**，否则会留下自相矛盾的注释。这属于"顺手做对"，
不是 bug。

### 7.2 加 PNG 后 logo 不显示

两个独立原因，都要修：

1. `rrmod/atlas.py:index()` 有模块级缓存 `_INDEX`（键 `(depot, folder, size)`），
   加完 logo 不失效就看不到。加一个 `forget(depot, folder)` 或者按文件 mtime 失效。
2. `BrandsPage._logo_for()` 读的是 `self.depot`（安装目录），而 `add_logo` 写到
   `editor.for_gfx()`（工作副本 `<ws>/.depot`）。应该读工作副本，找不到再回落安装。

### 7.3 品牌删不掉，撤销是全局的

- `rrmod/depot.py` 已经有 `unregister_brand()`，只是没有按钮。
- `undo_last()` 是 `ws.clear()`（全局），这就是"撤销品牌把 LFA 一起撤销了"。
  改成第 3 节的按步回滚。
- 还有一处：`register_brand()` 把品牌记进 `rr3mods.json`（**不是游戏文件**），
  所以撤销游戏文件不会删它 ⇒ 幽灵品牌。回滚时必须同时撤 `rr3mods.json` 的那一条。

---

## 8. 建议的动手顺序（2026-11-11 整合版）

分五期。**只有第 0 期是"必须现在做"**，后面每一期的入口都依赖它。

> **进度（2026-11-12 晚）**：**五期全部做完**，另加驾驶员姿势分配，
> `tools/test_rrmod.py` **993 passed / 0 failed**，exe 已重建。每期实际落盘的东西见
> `docs/HANDOFF-20261108-资源管理器与待办.md` §3.6.1–§3.6.11。

### 第 0 期：地基 + 三个 bug（半天到一天）  ✅ 已完成

1. **`manifestlib.owner_of(path) -> 账本文件名`** —— 扫一遍 1,236 本账建索引。
   实测 **0.227 s / 114,307 条路径 / 0 条重复**，可以直接每次启动建一次，不必落盘缓存。
2. **`edit.sync_file()` 改用它**：查这本账、改这一行；没有账认领就**拒绝写入并报警**，
   不再"默默只更新三本账"。
3. **`atlas` 缓存失效** + **`_logo_for()` 读工作副本**（修 7.2）
4. **品牌删除按钮 + `unregister_brand()`**（修 7.3 的一半；另一半是 `undo_last()` 不再全局清空，
   改成按 `_step` 撤销）

做完这四步，你报的三个 bug 就全没了，而且第 1 步是后面**全部**功能的地基——
包括 `common/` 记账、自制材质、品牌、地图。

### 第 1 期：历史与工程（用户 m24609 的方案）  ✅ 已完成

5. `_step.json` 元数据 + **浮动历史面板**（`QDockWidget.setFloating(True)` + `GroupedDragging`，
   Qt 6.11.1 三个 API 实测都在）+ `settings["history_dir"]` 可配置（跨盘会变真拷贝，要显示剩余空间）
6. **工程文件 `.rr3proj`**：zip + `project.json`，`params` 直接存 `BuildDialog.result_info()` 的
   27 个键（现在完全没落盘），文件用 level 1 压缩（66%，与 level 9 只差 1.2%）

### 第 2 期：贴图与依赖（m24703 / m24821 新增，见 §11）  ✅ 已完成

7. **`rrmod/deps.py`**：引用计数 + `shipped` 标记，一个 JSON，不引入数据库
8. **`liveryStringTable` 追加器**：一次追加两个名字（部件名 + tag 名），纯 append，往返逐字节一致
9. **`common/` 四行记账工具**：dxt / etc / atc / ptc 各一行，按家族分块插入（见 §11.1）
10. 部署前按文件备份 + `_state.json`

### 第 3 期：拆成两个程序  ✅ 已完成

11. 分区导航 + 两个入口（`rrmod_studio.py` / `rrmod_manager.py`，共用 `rrmod/` 后端，
    `QTabWidget.setTabVisible()` 够用）
    **实际做法**：没有两个入口文件，而是 `rrmod/profile.py` + `--studio` / `--manager` /
    `--all` 三个开关。理由是差别只有可见页面集合，编两份 exe 等于多占 110 MB 且每个修复改两遍。
12. 依赖声明 + 状态机（`installed,satisfied` 可启用 / `installed,missing` 禁用但可卸载）
    **实际做法**：`rrmod/pack.py` 的 `ready` / `missing` / `absent` 三态。
13. 发布页打包（长在 `share.py` 上，不新造格式）
    **实际做法**：`rrmod/publish.py` 六种 `kind`，格式是 `share.py` 的 zip 加一份
    `format: 2` 的清单；旧的 format 1 share 自动升级，所以老文件不作废。

### 第 4 期：自制材质（最难，最后）  ✅ 已完成

14. 材质包格式 + `materials.bin` 写侧（第一版只做"复制现成材质改名"）
    **实际做法**：`rr3lib/gamematerial.py` 加了 `block_spans` / `encode_records` /
    `clone_block` / `insert_block` / `insert_blocks` / `save_bytes`。克隆是**整块追加**
    到材质表末尾（`spans[-1][1]` 处），既有偏移一个都不动；`car_paint_matte` 的副本
    292 B，135,065 → 135,357 B。`edit.add_material()` 顺带补 livery 槽位（没槽位就
    没有车能穿它），`remove_material()` 只删本程序加的块（游戏自带 296 个用"问安装"
    区分）。Materials 页从只读改成两个按钮；`publish.py` 加 `material` 包类型，
    安装时**只并缺失的块、不覆盖接收方已有的**。
    **块内字段仍然不编辑**：记录没有长度前缀，错一个字节后面全部错位。

**为什么第 2 期排在第 3 期前面**：拆程序是纯粹的界面搬迁，不改变任何数据；
而贴图与依赖是**新增能力**，先做出来，拆程序时才知道这些页面该归谁。
反过来先拆，第 2 期的功能就得在"刚搬完家"的代码里再改一遍布局。

---

## 9. 我不同意用户的地方（说清楚理由）

1. **"mod 制作工具要求游戏的完整备份"** → 不需要。它从不写安装，只需要一份只读参考。
   要求完整备份会让用户多花 10.4 GB，而且会诱导实现成"改备份"而不是"改工作副本"。
2. **"音乐和画质保留到管理器，不纳入 mod 范围"** → 同意，但补一句：画质的 `plist` 改动
   也应该进 `_backup`（用户自己也说了"改 plist 确实需要备份"），只是它不打包成 mod。
3. **"钉住大步骤"已被工程文件取代** → 我原来的建议撤回。工程文件能带走、能分支、
   能保住参数，钉住只能保住文件状态。但**中等粒度仍然需要钉住**（一个工程里做 30 步小改，
   想留住中间某个"现在这样很好"的状态），所以两样都留，只是定位不同。

---

## 10. 用户新提的几点，逐条回应

| 用户的话 | 我的判断 | 依据 |
|---------|---------|------|
| 工程文件，重大修改时保存/另存为 | **采纳，比我原方案好** | 参数散在 8 个 nct 里，钉住保不住 |
| 工程文件打包当时修改的文件并压缩 | **采纳，用 level 1** | 实测 66%，level 1 与 level 9 只差 1.2%，0.23 s |
| 参数也记在工程文件上 | **采纳，直接存 `result_info()`** | 它有 27 个键，现在完全没落盘 |
| 外挂式历史面板，可悬浮 | **采纳，`QDockWidget` 原生支持** | `setFloating(True)` + `GroupedDragging` 实测可用 |
| 历史缓存位置可自由设置 | **采纳，加 `settings["history_dir"]`** | 跨盘会变真拷贝，要提示剩余空间 |
| 材质分两级：游戏材质换贴图 / 自定义材质 | **采纳，完全正确** | 第一级零依赖；第二级需独立包 |
| 用自定义贴图的材质打包时带上，不要依赖声明 | **采纳** | 贴图是车自己的文件，天然属于该车 |
| 自定义材质可被多台车复用，单独打包发布 | **采纳，`kind: "material"` 包** | 五本账 + 槽位纯 append（实测 +19 B） |
| 一个材质可带多张贴图，多个材质可做合集 | **采纳** | `textures` 是槽位映射；`material_pack` 带 `members` |
| 车引用自定义材质时打特殊标识 | **采纳，`requires: [{kind,id,version}]`** | 写进 `_state.json` 状态机 |
| 允许装进管理器，依赖没解决前不许启用 | **采纳，这是关键行为** | `installed,missing` → Enable 禁用 |
| 作者可写自定义声明/下载链接 | **采纳，只显示不自动联网** | 离线软件不该偷偷联网 |

---

## 11. 贴图放哪儿：`common/` 与车目录两条路（2026-11-11 新增）

用户 m24703 / m24821 提了两个需求：移植超级房车赛 2 的模型时窗户贴图有 alpha，
可能要往 `common/` 追加；车身想用只有内饰才出现的平铺纹理材质。两条都要，
`common/` 省空间但有依赖问题。

### 11.1 关键结论：材质和贴图是两条独立的链

引擎解析一个网格时走两条链，可以任意组合：

```
网格名 LOD_A_BODY_mm_ext
   ├─ 材质: part_slot(整个网格名) ──livery 表──> 材质槽 ──> materials.bin
   └─ 贴图: tag = "ext" ──> ext_ext(1932) ──livery 表──> 图集页
```

**m3g 里的材质名被完全忽略**：实测 `Vehicle Exterior_mm_ext`、`Vehicle Interior_mm_mat00`
等 6 个名字在 `liveryStringTable` 里**一个都查不到**（全 `None`）。所以：

- Blender 里材质怎么叫都行，导出的 m3g 写什么都无所谓
- 真正决定外观的只有**网格名**和**livery 表**

⇒ **UI 上绝不能让用户填"材质名"，要让他填"网格名 + tag"**，材质从表里选。填材质名是死路。

### 11.2 窗户贴图：可以直接做，没有技术障碍

窗户材质全是 `appDepthSort` + `cmAlphaNoZWrite`，alpha 是设计内用法：

| 材质 | 模板 | flags | 贴图槽 |
|---|---|---|---|
| `car_glass` | `car_glass` | FOG, SINGLE_SPEC, GLASS | 3 = `ext_windows` |
| `car_glass_convex` | `car_glass`（同一模板） | 同上 | 同上 |
| `car_glass_tint` | `car_glass_tint` | 同上 | 同上 |
| `car_glass_trim` | `car_matte` | FOG, SPEC_TEXTURE | 同上 |

`car_glass` 走 `car_rr3/car.vsh` + `car.fsh`，配 `fresnel_glass.pvr` / `spec_glass.pvr`
和 `s_carReflectionCubeMap`——**和车身同一套 shader，只换了 LUT**。

现有 41 张窗户页**全是 DXT5（带 alpha）、512×512、10 级 mip**：
`car_windows` 8,331 B（基本空白）、`car_windows_02` 59,725 B（全库最常用，2556 个网格）、
`car_windows_04` 70,945 B（1306 个）、`car_windows_05` 134,048 B。

**坑**：窗户走 slot 1/2/3（cracked / shattered / 完好），三张图必须**同一套 UV 布局**，
否则撞碎时裂纹会错位。原厂就是这么配的。

### 11.3 平铺材质上车身：游戏自己就在用，19 台车

463 台 LOD A 全扫一遍，内饰材质出现在**车身**网格上的有 19 台：

```
car_dash_matte        15 个网格
car_dash_flat         10
car_stitching          4
car_dash_chrome        3
car_dash_matte_dull    1
```

最直接的证据是 `2020_mclaren_speedtail`：
`LOD_A_CHASSIS_mm_chassis → car_dash_flat → common/car_chassis.ptc.pvr.z`
（`level=car`，说明是这台车自己的 livery 表指定的）。

`car_dash_flat` 的 shader 是 **`car_rr3/car_interior.vsh` + `car_interior.fsh`**，
和车身的 `car.vsh`/`car.fsh` 是两个不同的 shader。**原厂已经在车身件上用过内饰 shader。**

**真正卡人的不是材质，是 UV**（LFA 同一台车）：

```
内饰（平铺）  LOD_A_INT_INTERIOR_mm_mat01   u[-54.2, 41.2]  v[-52.0, 54.8]
              LOD_A_INT_DOOR_LEFT_mm_mat03  u[-29.7, 51.1]  v[-29.2, 16.2]
车身（图集）  LOD_A_BODY_mm_ext             u[ 0.162, 4.264] v[-2.99, 0.996]
              LOD_A_DOOR_LEFT_mm_ext        u[ 0.836, 2.674] v[-0.72, 0.174]
```

内饰 UV 能到 ±60 是因为靠 `REPEAT` 平铺，车身 UV 挤在 0..4 的图集里。
**要用平铺纹理就得在 Blender 里自己把 UV 展开成平铺**，插件帮不上。

**第二个卡点**：部件名必须进 `liveryStringTable`：

```
LOD_A_BODY_mm_mat00      part_slot = None   ← 表里没有，引擎解析不出材质
LOD_A_INT_BODY_mm_mat00  part_slot = 282    ← 有
```

全表 2,068 个名字里带 `_mm_mat0x` 的 **70 个清一色是 `LOD_A_INT_*` / `LOD_B_INT_*`**，
车身名一个都没有。但贴图那半边是通的：`texture_slot_for_tag("mat00")` 先试 `ext_mat00`
（没有）再试 `int_mat00` → **槽 13** → 默认表给 `common/carbon_fibre_dark_grey_mat00`。

**平铺贴图本来就该小**：`carbon_fibre_black_mat00` 128×128、`aluminium_foil_mat07` 128×128、
`speaker_mesh_mat05` 64×64。原厂"碳纤用打包低清图"不是性能妥协，是**平铺本来就该用小图**。
这也说明原厂优化的是显存与下载体积，不是 GPU 算力——用户那句"老游戏不代表现在设备承受不住"
更准确的说法是"原厂本来就在省显存，平铺小图恰恰更省"。

### 11.4 `common/` 的依赖问题：只需要引用计数

**不存在撞名风险**，因为文件名就是身份（`common/car_windows_s2_lemans.dxt.dds.z`）。
游戏只认 livery 表里写的那条路径字符串。真正要管的是"谁还依赖这个文件"：

```
装 mod A → common/car_windows_s2_lemans 引用 1 次
装 mod B → 也引用它，引用 2 次
卸 mod A → 引用 1 次，文件留着
卸 mod B → 引用 0 次，此时才删
```

⇒ **`rrmod/deps.py` 一个模块 + 一个 JSON，不引入数据库、不引入版本求解器。**
理由：这个游戏的资源依赖只有一种形态（"谁引用了 common 下的哪个文件"），
没有版本区间、没有传递依赖（贴图不依赖别的贴图）。

```json
{
  "shared/car_windows_s2_lemans": {
    "owners": ["s2_lemans_body", "s2_lemans_interior"],
    "files": ["/vehicles/common/car_windows_s2_lemans.dxt.dds.z"],
    "source": "s2_lemans_pack@1.0",
    "shipped": false
  }
}
```

`shipped: true` = 游戏自带的（`car_windows_04` 这些），**永远不删、也不算依赖**。
这就是用户说的"和游戏自带的区分开来"——**靠表里有没有记录，不是靠命名前缀**。

### 11.5 `common/` 记账必须补四行，而且是分块插入

`asset_list_vehicle_common.txt`（1,192 行 / 298 个 stem）的结构是**四个连续家族块**，
每块 298 行、块内按 stem 排序：

```
[   0..297]  atc.dds    ← 磁盘上没有
[ 298..595]  dxt.dds    ← 磁盘上有
[ 596..893]  etc.dds    ← 磁盘上没有
[ 894..1191] ptc.pvr    ← 磁盘上没有
```

**加一个新文件必须补 4 行**（三行是给别的 GPU 变体的，文件不在这个包里），
而且每行要插进**对应家族块**里保持块内排序——不是追加到文件末尾。
这一点必须写进工具，不能靠人记。

注册表那边简单：只加 1 行（`/vehicles/common/xxx.dxt.dds.z`）。

### 11.6 自定义材质的部件命名规则

```
LOD_<字母>_<部件>_mm_<tag>
     ↑         ↑         ↑
   必填     自由起名   决定材质与贴图
```

**硬约束：`LOD_<字母>_` 前缀必须对。** 扫了 a/b/c 三个 LOD 共 **73,242 个网格**，
`LOD_A_` 出现在 `_a.m3g` 里、`LOD_B_` 在 `_b.m3g` 里……**0 个例外**。
这个前缀是引擎按 LOD 分组剔除的依据。

**`_mm_` 右侧的 tag 决定两件事，而且是分别查表**：材质查整个网格名，贴图查 tag
（`ext_<tag>` 优先，没有就 `int_<tag>`，再没有就裸名）。

**左边半边必须整个进 `liveryStringTable`**，否则 `part_slot()` 返回 `None`。

两种情况：

- **情况 A：复用现成 tag**（`ext` / `misc` / `chassis` / `badges`…）→ **零记账**，
  直接在 livery 表里给那个 part_slot 指定新材质槽。但材质槽也只能是表里已有的名字。
- **情况 B：要新 tag**（用平铺贴图必须走这条）→ 三件事：
  1. 追加**部件名**（新槽 2068）
  2. 追加 **tag 名** `ext_<你的tag>` 或 `int_<你的tag>`（新槽 2069）—— 这步容易漏
  3. 车 livery 表里把 2068 → 材质槽、2069 → 图集路径

**长度上限 57 字符**（最长是 `LOD_A_TAILLIGHT_LENS_REARBUMPER_BROKEN_A_RIGHT_mm_windows`）。
表里**没有重复名、没有大小写碰撞**，但有 2 个以 `_mm_` 结尾的空 tag
（`LOD_A_INT_STEERING_WHEEL_mm_`、`LOD_A_INT_INTERIOR_mm_`）——合法但别学。

推荐命名：`LOD_A_BODY_mm_carbon`、`LOD_A_HOOD_mm_carbon_twill`（不同纹理不同 tag）。

### 11.7 顺带查清的两件事

- **asset list 全是 4 列**（`路径\tmd5\tpacked\traw`），1,236 个文件 / 114,307 行，
  **0 条路径出现在两本账里**（映射唯一）。所以 `owner_of()` 是**函数，不是启发式**。
- **排序状态不一致**：931 本账未排序、305 本已排序。`asset_list_vehicle_data.txt` 已排序
  （`DataList.insert` 用 `bisect` 是对的）；`asset_list_vehicle_common.txt` 与
  `asset_list_vehicle_<car>.txt` 未排序但**内部有分块结构**（按家族 / 按文件类型）。
  ⇒ 工具不能统一用"排序后插"，要按每本账自己的规矩插。
