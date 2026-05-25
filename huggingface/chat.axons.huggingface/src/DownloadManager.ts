/**
 * 下载任务管理器 — panel 维度的单例
 *
 * 设计目标：
 * - 把 EventSource 生命周期从 React 组件中剥离，避免卡片 unmount 就丢进度
 * - 提供 pub/sub，让卡片、顶部图标 badge、Popover 列表共享同一份状态
 * - 状态全部存在内存中，不落盘；进程内 source-of-truth 在后端 _active_downloads
 *
 * 使用方式：
 *   const mgr = getDownloadManager(pluginApi);
 *   const unsubscribe = mgr.subscribe((jobs) => setJobs(jobs));
 *   mgr.start('bartowski/Llama-3.2-3B-Instruct-GGUF', 'Q4_K_M');
 *   mgr.cancel('bartowski/Llama-3.2-3B-Instruct-GGUF:Q4_K_M');
 *   mgr.dismiss('bartowski/Llama-3.2-3B-Instruct-GGUF:Q4_K_M');
 */

import type { PluginApi } from './types';
import { buildDownloadKey, buildDownloadSsePath } from './utils';

export type DownloadStatus =
  | 'downloading'
  | 'completed'
  | 'error'
  | 'canceled';

export interface DownloadJob {
  /** 下载唯一 key，格式: repo_id:quantization */
  key: string;
  /** HF 仓库 ID */
  repo_id: string;
  /** 量化类型 */
  quantization: string;
  status: DownloadStatus;
  /** 0-1，无总大小时为 0 */
  progress: number;
  /** 已下载字节 */
  completed: number;
  /** 总字节 */
  total: number;
  /** 最近一次状态文本 */
  detail: string;
  /** error/canceled 时的错误说明 */
  error: string | null;
  /** 起始时间戳（ms） */
  startedAt: number;
}

export type DownloadListener = (jobs: DownloadJob[]) => void;

interface ServerJob {
  repo_id: string;
  quantization: string;
  status: DownloadStatus;
  started_at: number;
  completed: number;
  total: number;
  detail: string;
  error: string | null;
  completed_at?: number;
}

class DownloadManager {
  private jobs = new Map<string, DownloadJob>();
  private esMap = new Map<string, EventSource>();
  private listeners = new Set<DownloadListener>();
  private hydrated = false;

  constructor(private pluginApi: PluginApi) {}

  subscribe(listener: DownloadListener): () => void {
    this.listeners.add(listener);
    listener(this.snapshot());
    return () => { this.listeners.delete(listener); };
  }

  snapshot(): DownloadJob[] {
    return Array.from(this.jobs.values()).sort((a, b) => b.startedAt - a.startedAt);
  }

  hasActive(): boolean {
    for (const j of this.jobs.values()) {
      if (j.status === 'downloading') return true;
    }
    return false;
  }

  activeCount(): number {
    let n = 0;
    for (const j of this.jobs.values()) {
      if (j.status === 'downloading') n += 1;
    }
    return n;
  }

  async hydrate(): Promise<void> {
    if (this.hydrated) return;
    this.hydrated = true;
    try {
      const resp = await this.pluginApi.fetch('/api/models/download/status');
      const data = (await resp.json()) as { jobs: ServerJob[] };
      for (const sj of data.jobs || []) {
        const key = buildDownloadKey(sj.repo_id, sj.quantization);
        const job: DownloadJob = {
          key, repo_id: sj.repo_id, quantization: sj.quantization,
          status: sj.status,
          progress: sj.total > 0 ? sj.completed / sj.total : 0,
          completed: sj.completed || 0, total: sj.total || 0,
          detail: sj.detail || '', error: sj.error || null,
          startedAt: (sj.started_at || Date.now() / 1000) * 1000,
        };
        this.jobs.set(key, job);
        if (job.status === 'downloading') {
          this.attachEventSource(sj.repo_id, sj.quantization);
        }
      }
      this.emit();
    } catch { this.hydrated = false; }
  }

  start(repo_id: string, quantization: string): void {
    const key = buildDownloadKey(repo_id, quantization);
    const existing = this.jobs.get(key);
    if (existing && existing.status === 'downloading') return;
    const job: DownloadJob = {
      key, repo_id, quantization,
      status: 'downloading', progress: 0, completed: 0, total: 0,
      detail: '准备下载...', error: null, startedAt: Date.now(),
    };
    this.jobs.set(key, job);
    this.attachEventSource(repo_id, quantization);
    this.emit();
  }

