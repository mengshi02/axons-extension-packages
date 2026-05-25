# Axons 插件跨平台适配指南

> 适用于：所有需要在 Windows 和 Unix (Linux/macOS) 上运行的 Axons 插件

## 一、背景与问题

Axons 插件系统通过 `manifest.json` 声明插件的后端启动命令、安装脚本和卸载脚本。当前设计中，这些字段只有一套默认值：

```json
{
  "backend": {
    "command": [".venv/bin/python", "server.py"],
    "install": { "command": ["bash", "install.sh"] },
    "uninstall": { "command": ["bash", "uninstall.sh"] }
  }
}
```

这在类 Unix 系统上工作正常，但在 Windows 上会失败，原因如下：

| 字段 | Unix (正常) | Windows (失败) | 原因 |
|------|------------|---------------|------|
| `command` | `.venv/bin/python` | `.venv\Scripts\python.exe` | venv 目录结构不同 |
| `install.command` | `["bash", "install.sh"]` | `["cmd", "/c", "install.bat"]` 或 `["powershell", "-File", "install.ps1"]` | Windows 无 bash |
| `uninstall.command` | `["bash", "uninstall.sh"]` | `["cmd", "/c", "uninstall.bat"]` 或 `["powershell", "-File", "uninstall.ps1"]` | 同上 |
| `env` | `"OLLAMA_HOST": "http://localhost:11434"` | 部分环境需 `"http://127.0.0.1:11434"` | Windows DNS 解析行为差异 |

**核心矛盾**：`backend` 中的 `command`/`install`/`uninstall`/`env` 是平台相关的，但 `frontend`（panels/commands/entry）在所有平台上完全一致，不应重复声明。

## 二、解决方案：`platforms` 字段

在 `manifest.json` 的 `backend` 中增加 `platforms` 字段，按操作系统增量覆盖默认值：

```jsonc
{
  "backend": {
    // 默认值 — 适用于 Unix (Linux/macOS)
    "command": [".venv/bin/python", "server.py"],
    "install": { "command": ["bash", "install.sh"], "timeout": "300s" },
    "uninstall": { "command": ["bash", "uninstall.sh"] },
    "env": { "OLLAMA_HOST": "http://localhost:11434" },

    // 跨平台覆盖 — 仅覆盖与默认值不同的字段
    "platforms": {
      "windows": {
        "command": [".venv\\Scripts\\python.exe", "server.py"],
        "install": { "command": ["powershell", "-ExecutionPolicy", "Bypass", "-File", "install.ps1"] },
        "uninstall": { "command": ["powershell", "-ExecutionPolicy", "Bypass", "-File", "uninstall.ps1"] },
        "env": { "OLLAMA_HOST": "http://127.0.0.1:11434" }
      }
    }
  },
  "frontend": { /* ... 前端定义在所有平台一致，无需覆盖 ... */ }
}
```

**覆盖规则**：
1. `platforms.{os}` 中的字段**深度合并**覆盖 `backend` 同级默认值
2. 仅 `command` / `install` / `uninstall` / `env` 可被覆盖
3. 未在 `platforms.{os}` 中显式声明的字段保持默认值
4. 支持的 `os` 键：`windows` | `linux` | `darwin`
5. 不加 `platforms` 的插件自动以默认值运行，**无破坏性变更**

**宿主侧解析逻辑**：axons 在 `LoadManifest()` 时根据 `runtime.GOOS` 选择对应平台覆盖，深度合并到 `BackendDef`，合并后清除 `Platforms` 字段。后续所有流程（安装/启动/停止）使用的都是合并后的配置，无需额外感知平台差异。

## 三、插件包需要做的工作

### 3.1 修改 manifest.json

在 `backend` 中增加 `platforms.windows` 字段，覆盖 Windows 上不同的配置项。

**修改前**（仅 Unix）：

```json
{
  "backend": {
    "command": [".venv/bin/python", "server.py"],
    "install": { "command": ["bash", "install.sh"], "timeout": "300s" },
    "uninstall": { "command": ["bash", "uninstall.sh"] }
  }
}
```

**修改后**（Unix 默认 + Windows 覆盖）：

```json
{
  "backend": {
    "command": [".venv/bin/python", "server.py"],
    "install": { "command": ["bash", "install.sh"], "timeout": "300s" },
    "uninstall": { "command": ["bash", "uninstall.sh"] },
    "platforms": {
      "windows": {
        "command": [".venv\\Scripts\\python.exe", "server.py"],
        "install": { "command": ["powershell", "-ExecutionPolicy", "Bypass", "-File", "install.ps1"] },
        "uninstall": { "command": ["powershell", "-ExecutionPolicy", "Bypass", "-File", "uninstall.ps1"] }
      }
    }
  }
}
```

### 3.2 编写 Windows 安装/卸载脚本

为每个 Unix shell 脚本提供对应的 Windows 版本：

