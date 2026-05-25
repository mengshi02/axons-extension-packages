"""
Axons HuggingFace Plugin - llama-server 进程管理

包括：
- Metal GPU 支持检测
- llama-server 查找（插件 bin / 系统 PATH / Homebrew）
- 源码编译（Metal=ON）
- GitHub Release 下载安装
- Homebrew 安装
- 进程启停、端口分配、日志管理
"""

import asyncio
import io
import os
import platform
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Optional

import httpx

from app.config import (
    BIN_DIR,
    LLAMA_SERVER_BIN,
    LLAMA_SERVER_PATH,
    PLUGIN_DATA_DIR,
    _running_lock,
    _running_processes,
    BASE_PORT,
)


# ============================================================
# Metal GPU 支持检测
# ============================================================

def _check_metal_support() -> bool:
    """检测当前 macOS 系统是否支持 Metal GPU

    检测方法：
    1. sysctl -n hw.optional.arm64 == 1 → Apple Silicon（Metal 必可用）
    2. system_profiler SPDisplaysDataType 含 "Metal" → Intel Mac + Metal GPU
    3. 都不满足 → 无 Metal
    """
    if platform.system() != "Darwin":
        return False

    # Apple Silicon：arm64 → Metal 必可用
    try:
        result = subprocess.run(
            ["sysctl", "-n", "hw.optional.arm64"],
            capture_output=True, text=True, timeout=5,
        )
        if result.stdout.strip() == "1":
            return True
    except Exception:
        pass

    # Intel Mac：检查 GPU 是否支持 Metal
    try:
        result = subprocess.run(
            ["system_profiler", "SPDisplaysDataType"],
            capture_output=True, text=True, timeout=10,
        )
        if "Metal" in result.stdout:
            return True
    except Exception:
        pass

    return False


# ============================================================
# 源码编译 llama.cpp（Metal=ON）
# ============================================================

