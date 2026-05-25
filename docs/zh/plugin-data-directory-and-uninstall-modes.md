# 插件数据目录分离 & 卸载模式设计

## 1 背景与问题

### 1.1 现状

当前插件代码与插件数据混放在同一目录下：

```
~/.axons/plugins/
├── chat.axons.huggingface/          ← 插件代码 + 数据混放
│   ├── manifest.json                ← 代码
│   ├── server.py                    ← 代码
│   ├── .venv/                       ← 代码（安装产物）
│   ├── ui/                          ← 代码
│   ├── models/                      ← 数据（下载的 GGUF 模型）
│   ├── bin/                         ← 数据（llama-server 二进制）
│   └── models.json                  ← 数据（模型元数据）
├── com.axons.locale-zh-cn/          ← 纯代码插件，无运行时数据
└── installed.json                   ← 宿主注册表
```

宿主侧 [`UninstallPlugin()`](internal/plugin/manager.go:797) 执行 `os.RemoveAll(p.Dir)` 将整个目录删除。

### 1.2 问题

插件升级流程为"先卸载再导入新版本"，卸载时 `os.RemoveAll` 会将已下载的模型文件（可能数 GB）一起清理，升级后需要重新下载，代价极大。

### 1.3 目标

1. **插件代码与数据分离**：代码可随卸载删除，数据在升级场景下保留
2. **卸载模式区分**：支持"仅卸载代码"（升级场景）和"完全卸载"（不再使用场景）
3. **宿主 UI 适配**：卸载确认弹窗增加勾选框，让用户选择是否同时删除数据
4. **向后兼容**：新旧版本宿主与插件可组合使用

---

## 2 目录规范

### 2.1 新目录结构

```
~/.axons/plugins/
├── chat.axons.huggingface/          ← 插件代码目录（卸载时始终删除）
│   ├── manifest.json
│   ├── server.py
│   ├── .venv/
│   ├── ui/
│   ├── install.sh
│   └── uninstall.sh
├── data/                            ← 插件数据目录（仅完全卸载时删除）
│   └── chat.axons.huggingface/
│       ├── models/                  ← 下载的 GGUF 模型
│       ├── bin/                     ← llama-server 二进制
│       └── models.json              ← 模型元数据
├── com.axons.locale-zh-cn/          ← 无运行时数据的插件，无 data 子目录
└── installed.json
```

### 2.2 目录职责

| 路径 | 用途 | 内容示例 | 卸载策略 |
|------|------|----------|----------|
| `~/.axons/plugins/{id}/` | 插件代码 | manifest.json、server.py、.venv、ui/ | 始终删除 |
| `~/.axons/plugins/data/{id}/` | 插件运行时数据 | models/、bin/、models.json | 仅完全卸载时删除 |

### 2.3 数据目录发现机制

宿主在启动插件进程时注入环境变量 `AXONS_PLUGIN_DATA_DIR`，插件通过读取该变量获取数据目录路径。

```
AXONS_PLUGIN_DATA_DIR=~/.axons/plugins/data/{pluginId}
```

若环境变量不存在（旧版宿主），插件以 `~/.axons/plugins/data/{pluginId}` 为默认值回退。

---

## 3 宿主侧改动

> 仓库：`/Users/mengshi3/go/src/github.com/mengshi02/axons`

### 3.1 manifest 结构扩展

**文件**：`internal/plugin/manifest.go`

`UninstallDef` 新增 `Args` 字段，声明式描述卸载脚本支持的参数，供宿主侧校验和文档使用：

```go
// UninstallDef defines the uninstall script configuration.
type UninstallDef struct {
    Command []string       `json:"command"`
    Args    []UninstallArg `json:"args,omitempty"`
}

// UninstallArg describes a parameter accepted by the uninstall script.
type UninstallArg struct {
    Name        string `json:"name"`                  // 参数名，如 "purge_data"
    Type        string `json:"type"`                  // 类型："boolean"
    Default     bool   `json:"default,omitempty"`     // 默认值
    Description string `json:"description,omitempty"` // 参数说明
}
```

`UninstallArg` 的 `Name` 与卸载脚本命令行参数的映射规则：
- `Name: "purge_data"` → 命令行参数 `--purge-data`
- 转换规则：`snake_case` → `kebab-case`，加 `--` 前缀

