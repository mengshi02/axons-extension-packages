#!/bin/bash
# ============================================================
# Axons 插件统一打包脚本（根目录）
#
# 自动扫描仓库内所有含 manifest.json 的插件目录，
# 打包为 .axons-plugin.tar.gz 供 axons 离线导入。
#
# 用法:
#   bash pack.sh                                  # 打包所有插件
#   bash pack.sh chat.axons.locale-zh-cn           # 按 ID 过滤
#   bash pack.sh language/                        # 按目录前缀过滤
#   bash pack.sh -h
#
# 注: 本脚本只做打包，不触发构建或清理。组合操作请自己串联：
#   bash clean.sh --keep-artifacts && bash build.sh && bash pack.sh
#
# 输出: <repo_root>/dist/{plugin-id}-{version}.axons-plugin.tar.gz
# ============================================================
set -e

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
DIST_DIR="$REPO_ROOT/dist"

show_help() {
    cat <<'EOF'
用法: bash pack.sh [选项] [插件目标...]

将 Axons 插件打包为 .axons-plugin.tar.gz。
本脚本只负责打包当前目录状态，不会触发构建或清理。如需先构建/清理，
请独立调用 build.sh / clean.sh。

选项:
  -h, --help        显示本帮助

参数:
  插件目标...        插件 ID / 子目录 / 父目录路径
                    省略时打包仓库内所有插件

输出:
  <repo_root>/dist/{plugin-id}-{version}.axons-plugin.tar.gz

默认排除:
  .venv / node_modules / .git / .DS_Store / *.pyc / __pycache__
  src/ scripts/ tsconfig.json vite.config.* package*.json（前端源码不入包）
  *.axons-plugin.tar.gz / dist/

插件目录下可放 .axons-ignore 文件追加排除规则（每行一条）。

钩子:
  scripts/pre-pack.sh   打包前执行（可生成额外产物）
  scripts/post-pack.sh  打包后执行（接收 tar.gz 路径作为环境变量 PACKAGE_PATH）

导入方式:
  在 Axons UI: Extensions 面板 → Import from File
EOF
}

ARGS=()
for arg in "$@"; do
    case "$arg" in
        -h|--help) show_help; exit 0 ;;
        --*) echo "错误: 未知选项 ${arg}（如需查看用法: bash pack.sh -h）"; exit 2 ;;
        *) ARGS+=("$arg") ;;
    esac
done

# ------------------------------------------------------------
# 插件发现 + 过滤（与 build.sh 一致的语义）
# ------------------------------------------------------------
discover_plugins() {
    find "$REPO_ROOT" -type f -name "manifest.json" \
        -not -path "*/.venv/*" -not -path "*/node_modules/*" \
        -not -path "*/.git/*" -not -path "*/dist/*" \
        -not -path "*/.joycode/*" 2>/dev/null \
        | while IFS= read -r m; do dirname "$m"; done | sort -u
}

