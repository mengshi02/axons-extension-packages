#!/bin/bash
# Axons HuggingFace - macOS / Linux 安装脚本
#
# 设计原则：
# - 本脚本负责安装 Python 依赖 + 下载 llama-server 可执行文件
# - llama-server 也可由用户自行安装（在 PATH 中即可），本脚本仅作便捷安装
# - 即使 llama-server 未安装，也以 exit 0 结束：插件本身已装好，
#   面板会检测并引导用户点击"安装 llama-server"按钮
set -e

echo "=== Axons HuggingFace 安装 ==="

# ------------------------------------------------------------
# 1. 检查 Python 3.9+
# ------------------------------------------------------------
echo "[1/3] 检查 Python 环境..."
if command -v python3 &>/dev/null; then
    PY_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
    PY_MAJOR=$(echo "$PY_VERSION" | cut -d. -f1)
    PY_MINOR=$(echo "$PY_VERSION" | cut -d. -f2)
    if [ "$PY_MAJOR" -lt 3 ] || ([ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 9 ]); then
        echo "错误: 需要 Python 3.9+，当前版本 $PY_VERSION"
        exit 1
    fi
    echo "  Python $PY_VERSION ✓"
else
    echo "错误: 未找到 python3，请先安装 Python 3.9+"
    exit 1
fi

# ------------------------------------------------------------
# 2. venv + 依赖
# ------------------------------------------------------------
echo "[2/3] 安装 Python 依赖..."
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
python3 -m venv "$SCRIPT_DIR/.venv"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/.venv/bin/activate"
pip install --quiet --upgrade pip
pip install --quiet -r "$SCRIPT_DIR/requirements.txt"
echo "  依赖安装完成 ✓"

# ------------------------------------------------------------
# 3. 检查/下载 llama-server
# ------------------------------------------------------------
echo "[3/3] 检查 llama-server..."

# 插件数据目录：优先使用宿主注入的环境变量
DATA_DIR="${AXONS_PLUGIN_DATA_DIR:-$HOME/.axons/plugins/data/${AXONS_PLUGIN_ID:-chat.axons.huggingface}}"
BIN_DIR="$DATA_DIR/bin"
BIN_PATH="$BIN_DIR/llama-server"

# 如果 PATH 中已有，直接跳过
if command -v llama-server &>/dev/null; then
    echo "  llama-server 已在 PATH 中 ✓ ($(which llama-server))"
    echo ""
    echo "=== 安装完成 ==="
    exit 0
fi

# 如果插件 bin 目录已有，也跳过
if [ -x "$BIN_PATH" ]; then
    echo "  llama-server 已安装 ✓ ($BIN_PATH)"
    echo ""
    echo "=== 安装完成 ==="
    exit 0
fi

# 尝试从 GitHub Release 下载
echo "  尝试从 llama.cpp GitHub Release 下载..."

# 确定平台
OS="$(uname -s)"
ARCH="$(uname -m)"