### 3.2 Manager 改造

**文件**：`internal/plugin/manager.go`

#### 3.2.1 新增 PluginDataDir 方法

```go
// PluginDataDir returns the data directory for a plugin.
// Path: ~/.axons/plugins/data/{pluginId}
func (m *Manager) PluginDataDir(pluginID string) string {
    return filepath.Join(m.pluginsDir, "data", pluginID)
}
```

#### 3.2.2 启动时注入数据目录环境变量

**文件**：`internal/plugin/manager.go` → `startProcess()` 函数（约第 352 行）

在现有环境变量注入处新增一行：

```go
cmd.Env = append(os.Environ(),
    fmt.Sprintf("AXONS_API_URL=http://127.0.0.1:%d", m.axonsPort),
    fmt.Sprintf("AXONS_PLUGIN_PORT=%d", port),
    fmt.Sprintf("AXONS_PLUGIN_TOKEN=%s", inst.Token),
    fmt.Sprintf("AXONS_PLUGIN_ID=%s", manifest.ID),
    fmt.Sprintf("AXONS_PLUGIN_DATA_DIR=%s", m.PluginDataDir(manifest.ID)),  // 新增
)
```

同样，install 脚本和 uninstall 脚本执行时也需要注入此环境变量：

- `InstallPlugin()` 中执行安装脚本时，追加 `AXONS_PLUGIN_DATA_DIR`
- `UninstallPlugin()` 中执行卸载脚本时，追加 `AXONS_PLUGIN_DATA_DIR`

#### 3.2.3 修改 UninstallPlugin 签名

**文件**：`internal/plugin/manager.go`（约第 797 行）

```go
func (m *Manager) UninstallPlugin(pluginID string, purgeData bool) error {
    // 1. 停止运行中的插件实例（不变）
    if _, ok := m.instances[pluginID]; ok {
        if err := m.StopPlugin(pluginID); err != nil {
            fmt.Printf("[plugin-manager] WARN: failed to stop plugin %s during uninstall: %v\n", pluginID, err)
        }
    }

    // 2. 加载 manifest（不变）
    plugins, _ := m.ScanPlugins()
    var manifest *PluginManifest
    for _, p := range plugins {
        if p.ID == pluginID {
            if mf, err := LoadManifest(p.Dir); err == nil {
                manifest = mf
            }
            break
        }
    }

    // 3. 执行卸载脚本，传入 purge_data 参数
    for _, p := range plugins {
        if p.ID == pluginID && p.Backend != nil && p.Backend.Uninstall != nil {
            args := make([]string, len(p.Backend.Uninstall.Command))
            copy(args, p.Backend.Uninstall.Command)
            if purgeData {
                args = append(args, "--purge-data")
            }
            cmd := exec.Command(args[0], args[1:]...)
            cmd.Dir = p.Dir
            cmd.Env = append(os.Environ(),
                fmt.Sprintf("AXONS_PLUGIN_DATA_DIR=%s", m.PluginDataDir(pluginID)),
            )
            cmd.Run() // best effort
        }
    }

    // 4. 本地化插件清理（不变）
    if manifest != nil && manifest.Category == "localization" {
        m.unloadSingleLocalePlugin(pluginID, manifest)
    }

    // 5. 从运行时注册表移除（不变）
    m.mu.Lock()
    delete(m.instances, pluginID)
    m.mu.Unlock()
    m.registry.UnregisterPlugin(pluginID)

    // 6. 删除插件代码目录（不变，始终执行）
    for _, p := range plugins {
        if p.ID == pluginID {
            os.RemoveAll(p.Dir)
            break
        }
    }

    // 7. 删除插件数据目录（仅 purgeData=true 时执行）
    if purgeData {
        dataDir := m.PluginDataDir(pluginID)
        if _, err := os.Stat(dataDir); err == nil {
            os.RemoveAll(dataDir)
        }
    }

    // 8. 更新 installed.json（不变）
    m.removeInstalledPlugin(pluginID)

    // 9. 发送事件（新增 purgeData 字段）
    m.emitEvent("plugin.uninstalled", map[string]interface{}{
        "pluginId":  pluginID,
        "purgeData": purgeData,
    })

    fmt.Printf("[plugin-manager] Plugin %s uninstalled (purgeData=%v)\n", pluginID, purgeData)
    return nil
}
```