| Unix 脚本 | Windows 脚本 | 格式 |
|-----------|-------------|------|
| `install.sh` | `install.ps1` | PowerShell（推荐）或 `install.bat`（CMD） |
| `uninstall.sh` | `uninstall.ps1` | 同上 |

**命名约定**：
- 推荐 PowerShell (`.ps1`)，功能比 `.bat` 强大，错误处理更完善
- `.bat` 适用于简单场景，但缺少结构化错误处理和字符串处理能力
- 脚本文件放在插件根目录，与 `install.sh` 同级

**脚本职责对照**：

| 步骤 | install.sh | install.ps1 |
|------|-----------|-------------|
| 检查 Python | `python3 --version` | `& python --version` / `& python3 --version` |
| 创建 venv | `python3 -m venv .venv` | `& $PythonCmd -m venv .venv` |
| 激活 venv | `source .venv/bin/activate` | 无需激活，直接用 `.venv\Scripts\pip.exe` |
| 安装依赖 | `pip install -r requirements.txt` | `& ".venv\Scripts\pip.exe" install -r requirements.txt` |
| 检查 Ollama | `command -v ollama` | `Get-Command ollama -ErrorAction SilentlyContinue` |
| 启动 Ollama | `ollama serve &` | `Start-Process ollama -ArgumentList "serve"` |
| 轮询等待 | `curl -s ... && break` | `Invoke-WebRequest ...` |

**install.ps1 模板**：

```powershell
$ErrorActionPreference = "Stop"
Write-Host "=== 插件安装 ==="

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

# 1. 检查 Python
$PythonCmd = $null
foreach ($cmd in @("python3", "python")) {
    try {
        $result = & $cmd --version 2>&1
        if ($result -match "Python (\d+)\.(\d+)") {
            $major = [int]$Matches[1]; $minor = [int]$Matches[2]
            if ($major -gt 3 -or ($major -eq 3 -and $minor -ge 9)) {
                $PythonCmd = $cmd; break
            }
        }
    } catch {}
}
if (-not $PythonCmd) { Write-Host "错误: 需要 Python 3.9+"; exit 1 }

# 2. 创建虚拟环境并安装依赖
& $PythonCmd -m venv "$ScriptDir\.venv"
& "$ScriptDir\.venv\Scripts\pip.exe" install -r "$ScriptDir\requirements.txt"

# 3. 检查 Ollama
if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
    Write-Host "警告: 未找到 Ollama，请手动安装: https://ollama.com/download"
}

# 4. 检查 Ollama 服务
try {
    Invoke-WebRequest -Uri http://localhost:11434/ -UseBasicParsing -TimeoutSec 3 | Out-Null
    Write-Host "Ollama 服务运行中"
} catch {
    Write-Host "启动 Ollama 服务..."
    Start-Process ollama -ArgumentList "serve" -WindowStyle Hidden
    Start-Sleep -Seconds 3
}

Write-Host "安装完成"
```

### 3.3 无需改动的部分

以下内容在所有平台上完全一致，**无需任何修改**：

| 部分 | 原因 |
|------|------|
| `frontend`（entry/panels/commands） | 前端 UI 在浏览器/WebView 中运行，与操作系统无关 |
| `server.py`（后端业务逻辑） | Python 代码跨平台，通过环境变量 `AXONS_PLUGIN_PORT` 等获取配置 |
| `requirements.txt` | pip 依赖跨平台 |
| `ui/index.js`（前端组件） | JS 在浏览器运行，与操作系统无关 |

## 四、验证清单

完成适配后，按以下清单验证：

- [ ] `manifest.json` 中 `platforms.windows` 字段格式正确
- [ ] Windows 上 `install.ps1` 可独立运行（`powershell -ExecutionPolicy Bypass -File install.ps1`）
- [ ] Windows 上 `uninstall.ps1` 可独立运行
- [ ] Unix 上 `install.sh` 仍正常运行（platforms 不影响默认值）
- [ ] `server.py` 在两个平台上均可启动（通过 `.venv/bin/python` 或 `.venv\Scripts\python.exe`）
- [ ] 前端面板在两个平台上渲染一致

## 五、常见问题

**Q：如果插件只在 Unix 上运行，需要加 `platforms` 吗？**

不需要。`platforms` 是可选字段，不加则所有平台使用默认值。

**Q：`platforms.linux` 和 `platforms.darwin` 可以用吗？**

可以。`platforms` 支持三个键：`windows`、`linux`、`darwin`。大多数插件只需 `windows` 覆盖，如果 Linux 和 macOS 也有差异（如包管理器不同），可以分别声明。

**Q：`platforms.windows` 中必须覆盖所有字段吗？**

不需要。只需覆盖与默认值不同的字段。例如如果只有 `command` 不同，只需声明 `command`，`install` 和 `uninstall` 会自动使用默认值。

**Q：可以用 `.bat` 代替 `.ps1` 吗？**

可以。`.bat` 对应的 `install.command` 为 `["cmd", "/c", "install.bat"]`。但 PowerShell 功能更强大，推荐优先使用 `.ps1`。