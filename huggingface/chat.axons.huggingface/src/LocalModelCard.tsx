import React, { useState } from 'react';
import { Button, Badge, ConfirmDialog } from 'axons-plugin-ui';
import type { PluginApi, LocalModel, RunConfig } from './types';
import { formatSize, shortModelName } from './utils';
import RunConfigModal from './RunConfigModal';

interface LocalModelCardProps {
  model: LocalModel;
  pluginApi: PluginApi;
  onRefresh: () => void;
}

export default function LocalModelCard({ model, pluginApi, onRefresh }: LocalModelCardProps) {
  const [loading, setLoading] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);
  const [logOpen, setLogOpen] = useState(false);
  const [logContent, setLogContent] = useState<string>('');
  const [logLoading, setLogLoading] = useState(false);
  const [configModalOpen, setConfigModalOpen] = useState(false);

  const handleViewLog = async () => {
    setLogOpen(true);
    setLogLoading(true);
    try {
      const resp = await pluginApi.fetch(`/api/models/logs?model=${encodeURIComponent(model.name)}&tail=100`);
      const data = await resp.json();
      const parts: string[] = [];
      if (data.logs?.stderr?.length) {
        parts.push('=== stderr ===\n' + data.logs.stderr.join('\n'));
      }
      if (data.logs?.stdout?.length) {
        parts.push('=== stdout ===\n' + data.logs.stdout.join('\n'));
      }
      if (data.process) {
        parts.push(`=== 进程状态 ===\nPID: ${data.process.pid}\n运行中: ${data.process.running}\n退出码: ${data.process.exit_code ?? 'N/A'}\n端口: ${data.process.port}`);
      }
      setLogContent(parts.length ? parts.join('\n\n') : '(无日志)');
    } catch (err: any) {
      setLogContent(`获取日志失败: ${err?.message || '未知错误'}`);
    } finally {
      setLogLoading(false);
    }
  };

  const handleRun = async (config?: RunConfig) => {
    setLoading(true);
    setRunError(null);
    try {
      const resp = await pluginApi.fetch('/api/models/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model: model.name, ...config }),
      });
      if (!resp.ok) {
        const data = await resp.json().catch(() => ({ error: `HTTP ${resp.status}` }));
        setRunError(data.error || `启动失败 (HTTP ${resp.status})`);
      } else {
        onRefresh();
      }
    } catch (err: any) {
      setRunError(err?.message || '网络请求失败');
    } finally {
      setLoading(false);
    }
  };

  const handleStop = async () => {
    setLoading(true);
    setRunError(null);
    try {
      const resp = await pluginApi.fetch('/api/models/stop', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model: model.name }),
      });
      if (!resp.ok) {
        const data = await resp.json().catch(() => ({ error: `HTTP ${resp.status}` }));
        setRunError(data.error || `停止失败 (HTTP ${resp.status})`);
      } else {
        onRefresh();
      }
    } catch (err: any) {
      setRunError(err?.message || '网络请求失败');
    } finally {
      setLoading(false);
    }
  };

  const handleDelete = async () => {
    setLoading(true);
    try {
      await pluginApi.fetch('/api/models/delete', {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model: model.name }),
      });
      onRefresh();
    } catch (err) {
      console.error('Failed to delete model:', err);
    } finally {
      setLoading(false);
      setConfirmOpen(false);
    }
  };

  return (
    <div className="plugin-chat-axons-huggingface__local-card" style={{
      padding: '12px 16px',
      borderBottom: '1px solid var(--axons-border-subtle)',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '4px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span title={shortModelName(model.name)} style={{ fontWeight: 500, color: 'var(--axons-text-primary)', fontSize: '14px', maxWidth: '120px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {shortModelName(model.name)}
          </span>
          <Badge variant={model.running ? 'success' : 'default'}>
            {model.running ? '运行中' : '已停止'}
          </Badge>
        </div>
        <button
          onClick={handleViewLog}
          disabled={loading}
          title="查看日志"
          style={{
            background: 'none',
            border: 'none',
            cursor: loading ? 'not-allowed' : 'pointer',
            color: 'var(--axons-text-muted)',
            fontSize: '16px',
            padding: '2px 4px',
            lineHeight: 1,
            display: 'flex',
            alignItems: 'center',
            opacity: loading ? 0.5 : 1,
            transition: 'color 0.15s',
          }}
          onMouseEnter={e => e.currentTarget.style.color = 'var(--axons-text-primary)'}
          onMouseLeave={e => e.currentTarget.style.color = 'var(--axons-text-muted)'}
        >
          {/* 文档图标 SVG */}
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <path d="M4 2h5.5L12 4.5V14a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V3a1 1 0 0 1 1-1z" />
            <polyline points="9.5,2 9.5,4.5 12,4.5" />
            <line x1="5" y1="8" x2="10" y2="8" />
            <line x1="5" y1="10.5" x2="8" y2="10.5" />
          </svg>
        </button>
      </div>

      <div style={{
        fontSize: '12px',
        color: 'var(--axons-text-muted)',
        marginBottom: '8px',
      }}>
        {model.parameter_size && <span>{model.parameter_size} · </span>}
        {model.family && <span>{model.family} · </span>}
        <span>{formatSize(model.size)}</span>
      </div>

      <div style={{ display: 'flex', gap: '6px', justifyContent: 'flex-end' }}>
        {!model.running ? (
          <>
            <Button variant="primary" size="sm" onClick={() => setConfigModalOpen(true)} disabled={loading}>
              {loading ? '...' : '启动'}
            </Button>
          </>
        ) : (
          <Button variant="ghost" size="sm" onClick={handleStop} disabled={loading}>
            {loading ? '...' : '停止'}
          </Button>
        )}
        <Button variant="secondary" size="sm" onClick={() => setConfirmOpen(true)} disabled={loading}
          style={{ color: 'var(--axons-error)', borderColor: 'var(--axons-error)' }}>
          {loading ? '...' : '清理'}
        </Button>
      </div>

      {runError && (
        <div style={{
          marginTop: '8px',
          padding: '8px 12px',
          background: 'var(--axons-error-bg, #fef2f2)',
          border: '1px solid var(--axons-error, #ef4444)',
          borderRadius: '4px',
          fontSize: '12px',
          color: 'var(--axons-error, #ef4444)',
          whiteSpace: 'pre-wrap',
          maxHeight: '120px',
          overflow: 'auto',
        }}>
          {runError}
        </div>
      )}

      <ConfirmDialog
        isOpen={confirmOpen}
        title="确认清理模型"
        message={`确认删除模型 ${shortModelName(model.name)}？此操作不可恢复。`}
        confirmLabel="清理"
        cancelLabel="取消"
        variant="danger"
        onConfirm={handleDelete}
        onCancel={() => setConfirmOpen(false)}
      />

      <RunConfigModal
        isOpen={configModalOpen}
        onClose={() => setConfigModalOpen(false)}
        model={model}
        pluginApi={pluginApi}
        onRun={onRefresh}
      />

      {logOpen && (
        <div style={{
          position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
          background: 'rgba(0,0,0,0.5)', zIndex: 9999,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
        }} onClick={() => setLogOpen(false)}>
          <div style={{
            background: 'var(--axons-bg-primary, #fff)',
            borderRadius: '8px',
            width: '80%', maxWidth: '700px', maxHeight: '80vh',
            display: 'flex', flexDirection: 'column',
            boxShadow: '0 4px 16px rgba(0,0,0,0.2)',
          }} onClick={e => e.stopPropagation()}>
            <div style={{
              padding: '12px 16px',
              borderBottom: '1px solid var(--axons-border-subtle)',
              display: 'flex', justifyContent: 'space-between', alignItems: 'center',
            }}>
              <span style={{ fontWeight: 500 }}>模型日志 - {shortModelName(model.name)}</span>
              <Button variant="ghost" size="sm" onClick={() => setLogOpen(false)}>关闭</Button>
            </div>
            <div style={{
              padding: '12px 16px',
              flex: 1, overflow: 'auto',
              fontFamily: 'monospace',
              fontSize: '12px',
              whiteSpace: 'pre-wrap',
              color: 'var(--axons-text-primary)',
              background: 'var(--axons-bg-secondary, #f9fafb)',
            }}>
              {logLoading ? '加载中...' : logContent}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}