# 真实赛车3 逆向报告：载入 / 拼装 / 动画 / 着色器 + 资源校验

> 目标 .so：`lib/arm64-v8a/libRealRacing3.so`（33 112 064 B，ELF aarch64，9 个 program header）
> 反编译库：`re/lib/libRealRacing3.so`（与设备 base.apk 内同一份，APK md5 `e5f21b6f…`）
> 全部地址为 **Ghidra 地址**。⚠ **本工程 imageBase = 0x00100000**，故
> **Ghidra 地址 = 文件 vaddr + 0x100000**（文件 0x1CD13xx ↔ Ghidra 0x1DD13xx）。
> 需要文件偏移时一律减 0x100000；需要 vaddr 时同样减（第一段 `off == va`）。

---

## 0. 结论速查

| 逻辑 | 入口函数（Ghidra） | 关键数据 |
|---|---|---|
| 资源清单/校验 | `FUN_01dd1440` LoadCacheList → `FUN_01dd3a54` LoadAssetList → `FUN_01dd5770` StartListDownload → `FUN_01dd64b4` SaveCacheList | `.depot/asset_list_base.txtCache.txt`（注册表）、`apk/res/asset_list_*.txt`（清单） |
| 车辆载入 | `FUN_0166b26c`（外观应用入口）→ `FUN_01661060`（整车装配）→ `FUN_0165e64c`（模型文件集） | `vehicles/<车>/…`、`vehicles/wheels/<轮圈>` |
| 拼装 | `FUN_0165e64c` 写 16 槽位表 + `FUN_00d8f9a4` 按名字找 mesh group | CarDesc `+0x19c` = mesh group 名 |
| 动画 | `FUN_015ceaf4` → `FUN_015dc524`（动画条目解析）、`driver/driver.banim`、`_wing.banim` | `_animations.xml` 的 `banim=` / `start=` 属性 |
| 着色器 | `FUN_00df79dc` bindShaderOnly → `FUN_012cbb0c`（源码装载）→ `FUN_00c7d8fc`（GL 链接） | 材质 id 表、`.xsh`（如 `Shaders_rr4/pbr_utility.xsh`） |

---

## 1. 资源载入与校验（Cloudcell AssetManager）

模块整体位于 Ghidra `0x1DD13xx–0x1DDDC97`（文件 `0x1CD13xx–0x1CDDC97`），源码路径泄漏：
`E:\dev\builds\r3_update_a\source\src\Cloudcell\CloudcellApi\AssetManager.cpp`。

### 1.1 注册表 `LoadCacheList` (`FUN_01dd1440`, 1976 B)

```
if (this->loaded_at_0xe0) return;           // 一次性守卫
path = RootDir()/*vtable +0x130*/ + "/asset_list_base.txtCache.txt"
f = fopen(path, "rt")
如果读不到 f → 弹 Game Error / Game Load / Cached Asset File Loading Error
读 u32 magic  → 必须 == 0xa4f6f39d
读 u32 ver    → 必须 == 4                 // 否则 log "Incorrect Asset cache version, or file is corrupt!"
读第一行      → 与 FUN_01db9204(this->…+0x38 …) 生成的串比 len + memcmp
              不等 → *(u8*)(this+0xe1) = 1   // “缓存头版本标记失配”
循环：
  fscanf("%[^\t]\t%n")   → 路径（到 TAB）
  fscanf("%[^\n]\n%n")   → md5（到行尾）
  要求 行尾偏移 > 0x1e（即该行至少 31 字节）
  若 (verify_mode & 1)：先问虚表 +0x138，返回 0 则置 bVar4=true 并跳过此条
  map.insert(路径, md5)   // std::map，节点 0x70 B，路径存在 node+7
  this->count_0x35++
```

**注册表 = 纯文本**：`u32 magic | u32 ver | 一行版本标记 | 每行 "路径\tmd5"`。
实测文件头 13 字节 = `9d f3 f6 a4 | 04 00 00 00 | "7469" \n`，其后 47 090 行。
**没有任何签名/HMAC/服务端参与**。

