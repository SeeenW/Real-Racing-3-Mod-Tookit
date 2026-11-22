# tools —— 逆向分析工具链（已装好，可直接用）

本目录是 RR3 逆向分析的本地工具链，**所有东西都在工作区内**，不写注册表、不写 `%APPDATA%`。

## 目录

| 路径 | 说明 |
|---|---|
| `jdk21\` | JDK 21.0.3（415 MB）。从本机 PyCharm 自带的 JetBrains Runtime 复制而来；MSI 无法在非管理员下安装，所以直接用了这份完整 JDK（含 `javac`）。 |
| `ghidra_12.1.4_PUBLIC\` | Ghidra 12.1.4（864 MB，已解压）。 |
| `ghidra_user\` | Ghidra 的 settings 目录（原本会写到 `%APPDATA%\ghidra`，被沙箱拦，已重定向到这里）。 |
| `ghidra_cache\`、`ghidra_tmp\` | Ghidra 的 cache / temp，同样重定向。 |
| `ghidra_projects\` | Ghidra 工程目录，分析结果放这里。 |
| `rr3env.bat` | 环境变量：`JAVA_HOME`、`GHIDRA_HOME`、`PATH`。 |
| `ghidra_headless.bat` | 无界面入口，转调 `support\analyzeHeadless.bat`。 |
| `OpenJDK21U-...msi` | 用户下载的 JDK 安装包，**已不需要**，可以删掉。 |
| `ghidra_12.1.4_PUBLIC_20260921.zip` | 原始压缩包，保留作备份。 |

## 用法

```bat
cd tools
ghidra_headless.bat -help

rem 导入并分析一个文件（-deleteProject 表示分析完就删工程）
ghidra_headless.bat "%CD%\ghidra_projects" myproj -import "D:\path\to\libtarget.so" ^
    -analysisTimeoutPerFile 1800 -deleteProject

rem 带脚本跑（脚本放 tools\scripts\）
ghidra_headless.bat "%CD%\ghidra_projects" myproj -import "D:\path\to\libtarget.so" ^
    -scriptPath "%CD%\scripts" -postScript MyScript.java
```

## 关键改动（相对原版 Ghidra）

`ghidra_12.1.4_PUBLIC\support\launch.properties` 末尾追加了三行，把 Ghidra 的写入目录
从 `%APPDATA%` / `%LOCALAPPDATA%` 改到工作区内：

```
VMARGS=-Dapplication.settingsdir=D:\rr3\tools\ghidra_user
VMARGS=-Dapplication.cachedir=D:\rr3\tools\ghidra_cache
VMARGS=-Dapplication.tempdir=D:\rr3\tools\ghidra_tmp
```

不加这三行，`analyzeHeadless.bat` 会在 `LaunchSupport` 阶段直接报
`Failed to create directory: C:\Users\...\AppData\Roaming\ghidra\ghidra_12.1.4_PUBLIC`
然后 `JDK 21+ (64-bit) could not be found`。

## 验证记录

- `ghidra_headless.bat -help` → 正常打印用法。
- 端到端冒烟测试：`notepad.exe` 导入 + 全量分析 + 保存，172 秒，
  `REPORT: Import succeeded` / `Save succeeded`，`%APPDATA%\ghidra` 未被创建。
- 剩余空间：11.1 GB。

## 还没做的（等用户回来）

- MuMu 模拟器 + RR3（`com.ea.games.r3_row`）的安装，以及从 `adb` 里拉 `lib\arm64-v8a\*.so`。