### 3.3 API 层改造

**文件**：`internal/plugin/handlers.go`（约第 316 行）

`DELETE /v1/plugins/:id` 新增 query parameter `purgeData`：

```
DELETE /v1/plugins/{id}?purgeData=true    ← 完全卸载（删除代码 + 数据）
DELETE /v1/plugins/{id}                   ← 仅卸载代码（保留数据）
```

```go
func (m *Manager) handleUninstallPlugin(w http.ResponseWriter, r *http.Request, ps httprouter.Params) {
    pluginID := ps.ByName("id")
    purgeData := r.URL.Query().Get("purgeData") == "true"
    if err := m.UninstallPlugin(pluginID, purgeData); err != nil {
        writeJSONError(w, http.StatusInternalServerError, "UNINSTALL_ERROR", err.Error())
        return
    }
    writeJSON(w, http.StatusOK, map[string]interface{}{
        "status":    "uninstalled",
        "purgeData": purgeData,
    })
}
```

### 3.4 前端 API 层改造

**文件**：`ui/src/services/api.ts`（约第 920 行）

```typescript
/** Uninstall a plugin */
export async function uninstallPlugin(pluginId: string, purgeData = false): Promise<void> {
    const params = purgeData ? '?purgeData=true' : '';
    const response = await fetch(`${getBaseURL()}/v1/plugins/${pluginId}${params}`, { method: 'DELETE' });
    if (!response.ok) {
        const err = await response.json().catch(() => ({}));
        throw new Error(err.message || 'Failed to uninstall plugin');
    }
}
```

### 3.5 ConfirmDialog 组件扩展

**文件**：`ui/src/components/ConfirmDialog.tsx`

新增可选的 `checkbox` 属性，支持在确认弹窗中显示一个勾选框：

```typescript
interface ConfirmDialogCheckbox {
    id: string;                          // checkbox 的 DOM id
    label: string;                       // 勾选框文案
    defaultChecked?: boolean;            // 默认是否勾选，默认 false
}

interface ConfirmDialogProps {
    isOpen: boolean;
    title: string;
    message: string;
    confirmLabel?: string;
    cancelLabel?: string;
    variant?: 'danger' | 'warning' | 'default';
    checkbox?: ConfirmDialogCheckbox;                              // 新增
    onConfirm: (checkboxChecked?: boolean) => void;                // 签名变更
    onCancel: () => void;
}
```

组件内部实现要点：

```tsx
export function ConfirmDialog({
    isOpen, title, message, confirmLabel, cancelLabel,
    variant = 'danger', checkbox, onConfirm, onCancel,
}: ConfirmDialogProps) {
    const [checked, setChecked] = useState(checkbox?.defaultChecked ?? false);

    // ... 原有 focus/keydown 逻辑不变 ...

    return (
        <div className="fixed inset-0 ..." onClick={onCancel}>
            <div className="bg-surface ..." onClick={e => e.stopPropagation()}>
                <div className="px-6 py-5">
                    {/* 原有 icon + title + message 不变 */}
                    <div className="flex-1 min-w-0">
                        <h3 className="...">{title}</h3>
                        <p className="...">{message}</p>
                    </div>
                    {/* 新增：勾选框 */}
                    {checkbox && (
                        <label className="mt-3 flex items-center gap-2 text-sm text-text-secondary cursor-pointer select-none">
                            <input
                                type="checkbox"
                                id={checkbox.id}
                                checked={checked}
                                onChange={e => setChecked(e.target.checked)}
                                className="rounded border-border-subtle"
                            />
                            {checkbox.label}
                        </label>
                    )}
                </div>
                <div className="flex items-center justify-end gap-2 ...">
                    <button onClick={onCancel} className="...">{_cancelLabel}</button>
                    <button onClick={() => onConfirm(checked)} className="...">{_confirmLabel}</button>
                </div>
            </div>
        </div>
    );
}
```

### 3.6 ExtensionsPanel 卸载确认弹窗改造

**文件**：`ui/src/components/ExtensionsPanel.tsx`

