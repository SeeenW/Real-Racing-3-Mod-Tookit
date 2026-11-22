# RenderDoc 免安装版（已就绪）

来源：`tools\RenderDoc_1.46_64.msi`（1.46，x64）
做法：`analysis\rdoc_unpack.py` 读 MSI 的 `File` / `Directory` 表，按 MSI 记录的**真实文件名与目录结构**
重建到 `tools\renderdoc_portable\`（不需要管理员权限，没有写注册表）。

## 验证

| 检查 | 结果 |
|---|---|
| `renderdoccmd.exe version` | `renderdoccmd x64 v1.46 built from e4bd23b6…` ✓ |
| `qrenderdoc.exe` | 13.6 MB，与 `renderdoc.dll`(27.5 MB)、`qtplugins\`、`PySide2\` 同级 ✓ |
| Vulkan 层注册 | **未注册**（v1.46 只支持系统级注册，需管理员）；改用环境变量强制加载 |

## 抓帧方式

### A. 如果 MuMu 宿主走 Vulkan（`vulkan-1.dll`）

不注册也能用，启动 MuMu 前设置：

```
set "VK_LAYER_PATH=C:\Users\32439\Documents\deepseek-harness\rr3\tools\renderdoc_portable"
set "VK_INSTANCE_LAYERS=VK_LAYER_RENDERDOC_Capture"
```

然后启动 MuMu → 进车库 → 按 **F12** 抓帧，`.rdc` 落在 `%TEMP%`。

### B. 如果宿主走 OpenGL（`libGLESv2_nemu.dll` + `mesa_opengl32.dll`）

```
tools\renderdoc_portable\renderdoccmd.exe capture "D:\Program Files\Netease\MuMu\...\MuMuPlayer.exe"
```

或对已运行进程注入：`renderdoccmd.exe inject -p <pid>`（位数要匹配）。

## 抓帧后

`.rdc` 拷到 `re\rdc\`，然后按 `docs\下一步-游戏内截帧对照.md` 的流程解矩阵、逐件对照。
