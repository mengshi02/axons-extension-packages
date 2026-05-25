"""
Axons HuggingFace Plugin - 模型运行管理路由

/api/models/run, /api/models/stop, /api/models/delete,
/api/models/logs, /api/models/config, /api/models/defaults,
/api/models/register-to-axons
"""

import os
import platform
import time

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from app.config import (
    LLAMA_SERVER_PATH,
    MODELS_DIR,
    _running_lock,
    _running_processes,
)
from app.engine import (
    _allocate_port,
    _find_llama_server,
    _get_log_dir,
    _read_log_tail,
    _spawn_detached,
    _stop_process,
    _wait_server_ready,
)
from app.metadata import _load_metadata, _remove_model_metadata
from app.model_defaults import (
    _get_model_run_defaults,
    _load_model_configs,
    _save_model_configs,
)
from app.axons import _register_to_axons, _unregister_from_axons

router = APIRouter()


# --- 启动模型 ---


@router.get("/api/models/defaults")
async def model_defaults(model: str = Query(...), family: str = Query("")):
    """获取模型的推荐启动参数默认值

    返回基于兼容表和 Metal 状态的推荐配置，
    前端用于预填启动配置面板。
    """
    defaults = _get_model_run_defaults(model, family or None)
    _, has_metal = _find_llama_server()
    return {
        "defaults": defaults,
        "metal_support": has_metal,
        "available_options": {
            "n_gpu_layers": {
                "label": "GPU 层数",
                "description": "-1=全部offload到GPU, 0=纯CPU",
                "type": "number",
            },
            "ctx_size": {
                "label": "上下文长度",
                "description": "影响内存占用和推理能力",
                "type": "number",
            },
            "threads": {
                "label": "线程数",
                "description": "0=自动",
                "type": "number",
            },
            "no_warmup": {
                "label": "跳过预热",
                "description": "部分模型在Metal GPU上warmup会崩溃",
                "type": "boolean",
            },
            "flash_attn": {
                "label": "Flash Attention",
                "description": "auto/on/off",
                "type": "select",
                "options": ["", "auto", "on", "off"],
            },
            "cache_type_k": {
                "label": "KV Cache K 量化",
                "description": "f16/q8_0/q4_0 等，节省显存",
                "type": "select",
                "options": ["", "f16", "q8_0", "q4_0"],
            },
            "cache_type_v": {
                "label": "KV Cache V 量化",
                "description": "f16/q8_0/q4_0 等，节省显存",
                "type": "select",
                "options": ["", "f16", "q8_0", "q4_0"],
            },
        },
    }


@router.get("/api/models/config")
async def get_model_config(model: str = Query(...)):
    """获取用户自定义的模型启动配置"""
    configs = _load_model_configs()
    return {"config": configs.get(model, {})}


@router.put("/api/models/config")
async def set_model_config(body: dict):
    """保存用户自定义的模型启动配置

    body: { model: str, config: { n_gpu_layers?, ctx_size?, ... } }
    """
    model = body.get("model")
    config = body.get("config", {})
    if not model:
        return JSONResponse(status_code=400, content={"error": "model is required"})

    configs = _load_model_configs()
    configs[model] = config
    _save_model_configs(configs)
    return {"status": "saved", "model": model}


