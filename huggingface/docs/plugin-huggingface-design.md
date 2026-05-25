# Axons HuggingFace 插件设计文档

> 插件ID: `chat.axons.huggingface` | 版本: v1.0 | 日期: 2026-05-13 | 状态: 设计中

## 一、功能概述

HuggingFace 插件为 Axons 提供本地 LLM 模型的浏览、下载、启停、清理一站式管理能力，并与 Axons AI 面板集成，使运行中的模型可直接被 Agent 选用。

### 核心能力

| 能力 | 说明 |
|------|------|
| HF 模型浏览 | 展示 HuggingFace 上热门 GGUF 模型列表，支持关键字搜索 |
| 模型下载 | 通过 Ollama 下载 GGUF 模型到本地，带进度显示 |
| 模型启停 | 通过 Ollama 启动/停止模型推理服务 |
| 模型清理 | 从本地删除已下载的模型文件 |
| 推理引擎监控 | 检测 Ollama 服务健康状态，前端实时显示 |
| AI 面板集成 | 运行中的模型自动注册到 Axons LLM 模型列表 |

---

## 二、SDK 选型评估

### 2.1 模型发现：HuggingFace Hub Python SDK

**选择：`huggingface_hub`** — 用于浏览和搜索 HF 上的 GGUF 模型。

```python
from huggingface_hub import HfApi

api = HfApi()
# 搜索热门 GGUF 模型，按下载量排序
models = api.list_models(
    filter="gguf",           # 按 library=gguf 过滤
    sort="downloads",        # 按下载量排序
    direction=-1,            # 降序
    limit=50                 # 返回前50个
)

# 关键字搜索
models = api.list_models(
    filter="gguf",
    search="llama",          # 关键字搜索
    sort="downloads",
    limit=20
)
```

**返回字段**（`ModelInfo` 对象）：

| 字段 | 用途 |
|------|------|
| `id` | 模型 ID，如 `bartowski/Llama-3.2-3B-Instruct-GGUF` |
| `author` | 作者/组织 |
| `downloads` | 下载量（排序依据） |
| `pipeline_tag` | 任务类型（text-generation 等） |
| `tags` | 标签列表（含量化信息） |
| `last_modified` | 最后更新时间 |

### 2.2 模型下载与启停：Ollama REST API（而非 SDK）

**选择：直接调用 Ollama REST API**，理由如下：

| 维度 | Ollama Python SDK | Ollama REST API |
|------|-------------------|-----------------|
| 下载进度 | `ollama.pull()` 返回流式进度（内部封装 REST） | `POST /api/pull` 原生流式 JSON，`completed/total` 字段 |
| 启动模型 | `ollama.chat()` 触发加载（隐式） | `POST /api/generate` 空提示显式加载 |
| 停止模型 | `ollama.generate(keep_alive=0)` | `POST /api/generate {keep_alive: 0}` |
| 列出模型 | `ollama.list()` | `GET /api/tags` |
| 删除模型 | `ollama.delete()` | `DELETE /api/delete` |
| 健康检查 | 无 | `GET /` 返回 `Ollama is running` |
| 运行中模型 | `ollama.ps()` | `GET /api/ps` |
| **依赖** | 需要 `ollama` pip 包 | 零依赖，`urllib` 即可 |

**结论：用 REST API**。原因：
1. **零额外依赖** — 不需要 `ollama` pip 包（它依赖 `httpx`），减少安装复杂度
2. **进度控制更精确** — 原生流式 JSON 直接解析，`{status, digest, completed, total}` 格式清晰
3. **Ollama Python SDK 本质上是 REST API 的封装**，功能完全等价，没有额外能力
4. **一个模型从 HF 下载到 Ollama 可用，只需一步**：`POST /api/pull` 传入 HF 的模型名（见 2.3）

### 2.3 从 HuggingFace 下载模型到 Ollama 的流程

Ollama 原生支持从 HuggingFace 拉取 GGUF 模型，格式为 `hf.co/{username}/{model}:{tag}`：

```
POST http://localhost:11434/api/pull
{"model": "hf.co/bartowski/Llama-3.2-3B-Instruct-GGUF:Q4_K_M"}
```

流式响应：
```json
{"status":"pulling manifest"}
{"status":"pulling abc123","digest":"sha256:abc123","total":2019393189,"completed":241970}
{"status":"pulling abc123","digest":"sha256:abc123","total":2019393189,"completed":892381024}
...
{"status":"verifying sha256 digest"}
{"status":"writing manifest"}
{"status":"success"}
```

