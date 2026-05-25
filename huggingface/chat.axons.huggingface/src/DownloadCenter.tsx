/**
 * 下载中心 — Header 右侧图标 + Popover 列表
 *
 * 仅当有任务（含进行中/已完成/失败/取消）时显示图标。
 * 点击图标弹出任务列表，每条可取消或关闭。
 */
import React, { useState, useEffect, useRef, useMemo, useCallback } from 'react';
import { Button, Badge, ProgressBar, Card, CardBody } from 'axons-plugin-ui';
import type { PluginApi } from './types';
import { getDownloadManager, type DownloadJob } from './DownloadManager';
import { shortModelName, formatSize, buildDownloadKey } from './utils';

interface DownloadCenterProps {
  pluginApi: PluginApi;
}

export default function DownloadCenter({ pluginApi }: DownloadCenterProps) {
  const mgr = useMemo(() => getDownloadManager(pluginApi), [pluginApi]);
  const [jobs, setJobs] = useState<DownloadJob[]>([]);
  const [open, setOpen] = useState(false);
  const popoverRef = useRef<HTMLDivElement>(null);
  const iconRef = useRef<HTMLButtonElement>(null);

  // 订阅 manager
  useEffect(() => {
    return mgr.subscribe(setJobs);
  }, [mgr]);

  // 点击外部关闭 Popover
  useEffect(() => {
    if (!open) return;
    const handleClickOutside = (e: MouseEvent) => {
      const target = e.target as Node;
      if (
        popoverRef.current &&
        !popoverRef.current.contains(target) &&
        iconRef.current &&
        !iconRef.current.contains(target)
      ) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [open]);

  const activeCount = useMemo(
    () => jobs.filter((j) => j.status === 'downloading').length,
    [jobs],
  );

  const hasJobs = jobs.length > 0;

  const handleCancel = useCallback(
    (key: string) => {
      const job = jobs.find(j => j.key === key);
      if (job) mgr.cancel(job.repo_id, job.quantization);
    },
    [mgr, jobs],
  );

  const handleDismiss = useCallback(
    (key: string) => {
      mgr.dismiss(key);
    },
    [mgr],
  );

  const handleDismissAll = useCallback(() => {
    mgr.dismissAllFinished();
  }, [mgr]);

  const handleRetry = useCallback(
    (key: string) => {
      const job = jobs.find(j => j.key === key);
      if (job) mgr.retry(job.repo_id, job.quantization);
    },
    [mgr, jobs],
  );

  // 无任务时不渲染图标
  if (!hasJobs) return null;

  return (
    <>
      {/* 图标按钮 + badge */}
      <button
        ref={iconRef}
        type="button"
        onClick={() => setOpen((prev) => !prev)}
        aria-label="下载任务列表"
        style={{
          position: 'relative',
          background: 'none',
          border: 'none',
          cursor: 'pointer',
          padding: '2px 6px',
          display: 'flex',
          alignItems: 'center',
          gap: '4px',
          color: 'var(--axons-text-secondary)',
          lineHeight: 1,
        }}
      >
        {/* 下载箭头 SVG */}
        <svg
          width="16"
          height="16"
          viewBox="0 0 16 16"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d="M8 2v9M4 8l4 4 4-4" />
          <path d="M2 13h12" />
        </svg>
        {activeCount > 0 && (
          <span
            style={{
              position: 'absolute',
              top: -4,
              right: 0,
              background: 'var(--axons-accent, #3b82f6)',
              color: '#fff',
              fontSize: '10px',
              fontWeight: 600,
              minWidth: 16,
              height: 16,
              borderRadius: 8,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              padding: '0 3px',
              lineHeight: 1,
            }}
          >
            {activeCount}
          </span>
        )}
      </button>

      {/* Popover */}
      {open && (
        <div
          ref={popoverRef}
          style={{
            position: 'absolute',
            top: '38px',
            right: '8px',
            width: '340px',
            maxHeight: '400px',
            zIndex: 50,
            boxShadow: '0 4px 16px rgba(0,0,0,0.12)',
            borderRadius: '8px',
            overflow: 'hidden',
          }}
        >
          <Card>
            <CardBody>
              {/* 标题行 */}
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  marginBottom: '8px',
                }}
              >
                <span style={{ fontWeight: 600, fontSize: '13px' }}>
                  下载任务
                  {activeCount > 0 && (
                    <span style={{ marginLeft: 6 }}><Badge variant="info">
                      {activeCount}
                    </Badge></span>
                  )}
                </span>
                <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                  {jobs.some((j) => j.status !== 'downloading') && (
                    <button
                      type="button"
                      onClick={handleDismissAll}
                      style={{
                        background: 'none',
                        border: 'none',
                        fontSize: '11px',
                        color: 'var(--axons-accent)',
                        cursor: 'pointer',
                        padding: 0,
                      }}
                    >
                      清除已完成
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={() => setOpen(false)}
                    style={{
                      background: 'none',
                      border: 'none',
                      fontSize: '14px',
                      color: 'var(--axons-text-muted)',
                      cursor: 'pointer',
                      padding: 0,
                      lineHeight: 1,
                    }}
                    aria-label="关闭"
                  >
                    ✕
                  </button>
                </div>
              </div>

              {/* 任务列表 */}
              <div
                style={{
                  maxHeight: '320px',
                  overflowY: 'auto',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '8px',
                }}
              >
                {jobs.map((job) => (
                  <JobRow
                    key={job.key}
                    job={job}
                    onCancel={handleCancel}
                    onRetry={handleRetry}
                    onDismiss={handleDismiss}
                  />
                ))}
              </div>
            </CardBody>
          </Card>
        </div>
      )}
    </>
  );
}

// ---- 单条任务行 ----

interface JobRowProps {
  job: DownloadJob;
  onCancel: (key: string) => void;
  onRetry: (key: string) => void;
  onDismiss: (key: string) => void;
}

function JobRow({ job, onCancel, onRetry, onDismiss }: JobRowProps) {
  const displayName = shortModelName(buildDownloadKey(job.repo_id, job.quantization));
  const isDownloading = job.status === 'downloading';
  const isCompleted = job.status === 'completed';
  const isError = job.status === 'error';
  const isCanceled = job.status === 'canceled';

  const sizeText =
    job.total > 0
      ? `${formatSize(job.completed)} / ${formatSize(job.total)}`
      : job.completed > 0
        ? `${formatSize(job.completed)}`
        : '';

  return (
    <div
      style={{
        padding: '8px',
        borderRadius: '6px',
        background: 'var(--axons-color-surface-secondary, rgba(0,0,0,0.03))',
        fontSize: '12px',
      }}
    >
      {/* 第一行：名称 + 状态 */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginBottom: isDownloading ? '6px' : '4px',
        }}
      >
        <span
          style={{
            fontWeight: 500,
            color: 'var(--axons-text-primary)',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
            maxWidth: '200px',
          }}
          title={job.key}
        >
          {displayName}
        </span>
        <div style={{ display: 'flex', gap: '4px', alignItems: 'center' }}>
          {isCompleted && <Badge variant="success">已完成</Badge>}
          {isError && <Badge variant="error">失败</Badge>}
          {isCanceled && <Badge variant="default">已取消</Badge>}
          {isDownloading && onCancel && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => onCancel(job.key)}
              style={{ fontSize: '11px', color: 'var(--axons-error)' }}
            >
              取消
            </Button>
          )}
          {(isError || isCanceled) && onRetry && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => onRetry(job.key)}
              style={{ fontSize: '11px', color: 'var(--axons-accent)' }}
            >
              重试
            </Button>
          )}
          {!isDownloading && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => onDismiss(job.key)}
              style={{ fontSize: '11px', color: 'var(--axons-text-muted)' }}
            >
              关闭
            </Button>
          )}
        </div>
      </div>

      {/* 进度条（仅 downloading） */}
      {isDownloading && (
        <>
          <ProgressBar value={job.progress} />
          <div
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              fontSize: '11px',
              color: 'var(--axons-text-muted)',
              marginTop: '3px',
            }}
          >
            <span>{job.progress > 0 ? `${(job.progress * 100).toFixed(1)}%` : job.detail}</span>
            {sizeText && <span>{sizeText}</span>}
          </div>
        </>
      )}

      {/* 错误信息 */}
      {isError && job.error && (
        <div
          style={{
            fontSize: '11px',
            color: 'var(--axons-error, #ef4444)',
            marginTop: '2px',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}
          title={job.error}
        >
          {job.error}
        </div>
      )}

      {/* 取消/完成 文字行 */}
      {(isCanceled || isCompleted) && (
        <div
          style={{
            fontSize: '11px',
            color: 'var(--axons-text-muted)',
            marginTop: '2px',
          }}
        >
          {isCanceled ? '已取消下载' : sizeText || '下载完成'}
        </div>
      )}
    </div>
  );
}