if [ "$OS" = "Darwin" ]; then
    # macOS 安装策略（优先级从高到低）：
    #   1. Metal GPU 可用 + cmake/git 可用 → 源码编译（Metal=ON）
    #   2. 从 GitHub Release 下载预编译包完整解压（含 dylib，Metal 可用）
    #   3. 有 Homebrew → brew install llama.cpp（兜底）
    #
    # Metal 检测方法：
    #   - sysctl -n hw.optional.arm64 == 1 → Apple Silicon（Metal 必可用）
    #   - system_profiler SPDisplaysDataType 含 "Metal" → Intel Mac + Metal GPU

    HAS_METAL=false
    COMPILE_OK=false

    # 检测 Metal GPU
    if [ "$(sysctl -n hw.optional.arm64 2>/dev/null)" = "1" ]; then
        HAS_METAL=true
        echo "  检测到 Apple Silicon (arm64)，Metal GPU 可用 ✓"
    else
        DISPLAY_INFO="$(system_profiler SPDisplaysDataType 2>/dev/null)"
        if echo "$DISPLAY_INFO" | grep -q "Metal"; then
            HAS_METAL=true
            echo "  检测到 Metal 支持的 GPU ✓"
        else
            echo "  未检测到 Metal GPU"
        fi
    fi

    # ---- 清理旧的不完整安装 ----
    if [ -d "$BIN_DIR" ] && [ -x "$BIN_PATH" ]; then
        DYLIB_COUNT="$(find "$BIN_DIR" -name "*.dylib" -type f 2>/dev/null | wc -l | tr -d ' ')"
        if [ "$DYLIB_COUNT" -eq 0 ]; then
            echo "  检测到不完整的旧安装（缺少 dylib），清理..."
            rm -f "$BIN_DIR/llama-server"
            rm -f "$BIN_DIR/llama-server.build_tag"
        fi
    fi

    # ---- 策略 1：Metal 可用 + 有编译工具 → 源码编译 ----
    if [ "$HAS_METAL" = true ] && command -v cmake &>/dev/null && command -v git &>/dev/null; then
        echo ""
        echo "  策略1: 从源码编译 llama.cpp（Metal=ON）..."
        BUILD_TMP="$(mktemp -d /tmp/axons-llama-build-XXXXXX)"
        if git clone --depth 1 https://github.com/ggml-org/llama.cpp.git "$BUILD_TMP/llama.cpp" 2>&1; then
            echo "  编译中（Metal=ON, -j$(sysctl -n hw.ncpu)）..."
            cd "$BUILD_TMP/llama.cpp"
            if cmake -B build -DGGML_METAL=ON 2>&1 && \
               cmake --build build --config Release -j"$(sysctl -n hw.ncpu)" 2>&1; then
                mkdir -p "$BIN_DIR"
                # 拷贝 build/bin 下所有文件
                [ -d "build/bin" ] && cp -a build/bin/. "$BIN_DIR/"
                # 拷贝散落在 build/ 下的 dylib
                find build -maxdepth 3 -name "*.dylib" -exec cp {} "$BIN_DIR/" \; 2>/dev/null || true
                # 拷贝 Metal shader 源文件
                find ggml/src/ggml-metal -name "*.metal" -exec cp {} "$BIN_DIR/" \; 2>/dev/null || true

                if [ -x "$BIN_PATH" ]; then
                    LLAMA_TAG="$(git describe --tags --always 2>/dev/null || echo 'unknown')"
                    echo "$LLAMA_TAG" > "$BIN_DIR/llama-server.build_tag"
                    echo "  llama-server 编译安装完成 ✓ ($BIN_PATH, Metal=ON, tag=$LLAMA_TAG)"
                    COMPILE_OK=true
                else
                    echo "  ⚠ 编译成功但未找到 llama-server 二进制"
                fi
            else
                echo "  ⚠ 编译失败"
            fi
            cd - >/dev/null
        else
            echo "  ⚠ 克隆仓库失败"
        fi
        rm -rf "$BUILD_TMP"
    elif [ "$HAS_METAL" = true ]; then
        echo "  ⚠ Metal 可用但缺少 cmake/git，跳过编译，尝试下载预编译包"
    fi

    # ---- 策略 2：编译未成功 → 从 GitHub Release 下载预编译包完整解压 ----
    if [ "$COMPILE_OK" = false ]; then
        echo ""
        echo "  策略2: 从 GitHub Release 下载预编译包..."

        # 确定平台 asset pattern
        if [ "$ARCH" = "arm64" ]; then
            ASSET_PATTERN="llama-*-bin-macos-arm64.tar.gz"
        else
            ASSET_PATTERN="llama-*-bin-macos-x64.tar.gz"
        fi

        # 获取最新 release tag
        RELEASES_HTML="$(curl -fsSL --max-time 30 --retry 3 --retry-delay 2 \
            -H "User-Agent: axons-huggingface-plugin" \
            "https://github.com/ggml-org/llama.cpp/releases" 2>/dev/null || echo "")"

        LATEST_TAG=""
        DOWNLOAD_URL=""
        if [ -n "$RELEASES_HTML" ]; then
            LATEST_TAG="$(echo "$RELEASES_HTML" | python3 -c "