@router.post("/api/models/run")
async def run_model(body: dict):
    """启动模型推理服务：fork llama-server 进程并注册到 Axons"""
    model = body.get("model")
    if not model:
        return JSONResponse(status_code=400, content={"error": "model is required"})

    # 检查 llama-server 是否可用
    server_path, _ = _find_llama_server()
    if not server_path:
        return JSONResponse(
            status_code=404,
            content={"error": "llama-server 未安装，请先在状态栏点击安装"},
        )

    # 检查是否已在运行
    with _running_lock:
        if model in _running_processes and _running_processes[model]["process"].poll() is None:
            return {"status": "already_running", "model": model, "port": _running_processes[model]["port"]}

    # 从元数据获取 GGUF 文件路径
    data = _load_metadata()
    model_info = None
    for m in data["models"]:
        if m["name"] == model:
            model_info = m
            break

    if not model_info:
        return JSONResponse(
            status_code=404,
            content={"error": f"模型 {model} 未找到，请先下载"},
        )

    gguf_files = model_info.get("gguf_files", [])
    if not gguf_files:
        return JSONResponse(
            status_code=500,
            content={"error": f"模型 {model} 无 GGUF 文件记录"},
        )

    # 找到主 GGUF 文件（llama-server 只需传第一个文件，分片自动识别）
    gguf_path = gguf_files[0]
    if not os.path.isfile(gguf_path):
        return JSONResponse(
            status_code=500,
            content={"error": f"GGUF 文件不存在: {gguf_path}"},
        )

    # 分配端口
    port = _allocate_port()

    # 获取模型元数据中的 family 字段（用于兼容性判断）
    family = model_info.get("family", "") if model_info else ""

    # 推理参数：优先级 body > 用户持久化配置 > 兼容表默认值 > 通用默认值
    defaults = _get_model_run_defaults(model, family)
    ctx_size = body.get("ctx_size", 4096)
    n_gpu_layers = body.get("n_gpu_layers", defaults.get("n_gpu_layers", -1))
    threads = body.get("threads", 0)  # 0 = 自动
    no_warmup = body.get("no_warmup", defaults.get("no_warmup", False))
    flash_attn = body.get("flash_attn", defaults.get("flash_attn", ""))
    cache_type_k = body.get("cache_type_k", defaults.get("cache_type_k", ""))
    cache_type_v = body.get("cache_type_v", defaults.get("cache_type_v", ""))

    # macOS 无 Metal：强制 -ngl 0
    if platform.system() == "Darwin" and n_gpu_layers != 0:
        _, has_metal = _find_llama_server()
        if not has_metal:
            print(f"[axons-hf] macOS 无 Metal 支持，-ngl 强制为 0（纯 CPU 模式）")
            n_gpu_layers = 0

    argv = [
        server_path,
        "-m", gguf_path,
        "--port", str(port),
        "--host", "127.0.0.1",
        "-c", str(ctx_size),
        "-ngl", str(n_gpu_layers),
    ]
    if threads > 0:
        argv.extend(["-t", str(threads)])
    if no_warmup:
        argv.append("--no-warmup")
    if flash_attn:
        argv.extend(["--flash-attn", flash_attn])
    if cache_type_k:
        argv.extend(["--cache-type-k", cache_type_k])
    if cache_type_v:
        argv.extend(["--cache-type-v", cache_type_v])

    # 日志文件名：用模型名安全化
    safe_name = model.replace("/", "_").replace("\\", "_")
    log_name = f"llama-server_{safe_name}"

    # 设置动态库搜索路径
    # 关键：只在 llama-server 来自插件 bin 目录时设置 DYLD_LIBRARY_PATH，
    # 否则 brew 版 llama-server 会加载 bin 目录的不同版本 dylib导致符号冲突。
    # macOS: DYLD_LIBRARY_PATH + GGML_METAL_PATH_RESOURCES（仅插件 bin 版）
    # Linux: LD_LIBRARY_PATH 指向插件 bin 目录
    env = os.environ.copy()
    bin_dir = str(LLAMA_SERVER_PATH.parent)
    using_plugin_bin = server_path.startswith(bin_dir)

    if platform.system() == "Darwin":
        if using_plugin_bin:
            existing = env.get("DYLD_LIBRARY_PATH", "")
            env["DYLD_LIBRARY_PATH"] = f"{bin_dir}:{existing}" if existing else bin_dir
            # Metal shader 搜索路径（ggml-metal.metal 等）
            env["GGML_METAL_PATH_RESOURCES"] = bin_dir
    elif platform.system() == "Linux":
        if using_plugin_bin:
            existing = env.get("LD_LIBRARY_PATH", "")
            env["LD_LIBRARY_PATH"] = f"{bin_dir}:{existing}" if existing else bin_dir

    try:
        process = _spawn_detached(argv, log_name=log_name, env=env)
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": f"启动 llama-server 失败: {e}"},
        )

    with _running_lock:
        _running_processes[model] = {
            "process": process,
            "port": port,
            "gguf_path": gguf_path,
            "started_at": time.time(),
            "log_name": log_name,
        }

    # 等待就绪
    ready = await _wait_server_ready(port, timeout_seconds=30.0)
    if not ready:
        # 读取日志尾部用于诊断
        log_tail = _read_log_tail(log_name, max_lines=30)
        _stop_process(model)
        error_msg = "llama-server 启动超时（30s）"
        if log_tail:
            error_msg += f"\n\n--- 日志尾部 ---\n{log_tail}"
        return JSONResponse(
            status_code=504,
            content={"error": error_msg, "log_tail": log_tail},
        )

    # 注册到 Axons AI 面板
    _register_to_axons(model)

    return {"status": "running", "model": model, "port": port}


