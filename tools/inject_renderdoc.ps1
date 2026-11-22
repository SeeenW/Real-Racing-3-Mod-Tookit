# 用 RenderDoc 抓 MuMu 的画面帧（需要管理员权限：MuMu 本身以管理员运行）
# 双击 inject_renderdoc.bat，或在 PowerShell 里运行本脚本。

$ErrorActionPreference = "Stop"
$rd  = "C:\Users\32439\Documents\deepseek-harness\rr3\tools\renderdoc_portable"
$cmd = Join-Path $rd "renderdoccmd.exe"
$out = "C:\Users\32439\Documents\deepseek-harness\rr3\re\rdc\capture"
$mgr = "D:\Program Files\Netease\MuMu\nx_main\MuMuManager.exe"
$ui  = "D:\Program Files\Netease\MuMu\nx_main\MuMuNxMain.exe"

function Pause-Exit { Read-Host "按回车关闭"; exit }

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
           ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "需要管理员权限，正在弹出 UAC ..." -ForegroundColor Yellow
    Start-Process powershell -Verb RunAs -ArgumentList @(
        "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $PSCommandPath)
    exit
}

New-Item -ItemType Directory -Force -Path (Split-Path $out) | Out-Null

Write-Host ""
Write-Host "抓帧方式：" -ForegroundColor Cyan
Write-Host "  [1] 注入到正在运行的 MuMu（快，但 GL 上下文已建立，可能抓不到）"
Write-Host "  [2] 关掉 MuMu，由 RenderDoc 重新启动（推荐，GL 抓帧可靠）"
$mode = Read-Host "选择 1 或 2（默认 2）"
if ([string]::IsNullOrWhiteSpace($mode)) { $mode = "2" }

if ($mode -eq "1") {
    $json = & $mgr info -v 0 2>&1 | Out-String
    $m = [regex]::Match($json, '"pid"\s*:\s*(\d+)')
    if (-not $m.Success) { Write-Host "没查到 MuMu 实例，先启动模拟器。" -ForegroundColor Red; Pause-Exit }
    $pidTarget = [int]$m.Groups[1].Value
    Write-Host "注入 PID $pidTarget ..." -ForegroundColor Cyan
    & $cmd inject --PID=$pidTarget --capture-file=$out --opt-disallow-vsync
    if ($LASTEXITCODE -eq 0) {
        Write-Host "注入成功：回到游戏按 F12。" -ForegroundColor Green
        Write-Host "抓到的文件：$out*.rdc"
    } else {
        Write-Host "注入失败，改用方式 2 重试。" -ForegroundColor Red
    }
    Pause-Exit
}

# 方式 2：先关 MuMu，再由 RenderDoc 拉起（自动 hook 子进程）
$procs = Get-Process -Name "MuMuNxMain", "MuMuNxDevice", "MuMuNxService" -ErrorAction SilentlyContinue
if ($procs) {
    Write-Host "将关闭 MuMu：$($procs.ProcessName -join ', ')" -ForegroundColor Yellow
    $ok = Read-Host "确认？(Y/n)"
    if ($ok -ne "n") {
        $procs | Stop-Process -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 4
        Write-Host "已关闭。" -ForegroundColor Green
    }
}

Write-Host ""
Write-Host "正在用 RenderDoc 启动 MuMu（这个窗口会一直占用，直到你关闭 MuMu）..." -ForegroundColor Cyan
Write-Host "启动后：进车库 → 停在目标车 → 按 F12 抓帧 → 告诉我。" -ForegroundColor Yellow
Write-Host "抓完想结束：直接关掉 MuMu，这个窗口就会退出。" -ForegroundColor Yellow
Write-Host ""

& $cmd capture --opt-hook-children --opt-disallow-vsync --capture-file=$out $ui
Write-Host "RenderDoc 已退出（exit $LASTEXITCODE）" -ForegroundColor Cyan
Write-Host "抓到的文件："
Get-ChildItem "$out*.rdc" -ErrorAction SilentlyContinue | Select-Object Name, Length, LastWriteTime | Format-Table -AutoSize
Pause-Exit
