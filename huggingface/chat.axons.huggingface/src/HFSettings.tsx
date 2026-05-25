/**
 * 设置 — Header 右侧齿轮图标 + Popover 配置表单
 *
 * 配置项：
 * - 镜像站点域名（如 hf-mirror.com），留空则使用默认 hf.co
 * - HF Access Token，留空则匿名访问
 *
 * 持久化：通过 pluginApi.setState/getState 存储在 Axons 宿主侧
 */
import React, { useState, useEffect, useRef } from 'react';
import { Button, Input, Card, CardBody } from 'axons-plugin-ui';
import type { PluginApi } from './types';

interface HFConfig {
  hf_mirror: string;
  hf_token: string;
}

interface HFSettingsProps {
  pluginApi: PluginApi;
}

const STORAGE_KEY = 'hf_config';

export default function HFSettings({ pluginApi }: HFSettingsProps) {
  const [open, setOpen] = useState(false);
  const [mirror, setMirror] = useState('');
  const [token, setToken] = useState('');
  const [saved, setSaved] = useState(false);
  const popoverRef = useRef<HTMLDivElement>(null);
  const iconRef = useRef<HTMLButtonElement>(null);

  // 挂载时从持久化存储加载配置
  useEffect(() => {
    (async () => {
      try {
        const stored = await pluginApi.getState(STORAGE_KEY);
        if (stored && typeof stored === 'object') {
          setMirror(stored.hf_mirror || '');
          setToken(stored.hf_token || '');
        }
      } catch {
        // 宿主不支持或首次使用，忽略
      }
    })();
  }, [pluginApi]);

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

  const handleSave = async () => {
    const config: HFConfig = {
      hf_mirror: mirror.trim().replace(/^https?:\/\//, '').replace(/\/+$/, ''),
      hf_token: token.trim(),
    };

    // 持久化到宿主
    try {
      await pluginApi.setState(STORAGE_KEY, config);
    } catch {
      // 持久化失败不阻塞
    }

    // 同步到后端
    try {
      await pluginApi.fetch('/api/hf/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(config),
      });
    } catch {
      // 后端不可达，下次启动时会从持久化恢复
    }

    // 更新本地状态（确保显示的是清洗后的值）
    setMirror(config.hf_mirror);
    setToken(config.hf_token);

    // 保存成功提示
    setSaved(true);
    setTimeout(() => setSaved(false), 1500);
  };

  const handleReset = () => {
    setMirror('');
    setToken('');
  };

  return (
    <>
      {/* 齿轮图标按钮 */}
      <button
        ref={iconRef}
        type="button"
        onClick={() => setOpen((prev) => !prev)}
        aria-label="设置"
        title="设置"
        style={{
          background: 'none',
          border: 'none',
          cursor: 'pointer',
          padding: '2px 6px',
          display: 'flex',
          alignItems: 'center',
          color: 'var(--axons-text-secondary)',
          lineHeight: 1,
        }}
      >
        {/* 齿轮 SVG */}
        <svg
          width="16"
          height="16"
          viewBox="0 0 16 16"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.2"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <circle cx="8" cy="8" r="2.5" />
          <path d="M8 1.5v1.5M8 13v1.5M1.5 8h1.5M13 8h1.5M3.4 3.4l1.1 1.1M11.5 11.5l1.1 1.1M3.4 12.6l1.1-1.1M11.5 4.5l1.1-1.1" />
        </svg>
      </button>

      {/* Popover */}
      {open && (
        <div
          ref={popoverRef}
          style={{
            position: 'absolute',
            top: '38px',
            right: '8px',
            width: '300px',
            zIndex: 50,
            boxShadow: '0 4px 16px rgba(0,0,0,0.12)',
            borderRadius: '8px',
            overflow: 'hidden',
          }}
        >
          <Card>
            <CardBody>
              {/* 标题 */}
              <div style={{
                fontWeight: 600,
                fontSize: '13px',
                color: 'var(--axons-text-primary)',
                marginBottom: '12px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
              }}>
                <span>设置</span>
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

              {/* 镜像站点 */}
              <label style={{
                display: 'block',
                fontSize: '12px',
                fontWeight: 500,
                color: 'var(--axons-text-secondary)',
                marginBottom: '4px',
              }}>
                镜像站点
              </label>
              <Input
                type="text"
                value={mirror}
                onChange={(e) => setMirror(e.target.value)}
                placeholder="hf-mirror.com"
                style={{ fontSize: '12px', marginBottom: '4px' }}
              />
              <div style={{
                fontSize: '11px',
                color: 'var(--axons-text-muted)',
                marginBottom: '12px',
              }}>
                留空则使用默认 hf.co
              </div>

              {/* Access Token */}
              <label style={{
                display: 'block',
                fontSize: '12px',
                fontWeight: 500,
                color: 'var(--axons-text-secondary)',
                marginBottom: '4px',
              }}>
                Access Token
              </label>
              <Input
                type="password"
                value={token}
                onChange={(e) => setToken(e.target.value)}
                placeholder="hf_xxxxxxxx"
                style={{ fontSize: '12px', marginBottom: '4px' }}
              />
              <div style={{
                fontSize: '11px',
                color: 'var(--axons-text-muted)',
                marginBottom: '16px',
              }}>
                用于搜索 Gated 模型与解除限速
              </div>

              {/* 按钮行 */}
              <div style={{
                display: 'flex',
                gap: '8px',
                justifyContent: 'space-between',
                alignItems: 'center',
              }}>
                <button
                  type="button"
                  onClick={handleReset}
                  style={{
                    background: 'none',
                    border: 'none',
                    fontSize: '12px',
                    color: 'var(--axons-text-muted)',
                    cursor: 'pointer',
                    padding: 0,
                  }}
                >
                  重置为默认
                </button>
                <Button
                  variant={saved ? 'secondary' : 'primary'}
                  size="sm"
                  onClick={handleSave}
                >
                  {saved ? '已保存' : '保存'}
                </Button>
              </div>
            </CardBody>
          </Card>
        </div>
      )}
    </>
  );
}