import React, { useState, useCallback, useEffect, useMemo } from 'react';
import type { PluginApi, TabType } from './types';
import EngineStatusBar from './EngineStatusBar';
import LocalModelList from './LocalModelList';
import HFModelList from './HFModelList';
import DownloadCenter from './DownloadCenter';
import DownloadHistory from './DownloadHistory';
import HFSettings from './HFSettings';
import { getDownloadManager } from './DownloadManager';

interface ModelManagerPanelProps {
  pluginApi: PluginApi;
}

export default function ModelManagerPanel({ pluginApi }: ModelManagerPanelProps) {
  const [activeTab, setActiveTab] = useState<TabType>('local');
  const [localRefreshKey, setLocalRefreshKey] = useState(0);

  const mgr = useMemo(() => getDownloadManager(pluginApi), [pluginApi]);

  // 面板挂载时 hydrate：从后端拉回 ongoing 任务
  useEffect(() => {
    mgr.hydrate();
  }, [mgr]);

  const handleDownloadComplete = useCallback(() => {
    // 下载完成后刷新本地模型列表
    setLocalRefreshKey((k) => k + 1);
  }, []);

  const tabItems = [
    { id: 'local', label: '本地模型' },
    { id: 'huggingface', label: '模型仓库' },
    { id: 'history', label: '下载历史' },
  ];

  return (
    <div className="plugin-chat-axons-huggingface__panel" style={{
      display: 'flex',
      flexDirection: 'column',
      height: '100%',
      background: 'var(--axons-color-surface)',
      color: 'var(--axons-text-primary)',
      fontFamily: 'var(--axons-font-sans)',
      position: 'relative',
    }}>
      {/*
        标题栏 — 严格遵守 panel-alignment-guide.md：
        - 固定高度 38px（不靠 padding 撑高）
        - 内边距 px-3 py-2 = 8px 12px
        - 下边框 1px subtle
      */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '8px 12px',
        height: '38px',
        boxSizing: 'border-box',
        borderBottom: '1px solid var(--axons-border-subtle)',
        flexShrink: 0,
      }}>
        <span style={{ fontWeight: 600, fontSize: '14px', color: 'var(--axons-text-primary)' }}>HuggingFace</span>
        <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
          <HFSettings pluginApi={pluginApi} />
          <DownloadCenter pluginApi={pluginApi} />
        </div>
      </div>

      {/*
        Tab 切换 — Header 下方的第二行，必须严格对齐宿主面板 Tabs 行。
        规范 (panel-alignment-guide.md)：
        - 容器：flex + border-b border-border-subtle，固定高度 31px，无 padding
        - 按钮：flex-1 + px-4 + py-1.5 + text-xs + font-medium
        - 激活态：border-b-2 border-accent
        手写实现以避免宿主 axons-plugin-ui 的 Tabs 组件样式与目标高度不一致。
      */}
      <div
        style={{
          display: 'flex',
          height: '31px',
          boxSizing: 'border-box',
          borderBottom: '1px solid var(--axons-border-subtle)',
          flexShrink: 0,
        }}
      >
        {tabItems.map((tab) => {
          const isActive = tab.id === activeTab;
          return (
            <button
              key={tab.id}
              type="button"
              onClick={() => setActiveTab(tab.id as TabType)}
              style={{
                flex: 1,
                padding: '0 16px',
                height: '100%',
                fontSize: '12px',
                lineHeight: '16px',
                fontWeight: 500,
                background: 'transparent',
                border: 'none',
                borderBottom: isActive
                  ? '2px solid var(--axons-accent)'
                  : '2px solid transparent',
                color: isActive
                  ? 'var(--axons-text-primary)'
                  : 'var(--axons-text-secondary)',
                cursor: 'pointer',
                outline: 'none',
                boxSizing: 'border-box',
              }}
            >
              {tab.label}
            </button>
          );
        })}
      </div>

      {/* 引擎状态栏 — 放到 Tabs 下方，作为面板内容区的状态提示 */}
      <EngineStatusBar pluginApi={pluginApi} />

      {/* 内容区 */}
      <div style={{ flex: 1, overflowY: 'auto', minHeight: 0 }}>
        {activeTab === 'local' ? (
          <LocalModelList key={localRefreshKey} pluginApi={pluginApi} />
        ) : activeTab === 'huggingface' ? (
          <HFModelList
              pluginApi={pluginApi}
              onDownloadComplete={handleDownloadComplete}
            />
          ) : (
            <DownloadHistory
            pluginApi={pluginApi}
            onDownloadComplete={handleDownloadComplete}
          />
        )}
      </div>
    </div>
  );
}