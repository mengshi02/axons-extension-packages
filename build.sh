#!/bin/bash
# ============================================================
# Axons 插件统一构建/校验脚本（根目录）
#
# 自动扫描仓库内所有含 manifest.json 的插件目录，按插件特征
# 自动判断需要执行哪些校验/构建步骤：
#
#   - 含 package.json + "build" script  → 前端构建 + 产物验证
#   - 含 requirements.txt 或 *.py        → 后端校验（Python/pip/sh 语法）
#   - 含 scripts/build.sh               → 调用插件自带钩子（覆盖默认）
#   - 纯静态插件（如 language pack）      → 跳过构建
#
# 用法:
#   bash build.sh                                  # 处理所有插件
#   bash build.sh chat.axons.locale-zh-cn           # 按 ID 过滤
#   bash build.sh language/                        # 按子目录过滤
#   bash build.sh chat.axons.huggingface language/chat.axons.locale-zh-cn
#   bash build.sh -h
# ============================================================
set -e

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"

show_help() {
    cat <<'EOF'
用法: bash build.sh [选项] [插件目标...]

自动扫描所有插件并按需校验/构建。插件目标可以是：
  - 插件 ID（manifest.json 中的 id 字段，如 chat.axons.huggingface）
  - 插件目录路径（如 huggingface/chat.axons.huggingface）
  - 父目录（如 language/，匹配该目录下所有插件）
  省略时处理仓库内所有插件。

选项:
  -h, --help        显示本帮助

按插件特征自动判断行为:
  前端构建（条件: package.json 含 "build" script）
    - npm ci / npm install
    - npm run build
    - 验证产物（默认 ui/index.js，或 .axons-build 配置）

  后端校验（条件: 存在 *.py 或 requirements.txt）
    - python3 -m py_compile *.py
    - pip install --dry-run -r requirements.txt（兼容 PEP 668）
    - bash -n *.sh

  插件钩子（条件: 存在 scripts/build.sh）
    - 调用 bash scripts/build.sh，作为前端/后端校验后的补充步骤
    - 通过环境变量 PLUGIN_DIR / PLUGIN_ID / PLUGIN_VERSION 传入上下文

  纯静态插件:
    - 无以上任何特征，直接跳过

示例:
  bash build.sh                                  # 全部
  bash build.sh chat.axons.locale-zh-cn           # 按 ID
  bash build.sh language/                        # 按目录前缀
EOF
}

ARGS=()
for arg in "$@"; do
    case "$arg" in
        -h|--help) show_help; exit 0 ;;
        --*) echo "错误: 未知选项 ${arg}（如需查看用法: bash build.sh -h）"; exit 2 ;;
        *) ARGS+=("$arg") ;;
    esac
done

# ------------------------------------------------------------
# 插件发现：递归找所有含 manifest.json 的目录
# 自动忽略：.venv / node_modules / .git / dist
# ------------------------------------------------------------
discover_plugins() {
    find "$REPO_ROOT" -type f -name "manifest.json" \
        -not -path "*/.venv/*" \
        -not -path "*/node_modules/*" \
        -not -path "*/.git/*" \
        -not -path "*/dist/*" \
        -not -path "*/.joycode/*" 2>/dev/null \
        | while IFS= read -r m; do dirname "$m"; done \
        | sort -u
}

