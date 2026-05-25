import React, { useState, useEffect, useCallback } from 'react';
import { Spinner } from 'axons-plugin-ui';
import type { PluginApi, LocalModel } from './types';
import LocalModelCard from './LocalModelCard';

interface LocalModelListProps {
  pluginApi: PluginApi;
}

export default function LocalModelList({ pluginApi }: LocalModelListProps) {
  const [models, setModels] = useState<LocalModel[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchModels = useCallback(async () => {
    try {
      const resp = await pluginApi.fetch('/api/models/local');
      const data = await resp.json();
      setModels(data.models || []);
    } catch (err) {
      console.error('Failed to fetch local models:', err);
    } finally {
      setLoading(false);
    }
  }, [pluginApi]);

  useEffect(() => {
    fetchModels();
  }, [fetchModels]);

  if (loading) {
    return (
      <div style={{
        display: 'flex',
        justifyContent: 'center',
        alignItems: 'center',
        padding: '32px',
      }}>
        <Spinner size="md" />
      </div>
    );
  }

  if (models.length === 0) {
    return (
      <div style={{
        padding: '24px',
        textAlign: 'center',
        color: 'var(--axons-text-muted)',
        fontSize: '13px',
      }}>
        暂无本地模型
        <br />
        <span style={{ fontSize: '12px' }}>
          从 HuggingFace Tab 下载模型
        </span>
      </div>
    );
  }

  return (
    <div>
      {models.map((model) => (
        <LocalModelCard
          key={model.name}
          model={model}
          pluginApi={pluginApi}
          onRefresh={fetchModels}
        />
      ))}
    </div>
  );
}