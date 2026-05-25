import React, { useState, useEffect, useCallback } from 'react';
import { Modal, Button, Input, Select, Badge, Divider } from 'axons-plugin-ui';
import type { PluginApi, LocalModel, RunConfig, ModelDefaultsResponse } from './types';
import { shortModelName } from './utils';

interface RunConfigModalProps {
  /** 是否打开 */
  isOpen: boolean;
  /** 关闭回调 */
  onClose: () => void;
  /** 模型信息 */
  model: LocalModel;
  /** 插件 API */
  pluginApi: PluginApi;
  /** 启动成功后回调 */
  onRun: () => void;
}

/** KV cache 量化选项 */
const KV_CACHE_OPTIONS = [
  { value: '', label: '默认 (f16)' },
  { value: 'f16', label: 'f16' },
  { value: 'q8_0', label: 'q8_0 (推荐)' },
  { value: 'q4_0', label: 'q4_0 (省显存)' },
];

/** Flash Attention 选项 */
const FLASH_ATTN_OPTIONS = [
  { value: '', label: '自动' },
  { value: 'off', label: '关闭' },
  { value: 'on', label: '开启' },
];

export default function RunConfigModal({ isOpen, onClose, model, pluginApi, onRun }: RunConfigModalProps) {
  // 表单状态
  const [nGpuLayers, setNGpuLayers] = useState(-1);
  const [ctxSize, setCtxSize] = useState(4096);
  const [threads, setThreads] = useState(0);
  const [noWarmup, setNoWarmup] = useState(false);
  const [flashAttn, setFlashAttn] = useState('');
  const [cacheTypeK, setCacheTypeK] = useState('');
  const [cacheTypeV, setCacheTypeV] = useState('');
  const [rememberConfig, setRememberConfig] = useState(true);

  // UI 状态
  const [metalSupport, setMetalSupport] = useState(false);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [defaultsLoaded, setDefaultsLoaded] = useState(false);

  // 获取推荐配置
  useEffect(() => {
    if (!isOpen) return;

    let cancelled = false;
    (async () => {
      try {
        const resp = await pluginApi.fetch(
          `/api/models/defaults?model=${encodeURIComponent(model.name)}&family=${encodeURIComponent(model.family || '')}`
        );
        if (cancelled) return;
        if (resp.ok) {
          const data: ModelDefaultsResponse = await resp.json();
          const d = data.defaults;
          setMetalSupport(data.metal_support);
          setNGpuLayers(d.n_gpu_layers ?? (data.metal_support ? -1 : 0));
          setCtxSize(d.ctx_size ?? 4096);
          setNoWarmup(d.no_warmup ?? false);
          setFlashAttn(d.flash_attn ?? '');
          setCacheTypeK(d.cache_type_k ?? '');
          setCacheTypeV(d.cache_type_v ?? '');
        }
      } catch {
        // 降级：使用通用默认值
        setNGpuLayers(-1);
        setCtxSize(4096);
        setNoWarmup(false);
      } finally {
        if (!cancelled) setDefaultsLoaded(true);
      }
    })();

    return () => { cancelled = true; };
  }, [isOpen, model.name, model.family, pluginApi]);

  // 重置状态
  useEffect(() => {
    if (!isOpen) {
      setRunError(null);
      setStarting(false);
      setDefaultsLoaded(false);
      setAdvancedOpen(false);
    }
  }, [isOpen]);

  // 一键使用推荐配置
  const handleResetDefaults = useCallback(async () => {
    try {
      const resp = await pluginApi.fetch(
        `/api/models/defaults?model=${encodeURIComponent(model.name)}&family=${encodeURIComponent(model.family || '')}`
      );
      if (resp.ok) {
        const data: ModelDefaultsResponse = await resp.json();
        const d = data.defaults;
        setNGpuLayers(d.n_gpu_layers ?? (data.metal_support ? -1 : 0));
        setCtxSize(d.ctx_size ?? 4096);
        setNoWarmup(d.no_warmup ?? false);
        setFlashAttn(d.flash_attn ?? '');
        setCacheTypeK(d.cache_type_k ?? '');
        setCacheTypeV(d.cache_type_v ?? '');
      }
    } catch { /* ignore */ }
  }, [model.name, model.family, pluginApi]);

  // 构建启动配置
  const buildConfig = (): RunConfig => ({
    n_gpu_layers: nGpuLayers,
    ctx_size: ctxSize,
    threads: threads > 0 ? threads : undefined,
    no_warmup: noWarmup || undefined,
    flash_attn: flashAttn || undefined,
    cache_type_k: cacheTypeK || undefined,
    cache_type_v: cacheTypeV || undefined,
  });

  // 启动模型
  const handleRun = async () => {
    setStarting(true);
    setRunError(null);

    const config = buildConfig();

    // 保存配置（如果勾选记住）
    if (rememberConfig) {
      try {
        await pluginApi.fetch('/api/models/config', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ model: model.name, config }),
        });
      } catch { /* 保存失败不影响启动 */ }
    }

    // 发起启动请求
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
        onRun();
        onClose();
      }
    } catch (err: any) {
      setRunError(err?.message || '网络请求失败');
    } finally {
      setStarting(false);
    }
  };

  // 判断是否为 Qwen 系列模型
  const isQwenFamily = model.family?.toLowerCase().startsWith('qwen') ?? false;

  return (
    <Modal isOpen={isOpen} onClose={onClose} size="sm">
      <div style={{ padding: '16px 20px' }}>
        {/* 标题区 */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '4px' }}>
          <span style={{ fontWeight: 600, fontSize: '14px', color: 'var(--axons-text-primary)' }}>
            启动配置
          </span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '12px' }}>
          <span style={{ fontSize: '13px', color: 'var(--axons-text-secondary)' }}>
            {shortModelName(model.name)}
          </span>
          {metalSupport && <Badge variant="success">Metal GPU</Badge>}
          {isQwenFamily && <Badge variant="warning">需CPU模式</Badge>}
        </div>

        {!defaultsLoaded ? (
          <div style={{ textAlign: 'center', padding: '20px 0', color: 'var(--axons-text-muted)', fontSize: '13px' }}>
            加载推荐配置...
          </div>
        ) : (
          <>
            {/* GPU 层数 */}
            <div style={{ marginBottom: '12px' }}>
              <label style={{ fontSize: '12px', color: 'var(--axons-text-secondary)', display: 'block', marginBottom: '4px' }}>
                GPU 层数 <span style={{ color: 'var(--axons-text-muted)' }}>(-1=全部, 0=纯CPU)</span>
              </label>
              <Input
                type="number"
                value={nGpuLayers}
                onChange={(e) => setNGpuLayers(parseInt(e.target.value) || 0)}
                style={{ width: '100px', fontSize: '12px' }}
              />
              {isQwenFamily && (
                <div style={{ fontSize: '11px', color: 'var(--axons-color-warning, #d97706)', marginTop: '2px' }}>
                  Qwen 系列在 Metal GPU 上有 warmup 兼容性问题，推荐设为 0（纯CPU）
                </div>
              )}
              {!metalSupport && nGpuLayers !== 0 && (
                <div style={{ fontSize: '11px', color: 'var(--axons-error)', marginTop: '2px' }}>
                  当前系统不支持 Metal，GPU offload 将无效
                </div>
              )}
            </div>

            {/* 上下文长度 */}
            <div style={{ marginBottom: '12px' }}>
              <label style={{ fontSize: '12px', color: 'var(--axons-text-secondary)', display: 'block', marginBottom: '4px' }}>
                上下文长度
              </label>
              <Input
                type="number"
                value={ctxSize}
                onChange={(e) => setCtxSize(parseInt(e.target.value) || 4096)}
                style={{ width: '100px', fontSize: '12px' }}
              />
              <div style={{ fontSize: '11px', color: 'var(--axons-text-muted)', marginTop: '2px' }}>
                影响内存占用和推理能力，默认 4096
              </div>
            </div>

            {/* 线程数 */}
            <div style={{ marginBottom: '12px' }}>
              <label style={{ fontSize: '12px', color: 'var(--axons-text-secondary)', display: 'block', marginBottom: '4px' }}>
                线程数 <span style={{ color: 'var(--axons-text-muted)' }}>(0=自动)</span>
              </label>
              <Input
                type="number"
                value={threads}
                onChange={(e) => setThreads(parseInt(e.target.value) || 0)}
                style={{ width: '100px', fontSize: '12px' }}
              />
            </div>

            {/* 跳过预热 */}
            <div style={{ marginBottom: '12px' }}>
              <label style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '12px', color: 'var(--axons-text-secondary)', cursor: 'pointer' }}>
                <input
                  type="checkbox"
                  checked={noWarmup}
                  onChange={(e) => setNoWarmup(e.target.checked)}
                  style={{ width: 'auto' }}
                />
                跳过预热 (--no-warmup)
              </label>
              <div style={{ fontSize: '11px', color: 'var(--axons-text-muted)', marginTop: '2px', marginLeft: '20px' }}>
                部分模型在 Metal GPU warmup 时会崩溃
              </div>
            </div>

            {/* 高级选项折叠区 */}
            <Divider />
            <button
              type="button"
              onClick={() => setAdvancedOpen(!advancedOpen)}
              style={{
                background: 'none', border: 'none', cursor: 'pointer',
                color: 'var(--axons-text-secondary)', fontSize: '12px',
                padding: '8px 0', width: '100%', textAlign: 'left',
                display: 'flex', alignItems: 'center', gap: '4px',
              }}
            >
              <svg
                width="10" height="10" viewBox="0 0 10 10"
                style={{ transform: advancedOpen ? 'rotate(90deg)' : 'rotate(0deg)', transition: 'transform 0.15s' }}
                fill="currentColor"
              >
                <path d="M3 1l5 4-5 4z" />
              </svg>
              高级选项
            </button>

            {advancedOpen && (
              <div style={{ marginTop: '8px' }}>
                {/* Flash Attention */}
                <div style={{ marginBottom: '12px' }}>
                  <label style={{ fontSize: '12px', color: 'var(--axons-text-secondary)', display: 'block', marginBottom: '4px' }}>
                    Flash Attention
                  </label>
                  <Select
                    value={flashAttn}
                    onChange={(e) => setFlashAttn(e.target.value)}
                    style={{ width: '120px', fontSize: '12px' }}
                  >
                    {FLASH_ATTN_OPTIONS.map(opt => (
                      <option key={opt.value} value={opt.value}>{opt.label}</option>
                    ))}
                  </Select>
                </div>

                {/* KV Cache K 量化 */}
                <div style={{ marginBottom: '12px' }}>
                  <label style={{ fontSize: '12px', color: 'var(--axons-text-secondary)', display: 'block', marginBottom: '4px' }}>
                    KV Cache K 量化
                  </label>
                  <Select
                    value={cacheTypeK}
                    onChange={(e) => setCacheTypeK(e.target.value)}
                    style={{ width: '160px', fontSize: '12px' }}
                  >
                    {KV_CACHE_OPTIONS.map(opt => (
                      <option key={opt.value} value={opt.value}>{opt.label}</option>
                    ))}
                  </Select>
                  <div style={{ fontSize: '11px', color: 'var(--axons-text-muted)', marginTop: '2px' }}>
                    量化 KV cache 节省显存
                  </div>
                </div>

                {/* KV Cache V 量化 */}
                <div style={{ marginBottom: '12px' }}>
                  <label style={{ fontSize: '12px', color: 'var(--axons-text-secondary)', display: 'block', marginBottom: '4px' }}>
                    KV Cache V 量化
                  </label>
                  <Select
                    value={cacheTypeV}
                    onChange={(e) => setCacheTypeV(e.target.value)}
                    style={{ width: '160px', fontSize: '12px' }}
                  >
                    {KV_CACHE_OPTIONS.map(opt => (
                      <option key={opt.value} value={opt.value}>{opt.label}</option>
                    ))}
                  </Select>
                </div>
              </div>
            )}

            <Divider />

            {/* 记住此配置 */}
            <div style={{ marginBottom: '12px' }}>
              <label style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '12px', color: 'var(--axons-text-secondary)', cursor: 'pointer' }}>
                <input
                  type="checkbox"
                  checked={rememberConfig}
                  onChange={(e) => setRememberConfig(e.target.checked)}
                  style={{ width: 'auto' }}
                />
                记住此模型的配置
              </label>
            </div>

            {/* 错误提示 */}
            {runError && (
              <div style={{
                marginBottom: '12px', padding: '8px 12px',
                background: 'var(--axons-error-bg, #fef2f2)',
                border: '1px solid var(--axons-error, #ef4444)',
                borderRadius: '4px', fontSize: '12px',
                color: 'var(--axons-error, #ef4444)',
                whiteSpace: 'pre-wrap', maxHeight: '120px', overflow: 'auto',
              }}>
                {runError}
              </div>
            )}

            {/* 操作按钮 */}
            <div style={{ display: 'flex', gap: '8px', justifyContent: 'space-between', alignItems: 'center' }}>
              <Button variant="ghost" size="sm" onClick={handleResetDefaults}>
                使用推荐配置
              </Button>
              <div style={{ display: 'flex', gap: '8px' }}>
                <Button variant="ghost" size="sm" onClick={onClose}>
                  取消
                </Button>
                <Button variant="primary" size="sm" onClick={handleRun} disabled={starting}>
                  {starting ? '启动中...' : '启动'}
                </Button>
              </div>
            </div>
          </>
        )}
      </div>
    </Modal>
  );
}