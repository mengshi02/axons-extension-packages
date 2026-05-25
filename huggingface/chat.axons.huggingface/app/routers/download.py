"""
Axons HuggingFace Plugin - 模型下载路由

/api/models/download, /api/models/download/status, /api/models/download/cancel,
/api/models/download/history, /api/models/download/retry
"""

import json
import threading
import time

import sse_starlette
from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from app.config import (
    MODELS_DIR,
    _active_downloads,
    _active_downloads_lock,
)
from app.download_manager import (
    _download_key,
    _do_download,
    _serialize_download_job,
)
from app.history import _load_download_history, _save_download_history

router = APIRouter()


@router.get("/api/models/download/status")
async def download_status():
    """列出当前所有活跃/最近的下载任务"""
    now = time.time()
    with _active_downloads_lock:
        # 清理 5 分钟前结束的非进行中任务
        stale_keys = [
            k for k, j in _active_downloads.items()
            if j["status"] != "downloading"
            and (now - j.get("completed_at", j.get("started_at", now)) > 300)
        ]
        for k in stale_keys:
            del _active_downloads[k]
        jobs = [_serialize_download_job(j) for j in _active_downloads.values()]
    return {"jobs": jobs}


@router.post("/api/models/download/cancel")
async def cancel_download(body: dict):
    """中断某个模型的下载"""
    repo_id = body.get("repo_id")
    quantization = body.get("quantization")
    if not repo_id or not quantization:
        return JSONResponse(
            status_code=400,
            content={"error": "repo_id and quantization are required"},
        )

    key = _download_key(repo_id, quantization)
    with _active_downloads_lock:
        job = _active_downloads.get(key)
        if not job:
            return JSONResponse(
                status_code=404,
                content={"error": f"no active download for {key}"},
            )
        if job["status"] != "downloading":
            return {"status": "already_finished", "key": key, "state": job["status"]}
        job["cancel_event"].set()
        job["status"] = "canceled"
    return {"status": "canceling", "key": key}


@router.get("/api/models/download/history")
async def download_history():
    """获取下载历史列表（持久化，重启后仍可读取）

    返回所有历史下载记录，包含 status (started/completed/interrupted)、
    时间戳和文件大小，供前端在"下载历史" tab 展示。
    """
    history = _load_download_history()

    # 检查本地模型是否仍存在，附加 local_status 字段
    for entry in history:
        repo_id = entry.get("repo_id", "")
        # 检查模型目录是否存在
        model_dir = MODELS_DIR / repo_id
        if model_dir.exists() and any(model_dir.glob("*.gguf")):
            entry["local_status"] = "available"
        else:
            download_dir = model_dir / ".download"
            if download_dir.exists() and any(download_dir.glob("*.part.*")):
                entry["local_status"] = "partial"
            else:
                entry["local_status"] = "absent"

    # 按时间倒序：最新的在前
    history.sort(key=lambda e: e.get("completed_at") or e.get("started_at") or "", reverse=True)
    return {"history": history}


@router.delete("/api/models/download/history/{key:path}")
async def delete_download_history(key: str):
    """删除一条下载历史记录（仅删除记录，不删除已下载的文件）"""
    history = _load_download_history()
    original_len = len(history)
    history = [e for e in history if e.get("key") != key]
    if len(history) == original_len:
        return JSONResponse(status_code=404, content={"error": f"未找到记录: {key}"})
    _save_download_history(history)
    return {"status": "ok"}


@router.post("/api/models/download/retry")
async def retry_download(body: dict):
    """重试之前失败的下载任务。

    如果之前的下载处于 error 状态，重新发起下载。
    已下载的部分文件会被保留用于断点续传。
    """
    repo_id = body.get("repo_id")
    quantization = body.get("quantization")
    if not repo_id or not quantization:
        return JSONResponse(
            status_code=400,
            content={"error": "repo_id and quantization are required"},
        )

    key = _download_key(repo_id, quantization)

    with _active_downloads_lock:
        # 移除旧的失败/取消任务
        old_job = _active_downloads.get(key)
        if old_job and old_job["status"] == "downloading":
            return JSONResponse(
                status_code=409,
                content={"error": "下载任务正在进行中，无需重试"},
            )

        # 移除旧任务记录（保留磁盘上的部分文件用于续传）
        if old_job:
            del _active_downloads[key]

    # 重新发起下载（走 SSE 流端点）
    return {"status": "ready", "message": "可以重新发起下载", "key": key}


