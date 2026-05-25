#!/bin/bash
# ============================================================
# Axons 插件统一清理脚本（根目录）
#
# 清理所有插件的依赖目录、构建产物，方便重新打干净的发布包。
#
# 用法:
#   bash clean.sh                          # 清理所有插件
#   bash clean.sh chat.axons.huggingface  # 按 ID 过滤
#   bash clean.sh huggingface/           # 按目录过滤
#   bash clean.sh --all                    # 额外删除 dist/ 与 *.tar.gz
#   bash clean.sh --keep-artifacts         # 只清依赖，保留 ui/ 构建产物
#   bash clean.sh -h
# ============================================================
set -e

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
DIST_DIR="$REPO_ROOT/dist"

show_help() {
    cat <<'EOF'
用法: bash clean.sh [选项] [插件目标...]

清理所有 Axons 插件的依赖与构建产物。

选项:
  --all              额外清理打包产物:
                       - 各插件目录下残留的 *.axons-plugin.tar.gz
                       - 仓库根的 dist/ 整目录
  --keep-artifacts   保留 ui/ 构建产物，只清依赖缓存
  -h, --help         显示本帮助

参数:
  插件目标...         插件 ID / 子目录 / 父目录路径
                     省略时清理仓库内所有插件

默认会删除（每个插件目录下）:
  - node_modules/    前端依赖
  - .vite/           vite 缓存
  - dist/            前端默认产物目录（若存在；与根 dist/ 不冲突）
  - .venv/           Python 虚拟环境
  - __pycache__/     Python 字节码缓存（递归清理子目录）
  - *.pyc            Python 编译后的字节码文件
  - ui/index.js      vite 构建产物（默认；可由 .axons-build 配置）

钩子:
  scripts/clean.sh   插件自定义清理（接收环境变量 PLUGIN_DIR/PLUGIN_ID）
EOF
}

REMOVE_PACKAGES=0
KEEP_ARTIFACTS=0
ARGS=()
for arg in "$@"; do
    case "$arg" in
        --all) REMOVE_PACKAGES=1 ;;
        --keep-artifacts) KEEP_ARTIFACTS=1 ;;
        -h|--help) show_help; exit 0 ;;
        *) ARGS+=("$arg") ;;
    esac
done

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
                result+=("$plugin_dir"); break
            fi
        done
    done
    printf '%s\n' "${result[@]}"
}

remove_path() {
    local p="$1"
    if [ -e "$p" ] || [ -L "$p" ]; then
        local size="-"
        if [ -d "$p" ]; then size=$(du -sh "$p" 2>/dev/null | cut -f1)
        elif [ -f "$p" ]; then size=$(du -h "$p" 2>/dev/null | cut -f1); fi
        rm -rf "$p"
        echo "    ✓ 删除: ${p#$REPO_ROOT/} ($size)"
    fi
}

clean_plugin() {
    local PLUGIN_DIR="${1%/}"
    local REL="${PLUGIN_DIR#$REPO_ROOT/}"
    echo "==> $REL"

    # 前端依赖与缓存
    remove_path "$PLUGIN_DIR/node_modules"
    remove_path "$PLUGIN_DIR/.vite"
    # 注意: 这里清的是插件目录下的 dist/，不是仓库根的 dist/
    if [ "$PLUGIN_DIR/dist" != "$DIST_DIR" ]; then
        remove_path "$PLUGIN_DIR/dist"
    fi

    # 后端依赖与缓存
    remove_path "$PLUGIN_DIR/.venv"
    # __pycache__ 可能散落在子目录中，递归清理
    if [ -d "$PLUGIN_DIR" ]; then
        local pycount
        pycount=$(find "$PLUGIN_DIR" -type d -name "__pycache__" \
            -not -path "*/.venv/*" -not -path "*/node_modules/*" 2>/dev/null | wc -l | tr -d ' ')
        if [ "$pycount" -gt 0 ]; then
            find "$PLUGIN_DIR" -type d -name "__pycache__" \
                -not -path "*/.venv/*" -not -path "*/node_modules/*" \
                -exec rm -rf {} + 2>/dev/null || true
            echo "    ✓ 删除: $pycount 个 __pycache__ 目录"
        fi
        # .pyc 散文件
        local pyccount
        pyccount=$(find "$PLUGIN_DIR" -type f -name "*.pyc" \
            -not -path "*/.venv/*" -not -path "*/node_modules/*" 2>/dev/null | wc -l | tr -d ' ')
        if [ "$pyccount" -gt 0 ]; then
            find "$PLUGIN_DIR" -type f -name "*.pyc" \
                -not -path "*/.venv/*" -not -path "*/node_modules/*" \
                -delete 2>/dev/null || true
            echo "    ✓ 删除: $pyccount 个 .pyc 文件"
        fi
    fi

    if [ $KEEP_ARTIFACTS -eq 0 ]; then
        local ARTIFACTS=("ui/index.js")
        if [ -f "$PLUGIN_DIR/.axons-build" ]; then
            ARTIFACTS=()
            while IFS= read -r line || [ -n "$line" ]; do
                [[ -z "$line" || "$line" =~ ^# ]] && continue
                ARTIFACTS+=("$line")
            done < "$PLUGIN_DIR/.axons-build"
        fi
        for art in "${ARTIFACTS[@]}"; do
            [ -f "$PLUGIN_DIR/package.json" ] && remove_path "$PLUGIN_DIR/$art"
        done
    fi

    if [ $REMOVE_PACKAGES -eq 1 ]; then
        for pkg in "$PLUGIN_DIR"/*.axons-plugin.tar.gz; do
            [ -e "$pkg" ] && remove_path "$pkg"
        done
    fi

    # 插件自定义钩子
    if [ -f "$PLUGIN_DIR/scripts/clean.sh" ]; then
        local PID
        PID=$(python3 -c "import json; print(json.load(open('$PLUGIN_DIR/manifest.json'))['id'])" 2>/dev/null)
        echo "    → 执行 scripts/clean.sh"
        PLUGIN_DIR="$PLUGIN_DIR" PLUGIN_ID="$PID" \
            bash "$PLUGIN_DIR/scripts/clean.sh" || true
    fi
}

PLUGIN_DIRS=()
while IFS= read -r d; do
    [ -n "$d" ] && PLUGIN_DIRS+=("$d")
done < <(filter_plugins)

echo "=== Axons 插件清理 ==="
[ $REMOVE_PACKAGES -eq 1 ] && echo "    (--all: 同时清理 tar.gz 与 dist/)"
[ $KEEP_ARTIFACTS -eq 1 ] && echo "    (--keep-artifacts: 保留 ui/ 构建产物)"
echo ""

for d in "${PLUGIN_DIRS[@]}"; do
    clean_plugin "$d"
    echo ""
done

if [ $REMOVE_PACKAGES -eq 1 ] && [ -d "$DIST_DIR" ]; then
    echo "==> 顶层 dist/"
    remove_path "$DIST_DIR"
    echo ""
fi

echo "=== 清理完成 ==="