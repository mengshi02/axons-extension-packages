#!/bin/bash
# ============================================================
# 局部入口：转发到根目录 build.sh，作用域限定为 huggingface/
#
# 此脚本是薄封装，所有逻辑见 <repo_root>/build.sh。
# 如果未传插件名，默认构建 huggingface/ 下的所有插件。
# ============================================================
set -e
THIS_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$THIS_DIR/.." && pwd)"

if [ $# -eq 0 ]; then
    exec bash "$REPO_ROOT/build.sh" huggingface/
else
    exec bash "$REPO_ROOT/build.sh" "$@"
fi