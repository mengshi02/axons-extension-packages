# 推理引擎改造方案：Ollama → llama.cpp

> 插件ID: `chat.axons.huggingface` | 日期: 2026-05-19 | 状态: 方案评审

---

## 一、痛点与背景

### 1.1 当前架构

当前插件以 Ollama 作为推理引擎，架构如下：

```
┌──────────┐     REST API      ┌──────────┐     HTTP pull      ┌─────────────┐
│  前端 UI  │ ────────────────→ │ server.py │ ────────────────→ │   Ollama    │
│ (React)  │ ←──────────────── │ (FastAPI) │ ←──────────────── │  daemon     │
└──────────┘    SSE 进度流      └──────────┘    流式 JSON       └──────┬──────┘
                                                         模型管理/推理    │
                                                                    ┌─────▼─────┐
                                                                    │ GGUF 文件  │
                                                                    │ (Ollama管) │
                                                                    └───────────┘
```

核心特征：
- **Ollama 是常驻 daemon**：一个进程管理所有模型，通过 `/api/tags`、`/api/ps`、`/api/pull` 等 REST API 提供模型全生命周期管理
- **下载委托给 Ollama**：前端通过 `hf.co/owner/repo:Q4_K_M` 格式让 Ollama 执行 `POST /api/pull`，进度通过 SSE 流式推送
- **Axons 注册走 OpenAI 兼容**：`http://localhost:11434/v1`，provider 为 `custom`

### 1.2 痛点