**这比 HuggingFace SDK 下载 + 手动导入 Ollama 的方案简单得多**：
- 方案 A（HF SDK 下载 + 手动导入）：下载 .gguf → 计算 SHA256 → `POST /api/blobs/:digest` 上传 → `POST /api/create` 创建模型 — 至少 3 步，且要处理大文件上传
- 方案 B（Ollama 直接拉取，采用）：一步完成，Ollama 内部处理所有逻辑

### 2.4 最终 SDK 依赖

| 依赖 | 用途 | 版本 |
|------|------|------|
| `huggingface_hub` | HF 模型搜索与元数据获取 | >= 0.23.0 |
| Python 标准库 `urllib` | Ollama REST API 调用 | 内置 |
| `FastAPI` | 插件后端 HTTP 服务 | >= 0.110.0 |
| `uvicorn` | ASGI 服务器 | >= 0.29.0 |

---

## 三、后端设计

### 3.1 目录结构

```
chat.axons.chat.axons.huggingface/
├── manifest.json
├── install.sh
├── uninstall.sh
├── server.py                # FastAPI 后端入口
├── requirements.txt
├── ui/
│   ├── index.js             # 前端组件 (Vite + React 打包)
│   └── icon.svg
└── skills/                  # (二期) 插件贡献的 skill
```

### 3.2 API 设计

#### 基础前缀

所有 API 前缀为插件后端地址，前端通过 `pluginApi.fetch()` 直连。

#### 3.2.1 推理引擎状态

```
GET /api/engine/status
```

响应：
```json
{
  "ollama": {
    "running": true,
    "version": "0.5.1",
    "url": "http://localhost:11434"
  }
}
```

实现：`GET http://localhost:11434/` → 检查是否返回 `Ollama is running` + `GET /api/version`。

#### 3.2.2 HF 模型搜索

```
GET /api/hf/models?keyword=llama&limit=20&offset=0
GET /api/hf/models?sort=downloads&limit=50          # 热门模型
```

响应：
```json
{
  "models": [
    {
      "id": "bartowski/Llama-3.2-3B-Instruct-GGUF",
      "author": "bartowski",
      "downloads": 532000,
      "pipeline_tag": "text-generation",
      "tags": ["gguf", "llama-3", "instruct"],
      "last_modified": "2024-09-19T00:00:00Z",
      "available_quantizations": ["Q4_K_M", "Q5_K_M", "Q8_0"],
      "url": "https://huggingface.co/bartowski/Llama-3.2-3B-Instruct-GGUF"
    }
  ],
  "total": 176568
}
```

实现：调用 `HfApi().list_models(filter="gguf", search=keyword, sort="downloads", limit=limit)`。

**量化版本发现**：HF 模型仓库通常包含多个量化版本的 GGUF 文件。通过 `api.list_repo_files(repo_id, regex="\\.gguf$")` 获取文件列表，从文件名中解析量化类型（如 `*Q4_K_M.gguf`）。

#### 3.2.3 本地模型列表

```
GET /api/models/local
```

响应：
```json
{
  "models": [
    {
      "name": "hf.co/bartowski/Llama-3.2-3B-Instruct-GGUF:Q4_K_M",
      "size": 2019393189,
      "quantization": "Q4_K_M",
      "family": "llama",
      "parameter_size": "3.2B",
      "running": true,
      "status": "running"
    },
    {
      "name": "qwen2.5-coder:7b",
      "size": 4683075271,
      "quantization": "Q4_K_M",
      "family": "qwen2",
      "parameter_size": "7.6B",
      "running": false,
      "status": "stopped"
    }
  ]
}
```

实现：
1. `GET /api/tags` — 获取所有本地模型
2. `GET /api/ps` — 获取运行中模型
3. 合并两份数据，标记 running 状态

#### 3.2.4 下载模型

```
POST /api/models/pull
Content-Type: application/json

{
  "model": "hf.co/bartowski/Llama-3.2-3B-Instruct-GGUF:Q4_K_M"
}
```

**流式响应**（SSE）：

插件后端将 Ollama 的流式 JSON 转为 SSE 推送给前端：

```
event: pull_progress
data: {"status":"pulling manifest","model":"..."}

event: pull_progress
data: {"status":"pulling abc123","digest":"sha256:abc123","total":2019393189,"completed":241970}

event: pull_progress
data: {"status":"pulling abc123","digest":"sha256:abc123","total":2019393189,"completed":892381024}

event: pull_complete
data: {"status":"success","model":"..."}
```

