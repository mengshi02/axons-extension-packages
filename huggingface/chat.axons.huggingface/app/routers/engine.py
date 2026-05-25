"""
Axons HuggingFace Plugin - 引擎状态与安装路由

/health, /api/engine/status, /api/engine/install, /api/engine/llama-server-path
"""

import os
import platform
import random
import shutil
import time
from typing import Optional

import httpx
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.config import (
    BIN_DIR,
    LLAMA_SERVER_BIN,
    _HF_CONFIG,
    _running_lock,
    _running_processes,
    _ensure_data_dirs,
)
from app.engine import (
    _check_metal_support,
    _compile_llama_cpp_with_metal,
    _download_llama_cpp_release,
    _find_llama_server,
    _install_llama_cpp_via_brew,
)

router = APIRouter()


@router.get("/health")
async def health():
    """健康检查端点，供 axons 平台轮询"""
    return {"status": "ok"}


# --- 引擎状态 ---


@router.get("/api/engine/status")
async def engine_status():
    """检测 llama.cpp 引擎状态

    返回：
    - installed: llama-server 可执行文件是否存在
    - path: 可执行文件路径
    - metal_support: 当前系统是否支持 Metal GPU 加速（macOS only）
    - running_models: 当前运行中的模型数量
    """
    server_path, has_metal = _find_llama_server()
    installed = server_path is not None

    with _running_lock:
        running_count = len(_running_processes)
        running_models = [
            {
                "name": name,
                "port": info["port"],
                "pid": info["process"].pid if info["process"].poll() is None else None,
            }
            for name, info in _running_processes.items()
            if info["process"].poll() is None
        ]

    return {
        "engine": {
            "type": "llama.cpp",
            "installed": installed,
            "path": server_path,
            "metal_support": has_metal,
            "running_models": running_models,
            "running_count": running_count,
        }
    }


