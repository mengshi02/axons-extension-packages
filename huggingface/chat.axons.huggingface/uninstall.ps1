# Axons HuggingFace - Windows 卸载脚本
# 使用方法: powershell -ExecutionPolicy Bypass -File uninstall.ps1 [--purge-data]

Write-Host "=== 卸载 Axons HuggingFace ===" -ForegroundColor Cyan

# 解析参数
$PurgeData = $args -contains "--purge-data"

# 数据目录：优先使用宿主注入的环境变量
$PluginId = if ($env:AXONS_PLUGIN_ID) { $env:AXONS_PLUGIN_ID } else { "chat.axons.huggingface" }
$DataDir = if ($env:AXONS_PLUGIN_DATA_DIR) { $env:AXONS_PLUGIN_DATA_DIR } else { Join-Path $env:USERPROFILE ".axons\plugins\data\$PluginId" }

# 1. 停止 llama-server 进程
Write-Host "停止运行中的 llama-server 进程..."
Get-Process -Name "llama-server" -ErrorAction SilentlyContinue | Stop-Process -Force

# 2. 根据参数决定是否清理数据目录
if ($PurgeData) {
    Write-Host "清理插件数据（模型、llama-server、元数据）..."
    if (Test-Path $DataDir) {
        Remove-Item -Recurse -Force $DataDir
    }
    Write-Host "完全卸载完成。" -ForegroundColor Green
} else {
    Write-Host "卸载完成。" -ForegroundColor Green
    Write-Host "如需清理插件数据，请手动删除: $DataDir"
}