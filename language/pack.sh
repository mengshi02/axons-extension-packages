#!/bin/bash
# ============================================================
# 局部入口：转发到根目录 pack.sh，作用域限定为 language/
#
# 此脚本是薄封装，所有逻辑见 <repo_root>/pack.sh。
# 如果未传插件名，默认打包 language/ 下的所有插件。
# ============================================================
set -e
THIS_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$THIS_DIR/.." && pwd)"

if [ $# -eq 0 ]; then
    # 默认只打 language/ 下的插件
    exec bash "$REPO_ROOT/pack.sh" language/
else
    exec bash "$REPO_ROOT/pack.sh" "$@"
fi