# --- 停止模型 ---


@router.post("/api/models/stop")
async def stop_model(body: dict):
    """停止模型推理服务并从 Axons 取消注册"""
    model = body.get("model")
    if not model:
        return JSONResponse(status_code=400, content={"error": "model is required"})

    stopped = _stop_process(model)
    if not stopped:
        return JSONResponse(
            status_code=404,
            content={"error": f"模型 {model} 未在运行"},
        )

    # 从 Axons 取消注册
    _unregister_from_axons(model)

    return {"status": "stopped", "model": model}


# --- 删除模型 ---


@router.delete("/api/models/delete")
async def delete_model(body: dict):
    """从本地删除模型文件"""
    model = body.get("model")
    if not model:
        return JSONResponse(status_code=400, content={"error": "model is required"})

    # 先停止（如果在运行）
    with _running_lock:
        if model in _running_processes:
            _stop_process(model)

    # 从 Axons 取消注册
    _unregister_from_axons(model)

    # 获取 GGUF 文件路径
    data = _load_metadata()
    model_info = None
    for m in data["models"]:
        if m["name"] == model:
            model_info = m
            break

    if not model_info:
        return JSONResponse(
            status_code=404,
            content={"error": f"Model not found: {model}"},
        )

    # 删除 GGUF 文件
    deleted_files = []
    for f in model_info.get("gguf_files", []):
        try:
            if os.path.isfile(f):
                os.remove(f)
                deleted_files.append(f)
        except OSError:
            pass

    # 尝试清理空目录
    if model_info.get("repo_id"):
        model_dir = MODELS_DIR / model_info["repo_id"]
        try:
            if model_dir.exists() and not any(model_dir.iterdir()):
                model_dir.rmdir()
        except OSError:
            pass

    # 移除元数据
    _remove_model_metadata(model)

    return {"status": "deleted", "model": model, "deleted_files": len(deleted_files)}


# --- 模型日志 ---


@router.get("/api/models/logs")
async def model_logs(model: str = Query(..., description="模型名称"), tail: int = Query(50, description="尾部行数")):
    """获取 llama-server 日志内容

    返回 stderr 和 stdout 日志的尾部内容，用于诊断启动失败等问题。
    """
    safe_name = model.replace("/", "_").replace("\\", "_")
    log_name = f"llama-server_{safe_name}"
    log_dir = _get_log_dir()

    result: dict = {"model": model, "logs": {}}
    for suffix, label in [("err", "stderr"), ("out", "stdout")]:
        path = log_dir / f"{log_name}.{suffix}.log"
        if path.exists():
            try:
                lines = path.read_text(errors="replace").splitlines()
                result["logs"][label] = lines[-tail:]
            except Exception as e:
                result["logs"][label] = [f"(读取失败: {e})"]
        else:
            result["logs"][label] = []

    # 如果模型正在运行，附带进程状态
    with _running_lock:
        info = _running_processes.get(model)
        if info:
            proc = info["process"]
            result["process"] = {
                "pid": proc.pid,
                "running": proc.poll() is None,
                "exit_code": proc.returncode,
                "port": info["port"],
            }

    return result


# --- 注册模型到 Axons ---


@router.post("/api/models/register-to-axons")
async def register_to_axons(body: dict):
    """将模型手动注册到 Axons AI 面板"""
    model = body.get("model")
    base_url = body.get("base_url")

    if not model:
        return JSONResponse(status_code=400, content={"error": "model is required"})

    try:
        # 如果没有指定 base_url，从运行中的进程获取
        if not base_url:
            with _running_lock:
                info = _running_processes.get(model)
                if info and info["process"].poll() is None:
                    base_url = f"http://127.0.0.1:{info['port']}/v1"
                else:
                    return JSONResponse(
                        status_code=400,
                        content={"error": f"模型 {model} 未在运行，无法自动获取 base_url"},
                    )
        _register_to_axons(model, base_url=base_url)
        return {"status": "registered", "model": model}
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to register model to Axons: {str(e)}"},
        )