#### 3.6.1 handleUninstall 函数签名变更

```typescript
const handleUninstall = async (id: string, purgeData = false) => {
    setActionLoading(id);
    setConfirmDeleteId(null);
    try {
        await uninstallPlugin(id, purgeData);
        refresh();
    } catch (err) {
        console.error('Failed to uninstall plugin:', err);
    } finally {
        setActionLoading(null);
    }
};
```

#### 3.6.2 ConfirmDialog 调用改造

```tsx
<ConfirmDialog
    isOpen={confirmDeleteId !== null}
    title={t('extensions:uninstallTitle')}
    message={t('extensions:uninstallMessage')}
    confirmLabel={t('extensions:uninstallConfirm')}
    variant="danger"
    checkbox={{
        id: 'purge-data',
        label: t('extensions:uninstallPurgeData'),
        defaultChecked: false,
    }}
    onConfirm={(purgeData) => {
        if (confirmDeleteId !== null) handleUninstall(confirmDeleteId, purgeData);
    }}
    onCancel={() => setConfirmDeleteId(null)}
/>
```

### 3.7 i18n 文案

**文件**：`ui/src/i18n/en/extensions.json`

```json
{
    "uninstallTitle": "Uninstall Plugin",
    "uninstallMessage": "Are you sure you want to uninstall this plugin?",
    "uninstallConfirm": "Uninstall",
    "uninstallPurgeData": "Also delete plugin data (models, binaries, etc.)"
}
```

> 中文 i18n 由 `chat.axons.locale-zh-cn` 语言包提供，此处不列出。

### 3.8 SSE 事件扩展

**文件**：`ui/src/hooks/useEventStream.ts`

`plugin.uninstalled` 事件 payload 新增 `purgeData` 字段：

```typescript
// 已有
| 'plugin.uninstalled'

// 事件 data 结构扩展
interface PluginUninstalledEvent {
    pluginId: string;
    purgeData: boolean;  // 新增
}
```

现有消费方 `onPluginUninstalled` 回调无需改动，`purgeData` 为新增字段，不影响已有逻辑。

---

## 4 插件侧改动

> 仓库：`/Users/mengshi3/go/src/github.com/mengshi02/axons-extension-packages`

### 4.1 数据目录迁移

**文件**：`huggingface/chat.axons.huggingface/server.py`（第 46-50 行）

```python
# 旧：
PLUGIN_DATA_DIR = Path.home() / ".axons" / "plugins" / "chat.axons.huggingface"

# 新：优先使用宿主注入的环境变量
PLUGIN_DATA_DIR = Path(os.environ.get(
    "AXONS_PLUGIN_DATA_DIR",
    str(Path.home() / ".axons" / "plugins" / "data" / "chat.axons.huggingface")
))
MODELS_DIR = PLUGIN_DATA_DIR / "models"
BIN_DIR = PLUGIN_DATA_DIR / "bin"
METADATA_FILE = PLUGIN_DATA_DIR / "models.json"
```

### 4.2 安装脚本改造

**文件**：`huggingface/chat.axons.huggingface/install.sh`（第 48-51 行）

```bash
# 旧：
DATA_DIR="$HOME/.axons/plugins/chat.axons.huggingface"

# 新：优先使用宿主注入的环境变量
DATA_DIR="${AXONS_PLUGIN_DATA_DIR:-$HOME/.axons/plugins/data/chat.axons.huggingface}"
```

其余 install.sh 逻辑不变，`BIN_DIR`、`BIN_PATH` 仍基于 `DATA_DIR` 派生。

### 4.3 卸载脚本改造（macOS/Linux）

**文件**：`huggingface/chat.axons.huggingface/uninstall.sh`

