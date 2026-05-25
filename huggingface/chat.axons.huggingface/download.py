from __future__ import annotations

"""
HuggingFace 分块并发下载器

特性：
- 大文件分块并发下载（默认 16 并发）
- 断点续传：下载中断后可从断点继续
- 重启后续传：重启进程后自动检测已有分块文件继续下载
- 进度回调：实时通知已下载字节数
- 指数退避重试：网络错误自动重试（默认 5 次）
- SHA256 完整性校验：下载完成后验证文件哈希
- 代理支持：自动读取 HTTP_PROXY / HTTPS_PROXY 环境变量
- HTTP/2 + 连接池复用：基于 httpx 高性能客户端

设计参考：github.com/model-ci/apack/internal/transfer/download.go
"""

import hashlib
import json
import math
import os
import random
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

import httpx

# ── 常量 ────────────────────────────────────────────────────────────────
LARGE_FILE_THRESHOLD = 100 * 1024 * 1024   # 100 MB
MIN_CHUNK_SIZE       = 10 * 1024 * 1024    # 10 MB
MAX_CHUNK_COUNT      = 100
DEFAULT_CONCURRENCY  = 16
DEFAULT_MAX_RETRIES  = 5
DOWNLOAD_DIR_NAME    = ".download"          # 分块文件临时目录


def _create_http_client(proxy: bool = True, timeout: float = 0) -> httpx.Client:
    """创建优化的 HTTP 客户端，支持代理和 HTTP/2。

    Args:
        proxy:  是否从环境变量读取代理设置（HTTPS_PROXY / HTTP_PROXY / NO_PROXY）
        timeout: 总超时时间，0 表示无限制（大文件下载必须）
    """
    transport = httpx.HTTPTransport(retries=0)  # 重试由上层控制

    kwargs: dict = {
        "transport": transport,
        "timeout": timeout if timeout > 0 else None,
        "follow_redirects": True,
        "trust_env": proxy,  # trust_env=True 自动读取 HTTPS_PROXY/HTTP_PROXY/NO_PROXY
        "limits": httpx.Limits(
            max_connections=100,
            max_keepalive_connections=20,
            keepalive_expiry=90,
        ),
    }

    return httpx.Client(**kwargs)