### 1.2 清单 `LoadAssetList` (`FUN_01dd3a54`, 4688 B)

签名：`void FUN_01dd3a54(int *ret, long *this, char *listName, ulong p4, ulong p5, uint p6)`

返回结构（`ret`，AssetManager 侧存到 `this+0x144`）：

| 偏移 | 内容 |
|---|---|
| +0 | int 条目数（`local_384`） |
| +8 | long 全部条目「打包大小 + 8」之和（`local_398`） |
| +24 | long 全部条目「原始大小或打包大小」之和（`local_390`） |
| +32 | long **待下载字节**（`local_380`，只在命中下载分支累加） |
| +40 | byte 空间不足标志 |

逐行解析：

```
fscanf(f, "%511[^\t]\t%n%63[^\n]\n%n", path, &pathEnd, rest, &lineEnd)
条件：pathEnd > 0 && lineEnd > 0x1e
strtok(rest, "\t")[0] = md5            // 存 local_328
atoi(strtok rest "\t")[1] = 打包大小    // local_3a8 = 该值 + 8（.ast 包头）
atoi(strtok rest "\t")[2] = 原始大小    // local_3a0
```

判定（核心）：

```
node = registry.find(path)                     // FUN_01de0ee8
if (node == end) {
    // 注册表里没有这个文件
    if ((p6 & 1) == 0) goto 计入下载;           // ← 直接算“要下载”
    else {   // 只读模式：只统计“注册表里多出来的/残留的”
        if (FileExists(root + "/" + path))  log "Untracked asset file in cache: %s"  → 待删列表
        if (FileExists(root + "/" + path + ".ast")) log "Found temp asset file in cache: %s" → 待删列表
    }
} else {
    if (listName == this->currentListName) {    // 同一条清单
        if (md5 不同) node->needDownload_0xd = 1;
    } else {
        if (node->needDownload_0xd) 跳过此条（不计数）;
    }
}

计入下载（LAB_01dd43dc，每条都走）:
    total_packed  += 打包大小 + 8
    count         += 1
    total_orig    += 原始大小 ? 原始大小 : 打包大小
    if (注册表缺项 || md5 不等) {
        // 扣掉“本地已存在的 .ast 分片”能抵的字节
        realPath = vtable+0x138(path)
        if (realPath 以 RootDir 开头) 已有 = FS->GetFileSize(realPath)
        原始大小 -= 已有
        downloadBytes += 该条
        构造 0x38 字节下载队列项压入 this+0x180…0x190
    }
```

循环后：`fclose` → 清空「上一次清单名」状态 → 若清单名与 `this+0x221`（SSO 字符串）相等则置 `this+0x39 = 1`；
再检查磁盘剩余空间，不足则打印 `CC: AssetManager::LoadAssetList() : Warning:  Not enough space for downloads` 并清空下载队列。

**结论（重要）**：引擎对每一条资产只做一个比较 ——
**清单里写的 md5** vs **注册表里记的 md5**，两者都是本地文件，服务端不参与。
（`Utility::MD5HashString not is implemented in Android` —— Android 上连 md5 计算函数都没实现，
说明它从不现场算文件 md5，只信注册表。）

### 1.3 `StartListDownload` (`FUN_01dd5770`, 3396 B)

```
log "CC: AssetManager::StartListDownload() : Downloading %s "
清空 this+0x31/0x2b/0x2e/0x15c/0x244…
ret = LoadAssetList(this, listName, p4=0, p5=1, p6=0)
this+0x144 = ret.count; this+0x148 = ret.totalBytes; this+0x14c = ret.?; this+0x150 = ret.origBytes
log "nTotalDownloadBytes = %li, nDownloadedBytes = %li"
关闭缓存文件（"m_fpCache is still open? This shouldn't happen - PLEASE FIX!"）

if (this->loadOnly_0x2b0 == 0) {
    if (*(int*)(this+0x28c) == this->ret_count_0x144)
        → "*** CC_AssetManager_Class::StartListDownload() : Asset download skipped - all files up to date!"
    else
        → SaveCacheList(this, 1); 重试次数 = 3（某字符串非空时 20）; 进入下载流程 → 停服 403 → 8 次后 "ASSET DOWNLOAD ERROR!"
}
```