def _compile_llama_cpp_with_metal() -> Optional[str]:
    """从源码编译 llama.cpp 并开启 Metal GPU 加速

    流程：
    1. 检查编译依赖（cmake, git）
    2. git clone --depth 1 llama.cpp
    3. cmake -B build -DGGML_METAL=ON
    4. cmake --build build --config Release -j$(nproc)
    5. 拷贝 llama-server + dylib 到插件 bin 目录

    Returns:
        llama-server 路径（成功）或 None（失败）
    """
    # 检查编译依赖
    for tool in ("cmake", "git"):
        if not shutil.which(tool):
            # 尝试通过 brew 安装缺失依赖
            if shutil.which("brew"):
                try:
                    subprocess.run(["brew", "install", tool], check=True, timeout=120)
                except Exception:
                    print(f"[axons-hf] 无法安装 {tool}")
                    return None
            else:
                print(f"[axons-hf] 编译需要 {tool}，未安装且无 Homebrew")
                return None

    import tempfile
    build_dir = tempfile.mkdtemp(prefix="axons-llama-build-")
    try:
        # 克隆仓库
        print(f"[axons-hf] 克隆 llama.cpp 到 {build_dir}...")
        subprocess.run(
            ["git", "clone", "--depth", "1",
             "https://github.com/ggml-org/llama.cpp.git",
             os.path.join(build_dir, "llama.cpp")],
            check=True, timeout=120,
        )

        src_dir = os.path.join(build_dir, "llama.cpp")

        # 获取 CPU 核数用于并行编译
        ncpu = os.cpu_count() or 4

        # cmake 配置（开启 Metal）
        print(f"[axons-hf] cmake 配置（Metal=ON）...")
        subprocess.run(
            ["cmake", "-B", "build", "-DGGML_METAL=ON"],
            cwd=src_dir, check=True, timeout=60,
        )

        # 编译
        print(f"[axons-hf] 编译（-j{ncpu}）...")
        subprocess.run(
            ["cmake", "--build", "build", "--config", "Release", "-j", str(ncpu)],
            cwd=src_dir, check=True, timeout=600,
        )

        # 拷贝整个 build/bin 目录到插件 bin 目录
        # 包括：llama-server + dylib + Metal shader 缓存
        BIN_DIR.mkdir(parents=True, exist_ok=True)
        build_bin_dir = os.path.join(src_dir, "build", "bin")

        if os.path.isdir(build_bin_dir):
            # 拷贝 build/bin 下所有文件
            for item in os.listdir(build_bin_dir):
                src_item = os.path.join(build_bin_dir, item)
                dst_item = str(BIN_DIR / item)
                if os.path.isfile(src_item):
                    shutil.copy2(src_item, dst_item)
                    # 确保可执行文件有执行权限
                    if os.access(src_item, os.X_OK):
                        os.chmod(dst_item, 0o755)

        # 拷贝 build 目录下的所有 dylib（某些版本产物不在 bin/ 下）
        for root, dirs, files in os.walk(os.path.join(src_dir, "build")):
            for f in files:
                if f.endswith(".dylib"):
                    dylib_src = os.path.join(root, f)
                    shutil.copy2(dylib_src, str(BIN_DIR / f))

        # 拷贝 Metal shader 源文件（ggml-metal.metal）
        # llama.cpp Metal 后端在运行时需要 .metal shader 文件
        metal_shader_dir = os.path.join(src_dir, "ggml", "src", "ggml-metal")
        if os.path.isdir(metal_shader_dir):
            for f in os.listdir(metal_shader_dir):
                if f.endswith(".metal"):
                    shutil.copy2(
                        os.path.join(metal_shader_dir, f),
                        str(BIN_DIR / f),
                    )

        # 验证 llama-server 存在
        dest = str(LLAMA_SERVER_PATH)
        if not (os.path.isfile(dest) and os.access(dest, os.X_OK)):
            print("[axons-hf] 编译成功但未找到 llama-server 二进制")
            return None

        # 写入编译版本标记（用于诊断版本不匹配问题）
        try:
            tag_result = subprocess.run(
                ["git", "describe", "--tags", "--always"],
                cwd=src_dir, capture_output=True, text=True, timeout=5,
            )
            build_tag = tag_result.stdout.strip() or "unknown"
        except Exception:
            build_tag = "unknown"
        (BIN_DIR / "llama-server.build_tag").write_text(build_tag)

        print(f"[axons-hf] llama-server 编译安装完成: {dest} (Metal=ON, tag={build_tag})")
        return dest

    except subprocess.CalledProcessError as e:
        print(f"[axons-hf] 编译失败: {e}")
        return None
    except Exception as e:
        print(f"[axons-hf] 编译过程异常: {e}")
        return None
    finally:
        # 清理临时目录
        try:
            shutil.rmtree(build_dir, ignore_errors=True)
        except Exception:
            pass


# ============================================================
# 从 GitHub Release 下载预编译包
# ============================================================