实现：插件后端向 Ollama `POST /api/pull` 流式请求 → 逐行读取 → 转发为 SSE。

#### 3.2.5 启动模型

```
POST /api/models/run
Content-Type: application/json

{"model": "hf.co/bartowski/Llama-3.2-3B-Instruct-GGUF:Q4_K_M"}
```

响应：
```json
{
  "status": "running",
  "model": "hf.co/bartowski/Llama-3.2-3B-Instruct-GGUF:Q4_K_M"
}
```

实现：`POST /api/generate {"model": "xxx", "keep_alive": "24h"}` 空提示加载模型到内存。

#### 3.2.6 停止模型

```
POST /api/models/stop
Content-Type: application/json

{"model": "hf.co/bartowski/Llama-3.2-3B-Instruct-GGUF:Q4_K_M"}
```

实现：`POST /api/generate {"model": "xxx", "keep_alive": 0}`。

#### 3.2.7 删除模型

```
DELETE /api/models/delete
Content-Type: application/json

{"model": "hf.co/bartowski/Llama-3.2-3B-Instruct-GGUF:Q4_K_M"}
```

实现：`DELETE /api/delete {"model": "xxx"}`。

#### 3.2.8 注册模型到 Axons

```
POST /api/models/register-to-axons
Content-Type: application/json

{
  "model": "hf.co/bartowski/Llama-3.2-3B-Instruct-GGUF:Q4_K_M",
  "base_url": "http://localhost:11434/v1"
}
```

实现：调用 `AXONS_API_URL + POST /api/llm-models`，以 `custom` provider 注册（Ollama 兼容 OpenAI API 规范）。注册时 `api_key` 填 `"ollama"`（custom 要求非空），`base_url` 必须带 `/v1` 后缀。

#### 3.2.9 清理端点（平台调用）

```
POST /cleanup
```

插件停止前由平台调用（5s 超时），清理通过 Axons API 注册的副作用数据。将所有本插件注册到 Axons 的 Ollama 模型取消注册（`DELETE /api/llm-models/:id`）。不实现此端点则平台收到 404 即跳过，不影响停止流程。

---

## 四、与 Axons AI 面板集成

### 4.1 集成机制

Axons 已有 LLM 模型管理 API（[`handlers_settings.go`](internal/api/handlers_settings.go:20)）：

```
GET    /api/llm-models       — 列出所有模型配置
POST   /api/llm-models       — 新增模型配置
PUT    /api/llm-models/:id   — 更新模型配置
DELETE /api/llm-models/:id   — 删除模型配置
```

数据结构（[`handlers_settings.go`](../internal/api/handlers_settings.go:20)）：
```go
type LLMModel struct {
    ID         string `json:"id"`
    Name       string `json:"name"`
    Provider   string `json:"provider"`    // 必须用 "custom"，不能用 "ollama"
    APIKey     string `json:"api_key"`     // "ollama"（custom 要求非空，Ollama 不校验）
    Model      string `json:"model"`       // "hf.co/bartowski/...:Q4_K_M"
    BaseURL    string `json:"base_url"`    // "http://localhost:11434/v1"（注意 /v1 后缀）
    Multimodal bool   `json:"multimodal"`
}
```

> **为什么不能用 `provider: "ollama"`**：Axons 的 [`ReinitAgentFromDB()`](../internal/api/server.go:138) 只支持 `openai`、`anthropic`、`custom` 三种 provider，`ollama` 会走 default 分支报 `unsupported LLM provider` 错误。Ollama 兼容 OpenAI `/v1/chat/completions` 规范，用 `custom` + `base_url` 即可接入。

### 4.2 注册流程

**关键：provider 必须用 `custom`，不能用 `ollama`。**

Axons 的 LLM 客户端工厂（[`server.go`](../internal/api/server.go:138)）只支持三种 provider：
- `openai` — 调 OpenAI API
- `anthropic` — 调 Anthropic API
- `custom` — 调 OpenAI 兼容 API（必须提供 base_url）

Ollama 原生兼容 OpenAI `/v1/chat/completions` 接口规范，因此用 `custom` provider + Ollama 的 `http://localhost:11434/v1` 作为 base_url 即可接入。