**未解点（唯一剩下的）**：`this+0x28c` 这个 int 是谁写的。它和「本清单条目数」相等就判定“全部最新”，
看起来更像「已确认条目计数」而不是「待下载字节数」。要彻底钉死，需对 `*(int*)(this+0x28c) =` 做一次
写侧 xref（`storage` 型引用）。**但从外部行为看，下载与否完全由 1.2 的逐条 md5 比较决定，这一点已被实测反复验证。**

### 1.4 `SaveCacheList` (`FUN_01dd64b4`, 748 B)

`fopen("wt")` → 写 `magic | version | 版本行` → 按 map（std::map，键为路径，天然有序）逐行 `fprintf("%s\t%s\n")`
→ `fflush` → `fsync` → `fclose`；出错打 `SyncAndClose() : Error when syncing file to disk!`。

### 1.5 由此得到的「改文件不触发下载」规则

记 `L` = 含该文件的清单，`R` = 注册表。

1. **改任何资产内容** ⇒ 该文件 md5 变了 ⇒ 必须把 `L` 里这条的 md5 字段改成**新 md5**。
2. 同时把 `R` 里这条的 md5 改成同一个新值（否则 `R` 与 `L` 不等，照样下载）。
3. `L` 必须列出本地真实存在的路径（否则 `Untracked` 分支 + assetnotfound 重试）。
4. 新增条目同理：`L` 加行 + `R` 加行，两边 md5 一致。
5. **改 `L` 本身**会被 `res.zip` 每次启动解压覆盖 → 用已验证的招：`chmod 444` + 属主 `u0_a41`，
   `extractAssets` 里 `open(…O_TRUNC)` 得 EACCES，引擎保留我们的版本（日志里能看到 `open failed: EACCES`）。
6. `R` 里删条目是安全的（引擎不知道的旧文件会被当 `Untracked asset file in cache` 清掉）；
   `R` 里**加**条目也没问题，只要 `L` 里有对应且 md5 一致。
7. 不要动 `magic`/`version`/第一行；那只会让引擎把注册表判为失效（`this+0xe1 = 1`），
   但注意：**引擎依然照用已读入的条目**，所以即使第一行不匹配也不一定触发下载 —— 待实测确认。

---

## 2. 车辆载入

### 2.1 数据链

| 文件 | 读者 |
|---|---|
| `cardesc.list.nct` | `FUN_00d5b3c0` |
| `carappearances.appearances.nct` | `FUN_00d5925c` (`CarDataManager::loadCarAppearanceDescs`) |
| `appearances.link.nct` | `FUN_00d5e304` |
| 每车 `.appearances.nct` / `.suspension.nct` / `.suspensiondata.nct` | `FUN_00d58be4`（路径构造器） |
| `suspensionbehaviour.suspensiondata.nct` | `FUN_00d5acb0` (`loadSuspensionData unable to load suspension data file: '%s'`) |
| `cardamagethresholds.damage.nct` | `FUN_00d5a75c` (`loadCarDamageThresholds`) |
| `vehicles/data/carrepairs.repairs.nct` / `carupgrade.upgrades.nct` / `carparts.parts.nct` | `FUN_011b0ca8` / `FUN_011b1d14` |
| `vehicles/data/DriverSelection.dat.nct` | `FUN_00b8b8ac` |

悬架失败提示里有一句很关键：`Failed to match suspension data for car: %d. Does the whitelist need to be updated?`
—— 新车 id 在 `suspensiondata` 里没有记录就是走这里（旧文档的 `fault addr 0x28` 空指针就在这条链上）。

