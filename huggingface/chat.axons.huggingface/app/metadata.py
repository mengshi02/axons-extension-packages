"""
Axons HuggingFace Plugin - 模型元数据存储

管理 models.json 的读写操作，跟踪已下载模型的文件列表和大小。
"""

import json
import time

from app.config import _ensure_data_dirs, METADATA_FILE


def _load_metadata() -> dict:
    """加载模型元数据"""
    _ensure_data_dirs()
    if METADATA_FILE.exists():
        try:
            return json.loads(METADATA_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {"models": []}


def _save_metadata(data: dict):
    """保存模型元数据"""
    _ensure_data_dirs()
    METADATA_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _add_model_metadata(
    name: str,
    repo_id: str,
    quantization: str,
    gguf_files: list,
    total_size: int,
    family: str = "",
    parameter_size: str = "",
):
    """添加一条模型元数据"""
    data = _load_metadata()
    # 避免重复
    for m in data["models"]:
        if m["name"] == name:
            m["gguf_files"] = gguf_files
            m["total_size"] = total_size
            m["downloaded_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            _save_metadata(data)
            return
    data["models"].append({
        "name": name,
        "repo_id": repo_id,
        "quantization": quantization,
        "gguf_files": gguf_files,
        "total_size": total_size,
        "downloaded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "family": family,
        "parameter_size": parameter_size,
    })
    _save_metadata(data)


def _remove_model_metadata(name: str):
    """移除一条模型元数据"""
    data = _load_metadata()
    data["models"] = [m for m in data["models"] if m["name"] != name]
    _save_metadata(data)