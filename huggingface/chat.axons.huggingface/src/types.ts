/**
 * 类型定义
 */

/** pluginApi 接口 — 由 axons 宿主注入 */
export interface PluginApi {
  endpoint: string | null;
  pluginId: string;
  fetch(path: string, opts?: RequestInit): Promise<Response>;
  createEventSource(path: string): EventSource;
  onEvent(type: string, handler: (payload: any) => void): () => void;
  emitEvent(type: string, payload: any): void;
  getState(key: string): Promise<any>;
  setState(key: string, value: any): Promise<void>;
}

/** 推理引擎状态 */
export interface EngineStatus {
  engine: {
    type: 'llama.cpp';
    /** llama-server 可执行文件是否已安装 */
    installed: boolean;
    /** 可执行文件路径 */
    path: string | null;
    /** 当前系统是否支持 Metal GPU 加速（macOS only） */
    metal_support: boolean;
    /** 当前运行中的模型数量 */
    running_count: number;
    /** 运行中的模型列表 */
    running_models: RunningModel[];
  };
}

/** 运行中的模型 */
export interface RunningModel {
  name: string;
  port: number;
  pid: number | null;
}

/** 模型启动配置 */
export interface RunConfig {
  /** GPU offload 层数，-1=全部，0=纯CPU */
  n_gpu_layers?: number;
  /** 上下文长度 */
  ctx_size?: number;
  /** CPU线程数，0=自动 */
  threads?: number;
  /** 跳过warmup（Metal bug绕过） */
  no_warmup?: boolean;
  /** Flash Attention: auto/on/off */
  flash_attn?: string;
  /** KV cache K 量化类型 */
  cache_type_k?: string;
  /** KV cache V 量化类型 */
  cache_type_v?: string;
}

/** 模型默认启动参数 */
export interface ModelDefaultsResponse {
  defaults: RunConfig;
  metal_support: boolean;
  available_options: Record<string, {
    label: string;
    description: string;
    type: 'number' | 'boolean' | 'select';
    options?: string[];
  }>;
}

/** 本地模型 */
export interface LocalModel {
  name: string;
  repo_id: string;
  quantization: string;
  size: number;
  family: string;
  parameter_size: string;
  running: boolean;
  status: 'running' | 'stopped';
  /** 运行中的服务端口 */
  port: number | null;
}

/** HuggingFace 模型 */
export interface HFModel {
  id: string;
  author: string | null;
  downloads: number;
  pipeline_tag: string | null;
  tags: string[];
  last_modified: string | null;
  /** 可下载的量化标签（含分片和非分片） */
  available_quantizations: string[];
  url: string;
}

/** 下载进度 */
export interface DownloadProgress {
  status: string;
  file?: string;
  file_index?: number;
  file_total?: number;
  repo_id: string;
  quantization: string;
}

/** Tab 类型 */
export type TabType = 'local' | 'huggingface' | 'history';

/** 引擎健康状态 */
export type EngineHealth = 'healthy' | 'unhealthy' | 'checking';

/** 下载历史条目 */
export interface DownloadHistoryItem {
  /** 唯一 key，格式: repo_id:quantization */
  key: string;
  /** HF 仓库 ID */
  repo_id: string;
  /** 量化类型 */
  quantization: string;
  /** 下载状态: started | completed | interrupted */
  status: string;
  /** 文件总大小（字节） */
  total_size: number;
  /** 下载开始时间 ISO 8601 */
  started_at: string | null;
  /** 下载完成时间 ISO 8601 */
  completed_at: string | null;
  /** 本地文件状态: available=模型完整 | partial=部分下载 | absent=不存在 */
  local_status: 'available' | 'partial' | 'absent';
}