### 2.2 外观应用入口 `FUN_0166b26c`（CarAppearance.cpp:3336，1128 B）

```
group = FindMeshGroupByName(*(CarDesc + 0x19c))       // FUN_00d8f9a4
if (!group) {
    log "Couldn't find the mesh group for %s. This could mean there is a naming conflict
         between the car data and the m3g assets. Otherwise, try downloading all cars."
    log "[CarAppearance] Failed to find mesh group matching car appearance"
    return;                                          // ← 改错 mesh group 名就是这个后果
}
state = BuildAppearanceState(*param_2)                // FUN_00d9c4fc
if (param_4) 从上一层状态继承：+2/+8 两个串、+0x1a、+0x22 …
ok = ApplyAppearance(group, state)                    // FUN_00d8d39c
if (!ok) { Fallback(group); retry; }                  // FUN_00d8cc88

if (未变 && 缓存键相同 && state 相同) { 增量刷新 FUN_01660634 / FUN_01664180(param_1+0x30f0) }
else {
    保存状态 → FUN_016624d8(param_1)   // 释放旧资源
    → FUN_01661060(param_1, appearanceFlags, skipLoad)   // 整车装配
    → FUN_016644bc(param_1); FUN_01667834(param_1, 0); *(param_1+0x30e8)=1
}
```

缓存键 = `(CarDesc*, group*, appearanceFlags & 0xfffc06ff, LOD 列表指针, state)` ——
其中 `& 0xfffc06ff` 说明 **bit 9..17 的某些位不参与比较**（这几位的改动不会触发重载）。

### 2.3 整车装配 `FUN_01661060`（3908 B）

签名 `void FUN_01661060(long this, uint appearanceFlags, uint skipLoad)`。
开头 `this->dirty_0x30e8 = 0; this->appearanceFlags_0x49e0 = appearanceFlags;`
含 `"lemans"` 子串特判（memchr 找 `0x6c`，比较 `0x616d656c`/`0x736e`）和 `cosf` 调用。

装配顺序（按字符串与调用点）：

```
1) 车身模型        FUN_0165e64c(this, CarDesc, appearanceFlags, this+0x4950, skipLoad, this+0x30f0)
2) 阴影/环境       "<carDir>_sha.pvr"、"<carDir>_ext_shadows_high.pvr.bin"、"_self_shadows.pvr.bin"
3) 悬挂/贴地点     "<carDir>.points"       → FUN_01699a4c(this+0x33b0, …)
4) 内饰贴地点      "<carDir>_int.points"
5) 仪表盘平面      "<carDir>.dashplanes"
6) 车手            构造 "driver/driver.banim"（0x004B4907，含 CONCAT31(0x6d696e,…) = "…min…"）
                   + "vehicles/common/driver.pvr"
7) FUN_0165d174(this+0x18)   // 挂到渲染树
8) FUN_012ce18c / FUN_012ce2f4 / FUN_012cf598(…,1,0xffffffff,0,0) ×3  // m3g 场景/动画装载
9) FUN_01560c48(0x1bf, …)    // tweakable（tweakables.cpp:1835 "Uninitialised tweakable usage attempted"）
```

### 2.4 模型文件集 `FUN_0165e64c`（CarAppearance.cpp:798/893/977，8168 B）

**唯一的硬编码目录**：`carDir = "vehicles/" + CarDesc->name`（`FUN_016de5dc(&s, "vehicles/", name+8)`）。

然后写一张 **16 槽位表** `param_6`（stride `0x10`，槽 0x00…0x130），每槽 `+0x8` 是状态：
**0 = 尚未处理 / 2 = 缺失（走 `FUN_014fb9b8+FUN_014fc918` 或 `FUN_014fb9c4+FUN_014fcc10` 注册占位）**。

