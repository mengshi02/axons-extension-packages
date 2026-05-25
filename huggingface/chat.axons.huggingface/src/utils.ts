/**
 * 工具函数
 */

/**
 * 格式化文件大小
 * @param bytes 字节数
 * @returns 格式化后的字符串，如 "1.9 GB"
 */
export function formatSize(bytes: number): string {
  if (bytes === 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  const k = 1024;
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${(bytes / Math.pow(k, i)).toFixed(1)} ${units[i]}`;
}

/**
 * 格式化下载数量
 * @param count 下载数
 * @returns 格式化后的字符串，如 "532K"
 */
export function formatDownloads(count: number): string {
  if (count >= 1_000_000) return `${(count / 1_000_000).toFixed(1)}M`;
  if (count >= 1_000) return `${(count / 1_000).toFixed(0)}K`;
  return count.toString();
}

/**
 * 构建下载请求的 SSE 路径
 * @param repoId HF 仓库 ID，如 "bartowski/Llama-3.2-3B-Instruct-GGUF"
 * @param quantization 量化类型，如 "Q4_K_M"
 * @returns SSE 订阅路径，如 "/api/models/download?repo_id=...&quantization=..."
 */
export function buildDownloadSsePath(repoId: string, quantization: string): string {
  return `/api/models/download?repo_id=${encodeURIComponent(repoId)}&quantization=${encodeURIComponent(quantization)}`;
}

/**
 * 构建下载任务的唯一 key
 * @param repoId HF 仓库 ID
 * @param quantization 量化类型
 * @returns 如 "bartowski/Llama-3.2-3B-Instruct-GGUF:Q4_K_M"
 */
export function buildDownloadKey(repoId: string, quantization: string): string {
  return `${repoId}:${quantization}`;
}

/**
 * 从模型名中提取显示名
 * @param modelName 模型名
 * @returns 简短的显示名
 */
export function shortModelName(modelName: string): string {
  // bartowski/Llama-3.2-3B-Instruct-GGUF:Q4_K_M → Llama-3.2-3B-Instruct (Q4_K_M)
  // Llama-3.2-3B-Instruct-Q4_K_M → Llama-3.2-3B-Instruct (Q4_K_M)
  const parts = modelName.split(':');
  const basePart = parts[0].split('/').pop()?.replace('-GGUF', '').replace('-gguf', '') || modelName;
  const quant = parts[1];

  // 如果没有冒号分隔的量化，尝试从名称中提取
  if (!quant) {
    const match = basePart.match(/[-](Q[2-8](?:_[01KS](?:_[SML])?)?|IQ[1-4](?:_[A-Z]+)?|F16|BF16|F32)$/i);
    if (match) {
      const name = basePart.slice(0, -match[0].length);
      return `${name} (${match[1].toUpperCase()})`;
    }
    return basePart;
  }

  return `${basePart} (${quant})`;
}

/**
 * 生成唯一 ID（简单实现）
 */
export function uid(): string {
  return Math.random().toString(36).substring(2, 10);
}