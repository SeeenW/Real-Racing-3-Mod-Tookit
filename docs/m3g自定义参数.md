# RR3 `.m3g` 里的自定义参数（非 JSR-184 标准）

JSR-184 的 `Mesh` 只有 `vertexBuffer` / `submeshCount` / `indexBuffer` / `appearance`。
RR3 的引擎在这套结构里**塞了三块私有数据**，位置固定、长度固定（个别网格可变）。
下面每一条都是逐字节比对原厂文件 + 全库普查（3308 个网格、60 台车）得出的。

---

## 1. Mesh 载荷里的 81 字节块（kind = 7）

```
offset 0   : 8 字节 0
offset 8   : i32 kind              ; 5 / 6 / 7，7 表示带下面这块
offset 12  : 81 字节私有块         <-- 本节
offset 93  : i32 materialId        ; 0 基
offset 97  : cstr name
然后       : 50 字节块（见第 2 节）
然后       : i32 vertexBuffer, i32 submeshCount, submesh[]
```

kind = 5 时这块是 **48 字节**，kind = 6 时是 **56 字节**，kind = 7 时 **81 字节**。
LFA / Reventón 的整车网格几乎全是 kind 7（全库 3233 / 3308）。

### 81 字节内部布局（20 个 u32 视图）

| 偏移 | 类型 | 值 | 含义（已确认程度） |
|---|---|---|---|
| 0 | u32 | 0 | 保留 |
| 4 | u32 | 1 | 版本/标志，全库恒 1 |
| 8 | u32 | 0x00000100 | 分项标志位 |
| 12 | u32 | 0x00000100 | 分项标志位 |
| 16 | u32 | 0x00020000 | 分项标志位 |
| 20 | u32 | 0x00040000 | 分项标志位 |
| **24** | u32 | `0x0011_00xx` | **低位字节 = 部件描述符编号**，见下 |
| 28 | u32 | 0x00030000 | 分项标志位 |
| 32 | u32 | 0x00010000 | 分项标志位 |
| 36 | u32 | 0x06000000 | 分项标志位 |
| 40 | u32 | 0x11000000 | 分项标志位 |
| 44..59 | — | 0 | 保留 |
| 60 | f32 | **1.0** | 缩放/强度（全库恒 1.0） |
| 64 | u32 | 4 | 分项标志位 |
| 68 | u32 | 1 | 分项标志位 |
| 72 | u32 | `0x00000501` | 分项标志位 |
| 76 | u32 | 4 | 分项标志位 |

**唯一真正逐网格变化的是字节 26（= u32 偏移 24 的最低位字节）**，全库共 52 种不同取值。
它是个**部件描述符编号**，不是哈希：

- 同部件、同材质 = 同编号：`LOD_A_BODY_mm_ext` 在 LFA 与 Reventón 上都是 **17**；
  `LOD_A_BODY_mm_misc` 都是 **18**；`LOD_A_BODY_mm_badges` 都是 **20**。
- 左右成对递增：`BRAKES_LEFT` = 27 / `BRAKES_RIGHT` = 28；
  `HEADLIGHT_LENS_LEFT` = 36 / `_RIGHT` = 37；
  `TAILLIGHT_LENS_LEFT` = 35 / `_RIGHT` = 36。
- 编号按“车身→内装→灯具”分区段递增（17 起，LFA 用到 46，全库最大 56）。
- **主动空力件额外多一个标志：字节 17 = 1**（普通件是 0）。
  Reventón 的 `LOD_A_WING_REAR_mm_ext`、`LOD_A_WING_REAR_LEFT_mm_ext`、
  `LOD_A_WING_REAR_RIGHT_mm_ext` 都是 `byte17 = 1`，而 `_mm_misc` / `_mm_chassis` 是 0。

> 结论：这 81 字节是**部件描述符表**——引擎拿它把网格归类到“车身/车门/灯具/内装/空力件”等
> 渲染与逻辑分组。我们导出时必须**按名字从原厂模板照抄**，不能自己造。

---

## 2. Mesh 载荷里的 50 字节块（所有 kind 都有）

紧跟在 NUL 结尾的网格名之后：

```
01 00 00 00  00 00 00 00  00 00 00 00
80 00 00 80 3f  00 00 80 3f  00 00 80 3f
00 00 00 00 ... （12 字节 0）
00 01 01 ff ff ff ff ff ff 00
```

**全库 3308 个网格、1 个字节都不差**（`x3308` 同一种模式）。
里面三个 f32 都是 **1.0**（在偏移 13/17/21），其余是常量标志与 `0xFF` 填充。
→ 这是一个**固定默认值块**（三个 1.0 大概是“无缩放/无偏移”的默认），照抄即可。

---

## 3. 网格尾部块（只有主动空力件有）

在 `vertexBuffer / submeshCount / submesh[]` 之后：

```
u32 count
count × 14 字节:
    u32 time_ms      ; 关键帧时间
    u16 0x4000       ; 恒 16384
    u16 0
    u32 0
    f32 value        ; 每帧的形变量（米级小量）
```

