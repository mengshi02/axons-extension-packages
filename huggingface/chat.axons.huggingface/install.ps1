# Axons HuggingFace - Windows 安装脚本
# 使用方法: powershell -ExecutionPolicy Bypass -File install.ps1
#
# 设计原则（与 install.sh 一致）：
# - 安装 Python 依赖 + 检查/下载 llama-server
# - llama-server 也可由用户自行安装（在 PATH 中即可）
# - 即使 llama-server 未安装也以 exit 0 结束
$ErrorActionPreference = "Stop"

Write-Host "=== Axons HuggingFace 安装 ===" -ForegroundColor Cyan

# ------------------------------------------------------------
# 1. 检查 Python 3.9+
# ------------------------------------------------------------
Write-Host "[1/3] 检查 Python 环境..."

$PythonCmd = $null
$PyVersion = $null

foreach ($cmd in @("python3", "python")) {
    try {
        $result = & $cmd --version 2>&1
        if ($result -match "Python (\d+)\.(\d+)") {
            $major = [int]$Matches[1]
            $minor = [int]$Matches[2]
            if ($major -gt 3 -or ($major -eq 3 -and $minor -ge 9)) {
                $PythonCmd = $cmd
                $PyVersion = "$major.$minor"
                break
            }
        }
    } catch { }
}

if (-not $PythonCmd) {
    Write-Host "错误: 未找到 Python 3.9+" -ForegroundColor Red
    Write-Host "  请从 https://python.org 下载安装" -ForegroundColor Yellow
    exit 1
}

Write-Host "  Python $PyVersion OK" -ForegroundColor Green

# ------------------------------------------------------------
# 2. venv + 依赖
# ------------------------------------------------------------
Write-Host "[2/3] 安装 Python 依赖..."

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvDir = Join-Path $ScriptDir ".venv"

& $PythonCmd -m venv $VenvDir

$PipCmd = Join-Path $VenvDir "Scripts\pip.exe"

if (-not (Test-Path $PipCmd)) {
    Write-Host "错误: 虚拟环境创建失败" -ForegroundColor Red
    exit 1
}

& $PipCmd install --quiet --upgrade pip
& $PipCmd install --quiet -r (Join-Path $ScriptDir "requirements.txt")
Write-Host "  依赖安装完成 OK" -ForegroundColor Green

# ------------------------------------------------------------
# 3. 检查/下载 llama-server
# ------------------------------------------------------------
Write-Host "[3/3] 检查 llama-server..."

$PluginId = if ($env:AXONS_PLUGIN_ID) { $env:AXONS_PLUGIN_ID } else { "chat.axons.huggingface" }
$DataDir = if ($env:AXONS_PLUGIN_DATA_DIR) { $env:AXONS_PLUGIN_DATA_DIR } else { Join-Path $env:USERPROFILE ".axons\plugins\data\$PluginId" }
$BinDir = Join-Path $DataDir "bin"
$BinPath = Join-Path $BinDir "llama-server.exe"

# 检查 PATH
$InPath = $false
try {
    $whereResult = Get-Command llama-server -ErrorAction SilentlyContinue
    if ($whereResult) { $InPath = $true }
} catch { }

if ($InPath) {
    Write-Host "  llama-server 已在 PATH 中 OK" -ForegroundColor Green
    Write-Host ""
    Write-Host "=== 安装完成 ===" -ForegroundColor Cyan
    exit 0
}

# 检查插件 bin 目录
if (Test-Path $BinPath) {
    Write-Host "  llama-server 已安装 OK ($BinPath)" -ForegroundColor Green
    Write-Host ""
    Write-Host "=== 安装完成 ===" -ForegroundColor Cyan
    exit 0
}

Write-Host "  llama-server 未安装，将在面板状态栏引导安装" -ForegroundColor Yellow
Write-Host "  也可手动下载: https://github.com/ggerganov/llama.cpp/releases" -ForegroundColor Yellow

Write-Host ""
Write-Host "=== 安装完成 ===" -ForegroundColor Cyan
exit 0