```bash
#!/bin/bash
echo "=== 卸载 Axons HuggingFace ==="

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PURGE_DATA=false

# 解析命令行参数
for arg in "$@"; do
    case $arg in
        --purge-data) PURGE_DATA=true ;;
    esac
done

# 数据目录
DATA_DIR="${AXONS_PLUGIN_DATA_DIR:-$HOME/.axons/plugins/data/chat.axons.huggingface}"

# 1. 停止运行中的 llama-server 进程
echo "停止运行中的 llama-server 进程..."
if command -v pkill &>/dev/null; then
    pkill -f "llama-server.*$DATA_DIR" 2>/dev/null || true
fi

# 2. 删除虚拟环境（始终执行，属于插件代码）
if [ -d "$SCRIPT_DIR/.venv" ]; then
    echo "删除虚拟环境..."
    rm -rf "$SCRIPT_DIR/.venv"
fi

# 3. 根据参数决定是否清理数据
if [ "$PURGE_DATA" = true ]; then
    echo "清理插件数据（模型、llama-server、元数据）..."
    if [ -d "$DATA_DIR" ]; then
        rm -rf "$DATA_DIR"
    fi
    echo "完全卸载完成。"
else
    echo "插件已卸载，数据保留在: $DATA_DIR"
    echo "如需彻底清理，请手动删除: $DATA_DIR"
fi
```

### 4.4 卸载脚本改造（Windows）

**文件**：`huggingface/chat.axons.huggingface/uninstall.ps1`

```powershell
# Axons HuggingFace - Windows 卸载脚本
# 使用方法: powershell -ExecutionPolicy Bypass -File uninstall.ps1 [--purge-data]

Write-Host "=== 卸载 Axons HuggingFace ===" -ForegroundColor Cyan

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvDir = Join-Path $ScriptDir ".venv"

# 解析参数
$PurgeData = $args -contains "--purge-data"

# 数据目录
$DataDir = if ($env:AXONS_PLUGIN_DATA_DIR) { $env:AXONS_PLUGIN_DATA_DIR } else { Join-Path $env:USERPROFILE ".axons\plugins\data\chat.axons.huggingface" }

# 1. 停止 llama-server 进程
Write-Host "停止运行中的 llama-server 进程..."
Get-Process -Name "llama-server" -ErrorAction SilentlyContinue | Stop-Process -Force

# 2. 删除虚拟环境（始终执行）
if (Test-Path $VenvDir) {
    Write-Host "删除虚拟环境..."
    Remove-Item -Recurse -Force $VenvDir
}

# 3. 根据参数决定是否清理数据
if ($PurgeData) {
    Write-Host "清理插件数据（模型、llama-server、元数据）..."
    if (Test-Path $DataDir) {
        Remove-Item -Recurse -Force $DataDir
    }
    Write-Host "完全卸载完成。" -ForegroundColor Green
} else {
    Write-Host "卸载完成。" -ForegroundColor Green
    Write-Host "如需清理插件数据，请手动删除: $DataDir"
}
```

### 4.5 manifest.json 更新

**文件**：`huggingface/chat.axons.huggingface/manifest.json`

`uninstall` 节点新增 `args` 声明：

```json
{
    "backend": {
        "uninstall": {
            "command": ["bash", "uninstall.sh"],
            "args": [{
                "name": "purge_data",
                "type": "boolean",
                "default": false,
                "description": "Delete all plugin data (downloaded models, binaries, metadata)"
            }]
        },
        "platforms": {
            "windows": {
                "uninstall": {
                    "command": [
                        "powershell",
                        "-ExecutionPolicy",
                        "Bypass",
                        "-File",
                        "uninstall.ps1"
                    ],
                    "args": [{
                        "name": "purge_data",
                        "type": "boolean",
                        "default": false,
                        "description": "Delete all plugin data (downloaded models, binaries, metadata)"
                    }]
                }
            }
        }
    }
}
```

---

## 5 兼容性矩阵

| 场景 | 行为 |
|------|------|
| **新宿主 + 新插件** | 宿主注入 `AXONS_PLUGIN_DATA_DIR`，插件读取之，数据存于 `data/{id}/`。卸载支持 `purgeData` 参数。✅ 完整功能 |
| **旧宿主 + 新插件** | 宿主不注入 `AXONS_PLUGIN_DATA_DIR`，插件回退到默认路径 `~/.axons/plugins/data/{id}/`，功能正常。卸载时宿主不传 `--purge-data`，插件仅清理 .venv。⚠️ 旧宿主仍会 `os.RemoveAll` 整个代码目录，但数据已在 `data/{id}/` 不受影响 |
| **新宿主 + 旧插件** | 宿主注入 `AXONS_PLUGIN_DATA_DIR`，旧插件忽略。`purgeData=false` 时仅删代码目录；`purgeData=true` 时宿主删除 `data/{id}/`，但旧插件数据实际在 `plugins/{id}/` 下，该目录已被代码删除步骤清理。⚠️ 旧插件数据无法通过新机制保留 |