| 槽位 | 文件 | 条件 |
|---|---|---|
| 0x00… 按 LOD 列表 | `<carDir>_<字母>.m3g`，字母 = `'a' + index` | LOD 索引来自 `*(uint**)(this+0x52d0)` |
| 0x00… 第二组 LOD | `<carDir>_<字母>.m3g` | 索引来自全局 `*(u32*)(lVar29+0x110)` / `*(long*)(lVar29+0x118)` |
| 0xb0…0x120（8 个） | `driver/driver_lod_<a..h>` + 后缀 | 注意：**这 8 槽与 LOD 槽共用同一张表** |
| 0x90 | `<carDir>_shared.m3g` | 总是 |
| 0xa0 | `<carDir>_frontend.m3g` | `appearanceFlags >> 10 & 1` |
| 0x130 | `vehicles/wheels/<轮圈名>` | `this+0x499c >= 1`（否则记缺失） |

装载统一走 `FUN_00d55fa4(...)`，成功后 `FUN_0165de7c(slot, path, skipLoad)` 挂到槽上。
失败时若 `FUN_015773b0(PTR_DAT_0206df38, 1)` 为真即
`log(2, "CarAppearance.cpp:798", "Car '%s' is missing LOD %c.", name, index + 0x41)`。

> 这解释了旧文档里「LOD 整批换档 a/e/h/g → c/d/e/f」：
> 字母完全由**索引**决定（`'a'+i`），换档 = 换 `this+0x52d0` 里那组索引。

### 2.5 路径解析 `FUN_00d55fa4`（1676 B）

这是所有资产的统一入口：

```
扫描名字里是否含 ".pvr"（memcmp 0x7276702e）
   命中 → FUN_012cf210(名去扩展) → FUN_013bf4dc(…, roots, 1)   // 走 PVR 纹理专用通道
   未命中/失败 → fallback：
      if (this+0x160 == this+0x168) return 0;        // 没有任何搜索根
      取 name 的目录前缀（rfind '/'）
      依次对 this+0x160..+0x168 里的每个根尝试 FUN_013bf4dc(...)
```

`this+0x160/+0x168` 就是**搜索根向量**（对应实测的三层：`.depot` → `apk/res` → `doc`）。
所以“换目录 / 加资源根”只需改这个向量，不需要改代码逻辑。

---

## 3. 拼装（mesh group 绑定）

拼装 = m3g 场景里的 **mesh group** 与 CarDesc 里记录的**名字**对上号：

* CarDesc `+0x19c`（std::string）就是 mesh group 名；`FUN_00d8f9a4(场景, 名字+8)` 查找。
* 找不到 → 上面那两条日志 → 整车外观不生效（旧文档“底盘抬高/尾翼消失”的表现来源之一）。
* 材质/外观槽位在 CarDesc 里以 tag 名索引（`<类>_mm_<tag>`，tag 表在 `.data.rel.ro` +
  `R_AARCH64_RELATIVE` 重定位，见 `analysis/reloc_scan.py`）。
* 外观状态结构（`FUN_00d9c4fc` 构造）里 `+2`/`+8` 是两段变长数据（涂装/彩绘），
  `+0x1a`、`+0x22` 是标量；比较用 `FUN_00d9ca24`。
* 装配完成后 `FUN_016644bc` / `FUN_01667834` 做增量刷新与包围盒/阴影更新。

---

## 4. 动画

### 4.1 入口链

`FUN_015ceaf4`（清单/文件驱动）→ `FUN_015dc524`（单条目解析，1528 B）。

`FUN_015dc524` 的实质是**按键名取值**：

```
local_88 = FUN_0141a5fc(entry, &DAT_004ec217)   // 按 key 取属性
pcVar5   = FUN_01419bf4(&local_88)              // 转成 C 字符串
拷进 out[4..6]（std::string 三元组）
… 重复三组，键分别是 "banim"、"start" 等（字符串表 0x4A2CD4 "banim"、0x5944CE "start"）
```