  async cancel(repo_id: string, quantization: string): Promise<void> {
    const key = buildDownloadKey(repo_id, quantization);
    // 先将本地状态标记为 canceled，防止 closeEventSource 触发 onerror
    // 时 onerror 将状态覆盖为 'error'（连接中断）
    const job = this.jobs.get(key);
    if (job && job.status === 'downloading') {
      job.status = 'canceled'; job.detail = '已取消';
      this.jobs.set(key, job);
    }
    try {
      await this.pluginApi.fetch('/api/models/download/cancel', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ repo_id, quantization }),
      });
    } catch { /* ignore */ }
    this.closeEventSource(key);
    this.emit();
  }

  async retry(repo_id: string, quantization: string): Promise<void> {
    const key = buildDownloadKey(repo_id, quantization);
    const job = this.jobs.get(key);
    // 只允许重试 error/canceled 状态的任务
    if (!job || (job.status !== 'error' && job.status !== 'canceled')) return;

    try {
      await this.pluginApi.fetch('/api/models/download/retry', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ repo_id, quantization }),
      });
    } catch { /* ignore */ }

    // 移除旧记录，重新 start
    this.jobs.delete(key);
    this.closeEventSource(key);
    this.start(repo_id, quantization);
  }

  dismiss(key: string): void {
    const job = this.jobs.get(key);
    if (!job || job.status === 'downloading') return;
    this.jobs.delete(key);
    this.emit();
  }

  dismissAllFinished(): void {
    let changed = false;
    for (const [k, j] of this.jobs) {
      if (j.status !== 'downloading') { this.jobs.delete(k); changed = true; }
    }
    if (changed) this.emit();
  }

  private attachEventSource(repo_id: string, quantization: string): void {
    const key = buildDownloadKey(repo_id, quantization);
    this.closeEventSource(key);
    const path = buildDownloadSsePath(repo_id, quantization);
    const es = this.pluginApi.createEventSource(path);
    this.esMap.set(key, es);

    es.addEventListener('download_progress', (e: MessageEvent) => {
      try {
        const data = JSON.parse(e.data);
        this.applyProgress(key, data);
      } catch { /* ignore */ }
    });

    es.addEventListener('download_complete', () => {
      const job = this.jobs.get(key);
      if (job) {
        job.status = 'completed'; job.progress = 1; job.detail = '下载完成';
        this.jobs.set(key, job);
      }
      this.closeEventSource(key);
      this.emit();
    });

    es.addEventListener('download_error', (e: MessageEvent) => {
      let errMsg = '下载失败'; let canceled = false;
      try {
        const data = JSON.parse(e.data);
        errMsg = data.error || errMsg; canceled = !!data.canceled;
      } catch { /* ignore */ }
      const job = this.jobs.get(key);
      if (job) {
        job.status = canceled ? 'canceled' : 'error';
        job.error = errMsg; job.detail = errMsg;
        this.jobs.set(key, job);
      }
      this.closeEventSource(key);
      this.emit();
    });

    es.onerror = () => {
      const job = this.jobs.get(key);
      // 只在 downloading 状态下标记为 error；
      // 如果已经是 canceled/completed/error，说明状态已被正常流程设置，不要覆盖
      if (job && job.status === 'downloading') {
        job.status = 'error'; job.error = '连接中断'; job.detail = '连接中断';
        this.jobs.set(key, job); this.emit();
      }
      this.closeEventSource(key);
    };
  }

  private applyProgress(key: string, chunk: any): void {
    const job = this.jobs.get(key);
    if (!job) return;
    if (typeof chunk.total === 'number' && chunk.total > 0) job.total = chunk.total;
    if (typeof chunk.completed === 'number') job.completed = chunk.completed;
    if (job.total > 0) job.progress = Math.min(1, job.completed / job.total);
    if (chunk.file && chunk.file_total) {
      job.detail = `下载文件 ${chunk.file_index}/${chunk.file_total}: ${chunk.file}`;
    } else {
      job.detail = chunk.status || job.detail || '下载中...';
    }
    this.jobs.set(key, job); this.emit();
  }

  private closeEventSource(key: string): void {
    const es = this.esMap.get(key);
    if (es) { try { es.close(); } catch { /* ignore */ } this.esMap.delete(key); }
  }

  private emit(): void {
    const snap = this.snapshot();
    for (const l of this.listeners) { try { l(snap); } catch { /* ignore */ } }
  }
}

const _managerCache = new Map<string, DownloadManager>();

export function getDownloadManager(pluginApi: PluginApi): DownloadManager {
  const key = pluginApi.pluginId || 'default';
  let mgr = _managerCache.get(key);
  if (!mgr) { mgr = new DownloadManager(pluginApi); _managerCache.set(key, mgr); }
  return mgr;
}

export type { DownloadManager };