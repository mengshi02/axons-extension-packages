"""
Axons HuggingFace Plugin - 下载任务管理

管理活跃下载任务表，在后台线程中执行 GGUF 文件下载。
"""

import os
import threading
import time

from download import HFDownloader, DownloadCancelledError, IntegrityError

from app.config import (
    MODELS_DIR,
    _HF_CONFIG,
    _active_downloads,
    _active_downloads_lock,
    _ensure_data_dirs,
    _get_hf_api,
)
from app.gguf import _find_gguf_files_for_quant
from app.history import _add_download_history_entry
from app.metadata import _add_model_metadata


def _download_key(repo_id: str, quantization: str) -> str:
    """生成下载任务的唯一 key"""
    return f"{repo_id}:{quantization}"


def _serialize_download_job(job: dict) -> dict:
    """转成可 JSON 化的形式（去掉 cancel_event）"""
    return {k: v for k, v in job.items() if k != "cancel_event"}


def _do_download(repo_id: str, quantization: str, key: str, cancel_event: threading.Event):
    """在后台线程中执行实际的 GGUF 文件下载。

    使用自研 HFDownloader 分块并发下载（支持断点续传和重启后续传），
    下载是同步阻塞调用，所以必须在线程中运行，避免阻塞 FastAPI 事件循环。
    下载进度通过 _active_downloads 共享 dict 传递给 SSE 流。
    下载开始/完成时写入 download_history.json 以便重装后恢复。
    """
    def _update_job(**kwargs):
        with _active_downloads_lock:
            job = _active_downloads.get(key)
            if job is None:
                return
            if (
                "status" in kwargs
                and kwargs["status"] != "downloading"
                and job.get("status") == "downloading"
            ):
                job["completed_at"] = time.time()
            job.update(kwargs)

    try:
        # 0. 记录下载历史（started）
        _add_download_history_entry(repo_id, quantization, status="started")

        # 1. 找出该量化的所有 GGUF 文件
        _update_job(detail="查询文件列表...")
        gguf_files = _find_gguf_files_for_quant(repo_id, quantization)
        if not gguf_files:
            msg = f"未找到 {repo_id} 的 {quantization} 量化版本"
            _update_job(status="error", error=msg, detail=msg)
            return

        # 2. 构建 token 参数
        download_kwargs = {}
        if _HF_CONFIG["hf_token"]:
            download_kwargs["token"] = _HF_CONFIG["hf_token"]

        # 本地存储路径
        local_dir = MODELS_DIR / repo_id
        local_dir.mkdir(parents=True, exist_ok=True)

        # 3. 获取文件大小和 SHA256 信息（用于总进度计算 + 完整性校验）
        _update_job(detail="获取文件大小信息...")
        file_sizes = {}
        file_digests = {}  # filename → sha256 hex digest
        total_size_all = 0
        try:
            api = _get_hf_api()
            file_info = api.model_info(repo_id, files_metadata=True)
            for sibling in (file_info.siblings or []):
                if sibling.rfilename in gguf_files and sibling.size:
                    file_sizes[sibling.rfilename] = sibling.size
                    total_size_all += sibling.size
                    # HF API 返回的 digest 格式: "sha256:abcdef..."
                    if getattr(sibling, "digest", None):
                        digest = sibling.digest
                        if digest.startswith("sha256:"):
                            file_digests[sibling.rfilename] = digest[7:]
                        else:
                            file_digests[sibling.rfilename] = digest
        except Exception:
            pass

        if total_size_all > 0:
            _update_job(total=total_size_all)

        # 4. 逐个下载
        downloaded_paths = []
        total_files = len(gguf_files)
        completed_bytes = 0

        for i, filename in enumerate(gguf_files):
            if cancel_event.is_set():
                _update_job(status="canceled", detail="已取消")
                return

            _update_job(
                detail=f"下载文件 {i + 1}/{total_files}: {filename}",
                file_index=i + 1,
                file_total=total_files,
                current_file=filename,
            )

            try:
                local_path = os.path.join(str(local_dir), filename)
                expected_size = file_sizes.get(filename, 0)

                # 检查本地是否已完整（含 SHA256 校验）
                if os.path.isfile(local_path) and expected_size > 0:
                    existing_size = os.path.getsize(local_path)
                    if existing_size == expected_size:
                        # 如果有 digest，也校验哈希
                        expected_digest = file_digests.get(filename)
                        if expected_digest:
                            import hashlib as _hashlib
                            h = _hashlib.sha256()
                            with open(local_path, "rb") as _f:
                                while True:
                                    _chunk = _f.read(256 * 1024)
                                    if not _chunk:
                                        break
                                    h.update(_chunk)
                            if h.hexdigest() != expected_digest.lstrip("sha256:").lower():
                                # 哈希不匹配，文件损坏，重新下载
                                os.remove(local_path)
                            else:
                                downloaded_paths.append(local_path)
                                completed_bytes += existing_size
                                _update_job(completed=completed_bytes)
                                continue
                        else:
                            downloaded_paths.append(local_path)
                            completed_bytes += existing_size
                            _update_job(completed=completed_bytes)
                            continue

                # 构建 HF resolve URL
                hf_endpoint = _HF_CONFIG.get("hf_mirror", "") or "huggingface.co"
                download_url = f"https://{hf_endpoint}/{repo_id}/resolve/main/{filename}"

                # 进度回调：闭包捕获当前 completed_bytes
                _file_base = completed_bytes
                def _make_progress_cb(base):
                    def _on_progress(downloaded, total):
                        _update_job(completed=base + downloaded)
                    return _on_progress
                _progress_cb = _make_progress_cb(_file_base)

                # 使用 HFDownloader 分块并发下载（含 SHA256 校验）
                dl = HFDownloader(
                    url=download_url,
                    dest_path=local_path,
                    total_size=expected_size,
                    token=download_kwargs.get("token"),
                    expected_sha256=file_digests.get(filename),
                    on_progress=_progress_cb,
                )

                # 在子线程中运行下载，主线程监听取消事件
                download_error = [None]

                def _run_download():
                    try:
                        dl.start()
                    except Exception as ex:
                        download_error[0] = ex

                dl_thread = threading.Thread(target=_run_download, daemon=True)
                dl_thread.start()

                # 监听取消事件
                while dl_thread.is_alive():
                    if cancel_event.is_set():
                        dl.cancel()
                        _update_job(status="canceled", detail="已取消")
                        return
                    dl_thread.join(timeout=1.0)

                if download_error[0] is not None:
                    raise download_error[0]

                downloaded_paths.append(local_path)

                # 更新已完成字节数
                try:
                    file_size = os.path.getsize(local_path)
                    completed_bytes += file_size
                    _update_job(completed=completed_bytes)
                except OSError:
                    pass

            except IntegrityError as e:
                msg = f"文件校验失败 {filename}: {e}"
                _update_job(status="error", error=msg, detail=msg)
                return
            except Exception as e:
                msg = f"下载文件 {filename} 失败: {e}"
                _update_job(status="error", error=msg, detail=msg)
                return

            if cancel_event.is_set():
                _update_job(status="canceled", detail="已取消")
                return

        # 5. 计算总大小（用实际文件大小，比 API 返回的更准确）
        total_size = 0
        for p in downloaded_paths:
            try:
                total_size += os.path.getsize(p)
            except OSError:
                pass

        # 6. 写入元数据
        model_name = f"{repo_id.split('/')[-1].replace('-GGUF', '').replace('-gguf', '')}-{quantization}"
        _add_model_metadata(
            name=model_name,
            repo_id=repo_id,
            quantization=quantization,
            gguf_files=downloaded_paths,
            total_size=total_size,
        )

        # 7. 完成
        _update_job(status="completed", detail="下载完成", completed=total_size, total=total_size)

        # 8. 更新下载历史为 completed
        _add_download_history_entry(repo_id, quantization, status="completed", total_size=total_size)

    except Exception as e:
        msg = str(e)
        _update_job(status="error", error=msg, detail=msg)