def _download_llama_cpp_release() -> Optional[str]:
    """从 GitHub Release 下载 llama.cpp 预编译包并完整解压到插件 bin 目录

    macOS 预编译包包含 llama-server + 所有 dylib（含 libggml-metal），
    完整解压后 Metal 加速可用。

    Returns:
        llama-server 路径（成功）或 None（失败）
    """
    import fnmatch

    system = platform.system()
    machine = platform.machine().lower()

    # 确定 asset pattern
    if system == "Darwin":
        if machine == "arm64":
            asset_pattern = "llama-*-bin-macos-arm64.tar.gz"
        else:
            asset_pattern = "llama-*-bin-macos-x64.tar.gz"
    elif system == "Linux":
        if machine == "aarch64":
            asset_pattern = "llama-*-bin-linux-arm64.tar.gz"
        else:
            asset_pattern = "llama-*-bin-linux-x64.tar.gz"
    elif system == "Windows":
            asset_pattern = "llama-*-bin-win-x64.zip"
    else:
        return None

    # 获取最新 release 信息
    release = None
    gh_token = os.environ.get("GITHUB_TOKEN", "")
    from download import _create_http_client

    try:
        client = _create_http_client(proxy=True, timeout=30)
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "axons-huggingface-plugin",
        }
        if gh_token:
            headers["Authorization"] = f"token {gh_token}"
        try:
            resp = client.get(
                "https://api.github.com/repos/ggml-org/llama.cpp/releases/latest",
                headers=headers,
            )
            resp.raise_for_status()
            release = resp.json()
        except Exception:
            pass
    finally:
        try:
            client.close()
        except Exception:
            pass

    # API 失败时，从 releases 页面构造下载 URL
    download_url = ""
    if not release:
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
                    # asset 命名: llama-{tag}-bin-macos-arm64.tar.gz，tag 含 b 前缀
                    if system == "Darwin":
                        if machine == "arm64":
                            download_url = f"https://github.com/ggml-org/llama.cpp/releases/download/{latest_tag}/llama-{latest_tag}-bin-macos-arm64.tar.gz"
                        else:
                            download_url = f"https://github.com/ggml-org/llama.cpp/releases/download/{latest_tag}/llama-{latest_tag}-bin-macos-x64.tar.gz"
                    elif system == "Linux":
                        if machine == "aarch64":
                            download_url = f"https://github.com/ggml-org/llama.cpp/releases/download/{latest_tag}/llama-{latest_tag}-bin-linux-arm64.tar.gz"
                        else:
                            download_url = f"https://github.com/ggml-org/llama.cpp/releases/download/{latest_tag}/llama-{latest_tag}-bin-linux-x64.tar.gz"
                    elif system == "Windows":
                        download_url = f"https://github.com/ggml-org/llama.cpp/releases/download/{latest_tag}/llama-{latest_tag}-bin-win-x64.zip"
            finally:
                client2.close()
        except Exception:
            pass

    # 如果 API 成功，从 release 的 assets 中找匹配的 URL
    if release and not download_url:
        assets = release.get("assets", [])
        matching = [a for a in assets if fnmatch.fnmatch(a["name"], asset_pattern)]
        if matching:
            download_url = matching[0]["browser_download_url"]

    if not download_url:
        print("[axons-hf] 无法获取 llama.cpp 发布信息")
        return None

    # 下载并解压
    import tempfile
    tmp_dir = tempfile.mkdtemp(prefix="axons-llama-dl-")
    try:
        filename = download_url.split("/")[-1]
        archive_path = os.path.join(tmp_dir, filename)

        print(f"[axons-hf] 下载 {download_url} ...")
        # 使用 httpx 直接下载（支持代理）
        dl_client = _create_http_client(proxy=True, timeout=300)
        try:
            resp = dl_client.get(download_url, headers={"User-Agent": "axons-huggingface-plugin"})
            resp.raise_for_status()
            with open(archive_path, "wb") as f:
                f.write(resp.content)
        finally:
            try:
                dl_client.close()
            except Exception:
                pass

        # 解压
        BIN_DIR.mkdir(parents=True, exist_ok=True)
        if filename.endswith(".tar.gz"):
            subprocess.run(
                ["tar", "xzf", archive_path, "-C", tmp_dir],
                check=True, timeout=60,
            )
        elif filename.endswith(".zip"):
            subprocess.run(
                ["unzip", "-q", "-o", archive_path, "-d", tmp_dir],
                check=True, timeout=60,
            )

        # 找到解压后的 llama 子目录（如 llama-b9279/）
        extracted_dir = None
        for item in os.listdir(tmp_dir):
            item_path = os.path.join(tmp_dir, item)
            if os.path.isdir(item_path) and item.startswith("llama-"):
                extracted_dir = item_path
                break

        if not extracted_dir:
            # 可能直接解压到 tmp_dir 根目录
            extracted_dir = tmp_dir

        # 完整拷贝所有文件到插件 bin 目录
        for item in os.listdir(extracted_dir):
            src = os.path.join(extracted_dir, item)
            dst = str(BIN_DIR / item)
            if os.path.isfile(src):
                shutil.copy2(src, dst)
                if os.access(src, os.X_OK):
                    os.chmod(dst, 0o755)

        # 验证 llama-server
        if not (LLAMA_SERVER_PATH.exists() and os.access(str(LLAMA_SERVER_PATH), os.X_OK)):
            print("[axons-hf] 解压后未找到 llama-server")
            return None

        # 写入版本标记
        build_tag = release.get("tag_name", "") if release else "unknown"
        (BIN_DIR / "llama-server.build_tag").write_text(build_tag)
        print(f"[axons-hf] llama-server 下载安装完成: {LLAMA_SERVER_PATH} (tag={build_tag})")
        return str(LLAMA_SERVER_PATH)

    except Exception as e:
        print(f"[axons-hf] 下载安装异常: {e}")
        return None
    finally:
        try:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception:
            pass