即 `_animations.xml` 里
`<animation name="…" banim="vehicles/<车>/_wing.banim" start="…"/>` 这类条目：
**banim 文件路径与起始时刻都写在 xml 里**，引擎只按名字取。
所以给自定义车加动画 = 改 `<车>_animations.xml` + 放 banim 文件（同样是清单+注册表两边登记）。

### 4.2 banim 运行时

* `FUN_00d54898`（916 B）专管 `_wing.banim`；
* `FUN_01661060` 里对 `driver/driver.banim` + `vehicles/common/driver.pvr` 一起构造；
* `.points` / `_int.points` / `.dashplanes` 与 banim 同批装载（`FUN_01699a4c`）。
* RTTI 里能看到 `m3g::AnimationController`、`m3g::AnimationTrack`、`m3g::AnimationSequence`
  的实现类符号（`0x00515249`、`0x00515265`），说明**车身动画最终落到 m3g 的动画轨**（`_animations.xml` 只是把名字映射到轨）。
* `Banim "%s" has no objects in it. Skipping this banim so that the game doesn't crash!.`（`0x003F6EAB`）
  —— 空 banim 会被跳过而不是崩。

---

## 5. 着色器

### 5.1 材质 → 着色器绑定 `FUN_00df79dc`（CommonMaterials.cpp:31/36，344 B）

```
mats = this[0] .. this[1]                        // 材质表，元素步长 8
if (id >= count)  log "CommonMaterials::bindShaderOnly Invalid material id: %d"
mat = mats[id]
if (!mat || !*mat) log "CommonMaterials::bindShaderOnly Missing material for id: %d"   // ← 黑材质的日志锚点
app = *(long**)(mat->… + 0x30)                   // m3g Appearance / ShaderAppearance
sh  = *app
if (!sh) { MakeShader(renderer, mat); sh = *app; }
pass = FUN_012dd168(app, &state)
(*(vtbl+0x588))(renderer, sh, pass)              // 绑定（26 处调用点）
```

**关键**：`material id` → 材质表 → m3g Appearance → ShaderAppearance。
自定义车的材质若在 m3g 里没有对应 Appearance，就会落在
`Missing material for id: %d`（阴影发暗/纯黑），而不是崩溃。

### 5.2 着色器源码装载 `FUN_012cbb0c`（mtShaderManager.cpp:234/239，1344 B）

```
key = FUN_012cb9c8(vsDesc, fsDesc)               // 由 (顶点源, 片元源) 生成缓存键
node = shaderCache.find(key)
if (miss) {
    entry = FUN_01576dec(g_pool, this+8)
    entry->vs = param_2; entry->fs = param_3
    shaderCache.insert(key, entry)
    if (root != 0) Log(...)                       // 调试日志
    load 顶点源 → 失败 "Failed to load vertex shader file source: %s"   (:234)
    load 片元源 → 失败 "Failed to load fragment shader file source: %s" (:239)
}
```

即**运行时从资产文件读源码字符串**，不是预编译二进制。着色器库入口是 `.xsh`
（`Shaders_rr4/pbr_utility.xsh`，见 `FUN_0154b718`）—— 自定义车想换 shader，就是换 `.xsh` 里的一条。

### 5.3 GL 程序创建/链接 `FUN_00c7d8fc`（mercShader_GL.cpp，1800 B）

调用点由 `FUN_00c7ce40` 进入，日志十分完备（改模组时全靠这几句定位）：

* `glCreateProgram failed!`
* `Shader failed to link!` / `Shader linked with warnings.`
* `Program info log:\n%s\n` / `No program info log from the driver :(`
* `Shader uses too many vertex attributes!`
* `An attribute was used that we don't have a name for!`
* 上层 `FUN_00c7ce40`：`Failed to set shader attribute IDs in sequential order!`

**attribute 必须按顺序编号**（`Failed to set shader attribute IDs in sequential order!`）——
自定义 m3g 若增删顶点属性，编号顺序错了就在这里炸；改 `.xsh` 时要保持 attribute 声明顺序。

---