```
1. 用户在插件中启动模型 → Ollama 加载成功
2. 插件后端调 POST /api/llm-models（通过 AXONS_API_URL + AXONS_PLUGIN_TOKEN）
   {
     "name": "Llama-3.2-3B-Instruct (Q4_K_M) [Ollama]",
     "provider": "custom",
     "api_key": "ollama",
     "model": "hf.co/bartowski/Llama-3.2-3B-Instruct-GGUF:Q4_K_M",
     "base_url": "http://localhost:11434/v1",
     "multimodal": false
   }
3. Axons AI 面板自动刷新模型列表，用户可选择此模型
4. Agent 选中该模型后 → 走 custom 分支 → NewOpenAIClientWithBaseURL("ollama", model, "http://localhost:11434/v1")
5. 停止模型时 → 插件调 DELETE /api/llm-models/:id 删除对应配置
```

**字段说明：**

| 字段 | 值 | 理由 |
|------|-----|------|
| `provider` | `"custom"` | 走 OpenAI 兼容分支，Ollama 兼容 OpenAI API |
| `api_key` | `"ollama"` | custom provider 要求 apiKey 非空（见 `server.go:132-133`），Ollama 不校验 key，填任意值即可 |
| `base_url` | `"http://localhost:11434/v1"` | Ollama 的 OpenAI 兼容端点，注意 `/v1` 后缀 |
| `model` | Ollama 模型名 | 如 `hf.co/bartowski/Llama-3.2-3B-Instruct-GGUF:Q4_K_M` |

### 4.3 注意事项

- 注册前先检查是否已存在相同模型（通过 `GET /api/llm-models` + model name 匹配），避免重复
- 模型名映射：Ollama 模型名 `hf.co/bartowski/Llama-3.2-3B-Instruct-GGUF:Q4_K_M` → 显示名 `Llama-3.2-3B-Instruct (Q4_K_M) [Ollama]`
- 多模态模型检测：通过模型 family 或 Ollama `/api/show` 的 `capabilities` 字段判断
- **绝对不能用 `provider: "ollama"`**：当前 Axons 不支持 ollama provider，会走 default 分支报 `unsupported LLM provider`

---

## 五、前端设计

### 5.1 面板布局

```
┌────────────────────────────────────────────────────┐
│ HuggingFace                                   ✕  │
├────────────────────────────────────────────────────┤
│ 🔍 搜索 HuggingFace 模型...                         │
├────────────────────────────────────────────────────┤
│ 本地推理引擎: Ollama ● 健康  v0.5.1                 │
├────────────────────────────────────────────────────┤
│ [本地模型] [HuggingFace]                             │
├────────────────────────────────────────────────────┤
│                                                    │
│ ── 本地模型 Tab ──                                  │
│ ┌──────────────────────────────────────────────┐   │
│ │ ● Llama-3.2-3B-Instruct (Q4_K_M)   运行中    │   │
│ │   3.2B · llama · 1.9GB                       │   │
│ │                    [停止] [清理] [取消注册]     │   │
│ └──────────────────────────────────────────────┘   │
│ ┌──────────────────────────────────────────────┐   │
│ │ ○ qwen2.5-coder:7b                 已停止    │   │
│ │   7.6B · qwen2 · 4.7GB                      │   │
│ │                    [启动] [清理]               │   │
│ └──────────────────────────────────────────────┘   │
│                                                    │
│ ── HuggingFace Tab ──                              │
│ ┌──────────────────────────────────────────────┐   │
│ │ Llama-3.2-3B-Instruct-GGUF                   │   │
│ │ bartowski · 532K downloads · text-generation  │   │
│ │ 量化: [Q4_K_M] [Q5_K_M] [Q8_0]               │   │
│ │                              [下载 Q4_K_M]    │   │
│ └──────────────────────────────────────────────┘   │
│                                                    │
└────────────────────────────────────────────────────┘
```

### 5.2 核心交互

#### 模型下载进度

下载时卡片实时显示进度条：

```
┌──────────────────────────────────────────────┐
│ Llama-3.2-3B-Instruct-GGUF                   │
│ bartowski · 532K downloads                    │
│ ████████████████░░░░░░░  65%  (1.3GB/2.0GB)  │
│                                    [取消下载] │
└──────────────────────────────────────────────┘
```

前端通过 `pluginApi.createEventSource()` 连接插件后端的 SSE 端点，实时更新进度：

```tsx
const eventSource = pluginApi.createEventSource(
  `/api/models/pull?model=${encodeURIComponent(model)}`
);
eventSource.addEventListener('pull_progress', (e) => {
  const data = JSON.parse(e.data);
  const progress = data.completed / data.total;
  setDownloadProgress(model, progress);
});
eventSource.addEventListener('pull_complete', () => {
  setDownloadProgress(model, 1);
  refreshLocalHuggingFace();
  eventSource.close();
});
```

