# `materials.bin` 格式（材质总库 + 着色器绑定表）

> 路径：`<depot>\materials\materials.bin`（**不在** `vehicles\data\` 下）
> 大小：135,065 B，**明文**，无加密无压缩。
> 状态：2026-10-27 完整解出，`used == total == 135065`，零剩余。

---

## 1. 顶层：扁平记录流

```
repeat until EOF:
    u32 key
    u32 len
    u8  value[len]     # ASCII，无 NUL 结尾
```

实测 **5887 条记录**、**56 种 key**。同一 key 会在文件里重复出现几千次——
所以这个文件**不是**「一条记录一个材质」，而是一张**扁平的属性表**，
靠 key 的重复模式切块。

```python
import struct
recs = []
i = 0
while i + 8 <= len(d):
    k, L = struct.unpack_from('<II', d, i)
    if L > 8192 or i + 8 + L > len(d):
        break
    recs.append((k, d[i+8:i+8+L]))
    i += 8 + L
```

---

## 2. 第一张表：297 个「材质状态」块

按 key `1738848819` 切块（这个 key 在文件里正好出现 **297** 次，且**每个材质块的第一条记录就是它**）：

```
[1738848819 双面?] [2073958868 ?] [500458687 队列] [1290375661 优先级]
[4050242743 ?] [4275232 ?] [1875587694 实例名] [1424680013 基模板名]
[3133585612 application] [2002297458 cull] [3799239167 blend]
[1649669188 primitive] [711227395 stencil] [3519276840 RGBA]
[546467408 shader flags]   ← 可选，228 块有、68 块没有
```

块长 **15 条**（228 个）或 **14 条**（68 个，缺 flags）。14 条的块是 `ui_image`、
`debug_*` 这类不需要 shader flags 的。

### 2.1 字段语义

| key | 字段 | 取值域 |
|---|---|---|
| `1738848819` | 双面渲染？ | `False` 245 / `True` 52 |
| `2073958868` | ?（疑 alpha test） | `False` 256 / `True` 41 |
| `500458687` | 渲染队列 | `1` 260 / `3` 17 / `2` 17 / `10` 2 / `4` 1 |
| `1290375661` | 排序优先级 | `1` 268 / `3` 15 / `2` 9 / `-1` 4 / `5` 1 |
| `4050242743` | ? | `False` 290 / `True` 7 |
| `4275232` | ? | `False` 282 / `True` 15 |
| **`1875587694`** | **实例名（297 个，全不重复）** | 如 `car_paint_metallic_white` |
| **`1424680013`** | **基/模板名（137 个，可重复）** | 如 `car_paint_gloss` |
| **`3133585612`** | **application（着色器程序族）** | 见 §2.2 |
| `2002297458` | cull mode | `cmDefault` 166 / `cmAlphaNoZWrite` 40 / … |
| `3799239167` | blend mode | `blDefault` 296 / 缺 1 |
| `1649669188` | primitive | `pmDefault` 223 / `pmNoCull` 72 / `pmCullBoth` 1 |
| `711227395` | stencil | `stCarWrite` 112 / `stDefault` 93 / … |
| `3519276840` | RGBA | 如 `100, 200, 250, 255` |
| `546467408` | **shader flags（逗号分隔）** | `FOG, SPEC_TEXTURE, SPEC_MASK_TEXTURE, REF_TEXTURE_MASK` … |

### 2.2 ★ 关键：实例名 ≠ 模板名

这是这个文件最容易看错的地方。**297 个实例名全部唯一，但只有 137 个模板名。**
一个模板可以派生多个实例，靠 `application` + flags 区分：

```
实例名                     模板名                  application
car_paint_gloss        -> car_paint_gloss      appCarPaint        ← 真车漆
car_alpha              -> car_paint_gloss      appDefault         ← UI 用透明材质！
car_gloss              -> car_paint_gloss      appCarPaint
car_bumper_paint_gloss -> car_paint_gloss      appCarBumperPaint
car_bumper_gloss       -> car_paint_gloss      appCarBumperPaint
```

⇒ **`car_paint_gloss` 这个名字在文件里有 5 条记录，第一条（`car_alpha`）根本不是车漆。**
以前把「尾翼拿到 `car_paint_gloss`」当成单一材质来解读是错的——必须连 application 一起看。

`application` 全表分布（297 块）：

`appDefault` 132、`appCarPaint` 41、`appCarBumperPaint` 41、`appDepthSort` 18、
`appOverlays` 10、`appCarWheels` 9、`appShadows` 8、`appTree` 6、`appCarDash` 6、
`appBuildingalpha` 4、`appFence` 3、`appProjectedLights` 3、`appSkids` 3、`appSkyBack` 2、
`appCarMirror` 2，其余各 1（`appSkyFront`/`appDepthWriteOnly`/`appCrowd`/`appTreeLines*`/
`appGhostCar`/`appGhostCarBrakeLights`/`appFlareBlocker`）。

### 2.3 真正的车漆族

`application = appCarPaint` + `cull = cmDefault` + `stencil = stCarWrite`：

| 实例名 | flags | 特征 |
|---|---|---|
| `car_paint_gloss` | `FOG, SPEC_TEXTURE, SPEC_MASK_TEXTURE, REF_TEXTURE_MASK` | 基础清漆 |
| `car_paint_matte` | 同上 | |
| `car_paint_matte_high` | `FOG, SPEC_TEXTURE, SPEC_MASK_TEXTURE` | 无 REF |
| `car_paint_gold` | 上 + `COLOURED_FRESNEL` | |
| `car_paint_chrome` | 同上 REF 版 | |
| `car_paint_carbon_fibre` | 同上 | |
| `car_paint_metallic_{white,warm,cool,red,blue,darkblue,purple,green,bloodred,bloodorange,orange,yellow}` | REF 版 | 标准金属漆 |
| `car_paint_metallic_{green_light,cool_light}` | **无 `REF_TEXTURE_MASK`** | 浅色变体 |
| `car_paint_pearl_blue` | `+COLOURED_FRESNEL` | |
| `car_paint_metallic_spec_{yellow,orange,red,white}` | **`+SPEC_FLAKES`** | 闪光漆（额外绑 `[2]vehicles/common/metallic_spec.pvr`） |
| `car_paint_candy_{pink,apple,tangerine,cherry,copper,lime,emerald,lemon,blue,violet,pearl}` | 多数 `+COLOURED_FRESNEL` | 糖果漆 |
| `car_matte` | 只有 `FOG, SPEC_TEXTURE` | **没有 SPEC_MASK** |

每个车漆都有一个 `car_bumper_paint_*` 孪生版本（`appCarBumperPaint`，保险杠用，flags 略有差异）。

---

## 3. 第二张表：186 条「着色器绑定」

紧跟在 297 个材质块之后（从记录 #4386 开始），是另一张表。结构是**变长分组**：

```
key 1799195616  <shader 名>          ← 组头，出现 186 次
key 4259867639  <xxx.vsh>            ← 顶点着色器文件
key 548181663   <xxx.fsh>            ← 像素着色器文件
key 1720193402  <uniform 赋值>       ← 0..n 条，多行字符串
key 950256928   <[n]贴图路径>        ← 0..n 条，多行字符串
```

### 3.1 这是本轮最有用的发现

**这张表就是「材质 → LUT 贴图」的官方映射**，正好对上 2026-10-26 的 RenderDoc 取证
（尾翼与车身用同一个 `car_rr3/car.vsh`+`car.fsh`，只差绑定的 LUT）：

| 贴图槽 | 含义 | 出现次数 |
|---|---|---|
| `[2]` | 法线图 / 特殊 mask | 38 |
| `[3]` | **fresnel LUT** | 96 |
| `[4]` | **specular LUT** | 96 |

`[3]`/`[4]` 是成对出现的，路径形如：

```
car_paint_gloss   → [3]vehicles/shaders/fresnel_gloss.pvr   [4]vehicles/shaders/spec_gloss.pvr
car_paint_matte   → [3]vehicles/shaders/fresnel_matte.pvr   [4]vehicles/shaders/spec_matte.pvr
car_flat          → [3]vehicles/shaders/fresnel_flat.pvr    [4]vehicles/shaders/spec_flat.pvr
car_paint_metallic_white → [3]fresnel_metallic.pvr          [4]spec_metallic_white.pvr
```

⇒ **`fresnel_flat.pvr`（全库唯一纯黑渐变）只有 `car_flat` 和 `car_flat_low` 两个材质会绑。**
这就是「尾翼发暗」的物证来源：拿到 `car_flat` ⇒ 绑 `fresnel_flat` ⇒ 菲涅尔项全黑。

### 3.2 uniform 也在这里

```
car_paint_metallic_white:
   mu_MaterialSpecularColour_Base = 110, 110, 110
   mu_MaterialSpecularPower_Base  = 8
   mu_MaterialSpecularColour_Top  = 255, 255, 255
   mu_MaterialSpecularPower_Top   = 1000.0
   s_cubeMap = s_carReflectionCubeMap

