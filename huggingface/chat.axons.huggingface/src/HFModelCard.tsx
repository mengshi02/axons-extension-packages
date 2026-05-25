import React, { useState, useEffect, useMemo } from 'react';
import { Button, Badge, ProgressBar } from 'axons-plugin-ui';
import type { PluginApi, HFModel } from './types';
import { formatDownloads, buildDownloadKey, shortModelName } from './utils';
import { getDownloadManager, type DownloadJob } from './DownloadManager';

interface HFModelCardProps {
  model: HFModel;
  pluginApi: PluginApi;
  onDownloadComplete: () => void;
}

export default function HFModelCard({ model, pluginApi, onDownloadComplete }: HFModelCardProps) {
  const mgr = useMemo(() => getDownloadManager(pluginApi), [pluginApi]);

  const [selectedQuant, setSelectedQuant] = useState<string>(
    model.available_quantizations[0] || ''
  );

  // 当前选中量化的下载 key
  const downloadKey = selectedQuant
    ? buildDownloadKey(model.id, selectedQuant)
    : '';

  // 订阅 manager 中该模型的 job 状态
  const [job, setJob] = useState<DownloadJob | null>(null);

  useEffect(() => {
    if (!downloadKey) return;
    return mgr.subscribe((jobs) => {
      const found = jobs.find((j) => j.key === downloadKey);
      setJob(found || null);
    });
  }, [mgr, downloadKey]);

  // 当 job 变为 completed 时通知父组件刷新本地列表
  useEffect(() => {
    if (job?.status === 'completed') {
      onDownloadComplete();
    }
  }, [job?.status, onDownloadComplete]);

  const downloading = job?.status === 'downloading';
  const progress = job?.progress ?? 0;
  const progressDetail = job?.detail ?? '';

  const handleDownload = () => {
    if (!selectedQuant) return;
    mgr.start(model.id, selectedQuant);
  };

  const handleCancel = () => {
    if (!selectedQuant) return;
    mgr.cancel(model.id, selectedQuant);
  };

  const handleRetry = () => {
    if (!selectedQuant) return;
    mgr.retry(model.id, selectedQuant);
  };

  const displayName = model.id.split('/').pop()?.replace('-GGUF', '').replace('-gguf', '') || model.id;

  return (
    <div className="plugin-chat-axons-huggingface__hf-card" style={{
      padding: '12px 16px',
      borderBottom: '1px solid var(--axons-border-subtle)',
    }}>
      {/* 标题行 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '4px' }}>
        <span style={{
          fontWeight: 500,
          color: 'var(--axons-text-primary)',
          fontSize: '14px',
        }}>
          {displayName}
        </span>
        {model.pipeline_tag && (
          <Badge variant="info">{model.pipeline_tag}</Badge>
        )}
      </div>

      {/* 元信息 */}
      <div style={{
        fontSize: '12px',
        color: 'var(--axons-text-muted)',
        marginBottom: '8px',
      }}>
        {model.author && <span>{model.author} · </span>}
        <span>{formatDownloads(model.downloads)} downloads</span>
      </div>

      {/* 量化选择 — 所有量化版本均可下载（含分片） */}
      {model.available_quantizations.length > 0 && (
        <div style={{ display: 'flex', gap: '4px', flexWrap: 'wrap', marginBottom: '8px' }}>
          {model.available_quantizations.map((q) => (
            <button
              key={q}
              onClick={() => !downloading && setSelectedQuant(q)}
              className={`axons-badge ${q === selectedQuant ? 'axons-badge-info' : 'axons-badge-default'}`}
              style={{
                cursor: downloading ? 'not-allowed' : 'pointer',
                border: 'none',
                fontFamily: 'var(--axons-font-sans)',
              }}
            >
              {q}
            </button>
          ))}
        </div>
      )}
      {model.available_quantizations.length === 0 && (
        <div style={{ fontSize: '12px', color: 'var(--axons-text-muted)', marginBottom: '8px' }}>
          未检测到可用量化版本
        </div>
      )}

      {/* 下载进度 */}
      {downloading && (
        <div style={{ marginBottom: '8px' }}>
          <ProgressBar value={progress} />
          <div style={{
            fontSize: '11px',
            color: 'var(--axons-text-muted)',
            marginTop: '4px',
          }}>
            {progressDetail}
          </div>
        </div>
      )}

      {/* 错误/取消提示 */}
      {job && job.status === 'error' && (
        <div style={{ fontSize: '11px', color: 'var(--axons-error, #ef4444)', marginBottom: '8px' }}>
          {job.error || '下载失败'}
        </div>
      )}
      {job && job.status === 'canceled' && (
        <div style={{ fontSize: '11px', color: 'var(--axons-text-muted)', marginBottom: '8px' }}>
          已取消
        </div>
      )}

      {/* 操作按钮 */}
      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px' }}>
        {downloading ? (
          <Button variant="secondary" size="sm" onClick={handleCancel}
            style={{ color: 'var(--axons-error)', borderColor: 'var(--axons-error)' }}>
            取消下载
          </Button>
        ) : job && (job.status === 'error' || job.status === 'canceled') ? (
          <>
            <Button variant="primary" size="sm" onClick={handleRetry}>
              重新下载
            </Button>
          </>
        ) : (
          selectedQuant && (
            <Button variant="primary" size="sm" onClick={handleDownload}>
              下载 {selectedQuant}
            </Button>
          )
        )}
      </div>
    </div>
  );
}