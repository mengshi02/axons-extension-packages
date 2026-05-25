"""
Axons HuggingFace Plugin - 本地模型列表路由

/api/models/local
"""

from fastapi import APIRouter

from app.config import _running_lock, _running_processes
from app.metadata import _load_metadata

router = APIRouter()


@router.get("/api/models/local")
async def list_models():
    """获取本地已下载的模型列表及运行状态"""
    data = _load_metadata()

    with _running_lock:
        running_names = {
            name for name, info in _running_processes.items()
            if info["process"].poll() is None
        }

    result = []
    for m in data.get("models", []):
        name = m.get("name", "")
        is_running = name in running_names
        port = None
        if is_running:
            with _running_lock:
                port = _running_processes.get(name, {}).get("port")
        result.append({
            "name": name,
            "repo_id": m.get("repo_id", ""),
            "quantization": m.get("quantization", ""),
            "size": m.get("total_size", 0),
            "family": m.get("family", ""),
            "parameter_size": m.get("parameter_size", ""),
            "running": is_running,
            "status": "running" if is_running else "stopped",
            "port": port,
        })
    return {"models": result}