实测：

| 车 | 网格 | count | 时间 | value |
|---|---|---|---|---|
| Reventón | `LOD_A_WING_REAR_mm_ext` | 9 | 166, 333, 500 … 1500 ms | 恒 −0.02910 |
| Reventón | `LOD_A_WING_REAR_LEFT/RIGHT_mm_ext` | 9 | 同上 | −0.0333 等 |
| P1 | `LOD_A_WING_REAR_mm_ext` | 10 | 500, 666 … 2000 ms | −0.0501 → −0.0132 |
| P1 | `LOD_A_WING_STRUT_REAR_mm_ext` | — | — | 只有 4 字节（空表） |

时间步长 166 ms ≈ 6 Hz，和 banim 的旋转曲线是两套独立数据。
**这块必须和字节 17 = 1 同时存在**：只设标志不写尾块 → 引擎越界读 → `fault addr 0xdead1005` 崩溃；
只写尾块不设标志 → 尾块被忽略。

---

## 4. VertexBuffer 里的自定义字段

标准 JSR-184 的 VertexBuffer 到这里就结束了，RR3 还有两个私有字段：

```
offset 12  : RGBA colorRGBA        ; 每顶点色的默认值，实测恒 ff ff ff ff
offset 16  : i32 positions
offset 20  : 3 × f32 positionBias
offset 32  : f32 positionScale     ; 定点缩放：LFA 0.0021973606 / Reventón 0.0022958945
offset 36  : i32 normals
offset 40  : i32 colors
offset 44  : i32 texcoordCount
offset 48+ : 每层 (i32 array, 3×f32 bias, f32 scale)
```

- **`positionScale` 是定点的分母**：位置数组是 float32，真值 = `raw × positionScale`。
  原厂从不用 `1.0`：它约等于「整车峰值坐标 / 1024」（LFA 0.0021973606199026108、Reventón 0.0022958945482969284、
  P1 0.0023481915704905987、F1 0.0019114369060844183，峰值都是 ±1023），同一文件所有网格共用一个值。
  写 `1.0`（直接存米制浮点）虽然几何等价，但引擎会因此换一条顶点处理路径：
  实机表现为**扫描线卡顿 + 高光丢失**（LFA v36/v37 对照，2026-10-24）。导出器已默认按原厂规则写
  （`raw = 米 / scale`，模板优先，否则 `峰值/1024`，见 `rr3_blender_addon/README.md`「导出 .m3g」）。
- 替换部件时仍要**让 scale 跟着部件一起走**：拿原厂 0.0022 的槽位塞米制坐标，部件会缩成 0.004 m 的“点”（我们踩过）。
  现在两边都是原厂定点，只要别手改成 `1.0` 就不会再撞上。
- UV 层的 `bias` 存的是 **`1 − bias_y`**（读取时反转），`scale` 恒 `0.001953125`（= 1/512），
  也就是说 **UV 原始值 = 纹理坐标 × 512**，而纹理坐标本身又是 **4×4 平铺**的（u∈[0,4), v∈[−3,1)）。
  换算链：`文件 int16 → ×(1/512) → 4×4 tile 空间 → /4 且 v 取 (1−v)/4 → Blender UV`。

---

## 5. 其他自定义参数（不在 m3g 里，但同一套“自定义”体系）

| 文件 | 自定义内容 |
|---|---|
| `asset_list_vehicle_<car>.txt` | `路径 \t md5 \t 压缩后大小 \t 原始大小`；**引擎只加载表里列出的文件** |
| `<id>_<car>.bin.nct` | `u32 71` + `u32 车辆 ID` + 名字/数值交替；性能、价格、`DeployWhenBraking` |
| `carappearances.appearances.nct` | 每车 **266 字节**外观块：轮毂样式 + 轮胎尺寸 + 悬架外观 |
| `suspensionbehaviour.suspensiondata.nct` | 每车 140 字节：`+22/+23` 前后轮胎直径（米）、`+43..45` 悬架行程/离地 |
| `liveries/<car>.liveries.bin.nct` | 材质槽 → 纹理路径（`.ptc.pvr.z`），**没有着色参数** |
| `.points` | `SPLINE_SPECULAR` = 车漆环境反射探针弧线（165 台车有，Reventón 没有） |
| `_wing.banim` + `_animations.xml` | 空力件动画；1 帧 = 33 ms |

---

## 6. 段校验和（之前记为“未破解”，现已确认）

每段末尾 4 字节 = **Adler-32**，覆盖范围 `u8 compression + i32 totalLength + i32 uncompressedLength + 数据`。

```
a = 1, b = 0
for byte in data: a = (a + byte) % 65521; b = (b + a) % 65521
checksum = (b << 16) | a
```

实测吻合：`2012_lexus_lfa_a.m3g` 两段 `0ad60c81` / `e3aa23d6`，
`driver_lod_a.m3g` 两段 `f9f10c0d` / `32d7f1a5`。
**游戏本身不校验**（改一个顶点浮点照样跑），但写正确值没有坏处。