> **注意**：使用 `pluginApi.createEventSource()` 而非直接 `new EventSource(pluginApi.endpoint + ...)`，确保桌面端/Web端跨环境兼容。

#### Ollama 健康状态指示

插件前端定期（每 10s）轮询 `GET /api/engine/status`，顶部固定显示：

- `● 健康` (绿色) — Ollama 运行正常
- `○ 异常` (红色) — Ollama 未运行或不可达
- `◐ 检查中` (黄色) — 正在检测

---

## 六、安装脚本设计

### 6.1 install.sh

```bash
#!/bin/bash
set -e

echo "=== Axons HuggingFace 安装 ==="

# 1. 检查 Python 3.9+
echo "[1/4] 检查 Python 环境..."
if command -v python3 &>/dev/null; then
    PY_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
    PY_MAJOR=$(echo "$PY_VERSION" | cut -d. -f1)
    PY_MINOR=$(echo "$PY_VERSION" | cut -d. -f2)
    if [ "$PY_MAJOR" -lt 3 ] || ([ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 9 ]); then
        echo "错误: 需要 Python 3.9+，当前版本 $PY_VERSION"
        exit 1
    fi
    echo "  Python $PY_VERSION ✓"
else
    echo "错误: 未找到 python3，请先安装 Python 3.9+"
    exit 1
fi

# 2. 创建虚拟环境并安装依赖
echo "[2/4] 安装 Python 依赖..."
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
python3 -m venv "$SCRIPT_DIR/.venv"
source "$SCRIPT_DIR/.venv/bin/activate"
pip install --quiet --upgrade pip
pip install --quiet -r "$SCRIPT_DIR/requirements.txt"
echo "  依赖安装完成 ✓"

# 3. 检查 Ollama
echo "[3/4] 检查 Ollama 环境..."
if command -v ollama &>/dev/null; then
    OLLAMA_VERSION=$(ollama --version 2>/dev/null | head -1 || echo "unknown")
    echo "  Ollama $OLLAMA_VERSION ✓"
else
    echo "  警告: 未找到 Ollama，尝试安装..."
    if [[ "$OSTYPE" == "darwin"* ]]; then
        brew install ollama 2>/dev/null || echo "  请手动安装: https://ollama.com/download"
    elif [[ "$OSTYPE" == "linux"* ]]; then
        curl -fsSL https://ollama.com/install.sh | sh 2>/dev/null || echo "  请手动安装: https://ollama.com/download"
    else
        echo "  请手动安装 Ollama: https://ollama.com/download"
    fi
fi

# 4. 启动 Ollama 服务（如果未运行）
echo "[4/4] 检查 Ollama 服务..."
if curl -s http://localhost:11434/ >/dev/null 2>&1; then
    echo "  Ollama 服务运行中 ✓"
else
    echo "  启动 Ollama 服务..."
    ollama serve &
    sleep 3
    if curl -s http://localhost:11434/ >/dev/null 2>&1; then
        echo "  Ollama 服务启动成功 ✓"
    else
        echo "  警告: Ollama 服务启动失败，插件可能无法正常工作"
    fi
fi

echo ""
echo "=== 安装完成 ==="
echo "启动 axons 后，插件将自动加载。"
```

### 6.2 requirements.txt

```
fastapi>=0.110.0
uvicorn>=0.29.0
huggingface_hub>=0.23.0
sse-starlette>=2.0.0
```

> `sse-starlette` 用于 Ollama 下载进度的 SSE 推送。

### 6.3 uninstall.sh

```bash
#!/bin/bash
echo "=== 卸载 Axons HuggingFace ==="

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# 删除虚拟环境
if [ -d "$SCRIPT_DIR/.venv" ]; then
    echo "删除虚拟环境..."
    rm -rf "$SCRIPT_DIR/.venv"
fi

echo "卸载完成。Ollama 和已下载的模型不会被删除。"
echo "如需清理模型，请运行: ollama rm <model_name>"
```

---

## 七、manifest.json