# ============================================================
# Homebrew 安装
# ============================================================

def _install_llama_cpp_via_brew() -> Optional[str]:
    """通过 Homebrew 安装 llama.cpp

    Returns:
        llama-server 路径（成功）或 None（失败/无 brew）
    """
    if not shutil.which("brew"):
        return None

    try:
        print("[axons-hf] 使用 Homebrew 安装 llama.cpp...")
        subprocess.run(["brew", "install", "llama.cpp"], check=True, timeout=300)
    except subprocess.CalledProcessError as e:
        print(f"[axons-hf] brew install 失败: {e}")
        return None

    # brew 安装后查找 llama-server
    found = shutil.which("llama-server")
    if found:
        print(f"[axons-hf] llama-server brew 安装完成: {found}")
        return found

    # 桌面 app PATH 可能不含 brew 路径，显式查找
    brew_paths = []
    if platform.machine() == "arm64":
        brew_paths.append("/opt/homebrew/bin/llama-server")
    brew_paths.append("/usr/local/bin/llama-server")
    for bp in brew_paths:
        if os.path.isfile(bp) and os.access(bp, os.X_OK):
            print(f"[axons-hf] llama-server brew 安装完成: {bp}")
            return bp

    print("[axons-hf] brew install 完成 but llama-server 未找到")
    return None


# ============================================================
# 查找 llama-server
# ============================================================

def _find_llama_server() -> tuple:
    """查找 llama-server 可执行文件路径 + Metal 支持状态

    返回 (server_path, has_metal):
    - server_path: llama-server 可执行文件路径，None 表示未安装
    - has_metal: 当前系统是否支持 Metal GPU 加速

    优先级：
    1. 插件 bin 目录下的完整安装（llama-server + 配套 dylib）
       — 这是自编译或 GitHub Release 下载的版本，dylib 版本匹配
    2. 系统 PATH 中的 llama-server（包括 brew 安装的）
    3. Homebrew 显式路径（桌面 app PATH 可能不含 /opt/homebrew/bin）

    关键：插件 bin 目录优先于 brew，否则 brew 的 llama-server
    会加载 bin 目录下的不同版本 dylib 导致符号冲突崩溃。
    """
    has_metal = _check_metal_support()

    # 最高优先级：插件 bin 目录下的完整安装（llama-server + 配套 dylib）
    if LLAMA_SERVER_PATH.exists():
        # 完整性校验：检查是否有配套的 dylib
        if platform.system() == "Darwin":
            has_dylib = any(
                f.endswith(".dylib")
                for f in os.listdir(str(BIN_DIR))
                if os.path.isfile(str(BIN_DIR / f))
            )
            if has_dylib:
                print(f"[axons-hf] 使用插件 bin 目录下的 llama-server: {LLAMA_SERVER_PATH}")
                return str(LLAMA_SERVER_PATH), has_metal
            # 无 dylib 视为不完整，继续查找其他来源
            print("[axons-hf] 插件 bin 目录下的 llama-server 缺少 dylib，视为不完整安装")
        else:
            # Linux: bin 目录下的直接可用
            return str(LLAMA_SERVER_PATH), has_metal

    # 次优先级：系统 PATH
    found = shutil.which("llama-server")
    if found:
        return found, has_metal

    # macOS: Homebrew 显式路径（桌面 app 的 PATH 可能不含 brew 路径）
    if platform.system() == "Darwin":
        brew_paths = []
        if platform.machine() == "arm64":
            brew_paths.append("/opt/homebrew/bin/llama-server")
        brew_paths.append("/usr/local/bin/llama-server")
        for bp in brew_paths:
            if os.path.isfile(bp) and os.access(bp, os.X_OK):
                return bp, has_metal

    return None, has_metal