## 6. 「添加自定义车不触发校验/下载」的落地步骤

1. `vehicles/<新车>/…` 全部文件放进 `.depot`（属主 `u0_a41`）。
2. 写 `apk/res/asset_list_vehicle_<新车>.txt`：本车所有文件的 `路径 \t md5 \t 打包大小 \t 原始大小`。
   —— 打包大小填**原始大小**也能过（引擎只在下载时才用这个数字算总字节）。
3. 把同样的 `路径 \t md5` 追加进 `.depot/asset_list_base.txtCache.txt`（保持前 13 字节不动）。
4. 如果新车的清单名与已存在的清单不同，还要让**启动流程知道该拉这份清单**
   （`vehicle_common` / `vehicle_data` 之类的父清单里加入口，或复用一辆现有车的清单名）。
5. 需要新 physics 记录时改 `suspensiondata` / `cardamagethresholds`，**同步改它们所在清单的 md5 字段 + 注册表**。
6. 车 id 注册：`cardesc.list.nct`、`carappearances.appearances.nct`（这两个改内容不触发校验，但也要同步清单 md5）。

> 核心不变量只有一句：**对每一条资产，(清单 md5) == (注册表 md5) 且文件存在 ⇒ 永不下载。**

### 6.1 实测 A/B（2026-10-25，MuMu / u0_a41）

拿 `asset_list_vehicle_2021_porsche_911_gt3.txt` 里的 `2021_porsche_911_gt3_b.m3g`
（清单记录的 md5 `ce00d760…` 是**打包形态**，磁盘文件真实 md5 `c3455156…`，两者本来就不同）
做对照，只动「清单 md5」与「注册表 md5」这两个字段：

| 实验 | 清单 md5 | 注册表 md5 | 结果 |
|---|---|---|---|
| A：两边同步成新值 | `e0387452…` | `e0387452…` | `nTotalDownloadBytes = 8817368, nDownloadedBytes = 8817368` → `all files up to date!`，**0 次 CDN**，57 条清单全跳过 |
| B：只改清单、注册表留旧值 | `ce00d760…`（旧） | `e0387452…`（新） | `nDownloadedBytes = 7840404`（= 8817368 − **976956**，即该条目的**打包大小**）→ `bytes=1044682-1533163` 分段请求 → `httpCode : 403` → `ASSET DOWNLOAD ERROR` ×38 → 再启动时 `StartList=114` |

结论：
1. **判定只比这两个文本字段**；改了文件内容（A 里 `_b.m3g` 已被翻字节）完全不影响判定。
2. 待下载字节按 **打包大小**（清单第 3 列）累计，不是原始大小。
3. 失败时 URL = `https://firemonkeys.akamaized.net:443//rr3/live/<清单名>/<清单文件自身 md5>.bin`
   —— 引擎是拿「本地清单内容的 md5」去要对应版本，所以停服后必然 403，重试 8 次（每轮 3~20 次）。
4. 实验后已把 `_b.m3g`、两条车清单、注册表全部还原（注册表 md5 回到 `b4f9b38804b1a323e0623882d26c1120`），
   复测：57 条清单、`DLERR=0`、`EACCES=0`。

工具：`analysis/asset_md5_sync.py`（改文件后一条命令同步两边 md5，见文件头注释）。

---

## 7. 待办 / 未解

1. `*(int*)(this+0x28c)`（StartListDownload 的“全部最新”判据）由谁写 —— 需要写侧 xref。
2. 注册表第一行（"7469"）与 `FUN_01db9204` 生成串的含义 / `this+0xe1` 置位后的确切行为。
3. `FUN_0165e64c` 第二组 LOD 索引来源（全局 `lVar29+0x110`）与第一组（`this+0x52d0`）的分工。
4. `.xsh` 文件格式（`FUN_0154b718`）。
5. 尾翼发暗：现在有了 `Missing material for id: %d` 这条锚点，抓 logcat 即可判定是材质缺失还是 UV。