```json
{
    "id": "chat.axons.chat.axons.huggingface",
    "name": "HuggingFace",
    "version": "1.0.0",
    "description": "浏览 HuggingFace GGUF 模型，通过 Ollama 下载、启停、管理本地 LLM 模型",
    "author": "axons-community",
    "icon": "ui/icon.svg",
    "category": "productivity",
    "minAxonsVersion": "0.8.0",
    "permissions": [
        "project:read",
        "model:register",
        "panel:create"
    ],
    "backend": {
        "command": [".venv/bin/python", "server.py"],
        "port": 0,
        "healthCheck": "/health",
        "readyTimeout": "15s",
        "install": {
            "command": ["bash", "install.sh"],
            "timeout": "300s"
        },
        "uninstall": {
            "command": ["bash", "uninstall.sh"]
        }
    },
    "frontend": {
        "entry": "ui/index.js",
        "panels": [{
            "id": "chat.axons.huggingface",
            "title": "HuggingFace",
            "icon": "ui/icon.svg",
            "location": "right",
            "activator": "activityBar"
        }],
        "commands": [{
            "id": "chat.axons.huggingface.open",
            "title": "Open HuggingFace",
            "shortcut": "Ctrl+Shift+M"
        }]
    },
    "activationEvents": ["onStartup"]
}
```

---

## 八、后端核心实现概要

### 8.1 server.py 骨架