# ============================================================
# 端口分配
# ============================================================

def _allocate_port() -> int:
    """从端口池分配一个可用端口"""
    with _running_lock:
        used = {info["port"] for info in _running_processes.values()}
    port = BASE_PORT
    while port in used:
        port += 1
    return port


# ============================================================
# 日志管理
# ============================================================

def _get_log_dir() -> Path:
    """返回日志目录，不存在则创建"""
    d = PLUGIN_DATA_DIR / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _read_log_tail(log_name: str, max_lines: int = 30) -> str:
    """读取日志文件的尾部内容用于诊断

    优先读取 stderr 日志（含错误信息），其次 stdout 日志。
    """
    log_dir = _get_log_dir()
    # 先尝试 stderr 日志
    for suffix in ("err", "out"):
        path = log_dir / f"{log_name}.{suffix}.log"
        if path.exists():
            try:
                lines = path.read_text(errors="replace").splitlines()
                return "\n".join(lines[-max_lines:])
            except Exception:
                continue
    return ""


# ============================================================
# 进程启停
# ============================================================

def _spawn_detached(argv: list, log_name: str = "", **kwargs) -> subprocess.Popen:
    """以脱离当前进程树的方式启动子进程

    Args:
        argv: 命令行参数列表
        log_name: 日志文件名（不含扩展名），为空则不写日志
    """
    stdout_dest = subprocess.DEVNULL
    stderr_dest = subprocess.DEVNULL

    if log_name:
        log_dir = _get_log_dir()
        stdout_dest = open(log_dir / f"{log_name}.out.log", "w")
        stderr_dest = open(log_dir / f"{log_name}.err.log", "w")

    try:
        if platform.system() == "Windows":
            DETACHED_PROCESS = 0x00000008
            CREATE_NEW_PROCESS_GROUP = 0x00000200
            proc = subprocess.Popen(
                argv,
                creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP,
                close_fds=True,
                stdin=subprocess.DEVNULL,
                stdout=stdout_dest,
                stderr=stderr_dest,
                **kwargs,
            )
        else:
            proc = subprocess.Popen(
                argv,
                stdin=subprocess.DEVNULL,
                stdout=stdout_dest,
                stderr=stderr_dest,
                start_new_session=True,
                close_fds=True,
                **kwargs,
            )
        return proc
    finally:
        # Popen 已接管 fd，关闭我们这边的引用
        if isinstance(stdout_dest, io.IOBase):
            stdout_dest.close()
        if isinstance(stderr_dest, io.IOBase):
            stderr_dest.close()


async def _wait_server_ready(port: int, timeout_seconds: float = 15.0) -> bool:
    """轮询 /health 等待 llama-server 就绪"""
    deadline = asyncio.get_event_loop().time() + timeout_seconds
    timeout = httpx.Timeout(2.0, connect=1.5)
    async with httpx.AsyncClient(timeout=timeout) as client:
        while asyncio.get_event_loop().time() < deadline:
            try:
                resp = await client.get(f"http://127.0.0.1:{port}/health")
                if resp.status_code == 200:
                    return True
            except httpx.HTTPError:
                pass
            await asyncio.sleep(0.5)
    return False


def _stop_process(model_name: str) -> bool:
    """停止指定模型的 llama-server 进程

    优雅停止：SIGTERM → 等 5s → SIGKILL
    """
    with _running_lock:
        info = _running_processes.pop(model_name, None)
    if not info:
        return False

    process: subprocess.Popen = info["process"]
    try:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            try:
                process.wait(timeout=3)
            except Exception:
                pass
    except Exception:
        pass
    return True


def _stop_all_processes():
    """停止所有运行中的 llama-server 进程"""
    with _running_lock:
        names = list(_running_processes.keys())
    for name in names:
        _stop_process(name)