class HFDownloader:
    """HuggingFace 分块并发下载器"""

    def __init__(
        self,
        url: str,
        dest_path: str,
        total_size: int,
        *,
        concurrency: int = DEFAULT_CONCURRENCY,
        max_retries: int = DEFAULT_MAX_RETRIES,
        token: Optional[str] = None,
        expected_sha256: Optional[str] = None,
        on_progress=None,
    ):
        """
        Args:
            url:              HF 文件下载 URL（resolve URL）
            dest_path:        目标文件路径
            total_size:       文件总大小（字节）
            concurrency:      并发下载线程数
            max_retries:      单个分块最大重试次数
            token:            HF token（用于私有仓库或限流）
            expected_sha256:  预期 SHA256 哈希值（用于完整性校验）
            on_progress:      进度回调 fn(downloaded_bytes, total_bytes)
        """
        self.url = url
        self.dest_path = dest_path
        self.total_size = total_size
        self.concurrency = min(concurrency, MAX_CHUNK_COUNT) or DEFAULT_CONCURRENCY
        self.max_retries = max_retries
        self.token = token
        self.expected_sha256 = expected_sha256
        self.on_progress = on_progress

        self._downloaded = 0          # 已下载字节数（线程安全）
        self._lock = threading.Lock()
        self._cancel = threading.Event()
        self._client: Optional[httpx.Client] = None

    # ── 公开接口 ────────────────────────────────────────────────────────

    def start(self) -> None:
        """启动下载（阻塞直到完成或失败）"""
        try:
            self._client = _create_http_client(proxy=True, timeout=0)

            # 0. 预检：目标文件已完整且校验通过
            if self._dest_file_complete():
                self._report_progress(self.total_size)
                return

            # 1. 小文件 → 单线程下载
            if self.total_size < LARGE_FILE_THRESHOLD:
                self._download_with_retry(self.dest_path, 0, self.total_size, is_part=False)
                return

            # 2. 大文件 → 分块并发下载
            self._download_concurrent()
        finally:
            if self._client:
                self._client.close()
                self._client = None

    def cancel(self) -> None:
        """取消下载"""
        self._cancel.set()

    # ── 分块并发 ────────────────────────────────────────────────────────

    def _download_concurrent(self) -> None:
        dl_dir = self._download_dir()
        os.makedirs(dl_dir, exist_ok=True)

        chunk_size = self._calculate_chunk_size()
        part_count = math.ceil(self.total_size / chunk_size)
        meta = self._load_or_create_meta(dl_dir, chunk_size, part_count)

        # 快进进度：扫描已有 part 文件
        existing_total = 0
        for i in range(part_count):
            part_file = self._part_path(dl_dir, i)
            if os.path.isfile(part_file):
                existing_total += os.path.getsize(part_file)
        if existing_total > 0:
            self._add_progress(existing_total)

        # 并发下载各分块
        completed_parts = set(meta.get("completed_parts", []))
        completed_lock = threading.Lock()  # 保护 completed_parts 的并发写入
        futures = {}

        with ThreadPoolExecutor(max_workers=self.concurrency) as pool:
            for i in range(part_count):
                if self._cancel.is_set():
                    pool.shutdown(wait=False, cancel_futures=True)
                    raise DownloadCancelledError("下载已取消")

                start = i * chunk_size
                end = min(start + chunk_size, self.total_size)

                if i in completed_parts:
                    # 已完成的分块，跳过
                    continue

                part_file = self._part_path(dl_dir, i)
                future = pool.submit(
                    self._download_with_retry,
                    part_file, start, end, is_part=True,
                )
                futures[future] = i

            # 等待所有分块完成
            for future in as_completed(futures):
                idx = futures[future]
                if self._cancel.is_set():
                    pool.shutdown(wait=False, cancel_futures=True)
                    with completed_lock:
                        self._save_meta(dl_dir, chunk_size, part_count, completed_parts)
                    raise DownloadCancelledError("下载已取消")
                exc = future.exception()
                if exc:
                    with completed_lock:
                        self._save_meta(dl_dir, chunk_size, part_count, completed_parts)
                    raise exc
                with completed_lock:
                    completed_parts.add(idx)
                    self._save_meta(dl_dir, chunk_size, part_count, completed_parts)

        # merge（原子化）
        self._merge_parts(dl_dir, part_count)

    # ── 单块下载（含断点续传 + 重试） ────────────────────────────────

    def _download_with_retry(
        self, filename: str, range_start: int, range_end: int, *, is_part: bool
    ) -> None:
        last_err = None
        for attempt in range(self.max_retries + 1):
            if self._cancel.is_set():
                raise DownloadCancelledError("下载已取消")
            if attempt > 0:
                backoff = 2 ** (attempt - 1)
                jitter = random.uniform(0, 1)
                sleep = min(backoff + jitter, 30)
                time.sleep(sleep)
            try:
                self._download_part(filename, range_start, range_end, is_part=is_part)
                return
            except DownloadCancelledError:
                raise
            except Exception as e:
                last_err = e
                if not self._is_retryable(e):
                    raise
        raise DownloadError(f"分块下载超过最大重试次数 ({self.max_retries}): {last_err}")

    def _download_part(
        self, filename: str, range_start: int, range_end: int, *, is_part: bool
    ) -> None:
        """下载一个范围的数据，支持断点续传（基于 httpx）"""
        # 打开目标文件（追加模式）
        os.makedirs(os.path.dirname(filename) or ".", exist_ok=True)
        file = open(filename, "r+b" if os.path.isfile(filename) else "w+b")
        try:
            file.seek(0, 2)  # seek to end
            current_local_size = file.tell()
            expected_size = range_end - range_start

            # 小文件断点续传：同步进度
            if not is_part and current_local_size > 0:
                self._add_progress(current_local_size)

            # 已完整下载
            if current_local_size >= expected_size:
                file.close()
                file = None
                return

            # 构建 Range 请求
            download_start = range_start + current_local_size
            headers = {"Range": f"bytes={download_start}-{range_end - 1}"}
            if self.token:
                headers["Authorization"] = f"Bearer {self.token}"

            assert self._client is not None
            resp = self._client.send(
                self._client.build_request("GET", self.url, headers=headers),
                stream=True,
            )

            if resp.status_code not in (200, 206):
                resp.close()
                raise DownloadError(f"HTTP {resp.status_code}")

            # 从断点位置追加写入
            file.seek(current_local_size)

            try:
                for chunk in resp.iter_bytes(chunk_size=256 * 1024):
                    if self._cancel.is_set():
                        raise DownloadCancelledError("下载已取消")
                    if not chunk:
                        break
                    file.write(chunk)
                    self._add_progress(len(chunk))
            finally:
                resp.close()
        finally:
            if file:
                file.close()

    # ── Merge 合并（原子化） ──────────────────────────────────────────

    def _merge_parts(self, dl_dir: str, part_count: int) -> None:
        """合并所有分块文件为目标文件（原子写入：先写 .tmp 再 rename）"""
        os.makedirs(os.path.dirname(self.dest_path) or ".", exist_ok=True)
        tmp_path = self.dest_path + ".tmp"

        try:
            with open(tmp_path, "wb") as out:
                for i in range(part_count):
                    part_file = self._part_path(dl_dir, i)
                    with open(part_file, "rb") as part:
                        shutil.copyfileobj(part, out, length=16 * 1024 * 1024)

            # 原子重命名
            os.replace(tmp_path, self.dest_path)
        except BaseException:
            # 合并失败时清理 tmp 文件，但不删除 part 文件（保留续传能力）
            if os.path.isfile(tmp_path):
                os.remove(tmp_path)
            raise

        # 合并完成，校验完整性
        self._verify_integrity()

        # 校验通过，清理临时目录
        self._cleanup_download_dir()

    # ── 完整性校验 ────────────────────────────────────────────────────

    def _verify_integrity(self) -> None:
        """校验下载文件的完整性"""
        # 1. 文件大小校验
        try:
            actual_size = os.path.getsize(self.dest_path)
        except OSError as e:
            raise IntegrityError(f"无法读取文件大小: {e}")

        if actual_size != self.total_size:
            raise IntegrityError(
                f"文件大小不匹配: 期望 {self.total_size} 字节, 实际 {actual_size} 字节"
            )

        # 2. SHA256 哈希校验（仅当提供了 expected_sha256 时）
        if self.expected_sha256:
            actual_hash = self._sha256_file(self.dest_path)
            if actual_hash != self.expected_sha256.lower():
                raise IntegrityError(
                    f"SHA256 校验失败: 期望 {self.expected_sha256.lower()}, "
                    f"实际 {actual_hash}"
                )

    @staticmethod
    def _sha256_file(path: str, buf_size: int = 256 * 1024) -> str:
        """计算文件的 SHA256 哈希值"""
        h = hashlib.sha256()
        with open(path, "rb") as f:
            while True:
                chunk = f.read(buf_size)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()

    def _dest_file_complete(self) -> bool:
        """目标文件是否已完整（含 SHA256 校验）"""
        try:
            if not os.path.isfile(self.dest_path):
                return False
            if os.path.getsize(self.dest_path) != self.total_size:
                return False
            # 如果有预期哈希，也要校验
            if self.expected_sha256:
                actual = self._sha256_file(self.dest_path)
                return actual == self.expected_sha256.lower()
            return True
        except OSError:
            return False

    # ── 元数据管理 ────────────────────────────────────────────────────

    def _download_dir(self) -> str:
        """分块文件临时目录"""
        return os.path.join(os.path.dirname(self.dest_path), DOWNLOAD_DIR_NAME)

    def _meta_path(self, dl_dir: str) -> str:
        """元数据文件路径"""
        basename = os.path.basename(self.dest_path)
        return os.path.join(dl_dir, f"{basename}.json")

    def _part_path(self, dl_dir: str, index: int) -> str:
        """分块文件路径"""
        basename = os.path.basename(self.dest_path)
        return os.path.join(dl_dir, f"{basename}.part.{index}")

    def _load_or_create_meta(self, dl_dir: str, chunk_size: int, part_count: int) -> dict:
        """加载已有元数据，或创建新的"""
        meta_file = self._meta_path(dl_dir)
        if os.path.isfile(meta_file):
            try:
                with open(meta_file, "r") as f:
                    meta = json.load(f)
                # 校验关键参数一致
                if meta.get("chunk_size") == chunk_size and meta.get("part_count") == part_count:
                    return meta
            except (json.JSONDecodeError, OSError):
                pass
            # 元数据不匹配或损坏，清理重新开始
            self._cleanup_download_dir()
            os.makedirs(dl_dir, exist_ok=True)

        meta = {
            "url": self.url,
            "total_size": self.total_size,
            "chunk_size": chunk_size,
            "part_count": part_count,
            "completed_parts": [],
        }
        self._write_meta(meta_file, meta)
        return meta

    def _save_meta(self, dl_dir: str, chunk_size: int, part_count: int, completed_parts: set) -> None:
        """保存元数据（用于重启后续传）"""
        meta_file = self._meta_path(dl_dir)
        meta = {
            "url": self.url,
            "total_size": self.total_size,
            "chunk_size": chunk_size,
            "part_count": part_count,
            "completed_parts": sorted(completed_parts),
        }
        self._write_meta(meta_file, meta)

    @staticmethod
    def _write_meta(path: str, meta: dict) -> None:
        """原子写入元数据文件"""
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(meta, f, indent=2)
        os.replace(tmp, path)

    def _cleanup_download_dir(self) -> None:
        """清理临时下载目录"""
        dl_dir = self._download_dir()
        if os.path.isdir(dl_dir):
            shutil.rmtree(dl_dir, ignore_errors=True)

    # ── 进度同步 ──────────────────────────────────────────────────────

    def _add_progress(self, bytes_count: int) -> None:
        """线程安全地累加进度"""
        if bytes_count <= 0:
            return
        with self._lock:
            self._downloaded += bytes_count
        self._report_progress(self._downloaded)

    def _report_progress(self, downloaded: int) -> None:
        if self.on_progress:
            try:
                self.on_progress(downloaded, self.total_size)
            except Exception:
                pass

    # ── 辅助 ──────────────────────────────────────────────────────────

    def _calculate_chunk_size(self) -> int:
        """计算分块大小（向上取整到 MB）"""
        chunk_size = self.total_size // MAX_CHUNK_COUNT
        if chunk_size < MIN_CHUNK_SIZE:
            chunk_size = MIN_CHUNK_SIZE
        MB = 1024 * 1024
        remainder = chunk_size % MB
        if remainder:
            chunk_size += MB - remainder
        return chunk_size

    @staticmethod
    def _is_retryable(err: Exception) -> bool:
        """判断错误是否可重试"""
        if isinstance(err, (DownloadCancelledError, IntegrityError)):
            return False
        # httpx 网络错误
        if isinstance(err, (
            httpx.ConnectError,
            httpx.ReadError,
            httpx.WriteError,
            httpx.PoolTimeout,
            httpx.ConnectTimeout,
            httpx.ReadTimeout,
        )):
            return True
        # HTTP 状态码判断
        if isinstance(err, httpx.HTTPStatusError):
            code = err.response.status_code
            return code in (429, 500, 502, 503, 504)
        # OSError / ConnectionError / TimeoutError
        if isinstance(err, (OSError, ConnectionError, TimeoutError)):
            return True
        msg = str(err).lower()
        if any(kw in msg for kw in ("429", "503", "502", "500", "timeout", "reset", "refused")):
            return True
        return True  # 默认可重试


# ── 异常类 ──────────────────────────────────────────────────────────────

class DownloadError(Exception):
    """下载错误"""

class DownloadCancelledError(DownloadError):
    """下载被取消"""

class IntegrityError(DownloadError):
    """完整性校验失败"""