car_flat:
   mu_MaterialSpecularColour_Base = 0, 0, 0
   mu_MaterialSpecularPower_Base  = 1
   mu_MaterialSpecularColour_Top  = 0, 0, 0
   mu_MaterialSpecularPower_Top   = 1
   s_cubeMap = s_carReflectionCubeMapBlur
```

**全表只有 `car_flat` / `car_flat_low` 满足 `Colour_Base = 0,0,0` 且 `Power_Base = 1`**——
这与 RenderDoc 抓到的 `_child1 = 0,0,0 / 1` 逐字一致，是判定「拿到 car_flat」的指纹。

### 3.3 低模变体

大部分车漆有 `_low` 版本（`car_paint_gloss_low` 等），用 `car_rr3/car_low.vsh/.fsh`，
uniform 结构相同。`car_dash_*` 系列用 `car_rr3/car_interior.vsh/.fsh`，
`car_dash_*_low` 用 `car_interior_low`。

---

## 4. 这张表对「自定义材质」意味着什么

以前以为改材质只能从 70 个既有名字里挑，且必须靠 livery 表的 slot。
现在知道：

1. **材质名字来自 `liveryStringTable.bin.nct` 的 slot**（§见 `livery槽位表与材质名.md`），
   slot 只到 2067，所以能选的材质名就那 70 个 `car_*`。
2. 但**每个名字背后是「实例 → 模板 + application + flags + uniform + LUT」一整套**，
   全在这张 297 块的表里。
3. 想造**全新材质**（比如给尾翼一个自定义漆），理论上要：
   - 在 `liveryStringTable.bin.nct` 加名字（变长插入，slot 编号会顺延，风险高）
   - 在 `materials.bin` 加一个 15 条记录的块
   - 在 §3 的着色器绑定表加一组 VS/FS/uniform/贴图
   三处都要改，且 `liveryStringTable` 的 slot 顺延会破坏所有引用它的 liveries 文件。
   ⇒ **成本远高于「复用既有漆种」**，所以 §livery 文档里的做法（挑现成漆种）是对的。

---

## 5. 工具

`analysis/materials_bin.py`：

```
python analysis\materials_bin.py stats           # 记录数/块数/字段取值域
python analysis\materials_bin.py blocks          # 297 个材质块一览
python analysis\materials_bin.py show <名字>      # 单个材质的完整字段
python analysis\materials_bin.py shaders         # 186 条着色器绑定
python analysis\materials_bin.py shader <名字>    # 单个着色器的 VS/FS/uniform/贴图
python analysis\materials_bin.py flat            # 找出所有绑 fresnel_flat 的材质
```

---

## 6. 仍未解的问题

- **key 的哈希函数没破**。试过 FNV-1a / FNV-1 / djb2 / CRC32 对
  `mu_MaterialName`、`MaterialName`、`application`、`technique`、`shader` 等 40+ 候选名，
  无一命中 `0x54EAE44D` / `0x6FCB326E` / `0xBAC6B8CC` 等 key。
  （未试：CRC32C、xxhash、大小写变体、带前缀的完整路径名。）
  不影响使用——工具里用硬编码 key 表即可。
- `2073958868` / `4050242743` / `4275232` 三个 bool 字段的语义未定。
- `500458687` 与 `1290375661` 哪个是队列、哪个是优先级未定（两者都像排序参数）。