filter_plugins() {
    local all=()
    while IFS= read -r d; do all+=("$d"); done < <(discover_plugins)

    if [ ${#ARGS[@]} -eq 0 ]; then
        printf '%s\n' "${all[@]}"
        return
    fi

    local result=()
    for plugin_dir in "${all[@]}"; do
        local rel="${plugin_dir#$REPO_ROOT/}"
        local pid
        pid=$(python3 -c "import json; print(json.load(open('$plugin_dir/manifest.json')).get('id',''))" 2>/dev/null || echo "")
        for filter in "${ARGS[@]}"; do
            filter="${filter%/}"
            if [ "$filter" = "$pid" ] || [ "$rel" = "$filter" ] || [[ "$rel" == "$filter"/* ]]; then
                result+=("$plugin_dir")
                break
            fi
        done
    done
    printf '%s\n' "${result[@]}"
}

pack_plugin() {
    local PLUGIN_DIR="${1%/}"
    local REL="${PLUGIN_DIR#$REPO_ROOT/}"
    local MANIFEST="$PLUGIN_DIR/manifest.json"

    local PID PVER
    PID=$(python3 -c "import json; print(json.load(open('$MANIFEST'))['id'])" 2>/dev/null)
    PVER=$(python3 -c "import json; print(json.load(open('$MANIFEST'))['version'])" 2>/dev/null)
    if [ -z "$PID" ] || [ -z "$PVER" ]; then
        echo "错误: 无法读取 $MANIFEST 的 id/version"
        return 1
    fi

    echo "==> [$PID v$PVER]  $REL"

    # pre-pack 钩子
    if [ -f "$PLUGIN_DIR/scripts/pre-pack.sh" ]; then
        echo "    → 执行 scripts/pre-pack.sh"
        PLUGIN_DIR="$PLUGIN_DIR" PLUGIN_ID="$PID" PLUGIN_VERSION="$PVER" \
            bash "$PLUGIN_DIR/scripts/pre-pack.sh" || return 1
    fi

    mkdir -p "$DIST_DIR"
    local OUTPUT_NAME="${PID}-${PVER}.axons-plugin.tar.gz"
    local OUTPUT_PATH="$DIST_DIR/$OUTPUT_NAME"

    local EXCLUDES=(
        --exclude='.venv' --exclude='node_modules' --exclude='.git'
        --exclude='.DS_Store' --exclude='*.pyc' --exclude='__pycache__'
        --exclude='*.axons-plugin.tar.gz' --exclude='dist'
        # 前端源码与构建配置不进运行时包
        --exclude='src' --exclude='scripts'
        --exclude='package.json' --exclude='package-lock.json'
        --exclude='tsconfig.json' --exclude='vite.config.js' --exclude='vite.config.ts'
        --exclude='.axons-ignore' --exclude='.axons-build'
    )

    if [ -f "$PLUGIN_DIR/.axons-ignore" ]; then
        while IFS= read -r line || [ -n "$line" ]; do
            [[ -z "$line" || "$line" =~ ^# ]] && continue
            EXCLUDES+=(--exclude="$line")
        done < "$PLUGIN_DIR/.axons-ignore"
    fi

    (cd "$PLUGIN_DIR" && tar czf "$OUTPUT_PATH" "${EXCLUDES[@]}" .) || return 1

    local SIZE SHA
    SIZE=$(du -h "$OUTPUT_PATH" | cut -f1)
    SHA=$(shasum -a 256 "$OUTPUT_PATH" | cut -d' ' -f1)
    echo "    ✓ dist/$OUTPUT_NAME ($SIZE)"
    echo "      SHA256: $SHA"

    # post-pack 钩子
    if [ -f "$PLUGIN_DIR/scripts/post-pack.sh" ]; then
        echo "    → 执行 scripts/post-pack.sh"
        PLUGIN_DIR="$PLUGIN_DIR" PLUGIN_ID="$PID" PLUGIN_VERSION="$PVER" \
        PACKAGE_PATH="$OUTPUT_PATH" \
            bash "$PLUGIN_DIR/scripts/post-pack.sh" || return 1
    fi
}

PLUGIN_DIRS=()
while IFS= read -r d; do
    [ -n "$d" ] && PLUGIN_DIRS+=("$d")
done < <(filter_plugins)

if [ ${#PLUGIN_DIRS[@]} -eq 0 ]; then
    echo "未匹配到任何插件"
    exit 1
fi

echo "=== Axons 插件打包 ==="
echo "    匹配到 ${#PLUGIN_DIRS[@]} 个插件 → 输出 $DIST_DIR/"
echo ""

SUCCESS=0
FAIL=0
for d in "${PLUGIN_DIRS[@]}"; do
    if pack_plugin "$d"; then
        SUCCESS=$((SUCCESS + 1))
    else
        FAIL=$((FAIL + 1))
    fi
    echo ""
done

echo "=== 完成: ${SUCCESS} 成功, ${FAIL} 失败 ==="
if [ $SUCCESS -gt 0 ]; then
    echo ""
    echo "导入方式:"
    echo "在 Axons UI: Extensions 面板 → Import from File"
fi
[ $FAIL -eq 0 ]