# 按用户输入过滤插件目录
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
            if [ "$filter" = "$pid" ] \
               || [ "$rel" = "$filter" ] \
               || [[ "$rel" == "$filter"/* ]]; then
                result+=("$plugin_dir")
                break
            fi
        done
    done
    printf '%s\n' "${result[@]}"
}

# ------------------------------------------------------------
# 后端校验
# ------------------------------------------------------------
verify_backend() {
    local PLUGIN_DIR="$1"
    local FAILED=0
    local DID_CHECK=0

    # Python 语法
    local PY_FILES
    PY_FILES=$(find "$PLUGIN_DIR" -maxdepth 2 -type f -name "*.py" \
        -not -path "*/.venv/*" -not -path "*/node_modules/*" \
        -not -path "*/__pycache__/*" 2>/dev/null)

    if [ -n "$PY_FILES" ]; then
        DID_CHECK=1
        local PY_ERR; PY_ERR=$(mktemp)
        local PY_COUNT=0 PY_FAIL=0
        while IFS= read -r pyfile; do
            PY_COUNT=$((PY_COUNT + 1))
            if ! python3 -m py_compile "$pyfile" 2>"$PY_ERR"; then
                echo "    ✗ Python 语法错误: ${pyfile#$PLUGIN_DIR/}"
                sed 's/^/        /' "$PY_ERR"
                PY_FAIL=$((PY_FAIL + 1))
            fi
        done <<< "$PY_FILES"
        rm -f "$PY_ERR"
        if [ $PY_FAIL -gt 0 ]; then
            echo "    ✗ Python: $PY_FAIL/$PY_COUNT 个文件语法错误"
            FAILED=$((FAILED + 1))
        else
            echo "    ✓ Python 语法: $PY_COUNT 个文件全部通过"
        fi
    fi

    # requirements.txt
    if [ -f "$PLUGIN_DIR/requirements.txt" ]; then
        DID_CHECK=1
        local PIP_OUT; PIP_OUT=$(mktemp)
        local PIP_OK=0
        if python3 -m pip install --dry-run --quiet --disable-pip-version-check \
            -r "$PLUGIN_DIR/requirements.txt" >"$PIP_OUT" 2>&1; then
            PIP_OK=1
        elif python3 -m pip install --dry-run --quiet --disable-pip-version-check \
            --break-system-packages \
            -r "$PLUGIN_DIR/requirements.txt" >"$PIP_OUT" 2>&1; then
            PIP_OK=1
        fi
        local REQ_COUNT
        REQ_COUNT=$(grep -cvE '^\s*(#|$)' "$PLUGIN_DIR/requirements.txt" || true)
        if [ $PIP_OK -eq 1 ]; then
            echo "    ✓ requirements.txt: $REQ_COUNT 个依赖可解析"
        else
            if python3 - "$PLUGIN_DIR/requirements.txt" >"$PIP_OUT" 2>&1 <<'PYEOF'
import sys
from packaging.requirements import Requirement, InvalidRequirement
errors = 0
with open(sys.argv[1]) as f:
    for line in f:
        s = line.strip()
        if not s or s.startswith("#") or s.startswith("-"): continue
        try: Requirement(s)
        except InvalidRequirement as e:
            print(f"  无效需求: {s} -> {e}"); errors += 1
sys.exit(1 if errors else 0)
PYEOF
            then
                echo "    ✓ requirements.txt: $REQ_COUNT 个依赖格式有效（pip dry-run 不可用，已退回格式校验）"
            else
                echo "    ✗ requirements.txt 校验失败:"
                sed 's/^/        /' "$PIP_OUT" | tail -10
                FAILED=$((FAILED + 1))
            fi
        fi
        rm -f "$PIP_OUT"
    fi

    # Shell 脚本语法（不含 scripts/ 钩子目录，避免重复检查）
    local SH_FILES
    SH_FILES=$(find "$PLUGIN_DIR" -maxdepth 1 -type f -name "*.sh" 2>/dev/null)
    if [ -n "$SH_FILES" ]; then
        DID_CHECK=1
        local SH_ERR; SH_ERR=$(mktemp)
        local SH_COUNT=0 SH_FAIL=0
        while IFS= read -r shfile; do
            SH_COUNT=$((SH_COUNT + 1))
            if ! bash -n "$shfile" 2>"$SH_ERR"; then
                echo "    ✗ Shell 语法错误: ${shfile#$PLUGIN_DIR/}"
                sed 's/^/        /' "$SH_ERR"
                SH_FAIL=$((SH_FAIL + 1))
            fi
        done <<< "$SH_FILES"
        rm -f "$SH_ERR"
        if [ $SH_FAIL -gt 0 ]; then
            echo "    ✗ Shell: $SH_FAIL/$SH_COUNT 个脚本语法错误"
            FAILED=$((FAILED + 1))
        else
            echo "    ✓ Shell 脚本语法: $SH_COUNT 个文件全部通过"
        fi
    fi

    [ $DID_CHECK -eq 0 ] && return 0
    return $FAILED
}

# ------------------------------------------------------------
# 前端构建
# ------------------------------------------------------------
build_frontend() {
    local PLUGIN_DIR="$1"
    [ ! -f "$PLUGIN_DIR/package.json" ] && return 0

    local HAS_BUILD
    HAS_BUILD=$(python3 -c "import json; d=json.load(open('$PLUGIN_DIR/package.json')); print('1' if d.get('scripts',{}).get('build') else '')" 2>/dev/null)
    [ -z "$HAS_BUILD" ] && return 0

    if [ ! -d "$PLUGIN_DIR/node_modules" ]; then
        echo "    前端依赖未安装，正在安装..."
        if [ -f "$PLUGIN_DIR/package-lock.json" ]; then
            (cd "$PLUGIN_DIR" && npm ci --no-audit --no-fund) || return 1
        else
            (cd "$PLUGIN_DIR" && npm install --no-audit --no-fund) || return 1
        fi
    fi

    (cd "$PLUGIN_DIR" && npm run build) || return 1

    # 产物验证
    local ARTIFACTS=("ui/index.js")
    if [ -f "$PLUGIN_DIR/.axons-build" ]; then
        ARTIFACTS=()
        while IFS= read -r line || [ -n "$line" ]; do
            [[ -z "$line" || "$line" =~ ^# ]] && continue
            ARTIFACTS+=("$line")
        done < "$PLUGIN_DIR/.axons-build"
    fi
    local MISSING=0
    for art in "${ARTIFACTS[@]}"; do
        if [ ! -e "$PLUGIN_DIR/$art" ]; then
            echo "    ✗ 缺少前端产物: $art"; MISSING=$((MISSING + 1))
        else
            local SIZE; SIZE=$(du -h "$PLUGIN_DIR/$art" | cut -f1)
            echo "    ✓ 前端产物: $art ($SIZE)"
        fi
    done
    [ $MISSING -gt 0 ] && return 1
    return 0
}

# ------------------------------------------------------------
# 插件自定义钩子
# ------------------------------------------------------------
run_hook() {
    local PLUGIN_DIR="$1" HOOK="$2"
    local HOOK_PATH="$PLUGIN_DIR/scripts/$HOOK"
    [ ! -f "$HOOK_PATH" ] && return 0

    local PID PVER
    PID=$(python3 -c "import json; print(json.load(open('$PLUGIN_DIR/manifest.json'))['id'])" 2>/dev/null)
    PVER=$(python3 -c "import json; print(json.load(open('$PLUGIN_DIR/manifest.json'))['version'])" 2>/dev/null)

    echo "    → 执行插件钩子: scripts/$HOOK"
    PLUGIN_DIR="$PLUGIN_DIR" PLUGIN_ID="$PID" PLUGIN_VERSION="$PVER" \
        bash "$HOOK_PATH" || return 1
}

process_plugin() {
    local PLUGIN_DIR="$1"
    local REL="${PLUGIN_DIR#$REPO_ROOT/}"

    local PID
    PID=$(python3 -c "import json; print(json.load(open('$PLUGIN_DIR/manifest.json'))['id'])" 2>/dev/null) || PID="?"

    echo "==> [$PID]  $REL"

    local FAIL=0
    verify_backend "$PLUGIN_DIR" || FAIL=$((FAIL + 1))
    build_frontend "$PLUGIN_DIR" || FAIL=$((FAIL + 1))
    run_hook "$PLUGIN_DIR" "build.sh" || FAIL=$((FAIL + 1))

    # 纯静态插件提示
    if [ ! -f "$PLUGIN_DIR/package.json" ] \
       && [ ! -f "$PLUGIN_DIR/requirements.txt" ] \
       && [ -z "$(find "$PLUGIN_DIR" -maxdepth 2 -type f -name '*.py' -not -path '*/.venv/*' -not -path '*/__pycache__/*' 2>/dev/null)" ] \
       && [ -z "$(find "$PLUGIN_DIR" -maxdepth 1 -type f -name '*.sh' 2>/dev/null)" ] \
       && [ ! -f "$PLUGIN_DIR/scripts/build.sh" ]; then
        echo "    ⊘ 纯静态插件，无需构建/校验"
    fi
    return $FAIL
}

PLUGIN_DIRS=()
while IFS= read -r d; do
    [ -n "$d" ] && PLUGIN_DIRS+=("$d")
done < <(filter_plugins)

if [ ${#PLUGIN_DIRS[@]} -eq 0 ]; then
    echo "未匹配到任何插件"
    exit 1
fi

echo "=== Axons 插件校验/构建 ==="
echo "    扫描到 ${#PLUGIN_DIRS[@]} 个插件"
echo ""

SUCCESS=0
FAIL=0
for d in "${PLUGIN_DIRS[@]}"; do
    if process_plugin "$d"; then
        SUCCESS=$((SUCCESS + 1))
    else
        FAIL=$((FAIL + 1))
    fi
    echo ""
done

echo "=== 完成: ${SUCCESS} 成功, ${FAIL} 失败 ==="
[ $FAIL -eq 0 ]