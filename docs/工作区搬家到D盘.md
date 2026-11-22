# 工作区已搬到 D:\rr3（2026-11-10）

## 一句话

工作区从 `C:\Users\32439\Documents\deepseek-harness\rr3` **整体搬到了 `D:\rr3`**，
C: 释放 5.07 GB（2.25 GB → 7.32 GB）。所有代码、测试、文档、exe 都在新位置，
并且已经在 D: 上跑通了全部测试。

## 现在该在哪里工作

**`D:\rr3`** —— 不要再往旧的 C: 路径写东西，那个文件夹已经空了（只剩一个空目录）。

## 搬家做了什么

1. `robocopy C:\...\rr3 D:\rr3 /E /COPY:DAT` —— 11,450 文件 / 5.047 GB，**0 失败**。
2. **改写 188 个脚本里的硬编码路径**（`C:\Users\32439\Documents\deepseek-harness\rr3` → `D:\rr3`）：
   `analysis/` 107 个、`re/` 74 个、`work/` 7 个。改完复查：**0 处残留**。
3. `tools/smoke_addon.py` 与 `tools/test_car.py` 原本硬编码路径，已改成
   `os.path.dirname(os.path.dirname(os.path.abspath(__file__)))` —— 以后搬到哪里都不用改。

**不需要改的地方**（都是相对路径或环境变量）：

- `rrmod/ui/settings.py` 的 `_path()`：按序试 `%APPDATA%\RR3ModManager` → exe 目录 → `%TEMP%`。
- `rrmod/depot.py` 的 `mods_path()`、`rrmod/workspace.py:75 workspace_root(depot)`。
- `tools/build_exe.py`、`tools/rrmod.spec`。

## 搬家后的验证结果（全部在 D: 上跑）

| 项目 | 结果 |
|---|---|
| `python tools\sync_rr3lib.py --check` | 34 modules, already in sync |
| `python tools\build_addon.py --check` | `rr3_blender_addon.zip` current (38 files) |
| `python -X utf8 tools\test_rrmod.py` | **724 passed, 0 failed** |
| `tools/smoke_addon.py` | **SMOKE TEST: PASS**（19 步） |
| `tools/smoke_wheels.py` | **PASS**（107 ok） |
| `tools/smoke_materials.py` | **PASS**（113 ok） |
| `tools/smoke_driver.py` | **PASS**（54 ok） |
| `tools/test_car.py` | **CARTEST: PASS** |
| `dist\RR3ModManager\RR3ModManager.exe --check` | `540 cars: 540 vanilla, 0 mod, 0 unknown` |

源码树比对：`rrmod` / `rr3lib` / `rr3_blender_addon` / `docs` / `tools`
在 C: 与 D: 上**逐文件 md5 完全一致**（0 差异）。

## 搬迁时注意到的事

- `dist\RR3ModManager\rrmod_check.log` 两边差 73 字节 —— 那是 exe 自己写的运行日志，无所谓。
- `work/` 在 D: 上多 10 个文件 —— 是我验证时新生成的测试输出（`smoke_d.out`、`wheel_d.out`、
  `mat_d.out`、`drv_d.out`、`car_d.out` 等），可以直接删。
- `tools/` 占了 **2,924 MB**，其中 `ghidra_projects` 1,286 MB、`ghidra_12.1.4_PUBLIC` 864 MB、
  `jdk21` 415 MB、`renderdoc_portable` 203 MB。**运行时代码完全不引用它们**（全搜过），
  只在做逆向分析时才需要。
- `re/` 占 1,450 MB（`logs` 446 MB、`apk` 383 MB、`lib` 84 MB）。
- 工作区里没有 junction/symlink，也不是 git 仓库。

## DSH 会话状态仍在 C:

`C:\Users\32439\.dsh`（会话、凭据、GUI 状态）**没有动**，与工作区无关。
`C:\Users\32439\.dsh\storages\workspace.json` 里 rr3 工作区的 `path` 字段**仍然写着旧的 C: 路径**，
需要用 GUI 或插件把工作区指到 `D:\rr3`，否则沙箱根目录还是旧的（表现为：写 D: 需要每次授权）。

## 当前的未完成工作（搬过来之前的状态）

`docs/RRMOD-BACKLOG.md` 里的开放项，以及最近这一轮尾翼研究的收尾：

- 尾翼动画已经**在游戏里跑通**：`_a.m3g` + `_wing.banim` + `_animations.xml` + aero 标志 + livery 槽位，
  五样齐全才行。用户 m23303 确认「完美运行」。
- Blender 插件的 banim 导出器已改成**双 slot**（slot0 = 每帧节点，slot1 = 每段两个 Bezier 控制点，
  满足 `n1 == 2*(n0-1)`），并新增 `donor` 参数继承容器（魔数 `0x7F7F7F00` + 尾块）。
- 管理器已修：`Device.fix_permissions()`（目录 `2770`、文件 `660`，**绝不能用 `chmod -R`**，
  目录丢了搜索位会让贴图读不到、渲染成洋红黑格）、`edit.sync_wing_paint()`（自动给尾翼补涂装行）。
- 推送三本账：per-car 清单 `chmod 444`、`asset_list_vehicle_data.txt`、注册表
  `asset_list_base.txtCache.txt`（13 字节二进制头，**绝不能用文本模式读写**）。
