import React, { useState, useEffect, useRef, useCallback } from 'react';
import { Badge, Spinner } from 'axons-plugin-ui';
import type { PluginApi, EngineStatus, EngineHealth } from './types';

interface EngineStatusBarProps {
  pluginApi: PluginApi;
}

/**
 * 轮询参数（毫秒）
 *
 * 设计要点：
 * - 单一固定基础间隔，避免 health 状态变化触发 effect 重建导致"自激"。
 * - 失败时做有界指数退避（10s → 20s → 40s → 60s 封顶）。
 * - 失败需连续达到阈值才置为 unhealthy，避免单次网络抖动误报。
 * - 仅在"首次挂载"显示 checking；之后状态变化只在 healthy ↔ unhealthy 间切换。
 */
const BASE_INTERVAL_MS = 10_000;
const MAX_BACKOFF_MS = 60_000;
const UNHEALTHY_THRESHOLD = 2;

export default function EngineStatusBar({ pluginApi }: EngineStatusBarProps) {
  const [health, setHealth] = useState<EngineHealth>('checking');
  const [installed, setInstalled] = useState(false);
  const [installing, setInstalling] = useState(false);
  const [installError, setInstallError] = useState<string | null>(null);
  const [runningCount, setRunningCount] = useState(0);

  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const failCountRef = useRef(0);
  const mountedRef = useRef(true);
  const firstProbeRef = useRef(true);
  const apiRef = useRef(pluginApi);
  apiRef.current = pluginApi;

  const probeRef = useRef<() => Promise<void>>(async () => { });

  const probe = useCallback(async () => {
    if (!mountedRef.current) return;

    if (firstProbeRef.current) {
      setHealth('checking');
    }

    let ok = false;
    let nextInstalled = false;
    let nextRunningCount = 0;
    try {
      const resp = await apiRef.current.fetch('/api/engine/status');
      const data: EngineStatus = await resp.json();
      if (data.engine?.installed) {
        ok = true;
        nextInstalled = true;
        nextRunningCount = data.engine.running_count ?? 0;
      }
    } catch {
      ok = false;
    }

    if (!mountedRef.current) return;

    if (ok) {
      failCountRef.current = 0;
      setHealth('healthy');
      setInstalled(nextInstalled);
      setRunningCount(nextRunningCount);
      setInstallError(null);
      firstProbeRef.current = false;
      if (timerRef.current) clearTimeout(timerRef.current);
      timerRef.current = setTimeout(() => probeRef.current(), BASE_INTERVAL_MS);
    } else {
      failCountRef.current += 1;
      if (failCountRef.current >= UNHEALTHY_THRESHOLD || firstProbeRef.current) {
        setHealth('unhealthy');
        setInstalled(false);
      }
      firstProbeRef.current = false;
      const backoff = Math.min(
        BASE_INTERVAL_MS * Math.pow(2, failCountRef.current - 1),
        MAX_BACKOFF_MS,
      );
      if (timerRef.current) clearTimeout(timerRef.current);
      timerRef.current = setTimeout(() => probeRef.current(), backoff);
    }
  }, []);

  probeRef.current = probe;

  useEffect(() => {
    mountedRef.current = true;
    probeRef.current();

    return () => {
      mountedRef.current = false;
      if (timerRef.current) {
        clearTimeout(timerRef.current);
        timerRef.current = null;
      }
    };
  }, []);

  // 用户点击"安装 llama-server"按钮
  const handleInstall = useCallback(async () => {
    if (installing) return;
    setInstalling(true);
    setInstallError(null);
    try {
      const resp = await apiRef.current.fetch('/api/engine/install', {
        method: 'POST',
      });
      if (!resp.ok) {
        let errMsg = `HTTP ${resp.status}`;
        try {
          const data = await resp.json();
          errMsg = data?.error || errMsg;
        } catch {
          /* ignore */
        }
        setInstallError(errMsg);
      }
    } catch (e: any) {
      setInstallError(e?.message || '请求失败');
    } finally {
      failCountRef.current = 0;
      firstProbeRef.current = true;
      setInstalling(false);
      if (timerRef.current) clearTimeout(timerRef.current);
      timerRef.current = setTimeout(() => probeRef.current(), 0);
    }
  }, [installing]);

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: '8px',
        padding: '8px 12px',
        borderBottom: '1px solid var(--axons-border-subtle)',
        fontSize: '13px',
        color: 'var(--axons-text-secondary)',
        flexWrap: 'wrap',
      }}
    >
      {(health === 'checking' || installing) && <Spinner size="sm" />}
      <span>本地推理引擎: llama.cpp</span>
      <Badge
        variant={
          health === 'healthy'
            ? 'success'
            : health === 'unhealthy'
              ? 'error'
              : 'warning'
        }
      >
        {installing
          ? '安装中…'
          : health === 'healthy'
            ? '已就绪'
            : health === 'unhealthy'
              ? '未安装'
              : '检查中'}
      </Badge>
      {health === 'healthy' && runningCount > 0 && (
        <span style={{ opacity: 0.7 }}>{runningCount} 个模型运行中</span>
      )}

      {health === 'unhealthy' && (
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 8, alignItems: 'center' }}>
          <button
            type="button"
            disabled={installing}
            onClick={handleInstall}
            style={{
              fontSize: 12,
              padding: '2px 10px',
              cursor: installing ? 'wait' : 'pointer',
              background: 'var(--axons-accent, #3b82f6)',
              color: '#fff',
              border: 'none',
              borderRadius: 4,
              opacity: installing ? 0.7 : 1,
            }}
          >
            {installing ? '安装中…' : '安装 llama-server'}
          </button>
          <a
            href="https://github.com/ggml-org/llama.cpp/releases"
            target="_blank"
            rel="noopener noreferrer"
            style={{
              color: 'var(--axons-accent)',
              textDecoration: 'none',
              fontSize: 12,
            }}
          >
            手动下载
          </a>
        </div>
      )}

      {installError && (
        <div
          style={{
            width: '100%',
            marginTop: 4,
            fontSize: 12,
            color: 'var(--axons-text-error, #ef4444)',
          }}
        >
          安装失败：{installError}
        </div>
      )}
    </div>
  );
}