@router.post("/api/engine/install")
async def engine_install(body: dict = None):
    """安装 llama-server 可执行文件

    macOS: 
    - Metal 可用 → 源码编译 llama.cpp（GGML_METAL=ON）
    - Metal 不可用或编译失败 → Homebrew 兜底
    Linux/Windows: 从 GitHub Release 下载预编译版
    
    支持 force=1 强制重装（清理旧的不完整安装后重新编译）。
    """
    force = body.get("force", False) if isinstance(body, dict) else False

    # 如果已经安装且非强制重装，直接返回
    existing, has_metal = _find_llama_server()
    if existing and not force:
        return {"status": "already_installed", "path": existing, "metal_support": has_metal}

    # 强制重装时清理插件 bin 目录下不完整的旧文件
    if force and BIN_DIR.exists():
        print(f"[axons-hf] 强制重装：清理旧文件 {BIN_DIR}...")
        # 只清理插件 bin 目录，不动 models 等其他数据
        for item in BIN_DIR.iterdir():
            try:
                if item.is_file():
                    item.unlink()
            except Exception as e:
                print(f"[axons-hf] 清理失败 {item}: {e}")

    _ensure_data_dirs()

    # 确定平台和架构
    system = platform.system()
    machine = platform.machine().lower()

    # macOS: Metal 可用则源码编译，否则 Homebrew 兜底
    if system == "Darwin":
        has_metal = _check_metal_support()

        # 策略1: Metal 可用 + 有编译工具 → 源码编译（Metal=ON）
        if has_metal and shutil.which("cmake") and shutil.which("git"):
            compile_result = _compile_llama_cpp_with_metal()
            if compile_result:
                return {
                    "status": "compiled",
                    "path": compile_result,
                    "metal_support": True,
                    "message": "llama-server 已从源码编译安装（Metal GPU 加速已开启）",
                }

        # 策略2: 从 GitHub Release 下载预编译包完整解压（含 dylib）
        dl_result = _download_llama_cpp_release()
        if dl_result:
            return {
                "status": "downloaded",
                "path": dl_result,
                "metal_support": has_metal,
                "message": f"llama-server 已从 GitHub Release 下载安装（Metal={has_metal}）",
            }

        # 策略3: Homebrew 兜底
        brew_result = _install_llama_cpp_via_brew()
        if brew_result:
            return {
                "status": "brew_installed",
                "path": brew_result,
                "metal_support": has_metal,
                "message": f"llama-server 已通过 Homebrew 安装（Metal={has_metal}）",
            }

        return JSONResponse(
            status_code=502,
            content={
                "error": "无法安装 llama-server：编译/下载/brew 均失败。"
                         "请安装 Homebrew (https://brew.sh) 或手动从 "
                         "https://github.com/ggml-org/llama.cpp/releases 下载。",
                "metal_support": has_metal,
            },
        )

    # Linux / Windows: 从 GitHub Release 下载预编译版
    # llama.cpp GitHub Release 命名规则
    # 参考: https://github.com/ggml-org/llama.cpp/releases
    if system == "Linux":
        if machine == "aarch64":
            asset_pattern = "llama-*-bin-linux-arm64.tar.gz"
        else:
            asset_pattern = "llama-*-bin-linux-x64.tar.gz"
    elif system == "Windows":
        asset_pattern = "llama-*-bin-win-x64.zip"
    else:
        return JSONResponse(
            status_code=501,
            content={"error": f"暂不支持的平台: {system}"},
        )

    # 使用 GitHub API 获取最新 release（带 token 避免 rate limit）
    import fnmatch

    release = None
    gh_token = os.environ.get("GITHUB_TOKEN", "") or _HF_CONFIG.get("hf_token", "")

    # 尝试带 token 的 API 调用（避免 rate limit）
    api_urls = [
        "https://api.github.com/repos/ggml-org/llama.cpp/releases/latest",
    ]

    # 使用 httpx 发起请求（支持代理、重试、HTTP/2）
    from download import _create_http_client

    try:
        client = _create_http_client(proxy=True, timeout=30)
        for api_url in api_urls:
            try:
                headers = {
                    "Accept": "application/vnd.github+json",
                    "User-Agent": "axons-huggingface-plugin",
                }
                if gh_token:
                    headers["Authorization"] = f"token {gh_token}"
                resp = client.get(api_url, headers=headers)
                resp.raise_for_status()
                release = resp.json()
                break
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 403:
                    # rate limited, 尝试下一个方式
                    continue
                raise
            except Exception:
                continue
    except Exception:
        pass
    finally:
        try:
            client.close()
        except Exception:
            pass

    # API 失败时，尝试直接构造下载 URL（基于已知的 release tag 格式）
    if not release:
        latest_tag = None
        try:
            client2 = _create_http_client(proxy=True, timeout=30)
            try:
                resp = client2.get(
                    "https://github.com/ggml-org/llama.cpp/releases",
                    headers={"User-Agent": "axons-huggingface-plugin"},
                )
                html = resp.text
                import re as _re
                tag_match = _re.search(r'/ggml-org/llama\.cpp/releases/tag/([^"<>]+)', html)
                if tag_match:
                    latest_tag = tag_match.group(1)
            finally:
                client2.close()
        except Exception:
            pass

        if latest_tag:
            # 直接构造下载 URL（asset 命名含 tag 的 b 前缀）
            constructed_url = None
            if system == "Darwin":
                if machine == "arm64":
                    constructed_url = f"https://github.com/ggml-org/llama.cpp/releases/download/{latest_tag}/llama-{latest_tag}-bin-macos-arm64.tar.gz"
                else:
                    constructed_url = f"https://github.com/ggml-org/llama.cpp/releases/download/{latest_tag}/llama-{latest_tag}-bin-macos-x64.tar.gz"
            elif system == "Linux":
                if machine == "aarch64":
                    constructed_url = f"https://github.com/ggml-org/llama.cpp/releases/download/{latest_tag}/llama-{latest_tag}-bin-linux-arm64.tar.gz"
                else:
                    constructed_url = f"https://github.com/ggml-org/llama.cpp/releases/download/{latest_tag}/llama-{latest_tag}-bin-linux-x64.tar.gz"
            elif system == "Windows":
                constructed_url = f"https://github.com/ggml-org/llama.cpp/releases/download/{latest_tag}/llama-{latest_tag}-bin-win-x64.zip"

            if constructed_url:
                # 验证 URL 可达
                try:
                    client3 = _create_http_client(proxy=True, timeout=15)
                    try:
                        resp = client3.head(constructed_url, headers={"User-Agent": "axons-huggingface-plugin"})
                        resp.raise_for_status()
                        # 可达，构造一个最小的 release 结构
                        asset_name_from_url = constructed_url.split("/")[-1]
                        release = {
                            "assets": [{"browser_download_url": constructed_url, "name": asset_name_from_url}],
                            "html_url": f"https://github.com/ggml-org/llama.cpp/releases/tag/{latest_tag}",
                        }
                    finally:
                        client3.close()
                except Exception:
                    pass

    if not release:
        return JSONResponse(
            status_code=502,
            content={
                "error": "无法获取 llama.cpp 发布信息（GitHub API 限流或网络问题）。"
                         "请设置 GITHUB_TOKEN 环境变量，或手动从 https://github.com/ggml-org/llama.cpp/releases 下载 llama-server "
                         f"放置到 {BIN_DIR}",
            },
        )

    # 找到匹配的 asset
    assets = release.get("assets", [])
    matching = [a for a in assets if fnmatch.fnmatch(a["name"], asset_pattern)]

    if not matching:
        return JSONResponse(
            status_code=404,
            content={
                "error": f"未找到匹配的预编译包 (pattern: {asset_pattern})",
                "release_url": release.get("html_url", ""),
            },
        )

    download_url = matching[0]["browser_download_url"]
    asset_name = matching[0]["name"]

    # 下载并解压（使用 httpx + 重试）
    import tempfile
    import zipfile

    max_retries = 3
    last_err = None

    for attempt in range(max_retries):
        if attempt > 0:
            backoff = min(2 ** (attempt - 1) + random.uniform(0, 1), 30)
            time.sleep(backoff)

        try:
            tmp_dir = tempfile.mkdtemp(prefix="axons-llama-")
            archive_path = os.path.join(tmp_dir, asset_name)

            # 使用 httpx 流式下载（支持代理 + 大文件）
            dl_client = _create_http_client(proxy=True, timeout=0)
            try:
                with dl_client.stream("GET", download_url, headers={"User-Agent": "axons-huggingface-plugin"}) as resp:
                    resp.raise_for_status()
                    with open(archive_path, "wb") as f:
                        for chunk in resp.iter_bytes(chunk_size=256 * 1024):
                            f.write(chunk)
            finally:
                dl_client.close()

            # 解压并找到 llama-server
            if asset_name.endswith(".zip"):
                with zipfile.ZipFile(archive_path, "r") as zf:
                    zf.extractall(tmp_dir)
            elif asset_name.endswith(".tar.gz"):
                subprocess.run(
                    ["tar", "xzf", archive_path, "-C", tmp_dir],
                    check=True,
                )

            # 在解压目录中搜索 llama-server
            server_binary = None
            for root, dirs, files in os.walk(tmp_dir):
                for f in files:
                    if f == LLAMA_SERVER_BIN or f == "llama-server":
                        server_binary = os.path.join(root, f)
                        break
                if server_binary:
                    break

            if not server_binary:
                shutil.rmtree(tmp_dir, ignore_errors=True)
                return JSONResponse(
                    status_code=500,
                    content={"error": "解压后未找到 llama-server 可执行文件"},
                )

            # 复制到 bin 目录（原子写入）
            from app.config import LLAMA_SERVER_PATH
            dest = str(LLAMA_SERVER_PATH)
            tmp_dest = dest + ".tmp"
            shutil.copy2(server_binary, tmp_dest)
            os.chmod(tmp_dest, 0o755)
            os.replace(tmp_dest, dest)

            # 清理临时目录
            shutil.rmtree(tmp_dir, ignore_errors=True)

            return {"status": "installed", "path": dest}

        except Exception as e:
            last_err = e
            # 清理可能残留的临时文件
            if "tmp_dir" in dir():
                shutil.rmtree(tmp_dir, ignore_errors=True)
            continue

    return JSONResponse(
        status_code=500,
        content={"error": f"下载/安装 llama-server 失败（重试 {max_retries} 次后）: {last_err}"},
    )


@router.get("/api/engine/llama-server-path")
async def llama_server_path():
    """返回 llama-server 可执行文件路径"""
    path, has_metal = _find_llama_server()
    return {"path": path, "installed": path is not None, "metal_support": has_metal}