| # | 痛点 | 影响 | 根因 |
|---|------|------|------|
| P1 | **分片 GGUF 不支持** | 大量热门模型（如大参数量的 Q4_K_M/Q5_K_M）只有分片版本，用户下载后报错 "sharded GGUF is not supported" | Ollama [issue #5245](https://github.com/ollama/ollama/issues/5245)，长期未解决 |
| P2 | **下载速度慢** | 中国用户下载模型经常超时或极慢 | Ollama 内部走 HF 默认源，不支持镜像站；而插件已实现 HF 镜像站配置，但 Ollama 拉取时完全绕过 |
| P3 | **HF 模型兼容性差** | 部分 GGUF 仓库 Ollama 无法识别，报 "manifest not found" | Ollama 要求仓库提供 `Modelfile` 或遵循其特定的目录结构，与 HF 上的 GGUF 仓库生态不完全兼容 |
| P4 | **模型格式转换损耗** | Ollama 不是原生加载 GGUF，而是先转成自己的 GGUF 变体（修改 metadata），增加内存开销和兼容风险 | Ollama 的模型管理层引入了不必要的中间层 |
| P5 | **引擎黑盒** | 用户无法控制 GPU 层数、上下文长度、线程数等推理参数 | Ollama 的 API 暴露的参数有限，高级调优只能通过环境变量 |

### 1.3 改造动力

- **P1 是硬伤**：分片 GGUF 不支持意味着大量模型直接不可用，且无 workaround
- **P2 影响核心体验**：下载是用户使用插件的第一个环节，慢=流失
- **llama.cpp 与 GGUF 是同源生态**：llama.cpp 是 GGUF 格式的制定者和参考实现，兼容性天然最优

---

## 二、改造收益

### 2.1 功能收益

| 收益 | 说明 |
|------|------|
| 分片 GGUF 完整支持 | llama.cpp 原生支持分片加载，所有 HF 上的 GGUF 模型均可使用 |
| 下载速度可控 | 插件直接通过 HF SDK 下载，支持镜像站加速，已配置的 `hf_mirror` 和 `hf_token` 竟然能真正生效 |
| 100% GGUF 兼容 | llama.cpp 是 GGUF 格式的参考实现，任何合法 GGUF 文件均可加载 |
| 推理参数可调 | 可暴露 `n-gpu-layers`、`ctx-size`、`threads` 等关键参数，适配不同硬件 |
| 模型文件透明 | GGUF 文件存放在插件管理的目录，用户可直接查看/备份/清理 |
| 多模型并行 | 每个模型独立进程、独立端口，可同时运行多个模型（Ollama 也支持但端口固定） |

### 2.2 架构收益

| 收益 | 说明 |
|------|------|
| 去除外部 daemon 依赖 | 不再依赖 Ollama 常驻服务，插件自身即完整运行时 |
| 下载与推理解耦 | 下载（HF SDK）和推理（llama-server）独立管理，互不影响 |
| Axons 注册零改动 | llama-server 同样兼容 OpenAI API（`/v1/chat/completions`），`provider: custom` 不变 |

---

## 三、目标架构

```
┌──────────┐                ┌──────────────────────────────────┐
│  前端 UI  │                │           server.py (FastAPI)      │
│ (React)  │                │                                    │
│          │  /api/hf/*     │  ┌────────────────────────────┐    │
│          │───────────────→│  │ HF 模型搜索 (HfApi)         │    │
│          │                │  └────────────────────────────┘    │
│          │                │                                    │
│          │  /api/models/* │  ┌────────────────────────────┐    │
│          │───────────────→│  │ 下载管理器 (HF SDK)         │    │     ┌──────────────────┐
│          │←───────────────│  │  · hf_hub_download          │    │     │  本地 GGUF 文件   │
│          │  SSE 进度流     │  │  · 断点续传 / 取消 / 分片   │────┼────→│  (插件 data 目录) │
│          │                │  └────────────────────────────┘    │     └──────────────────┘
│          │                │                                    │              │
│          │  /api/engine/* │  ┌────────────────────────────┐    │              │
│          │───────────────→│  │ 进程管理器                   │    │     ┌────────▼─────────┐
│          │                │  │  · fork llama-server        │────┼────→│  llama-server     │
│          │                │  │  · 端口分配 / PID 跟踪      │    │     │  -m model.gguf    │
│          │                │  │  · kill / 异常退出处理       │    │     │  --port XXXX      │
│          │                │  └────────────────────────────┘    │     └────────┬─────────┘
│          │                │                                    │              │
│          │                │  ┌────────────────────────────┐    │     ┌────────▼─────────┐
│          │  /api/axons/*  │  │ Axons 注册                  │    │     │  Axons AI 面板    │
│          │───────────────→│  │  · provider: custom         │────┼────→│  /v1/chat/comp... │
│          │                │  │  · base_url: localhost:XXXX │    │     └──────────────────┘
│          │                │  └────────────────────────────┘    │
│          │                │                                    │
│          │                │  ┌────────────────────────────┐    │
│          │                │  │ 模型元数据 (JSON 文件)       │    │
│          │                │  │  · 模型名 ↔ GGUF 路径映射   │    │
│          │                │  │  · 端口 ↔ PID 映射          │    │
│          │                │  └────────────────────────────┘    │
└──────────┘                └──────────────────────────────────┘
```

### 3.1 核心架构变化

| 维度 | Ollama（当前） | llama.cpp（目标） |
|------|---------------|-------------------|
| 引擎形态 | 常驻 daemon，单进程管理所有模型 | 每模型一进程，按需 fork/kill |
| 模型下载 | `POST /api/pull`（Ollama 内部实现） | `huggingface_hub.hf_hub_download`（插件自管） |
| 模型存储 | Ollama 内部目录，格式不透明 | 插件 data 目录，GGUF 原文件直存 |
| 模型列表 | `GET /api/tags` | JSON 元数据文件 + 文件系统扫描 |
| 模型启停 | `keep_alive` 参数控制加载/卸载 | fork / kill `llama-server` 子进程 |
| 推理参数 | 有限（环境变量） | 丰富（`--n-gpu-layers`、`--ctx-size` 等） |
| OpenAI API | `:11434/v1/chat/completions` | `:{port}/v1/chat/completions` |
| 端口 | 固定 11434 | 动态分配（端口池） |

### 3.2 下载层设计：HF Python SDK

**选择 `huggingface_hub.hf_hub_download`**，不使用 llama.cpp 的 `--hf-repo` 参数。

| 维度 | HF Python SDK | llama.cpp `--hf-repo` |
|------|--------------|----------------------|
| 进度回调 | 支持 `Callback`，可 SSE 推给前端 | 无，阻塞式下载 |
| 断点续传 | 内置支持 | 无 |
| 取消下载 | 可中断线程 + 清理临时文件 | 无法取消 |
| 分片 GGUF | 可逐个下载所有分片文件 | 只能指定单个 `--hf-file` |
| 镜像站 | 项目已支持（`_HF_CONFIG["hf_mirror"]`） | 不支持自定义镜像 |
| Token 认证 | 项目已支持 | 需设 `HF_TOKEN` 环境变量 |
| 文件存放 | 可控路径（插件 data 目录） | 只能存 HF 默认 cache |
| 依赖 | **已有**（`requirements.txt`） | 无额外依赖 |

下载流程：
1. 用户选择模型 + 量化 → 前端调 `/api/models/download`
2. 后端解析出该量化的所有 GGUF 文件（含分片），用 `hf_hub_download` 逐个下载
3. 下载过程中通过 SSE 流式推送进度（已完成字节 / 总字节）
4. 支持断点续传：已下载的文件 `hf_hub_download` 自动跳过
5. 支持取消：通过 `threading.Event` 中断下载线程
6. 全部下载完成 → 写入模型元数据 JSON

### 3.3 进程管理器设计

```python
# 进程管理器核心结构
class LlamaServerManager:
    """管理所有 llama-server 子进程"""

    # 端口池：从 BASE_PORT 开始分配
    BASE_PORT = 18081

    # 运行中的模型：model_name → ProcessInfo
    # ProcessInfo = {pid, port, model_name, gguf_path, started_at, process}
    _running: dict[str, ProcessInfo] = {}

    def start_model(self, model_name: str, gguf_path: str, **kwargs) -> ProcessInfo:
        """fork 一个 llama-server 子进程"""
        port = self._allocate_port()
        argv = [
            self._llama_server_path,
            "-m", gguf_path,
            "--port", str(port),
            "--host", "127.0.0.1",
            "-c", str(kwargs.get("ctx_size", 4096)),
            "-ngl", str(kwargs.get("n_gpu_layers", -1)),
        ]
        process = subprocess.Popen(argv, start_new_session=True, ...)
        self._running[model_name] = ProcessInfo(...)
        return self._running[model_name]

    def stop_model(self, model_name: str) -> None:
        """优雅停止：SIGTERM → 等 5s → SIGKILL"""
        info = self._running.pop(model_name)
        info.process.terminate()
        try: info.process.wait(timeout=5)
        except: info.process.kill()

    def _allocate_port(self) -> int:
        """从端口池分配一个可用端口"""
        used = {info.port for info in self._running.values()}
        port = self.BASE_PORT
        while port in used:
            port += 1
        return port
```

### 3.4 模型元数据设计

替代 Ollama 的 `/api/tags`，用 JSON 文件记录本地模型信息：

```json
{
  "models": [
    {
      "name": "Llama-3.2-3B-Instruct-Q4_K_M",
      "repo_id": "bartowski/Llama-3.2-3B-Instruct-GGUF",
      "quantization": "Q4_K_M",
      "gguf_files": [
        "~/.axons/plugins/chat.axons.huggingface/models/bartowski/Llama-3.2-3B-Instruct-GGUF/Llama-3.2-3B-Instruct-Q4_K_M.gguf"
      ],
      "total_size": 2019393189,
      "downloaded_at": "2026-05-19T10:30:00Z",
      "family": "llama",
      "parameter_size": "3B"
    }
  ]
}
```

存储路径：`~/.axons/plugins/chat.axons.huggingface/models.json`

GGUF 文件存储：`~/.axons/plugins/chat.axons.huggingface/models/{repo_id}/`

llama-server 可执行文件：`~/.axons/plugins/chat.axons.huggingface/bin/llama-server`

> 路径约定：所有插件持久化数据统一存放在 `~/.axons/plugins/{plugin_id}/` 下，由 Axons 平台按插件 ID 隔离。

---

## 四、改造范围与影响分析

### 4.1 后端改造（server.py，影响最大）

| 模块 | 当前实现 | 改造内容 | 改造程度 |
|------|---------|---------|---------|
| `ollama_*` 代理函数（6个） | 所有模型操作通过 Ollama REST API | 全部移除，替换为自管模块 | **重写** |
| `/api/engine/status` | 探测 Ollama daemon | 探测 llama-server 可执行文件 + 运行中的进程 | **重写** |
| `/api/engine/start` | 拉起 Ollama daemon | 不再需要"启动引擎"概念；改为检查/下载 llama-server | **重写** |
| `/api/models/pull` + SSE | Ollama `/api/pull` 流式代理 | HF SDK 自管下载 + SSE 进度推送 | **重写** |
| `/api/models/pull/cancel` | 断开 Ollama 连接 | 中断下载线程 + 清理临时文件 | **重写** |
| `/api/models/pull/status` | 从 Ollama 代理 | 从进程内 `_active_downloads` dict | 小改 |
| `/api/models/local` | Ollama `/api/tags` + `/api/ps` | 读 JSON 元数据 + 查进程管理器 | **重写** |
| `/api/models/run` | Ollama `/api/generate keep_alive=24h` | fork llama-server + 等健康检查 | **重写** |
| `/api/models/stop` | Ollama `/api/generate keep_alive=0` | kill llama-server 进程 | **重写** |
| `/api/models/delete` | Ollama `DELETE /api/delete` | 删除本地 GGUF 文件 + 清理元数据 | **重写** |
| `_register_to_axons` | `base_url = localhost:11434/v1` | `base_url = localhost:{port}/v1` | 小改 |
| `_model_display_name` | `[Ollama]` 后缀 | `[Local]` 后缀 | 小改 |
| `/cleanup` | 清理 Ollama 相关注册 | 改为清理所有本插件注册的模型 | 小改 |
| `_extract_quantizations` | 区分 `available` / `sharded_only` | **移除 sharded_only 分类**，所有量化均为可用 | **简化** |
| HF 搜索 (`/api/hf/models`) | 无变化 | 响应中移除 `sharded_only_quantizations` 字段 | 小改 |

**新增模块**：

| 模块 | 说明 |
|------|------|
| `GGUFDownloader` | 用 HF SDK 下载 GGUF 文件，支持进度回调、取消、分片 |
| `LlamaServerManager` | 进程管理器：fork/kill/端口分配/健康检查 |
| `ModelMetadataStore` | JSON 文件读写，模型元数据 CRUD |

### 4.2 前端改造

| 文件 | 改造内容 | 改造程度 |
|------|---------|---------|
| [`EngineStatusBar.tsx`](huggingface/chat.axons.huggingface/src/EngineStatusBar.tsx) | "启动 Ollama"→引擎安装/检测引导；状态结构从 `ollama` 泛化为 `engine` | **重写** |
| [`types.ts`](huggingface/chat.axons.huggingface/src/types.ts) | `EngineStatus.ollama` → `EngineStatus.engine`；`HFModel.sharded_only_quantizations` 移除 | 中改 |
| [`utils.ts`](huggingface/chat.axons.huggingface/src/utils.ts) | `buildOllamaModelName()` → `buildDownloadRequest()`；`shortModelName()` 调整 | 中改 |
| [`HFModelCard.tsx`](huggingface/chat.axons.huggingface/src/HFModelCard.tsx) | 移除分片 GGUF 不可用提示；下载请求改为 `/api/models/download` | 中改 |
| [`DownloadManager.ts`](huggingface/chat.axons.huggingface/src/DownloadManager.ts) | SSE 路径从 `/api/models/pull` → `/api/models/download`；事件名适配 | 小改 |
| [`LocalModelList.tsx`](huggingface/chat.axons.huggingface/src/LocalModelList.tsx) | 移除 "ollama pull" 提示文案 | 小改 |
| [`LocalModelCard.tsx`](huggingface/chat.axons.huggingface/src/LocalModelCard.tsx) | 运行状态从进程管理器获取而非 Ollama `/api/ps` | 小改 |

### 4.3 安装脚本改造

| 文件 | 改造内容 | 改造程度 |
|------|---------|---------|
| [`install.sh`](huggingface/chat.axons.huggingface/install.sh) | 移除 Ollama 检查/探测；新增 llama-server 可执行文件下载/校验 | **重写** |
| [`install.ps1`](huggingface/chat.axons.huggingface/install.ps1) | 同上 | **重写** |
| [`uninstall.sh`](huggingface/chat.axons.huggingface/uninstall.sh) | 新增：停止所有运行中的 llama-server + 清理 GGUF 文件 | 中改 |
| [`uninstall.ps1`](huggingface/chat.axons.huggingface/uninstall.ps1) | 同上 | 中改 |

llama-server 可执行文件获取策略：
- **优先**：从 llama.cpp GitHub Release 下载预编译版（按平台+架构选择）
- **备选**：用户自行编译/安装，插件检测 `llama-server` 在 PATH 中即可

### 4.4 配置与元数据改造

| 文件 | 改造内容 | 改造程度 |
|------|---------|---------|
| [`manifest.json`](huggingface/chat.axons.huggingface/manifest.json) | description 移除 "通过 Ollama"；permissions 不变 | 小改 |
| [`requirements.txt`](huggingface/chat.axons.huggingface/requirements.txt) | 不变（已有 `huggingface_hub`） | 无 |

---

## 五、API 前后对照

### 5.1 保留不变的端点

| 端点 | 说明 |
|------|------|
| `GET /health` | 插件自身健康检查 |
| `GET /api/hf/config` | HF 镜像站/Token 配置 |
| `POST /api/hf/config` | 设置 HF 配置 |
| `GET /api/hf/models` | HF 模型搜索（移除 `sharded_only_quantizations` 字段） |

### 5.2 重写的端点

| 原端点 | 新端点 | 变化说明 |
|--------|--------|---------|
| `GET /api/engine/status` | `GET /api/engine/status` | 响应结构从 `{ollama: {...}}` → `{engine: {type, installed, running_models}}` |
| `POST /api/engine/start` | `POST /api/engine/install` | 不再启动 daemon，改为检查/下载 llama-server 可执行文件 |
| `GET /api/models/pull?model=xxx` | `GET /api/models/download?repo_id=xxx&quantization=xxx` | 参数从 Ollama 模型名改为 repo_id + quantization；SSE 事件名适配 |
| `POST /api/models/pull/cancel` | `POST /api/models/download/cancel` | 参数改为 repo_id + quantization |
| `GET /api/models/pull/status` | `GET /api/models/download/status` | 字段名微调 |
| `GET /api/models/local` | `GET /api/models/local` | 数据来源从 Ollama → 元数据 JSON + 进程管理器 |
| `POST /api/models/run` | `POST /api/models/run` | 实现从 Ollama generate → fork llama-server |
| `POST /api/models/stop` | `POST /api/models/stop` | 实现从 Ollama keep_alive=0 → kill 进程 |
| `DELETE /api/models/delete` | `DELETE /api/models/delete` | 实现从 Ollama delete → 删除本地文件 |

### 5.3 新增端点

| 端点 | 说明 |
|------|------|
| `GET /api/engine/llama-server-path` | 返回 llama-server 可执行文件路径（前端可展示） |

---

## 六、风险与应对

| 风险 | 影响 | 应对策略 |
|------|------|---------|
| **llama-server 进程管理复杂度** | 进程异常退出、端口冲突、僵尸进程 | 进程管理器定期健康检查；启动后轮询 `/health` 确认就绪；kill 时 SIGTERM → SIGKILL 分级；端口分配时先 bind 测试 |
| **llama-server 可执行文件分发** | 不同平台/架构需不同版本；用户可能没有编译环境 | install.sh 从 GitHub Release 下载预编译版；支持用户自行提供 PATH 中的 llama-server |
| **多模型并行资源占用** | 同时运行多个大模型可能内存不足 | 前端展示内存预估；超过阈值时提示用户；进程管理器可限制最大并行数 |
| **Windows 兼容性** | llama-server 在 Windows 上的 GPU 支持（cuBLAS）需额外 DLL | install.ps1 同时下载依赖 DLL；提供 CPU-only fallback |
| **迁移过渡** | 已用 Ollama 的用户有存量模型 | 提供一次性的 "从 Ollama 导入" 功能，扫描 Ollama 模型目录并注册到元数据 |

---

## 七、改造优先级与里程碑

### Phase 1：核心引擎替换（MVP）

**目标**：替换推理引擎，基本功能可用。

1. 后端：实现 `LlamaServerManager` + `ModelMetadataStore`
2. 后端：重写 `/api/engine/status`、`/api/models/run`、`/api/models/stop`
3. 后端：重写 `/api/models/local`、`/api/models/delete`
4. 安装脚本：下载 llama-server 可执行文件
5. 前端：`EngineStatusBar` 适配新状态结构

### Phase 2：下载层替换

**目标**：HF SDK 自管下载替代 Ollama pull。

1. 后端：实现 `GGUFDownloader`
2. 后端：重写 `/api/models/download` + SSE + 取消
3. 前端：`DownloadManager` + `HFModelCard` 适配新下载流程
4. 移除所有分片 GGUF 不可用提示

### Phase 3：增强与打磨

**目标**：推理参数暴露、Ollama 迁移辅助。

1. 推理参数配置（`n-gpu-layers`、`ctx-size`、`threads`）
2. Ollama 存量模型导入工具
3. 内存预估与并行限制
4. 前端 UX 优化（模型卡片展示、参数面板）

---

## 八、与原设计文档的关系

本文档是对 [`plugin-huggingface-design.md`](huggingface/docs/plugin-huggingface-design.md) 的补充和修订。原文档中以下章节需更新：

| 原章节 | 变化 |
|--------|------|
| §2.2 模型下载与启停：Ollama REST API | 整节替换为 "HF SDK 下载 + llama-server 推理" |
| §2.3 从 HuggingFace 下载到 Ollama 的流程 | 整节替换为 "HF SDK 自管下载流程" |
| §2.4 最终 SDK 依赖 | 增加 `psutil`（进程管理），移除对 Ollama 的依赖说明 |
| §3.2 API 设计 | 按 §五 的对照表更新 |

原文档其余章节（HF 模型搜索、前端设计、Axons 集成）基本不变。