import React, { useState, useCallback } from 'react';
import { Spinner } from 'axons-plugin-ui';
import type { PluginApi, HFModel } from './types';
import HFModelCard from './HFModelCard';

interface HFModelListProps {
  pluginApi: PluginApi;
  onDownloadComplete: () => void;
}

export default function HFModelList({ pluginApi, onDownloadComplete }: HFModelListProps) {
  const [keyword, setKeyword] = useState('');
  const [models, setModels] = useState<HFModel[]>([]);
  const [loading, setLoading] = useState(false);
  const [searched, setSearched] = useState(false);

  const searchModels = useCallback(async () => {
    setLoading(true);
    try {
      const resp = await pluginApi.fetch(
        `/api/hf/models?keyword=${encodeURIComponent(keyword)}&limit=20`
      );
      const data = await resp.json();
      setModels(data.models || []);
      setSearched(true);
    } catch (err) {
      console.error('Failed to search HF models:', err);
    } finally {
      setLoading(false);
    }
  }, [pluginApi, keyword]);

  const loadPopular = useCallback(async () => {
    setLoading(true);
    try {
      const resp = await pluginApi.fetch('/api/hf/models?sort=downloads&limit=20');
      const data = await resp.json();
      setModels(data.models || []);
      setSearched(true);
    } catch (err) {
      console.error('Failed to load popular models:', err);
    } finally {
      setLoading(false);
    }
  }, [pluginApi]);

  React.useEffect(() => {
    loadPopular();
  }, [loadPopular]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      searchModels();
    }
  };

  return (
    <div>
      {/*
        搜索栏 — 手写以避免宿主 Input/Button 默认样式溢出。
        与 panel-alignment-guide.md 一致：px-3 py-2 内边距，subtle 下边框。
      */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        gap: '6px',
        padding: '8px 12px',
        borderBottom: '1px solid var(--axons-border-subtle)',
        boxSizing: 'border-box',
      }}>
        <input
          type="text"
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="搜索 HuggingFace 模型..."
          style={{
            flex: 1,
            minWidth: 0,
            height: '28px',
            padding: '0 10px',
            borderRadius: '4px',
            border: '1px solid var(--axons-border-default)',
            background: 'var(--axons-color-surface)',
            color: 'var(--axons-text-primary)',
            fontSize: '12px',
            lineHeight: '16px',
            outline: 'none',
            boxSizing: 'border-box',
          }}
        />
        <button
          type="button"
          onClick={searchModels}
          disabled={loading}
          style={{
            flexShrink: 0,
            height: '28px',
            padding: '0 12px',
            borderRadius: '4px',
            border: '1px solid var(--axons-accent)',
            background: 'var(--axons-accent)',
            color: '#fff',
            fontSize: '12px',
            lineHeight: '16px',
            fontWeight: 500,
            cursor: loading ? 'not-allowed' : 'pointer',
            opacity: loading ? 0.6 : 1,
            outline: 'none',
            boxSizing: 'border-box',
            whiteSpace: 'nowrap',
          }}
        >
          {loading ? '...' : '搜索'}
        </button>
      </div>

      {/* 模型列表 */}
      {loading && models.length === 0 ? (
        <div style={{
          display: 'flex',
          justifyContent: 'center',
          alignItems: 'center',
          padding: '32px',
        }}>
          <Spinner size="md" />
        </div>
      ) : models.length === 0 && searched ? (
        <div style={{
          padding: '24px',
          textAlign: 'center',
            color: 'var(--axons-text-muted)',
          fontSize: '13px',
        }}>
          未找到匹配的模型
        </div>
      ) : (
            <div>
          {models.map((model) => (
            <HFModelCard
              key={model.id}
              model={model}
              pluginApi={pluginApi}
              onDownloadComplete={onDownloadComplete}
            />
          ))}
        </div>
      )}
    </div>
  );
}