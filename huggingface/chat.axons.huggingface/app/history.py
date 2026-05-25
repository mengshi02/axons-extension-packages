"""
Axons HuggingFace Plugin - 下载历史持久化

管理 download_history.json 的读写操作，记录下载任务的开始和完成状态。
"""

import json
import time

from app.config import _ensure_data_dirs, DOWNLOAD_HISTORY_FILE


def _load_download_history() -> list:
    """加载下载历史列表"""
    _ensure_data_dirs()
    if DOWNLOAD_HISTORY_FILE.exists():
        try:
            data = json.loads(DOWNLOAD_HISTORY_FILE.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
        except (json.JSONDecodeError, OSError):
            pass
    return []


def _save_download_history(history: list):
    """保存下载历史列表"""
    _ensure_data_dirs()
    DOWNLOAD_HISTORY_FILE.write_text(
        json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _add_download_history_entry(
    repo_id: str,
    quantization: str,
    status: str = "started",
    total_size: int = 0,
):
    """添加或更新一条下载历史记录

    下载开始时记录 status=started，下载完成后更新为 completed。
    同一 repo_id:quantization 组合只保留最新一条。
    """
    history = _load_download_history()
    key = f"{repo_id}:{quantization}"

    # 查找已有记录，更新状态
    for entry in history:
        if entry.get("key") == key:
            entry["status"] = status
            entry["total_size"] = total_size
            if status == "completed":
                entry["completed_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            _save_download_history(history)
            return

    # 新记录
    history.append({
        "key": key,
        "repo_id": repo_id,
        "quantization": quantization,
        "status": status,
        "total_size": total_size,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "completed_at": None,
    })
    _save_download_history(history)