```python
import os
import json
import urllib.request
import urllib.error
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from huggingface_hub import HfApi
import sse_starlette

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

OLLAMA_URL = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
AXONS_API_URL = os.environ.get("AXONS_API_URL", "http://127.0.0.1:9090")
AXONS_PLUGIN_TOKEN = os.environ.get("AXONS_PLUGIN_TOKEN", "")
AXONS_PLUGIN_PORT = os.environ.get("AXONS_PLUGIN_PORT", "18080")

hf_api = HfApi()

# --- Ollama 代理函数 ---

def ollama_get(path: str):
    """GET 请求到 Ollama"""
    req = urllib.request.Request(f"{OLLAMA_URL}{path}")
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())

def ollama_post_stream(path: str, body: dict):
    """流式 POST 请求到 Ollama，返回生成器"""
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        f"{OLLAMA_URL}{path}",
        data=data,
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=None) as resp:
        for line in resp:
            if line.strip():
                yield json.loads(line)

# --- API 路由 ---

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.get("/api/engine/status")
async def engine_status():
    try:
        version = ollama_get("/api/version")
        return {"ollama": {"running": True, "version": version.get("version", "unknown"), "url": OLLAMA_URL}}
    except Exception:
        return {"ollama": {"running": False, "version": None, "url": OLLAMA_URL}}

@app.get("/api/hf/models")
async def hf_models(keyword: str = "", sort: str = "downloads", limit: int = 50, offset: int = 0):
    models = hf_api.list_models(filter="gguf", search=keyword or None, sort=sort, direction=-1, limit=limit)
    result = []
    for m in models:
        # 从 repo 文件列表中提取量化版本
        quants = _extract_quantizations(m.id)
        result.append({
            "id": m.id, "author": m.author, "downloads": m.downloads,
            "pipeline_tag": m.pipeline_tag, "tags": m.tags,
            "last_modified": m.last_modified.isoformat() if m.last_modified else None,
            "available_quantizations": quants,
            "url": f"https://huggingface.co/{m.id}"
        })
    return {"models": result, "total": len(result)}

@app.get("/api/models/local")
async def list_models():
    tags = ollama_get("/api/tags")
    running = ollama_get("/api/ps")
    running_names = {m["name"] for m in running.get("models", [])}
    result = []
    for m in tags.get("models", []):
        details = m.get("details", {})
        result.append({
            "name": m["name"], "size": m.get("size", 0),
            "quantization": details.get("quantization_level", ""),
            "family": details.get("family", ""),
            "parameter_size": details.get("parameter_size", ""),
            "running": m["name"] in running_names,
            "status": "running" if m["name"] in running_names else "stopped"
        })
    return {"models": result}

@app.post("/api/models/pull")
async def pull_model(body: dict):
    model = body["model"]
    def stream():
        for chunk in ollama_post_stream("/api/pull", {"model": model, "stream": True}):
            if chunk.get("status") == "success":
                yield {"event": "pull_complete", "data": json.dumps({"status": "success", "model": model})}
            else:
                yield {"event": "pull_progress", "data": json.dumps(chunk)}
    return StreamingResponse(sse_starlette.EventSourceResponse(stream()), media_type="text/event-stream")

@app.post("/api/models/run")
async def run_model(body: dict):
    model = body["model"]
    # 加载模型到内存 (空 prompt + keep_alive)
    for chunk in ollama_post_stream("/api/generate", {"model": model, "keep_alive": "24h"}):
        if chunk.get("done"):
            break
    # 注册到 Axons
    _register_to_axons(model)
    return {"status": "running", "model": model}

@app.post("/api/models/stop")
async def stop_model(body: dict):
    model = body["model"]
    # 卸载模型
    for chunk in ollama_post_stream("/api/generate", {"model": model, "keep_alive": 0}):
        if chunk.get("done"):
            break
    _unregister_from_axons(model)
    return {"status": "stopped", "model": model}

@app.delete("/api/models/delete")
async def delete_model(body: dict):
    model = body["model"]
    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/delete",
        data=json.dumps({"model": model}).encode(),
        headers={"Content-Type": "application/json"},
        method="DELETE"
    )
    urllib.request.urlopen(req, timeout=30)
    _unregister_from_axons(model)
    return {"status": "deleted", "model": model}

@app.post("/cleanup")
async def cleanup():
    """插件停止前由平台调用，清理通过 Axons API 注册的副作用数据。
    
    将所有本插件注册到 Axons 的 Ollama 模型取消注册。
    平台 5s 超时，此端点必须快速完成。
    """
    existing = _get_axons_models()
    for m in existing:
        if m.get("provider") == "custom" and m.get("model"):
            try:
                req = urllib.request.Request(
                    f"{AXONS_API_URL}/api/llm-models/{m['id']}",
                    headers={"Authorization": f"Bearer {AXONS_PLUGIN_TOKEN}"},
                    method="DELETE"
                )
                urllib.request.urlopen(req, timeout=3)
            except Exception:
                pass  # 超时或已删除，跳过
    return {"status": "cleaned"}

# --- Axons 集成 ---

def _register_to_axons(model_name: str):
    """将运行中的模型注册到 Axons LLM 模型列表

    重要：provider 必须用 "custom"，不能用 "ollama"。
    Axons 只支持 openai/anthropic/custom 三种 provider。
    Ollama 兼容 OpenAI API 规范 (/v1/chat/completions)，走 custom 分支。
    """
    existing = _get_axons_models()
    # 检查是否已注册
    for m in existing:
        if m.get("model") == model_name and m.get("provider") == "custom":
            return  # 已存在
    display_name = _model_display_name(model_name)
    # Ollama 的 OpenAI 兼容端点需要 /v1 后缀
    ollama_openai_url = OLLAMA_URL.rstrip("/") + "/v1"
    body = json.dumps({
        "name": display_name,
        "provider": "custom",          # 不能用 "ollama"，Axons 不支持
        "api_key": "ollama",           # custom 要求非空，Ollama 不校验 key
        "model": model_name,
        "base_url": ollama_openai_url, # http://localhost:11434/v1
        "multimodal": False
    }).encode()
    req = urllib.request.Request(
        f"{AXONS_API_URL}/api/llm-models",
        data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {AXONS_PLUGIN_TOKEN}"},
        method="POST"
    )
    urllib.request.urlopen(req, timeout=10)

def _unregister_from_axons(model_name: str):
    """从 Axons LLM 模型列表中移除"""
    existing = _get_axons_models()
    for m in existing:
        if m.get("model") == model_name and m.get("provider") == "custom":
            req = urllib.request.Request(
                f"{AXONS_API_URL}/api/llm-models/{m['id']}",
                headers={"Authorization": f"Bearer {AXONS_PLUGIN_TOKEN}"},
                method="DELETE"
            )
            urllib.request.urlopen(req, timeout=10)
            break

def _get_axons_models():
    req = urllib.request.Request(
        f"{AXONS_API_URL}/api/llm-models",
        headers={"Authorization": f"Bearer {AXONS_PLUGIN_TOKEN}"}
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read())
    return data.get("models", [])

def _model_display_name(model_name: str) -> str:
    """hf.co/bartowski/Llama-3.2-3B-Instruct-GGUF:Q4_K_M → Llama-3.2-3B-Instruct (Q4_K_M) [Ollama]"""
    parts = model_name.split(":")
    base = parts[0].split("/")[-1].replace("-GGUF", "").replace("-gguf", "")
    quant = parts[1] if len(parts) > 1 else ""
    name = f"{base} ({quant})" if quant else base
    return f"{name} [Ollama]"

def _extract_quantizations(repo_id: str) -> list[str]:
    """从 HF repo 文件列表中提取可用的量化版本"""
    try:
        files = hf_api.list_repo_files(repo_id)
        quants = []
        for f in files:
            if f.endswith(".gguf"):
                # 从文件名提取量化类型，如 Q4_K_M, Q5_K_M, Q8_0
                for part in f.replace(".gguf", "").split("-"):
                    if part.startswith("Q") or part.startswith("q"):
                        quants.append(part.upper())
                        break
        return sorted(set(quants))
    except Exception:
        return []

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=int(AXONS_PLUGIN_PORT))
```

