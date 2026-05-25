/**
 * 下载历史列表 — 持久化的下载记录，重装后仍可查看
 *
 * 功能：
 * - 展示所有历史下载记录（含完成、中断、进行中）
 * - 显示本地文件状态（完整/部分/不存在）
 * - 可从历史记录一键重新下载（利用断点续传）
 * - 可删除历史记录
 */
import React, { useState, useEffect, useCallback } from 'react';
import { Button, Badge, Spinner } from 'axons-plugin-ui';
import type { PluginApi, DownloadHistoryItem } from './types';
import { shortModelName, formatSize } from './utils';
import { getDownloadManager } from './DownloadManager';

interface DownloadHistoryProps {
  pluginApi: PluginApi;
  onDownloadComplete: () => void;
}

export default function DownloadHistory({ pluginApi, onDownloadComplete }: DownloadHistoryProps) {
  const [history, setHistory] = useState<DownloadHistoryItem[]>([]);
  const [loading, setLoading] = useState(true);

  const mgr = React.useMemo(() => getDownloadManager(pluginApi), [pluginApi]);

  const loadHistory = useCallback(async () => {
    try {
      const resp = await pluginApi.fetch('/api/models/download/history');
      const data = await resp.json();
      setHistory(data.history || []);
    } catch (err) {
      console.error('Failed to load download history:', err);
    } finally {
      setLoading(false);
    }
  }, [pluginApi]);

  useEffect(() => {
    loadHistory();
  }, [loadHistory]);

  const handleRedownload = useCallback((item: DownloadHistoryItem) => {
    mgr.start(item.repo_id, item.quantization);
  }, [mgr]);

  const handleDelete = useCallback(async (key: string) => {
    try {
      await pluginApi.fetch(`/api/models/download/history/${encodeURIComponent(key)}`, {
        method: 'DELETE',
      });
      setHistory((prev) => prev.filter((item) => item.key !== key));
    } catch (err) {
      console.error('Failed to delete download history:', err);
    }
  }, [pluginApi]);

  const formatTime = (iso: string | null) => {
    if (!iso) return '-';
    try {
      const d = new Date(iso);
      return d.toLocaleString();
    } catch {
      return iso;
    }
  };

  if (loading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', padding: '32px' }}>
        <Spinner size="md" />
      </div>
    );
  }

  if (history.length === 0) {
    return (
      <div style={{
        padding: '24px',
        textAlign: 'center',
        color: 'var(--axons-text-muted)',
        fontSize: '13px',
      }}>
        暂无下载历史
      </div>
    );
  }

  return (
    <div>
      {history.map((item) => (
        <HistoryRow
          key={item.key}
          item={item}
          onRedownload={handleRedownload}
          onDelete={handleDelete}
          formatTime={formatTime}
        />
      ))}
    </div>
  );
}

// ---- 单条历史记录 ----

interface HistoryRowProps {
  item: DownloadHistoryItem;
  onRedownload: (item: DownloadHistoryItem) => void;
  onDelete: (key: string) => void;
  formatTime: (iso: string | null) => string;
}

function HistoryRow({ item, onRedownload, onDelete, formatTime }: HistoryRowProps) {
  const displayName = shortModelName(item.key);

  const isCompleted = item.status === 'completed';
  const isStarted = item.status === 'started';

  // 本地状态标签
  const localStatusLabel = {
    available: '本地已有',
    partial: '部分下载',
    absent: '未下载',
  }[item.local_status] || item.local_status;

  const localStatusVariant = {
    available: 'success',
    partial: 'info',
    absent: 'default',
  }[item.local_status] || 'default';

  return (
    <div style={{
      padding: '10px 16px',
      borderBottom: '1px solid var(--axons-border-subtle)',
    }}>
      {/* 第一行：名称 + 状态标签 */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '4px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', overflow: 'hidden' }}>
          <span style={{
            fontWeight: 500,
            color: 'var(--axons-text-primary)',
            fontSize: '13px',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }} title={item.key}>
            {displayName}
          </span>
          {isCompleted && <Badge variant="success">完成</Badge>}
          {isStarted && !isCompleted && <Badge variant="default">中断</Badge>}
        </div>
        <Badge variant={localStatusVariant as any}>{localStatusLabel}</Badge>
      </div>

      {/* 第二行：元信息 */}
      <div style={{
        fontSize: '11px',
        color: 'var(--axons-text-muted)',
        marginBottom: '6px',
        display: 'flex',
        gap: '12px',
        flexWrap: 'wrap',
      }}>
        {item.total_size > 0 && <span>{formatSize(item.total_size)}</span>}
        <span>下载于 {formatTime(item.started_at)}</span>
        {isCompleted && item.completed_at && (
          <span>完成于 {formatTime(item.completed_at)}</span>
        )}
      </div>

      {/* 第三行：操作按钮 */}
      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px' }}>
        {item.local_status !== 'available' && (
          <Button
            variant="primary"
            size="sm"
            onClick={() => onRedownload(item)}
          >
            {item.local_status === 'partial' ? '续传下载' : '重新下载'}
          </Button>
        )}
        <Button
          variant="ghost"
          size="sm"
          onClick={() => onDelete(item.key)}
          style={{ color: 'var(--axons-text-muted)' }}
        >
          删除记录
        </Button>
      </div>
    </div>
  );
}