import sys, re
html = sys.stdin.read()
m = re.search(r'/ggml-org/llama.cpp/releases/tag/([^\"<>]+)', html)
if m: print(m.group(1))
" 2>/dev/null || echo "")"
        fi

        if [ -n "$LATEST_TAG" ]; then
            # GitHub Release asset 命名: llama-{tag}-bin-macos-arm64.tar.gz
            # tag 本身含 b 前缀（如 b9279），asset 名也含 b（如 llama-b9279-bin-...）
            # 所以直接用 LATEST_TAG 拼接，不再去掉 b
            if [ "$ARCH" = "arm64" ]; then
                DOWNLOAD_URL="https://github.com/ggml-org/llama.cpp/releases/download/${LATEST_TAG}/llama-${LATEST_TAG}-bin-macos-arm64.tar.gz"
            else
                DOWNLOAD_URL="https://github.com/ggml-org/llama.cpp/releases/download/${LATEST_TAG}/llama-${LATEST_TAG}-bin-macos-x64.tar.gz"
            fi
        fi

        if [ -n "$DOWNLOAD_URL" ]; then
            echo "  下载 $DOWNLOAD_URL ..."
            DL_TMP="$(mktemp -d /tmp/axons-llama-dl-XXXXXX)"
            ARCHIVE_PATH="$DL_TMP/llama-macos.tar.gz"
            if curl -fSL --progress-bar --max-time 300 -o "$ARCHIVE_PATH" "$DOWNLOAD_URL" 2>&1; then
                mkdir -p "$BIN_DIR"
                tar xzf "$ARCHIVE_PATH" -C "$DL_TMP"
                # 预编译包结构: llama-{tag}/llama-server, llama-{tag}/*.dylib
                # 完整拷贝所有文件到 bin 目录
                EXTRACTED_DIR="$(find "$DL_TMP" -maxdepth 1 -type d -name "llama-*" | head -1)"
                if [ -n "$EXTRACTED_DIR" ] && [ -d "$EXTRACTED_DIR" ]; then
                    # 拷贝所有二进制和 dylib
                    for f in "$EXTRACTED_DIR"/*; do
                        [ -f "$f" ] && cp "$f" "$BIN_DIR/"
                    done
                    if [ -x "$BIN_PATH" ]; then
                        echo "$LATEST_TAG" > "$BIN_DIR/llama-server.build_tag"
                        echo "  llama-server 下载安装完成 ✓ ($BIN_PATH, tag=$LATEST_TAG)"
                        COMPILE_OK=true
                    else
                        echo "  ⚠ 解压后未找到 llama-server"
                    fi
                else
                    echo "  ⚠ 解压后未找到预期目录结构"
                fi
            else
                echo "  ⚠ 下载失败"
            fi
            rm -rf "$DL_TMP"
        else
            echo "  ⚠ 无法获取下载 URL"
        fi
    fi

    # ---- 策略 3：下载也失败 → brew 兜底 ----
    if [ "$COMPILE_OK" = false ]; then
        echo ""
        echo "  策略3: Homebrew 兜底..."
        if command -v brew &>/dev/null; then
            echo "  使用 Homebrew 安装 llama.cpp..."
            brew install llama.cpp
            if command -v llama-server &>/dev/null; then
                echo "  llama-server 安装完成 ✓ ($(which llama-server))"
            else
                echo "  ⚠ brew install 完成 but llama-server 未在 PATH 中"
                echo "    请确认 Homebrew 已正确配置"
            fi
        else
            echo "  ⚠ 所有安装策略均失败"
            echo "    请选择以下方式之一安装 llama-server："
            echo "    1. 安装 Homebrew (https://brew.sh) 后运行: brew install llama.cpp"
            echo "    2. 手动从 https://github.com/ggml-org/llama.cpp/releases 下载"
            echo "    3. 安装 cmake+git 后重新运行此脚本（将自动编译）"
        fi
    fi

    echo ""
    echo "=== 安装完成 ==="
    exit 0
elif [ "$OS" = "Linux" ]; then
    if [ "$ARCH" = "aarch64" ]; then
        ASSET_PATTERN="llama-*-bin-linux-arm64.tar.gz"
    else
        ASSET_PATTERN="llama-*-bin-linux-x64.tar.gz"
    fi
else
    echo "  ⚠ 不支持自动下载的平台: $OS"
    echo "    请手动下载 llama-server: https://github.com/ggml-org/llama.cpp/releases"
    echo "    放置到 $BIN_PATH 或加入 PATH"
    echo ""
    echo "=== 安装完成（llama-server 需手动安装）==="
    exit 0
fi

# 获取最新 release
echo "  获取 llama.cpp 最新发布信息..."

# 方式1：用 GitHub API（如果设了 GITHUB_TOKEN 则用它避免限流）
GH_TOKEN="${GITHUB_TOKEN:-}"
RELEASE_JSON=""

if [ -n "$GH_TOKEN" ]; then
    RELEASE_JSON=$(curl -fsSL --max-time 30 --retry 3 --retry-delay 2 \
        -H "Accept: application/vnd.github+json" \
        -H "Authorization: token $GH_TOKEN" \
        -H "User-Agent: axons-huggingface-plugin" \
        "https://api.github.com/repos/ggml-org/llama.cpp/releases/latest" 2>/dev/null || echo "")
fi

# 方式2：匿名 API（可能被限流）
if [ -z "$RELEASE_JSON" ]; then
    RELEASE_JSON=$(curl -fsSL --max-time 30 --retry 3 --retry-delay 2 \
        -H "Accept: application/vnd.github+json" \
        -H "User-Agent: axons-huggingface-plugin" \
        "https://api.github.com/repos/ggml-org/llama.cpp/releases/latest" 2>/dev/null || echo "")
fi

# 方式3：从 releases 页面 HTML 提取 tag，直接构造下载 URL（不走 API）
if [ -z "$RELEASE_JSON" ]; then
    echo "  API 限流，尝试从 releases 页面获取..."
    RELEASES_HTML=$(curl -fsSL --max-time 30 --retry 3 --retry-delay 2 \
        -H "User-Agent: axons-huggingface-plugin" \
        "https://github.com/ggml-org/llama.cpp/releases" 2>/dev/null || echo "")
    if [ -n "$RELEASES_HTML" ]; then
        LATEST_TAG=$(echo "$RELEASES_HTML" | python3 -c "
import sys, re
html = sys.stdin.read()
m = re.search(r'/ggml-org/llama.cpp/releases/tag/([^\"<>]+)', html)
if m: print(m.group(1))
" 2>/dev/null || echo "")
        if [ -n "$LATEST_TAG" ]; then
            echo "  最新版本: $LATEST_TAG"
            # 直接构造下载 URL，不走 API
            # GitHub Release asset 命名规则: llama-{tag}-{platform}.{ext}
            # 将 tag 中的 'b' 前缀去掉（如 b6145 → 6145）
            TAG_NUM=$(echo "$LATEST_TAG" | sed 's/^b//')
            if [ "$OS" = "Darwin" ]; then
                if [ "$ARCH" = "arm64" ]; then
                    CONSTRUCTED_URL="https://github.com/ggml-org/llama.cpp/releases/download/${LATEST_TAG}/llama-${TAG_NUM}-bin-macos-arm64.tar.gz"
                else
                    CONSTRUCTED_URL="https://github.com/ggml-org/llama.cpp/releases/download/${LATEST_TAG}/llama-${TAG_NUM}-bin-macos-x64.tar.gz"
                fi
            elif [ "$OS" = "Linux" ]; then
                if [ "$ARCH" = "aarch64" ]; then
                    CONSTRUCTED_URL="https://github.com/ggml-org/llama.cpp/releases/download/${LATEST_TAG}/llama-${TAG_NUM}-bin-linux-arm64.tar.gz"
                else
                    CONSTRUCTED_URL="https://github.com/ggml-org/llama.cpp/releases/download/${LATEST_TAG}/llama-${TAG_NUM}-bin-linux-x64.tar.gz"
                fi
            fi
        fi
    fi
fi

# 从 JSON 中找 asset URL，或用直接构造的 URL
DOWNLOAD_URL=""
if [ -n "$RELEASE_JSON" ]; then
    DOWNLOAD_URL=$(echo "$RELEASE_JSON" | python3 -c "
import sys, json, fnmatch
data = json.load(sys.stdin)
for a in data.get('assets', []):
    if fnmatch.fnmatch(a['name'], '$ASSET_PATTERN'):
        print(a['browser_download_url'])
        break
" 2>/dev/null || echo "")
fi

# 如果 API 没拿到 URL，尝试直接构造的 URL
if [ -z "$DOWNLOAD_URL" ] && [ -n "$CONSTRUCTED_URL" ]; then
    echo "  使用构造的下载 URL: $CONSTRUCTED_URL"
    # 验证 URL 是否可达
    if curl -fsSL --head --max-time 10 "$CONSTRUCTED_URL" >/dev/null 2>&1; then
        DOWNLOAD_URL="$CONSTRUCTED_URL"
    else
        echo "  ⚠ 构造的 URL 不可达，尝试从 release 页面解析..."
        # 最后兜底：从 release 页面 HTML 解析 asset 列表
        RELEASE_PAGE_HTML=$(curl -fsSL --max-time 30 --retry 2 \
            -H "User-Agent: axons-huggingface-plugin" \
            "https://github.com/ggml-org/llama.cpp/releases/tag/${LATEST_TAG}" 2>/dev/null || echo "")
        if [ -n "$RELEASE_PAGE_HTML" ]; then
            DOWNLOAD_URL=$(echo "$RELEASE_PAGE_HTML" | python3 -c "
import sys, re
html = sys.stdin.read()
# 匹配 href 中包含 ASSET_PATTERN 的链接
pattern = r'href=\"(https://github\.com/ggml-org/llama.cpp/releases/download/[^\"]*$(echo $ASSET_PATTERN | sed 's/\*/[^\"]*/g'))\"'
for m in re.finditer(pattern, html):
    print(m.group(1))
    break
" 2>/dev/null || echo "")
        fi
    fi
fi

if [ -z "$DOWNLOAD_URL" ]; then
    echo "  ⚠ 未找到匹配的预编译包 ($ASSET_PATTERN)"
    echo "    请手动下载 llama-server: https://github.com/ggml-org/llama.cpp/releases"
    echo ""
    echo "=== 安装完成（llama-server 需手动安装）==="
    exit 0
fi

# 下载并解压
TMP_DIR=$(mktemp -d /tmp/axons-llama-XXXXXX)
FILENAME=$(basename "$DOWNLOAD_URL")
ARCHIVE_PATH="$TMP_DIR/$FILENAME"

echo "  下载 $DOWNLOAD_URL ..."
curl -fSL --progress-bar --max-time 300 -o "$ARCHIVE_PATH" "$DOWNLOAD_URL"

mkdir -p "$BIN_DIR"

if [[ "$FILENAME" == *.zip ]]; then
    unzip -q -o "$ARCHIVE_PATH" -d "$TMP_DIR"
elif [[ "$FILENAME" == *.tar.gz ]]; then
    tar xzf "$ARCHIVE_PATH" -C "$TMP_DIR"
fi

# 搜索 llama-server
FOUND_BIN=$(find "$TMP_DIR" -name "llama-server" -type f | head -1)

if [ -n "$FOUND_BIN" ]; then
    cp "$FOUND_BIN" "$BIN_PATH"
    chmod +x "$BIN_PATH"
    echo "  llama-server 安装完成 ✓ ($BIN_PATH)"
else
    echo "  ⚠ 解压后未找到 llama-server"
    echo "    请手动下载: https://github.com/ggml-org/llama.cpp/releases"
fi

# 清理
rm -rf "$TMP_DIR"

echo ""
echo "=== 安装完成 ==="
exit 0