> 第三种场景是过渡期问题，软件尚未上市，不存在已安装旧插件需要兼容的情况。

---

## 6 改动文件清单

### 宿主侧（axons 仓库）

| # | 文件 | 改动说明 |
|---|------|----------|
| 1 | `internal/plugin/manifest.go` | `UninstallDef` 新增 `Args` 字段，新增 `UninstallArg` 结构体 |
| 2 | `internal/plugin/manager.go` | 新增 `PluginDataDir()` 方法；`startProcess()` 注入 `AXONS_PLUGIN_DATA_DIR`；`InstallPlugin()` 注入 `AXONS_PLUGIN_DATA_DIR`；`UninstallPlugin()` 签名变更 + 逻辑改造 |
| 3 | `internal/plugin/handlers.go` | `handleUninstallPlugin` 解析 `purgeData` query param |
| 4 | `ui/src/components/ConfirmDialog.tsx` | 新增 `checkbox` 属性支持，`onConfirm` 签名变更 |
| 5 | `ui/src/components/ExtensionsPanel.tsx` | 卸载确认弹窗传入 checkbox，`handleUninstall` 传入 `purgeData` |
| 6 | `ui/src/services/api.ts` | `uninstallPlugin` 函数新增 `purgeData` 参数 |
| 7 | `ui/src/i18n/en/extensions.json` | 新增 `uninstallConfirm`、`uninstallPurgeData` key |
| 8 | `ui/src/hooks/useEventStream.ts` | `plugin.uninstalled` 事件 data 新增 `purgeData` 字段 |

### 插件侧（axons-extension-packages 仓库）

| # | 文件 | 改动说明 |
|---|------|----------|
| 1 | `huggingface/chat.axons.huggingface/server.py` | `PLUGIN_DATA_DIR` 改读 `AXONS_PLUGIN_DATA_DIR` 环境变量 |
| 2 | `huggingface/chat.axons.huggingface/install.sh` | `DATA_DIR` 改读 `AXONS_PLUGIN_DATA_DIR` 环境变量 |
| 3 | `huggingface/chat.axons.huggingface/uninstall.sh` | 支持 `--purge-data` 参数，数据目录改读 `AXONS_PLUGIN_DATA_DIR` |
| 4 | `huggingface/chat.axons.huggingface/uninstall.ps1` | 同上，Windows 版同步改造 |
| 5 | `huggingface/chat.axons.huggingface/manifest.json` | `uninstall` 节点新增 `args` 声明 |

---

## 7 用户交互流程

### 7.1 卸载插件

```
用户点击插件卡片上的 "卸载" 按钮
        │
        ▼
┌─────────────────────────────────────┐
│  Uninstall Plugin                    │
│                                      │
│  Are you sure you want to uninstall  │
│  this plugin?                        │
│                                      │
│  ☐ Also delete plugin data           │
│    (models, binaries, etc.)          │
│                                      │
│           [Cancel]  [Uninstall]      │
└─────────────────────────────────────┘
        │
        ├── 勾选框未勾选（默认）          ├── 勾选框已勾选
        │                                │
        ▼                                ▼
  仅卸载插件代码                    卸载插件代码 + 删除数据
  保留已下载的模型等               所有数据彻底删除
  (适用于升级场景)                  (适用于不再使用场景)
```

### 7.2 升级插件流程（改动后）

```
1. 用户卸载旧版本（勾选框不勾选） → 仅删除代码，模型保留在 data/{id}/
2. 用户导入新版本 .tar.gz          → 代码安装到 plugins/{id}/
3. 新版本启动                      → 读取 AXONS_PLUGIN_DATA_DIR，发现已有模型数据，直接可用
```

对比旧流程：

```
1. 用户卸载旧版本 → 代码 + 模型全部删除
2. 用户导入新版本 → 代码安装
3. 新版本启动     → 需重新下载模型（耗时、耗流量）
```