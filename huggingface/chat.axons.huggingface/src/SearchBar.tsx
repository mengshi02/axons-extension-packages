import React, { useState } from 'react';

interface SearchBarProps {
  value: string;
  onChange: (value: string) => void;
  onSearch: () => void;
  placeholder?: string;
}

export default function SearchBar({ value, onChange, onSearch, placeholder = '搜索...' }: SearchBarProps) {
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      onSearch();
    }
  };

  return (
    <div style={{
      display: 'flex',
      gap: '6px',
      padding: '8px 12px',
      borderBottom: '1px solid var(--axons-border-subtle, #1e1e2a)',
    }}>
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder={placeholder}
        style={{
          flex: 1,
          padding: '6px 10px',
          borderRadius: '4px',
          border: '1px solid var(--axons-border-default, #2a2a3a)',
          background: 'var(--axons-color-surface, #101018)',
          color: 'var(--axons-text-primary, #e4e4ed)',
          fontSize: '13px',
          outline: 'none',
        }}
      />
    </div>
  );
}