@router.get("/api/models/download")
async def download_model(
    repo_id: str = Query(..., description="HF 仓库 ID"),
    quantization: str = Query(..., description="量化类型"),
):
    """下载指定模型的指定量化版本

    架构：
    - 实际下载在后台线程中执行（HF SDK 是同步阻塞的）
    - SSE 流轮询 _active_downloads 共享 dict 推送进度
    - 前端通过 EventSource 接收实时进度更新
    """
    key = _download_key(repo_id, quantization)
    cancel_event = threading.Event()

    with _active_downloads_lock:
        existing = _active_downloads.get(key)
        if existing and existing["status"] == "downloading":
            # 同名任务已经在下载；直接订阅进度
            cancel_event = existing["cancel_event"]
        else:
            _active_downloads[key] = {
                "repo_id": repo_id,
                "quantization": quantization,
                "status": "downloading",
                "started_at": time.time(),
                "completed": 0,
                "total": 0,
                "detail": "准备下载...",
                "error": None,
                "cancel_event": cancel_event,
                "file_index": 0,
                "file_total": 0,
                "current_file": "",
            }
            # 在后台线程中启动下载
            t = threading.Thread(
                target=_do_download,
                args=(repo_id, quantization, key, cancel_event),
                daemon=True,
            )
            t.start()

    def stream():
        """轮询 job 状态并通过 SSE 推送进度"""
        # 立即推送初始状态，让前端知道下载已开始
        yield {
            "event": "download_progress",
            "data": json.dumps({
                "status": "downloading",
                "repo_id": repo_id,
                "quantization": quantization,
                "completed": 0,
                "total": 0,
                "progress": 0,
                "detail": "准备下载...",
                "file": "",
                "file_index": 0,
                "file_total": 0,
            }),
        }

        last_status = "downloading"
        last_detail = "准备下载..."
        last_completed = -1
        last_total = -1
        last_file_index = -1

        while True:
            with _active_downloads_lock:
                job = _active_downloads.get(key)
                if job is None:
                    break

            status = job.get("status", "downloading")
            detail = job.get("detail", "")
            completed = job.get("completed", 0)
            total = job.get("total", 0)
            file_index = job.get("file_index", 0)
            file_total = job.get("file_total", 0)
            current_file = job.get("current_file", "")
            error = job.get("error")

            # 只有状态变化时才推送，避免重复推送相同数据
            has_change = (
                status != last_status
                or detail != last_detail
                or completed != last_completed
                or total != last_total
                or file_index != last_file_index
            )

            if has_change:
                last_status = status
                last_detail = detail
                last_completed = completed
                last_total = total
                last_file_index = file_index

                if status == "completed":
                    yield {
                        "event": "download_complete",
                        "data": json.dumps({
                            "status": "success",
                            "repo_id": repo_id,
                            "quantization": quantization,
                            "completed": completed,
                            "total": total,
                            "detail": detail,
                        }),
                    }
                    return
                elif status == "error":
                    yield {
                        "event": "download_error",
                        "data": json.dumps({
                            "error": error or detail,
                            "repo_id": repo_id,
                            "quantization": quantization,
                        }),
                    }
                    return
                elif status == "canceled":
                    yield {
                        "event": "download_error",
                        "data": json.dumps({
                            "error": "下载已取消",
                            "repo_id": repo_id,
                            "quantization": quantization,
                            "canceled": True,
                        }),
                    }
                    return
                else:
                    # downloading
                    progress = completed / total if total > 0 else 0
                    yield {
                        "event": "download_progress",
                        "data": json.dumps({
                            "status": "downloading",
                            "repo_id": repo_id,
                            "quantization": quantization,
                            "completed": completed,
                            "total": total,
                            "progress": round(progress, 4),
                            "detail": detail,
                            "file": current_file,
                            "file_index": file_index,
                            "file_total": file_total,
                        }),
                    }

            time.sleep(0.3)

    return sse_starlette.EventSourceResponse(stream())