---

## 九、前端组件概要

前端使用 React + Vite 打包为 ESM 模块，复用 axons 的 React 运行时。

### 9.1 核心组件

| 组件 | 职责 |
|------|------|
| `ModelManagerPanel` | 面板主容器，Tab 切换（本地/HF） |
| `EngineStatusBar` | Ollama 健康状态指示条 |
| `LocalModelList` | 本地模型列表，卡片式布局 |
| `LocalModelCard` | 单个本地模型卡片，含启停/清理按钮 |
| `HFModelList` | HuggingFace 模型搜索列表 |
| `HFModelCard` | 单个 HF 模型卡片，含下载按钮和量化选择 |
| `DownloadProgress` | 下载进度条组件 |
| `SearchBar` | 搜索输入框 |

### 9.2 pluginApi 使用

```tsx
export default function ModelManagerPanel({ pluginApi }) {
  // 健康检查
  const checkEngine = () => pluginApi.fetch('/api/engine/status').then(r => r.json());

  // 搜索 HF 模型
  const searchModels = (keyword: string) =>
    pluginApi.fetch(`/api/hf/models?keyword=${keyword}&limit=20`).then(r => r.json());

  // 本地模型列表
  const localModels = () => pluginApi.fetch('/api/models/local').then(r => r.json());

  // 启动模型 → 注册到 Axons
  const runModel = (name: string) =>
    pluginApi.fetch('/api/models/run', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({model: name})
    });

  // 停止模型 → 从 Axons 取消注册
  const stopModel = (name: string) =>
    pluginApi.fetch('/api/models/stop', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({model: name})
    });

  // 下载进度 — 使用 pluginApi.createEventSource
  const pullModel = (name: string, onProgress: (p: number) => void) => {
    const es = pluginApi.createEventSource(`/api/models/pull?model=${encodeURIComponent(name)}`);
    es.addEventListener('pull_progress', (e) => {
      const d = JSON.parse(e.data);
      if (d.total && d.completed) onProgress(d.completed / d.total);
    });
    es.addEventListener('pull_complete', () => { onProgress(1); es.close(); });
  };
}
```

---

## 十、Ollama 健康监控

### 10.1 检测策略

| 场景 | 检测方式 | 间隔 |
|------|---------|------|
| 插件加载时 | `GET /api/engine/status` | 一次性 |
| 正常运行中 | `GET /api/engine/status` | 每 10 秒 |
| 检测到异常 | `GET /api/engine/status` | 每 3 秒（直到恢复） |

### 10.2 前端状态映射

```typescript
type EngineStatus = 'healthy' | 'unhealthy' | 'checking';

// 显示逻辑
const statusDisplay = {
  healthy:   { label: '健康', color: 'green', icon: '●' },
  unhealthy: { label: '异常', color: 'red',   icon: '○' },
  checking:  { label: '检查中', color: 'yellow', icon: '◐' },
};
```

---

## 十一、风险与注意事项

| 风险 | 缓解措施 |
|------|---------|
| HF API 限流 | 搜索结果缓存 5 分钟；`huggingface_hub` 内置重试和限流处理 |
| Ollama 未安装 | install.sh 检测并提示安装；运行时检测到 Ollama 不可达，前端显示异常状态并提供安装指引 |
| 大模型下载耗时 | SSE 实时进度 + 取消下载支持（前端关闭 EventSource 即可） |
| Ollama 端口非默认 | install.sh 中可通过 `OLLAMA_HOST` 环境变量配置；插件后端读环境变量 |
| 模型名映射复杂 | `_model_display_name()` 处理 `hf.co/` 前缀和量化后缀的映射 |
| HF 仓库量化文件名不统一 | `_extract_quantizations()` 容错解析，解析失败返回空列表，用户可手动输入 |

---

## 十二、二期扩展

| 能力 | 说明 |
|------|------|
| 推理引擎多选 | 支持 LM Studio、llama.cpp server 等 |
| 模型基准测试 | 展示模型在常见 benchmark 上的得分 |
| 批量下载 | 选择多个模型一次性下载 |
| 模型配置调优 | 温度、上下文长度等参数可视化调整 |
| 模型评分与评论 | 对本地模型进行评分和备注 |