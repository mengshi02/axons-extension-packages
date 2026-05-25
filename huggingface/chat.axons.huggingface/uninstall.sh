#!/bin/bash
echo "=== 卸载 Axons HuggingFace ==="

PURGE_DATA=false

# 解析命令行参数
for arg in "$@"; do
    case $arg in
        --purge-data) PURGE_DATA=true ;;
    esac
done

# 数据目录：优先使用宿主注入的环境变量
DATA_DIR="${AXONS_PLUGIN_DATA_DIR:-$HOME/.axons/plugins/data/${AXONS_PLUGIN_ID:-chat.axons.huggingface}}"

# 1. 停止运行中的 llama-server 进程
echo "停止运行中的 llama-server 进程..."
if command -v pkill &>/dev/null; then
    pkill -f "llama-server.*$DATA_DIR" 2>/dev/null || true
fi

# 2. 根据参数决定是否清理数据目录
if [ "$PURGE_DATA" = true ]; then
    echo "清理插件数据（模型、llama-server、元数据）..."
    if [ -d "$DATA_DIR" ]; then
        rm -rf "$DATA_DIR"
    fi
    echo "完全卸载完成。"
else
    echo "插件已卸载，数据保留在: $DATA_DIR"
    echo "如需彻底清理，请手动删除: $DATA_DIR"
fi