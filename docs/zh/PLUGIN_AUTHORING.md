# 插件作者指南

三步从零创建一个 Axons 插件：脚手架 → 开发 → 打包。

**[English](../PLUGIN_AUTHORING.md) | 简体中文**

## 目录
- [最低要求](#最低要求)
- [选择插件原型](#选择插件原型)
- [原型 1：纯静态插件](#原型-1纯静态插件)
- [原型 2：仅前端插件](#原型-2仅前端插件)
- [原型 3：仅后端插件](#原型-3仅后端插件)
- [原型 4：全栈插件](#原型-4全栈插件)
- [Manifest 字段参考](#manifest-字段参考)
- [命名与版本号](#命名与版本号)
- [测试你的插件](#测试你的插件)
- [发布检查清单](#发布检查清单)

---

## 最低要求

一个合法的插件就是**任何包含 `manifest.json` 的目录**，至少含 `id` 和 `version`：

```json
{
  "id": "com.example.hello",
  "name": "Hello",
  "version": "0.1.0"
}
```

这就够了。运行 `bash build.sh com.example.hello` 确认脚本能发现它。目录可以放在仓库任意位置——脚本会遍历整棵目录树。

---

## 选择插件原型

| 原型 | 有前端？ | 有后端？ | 示例 |
|---|---|---|---|
| **纯静态** | 否 | 否 | 语言包、图标主题、代码片段库 |
| **仅前端** | 是 | 否 | 调用已有 API 的 UI 面板 |
| **仅后端** | 否 | 是 | 无头服务、暴露 HTTP 的守护进程 |
| **全栈** | 是 | 是 | 大多数非平凡插件（如 huggingface） |

选最简单的原型即可——以后随时可以往更复杂的方向演进。

---

## 原型 1：纯静态插件

**实例：** `chat.axons.locale-zh-cn`

### 目录结构
```
language/com.example.my-locale/
├── manifest.json
├── icon.svg
└── locales/
    └── frontend/
        └── strings.json
```

### `manifest.json`
```json
{
  "id": "com.example.my-locale",
  "name": "Esperanto Language Pack",
  "version": "0.1.0",
  "description": "Esperanto translations for Axons",
  "author": "you",
  "icon": "icon.svg",
  "category": "localization",
  "minAxonsVersion": "0.8.0",
  "backend": null,
  "frontend": {
    "entry": null,
    "locale": {
      "language": "eo",
      "displayName": { "native": "Esperanto", "english": "Esperanto" },
      "resources": ["locales/frontend/strings.json"]
    }
  }
}
```

### 校验与打包
```bash
bash build.sh com.example.my-locale          # 输出"纯静态，无需构建"
bash pack.sh  com.example.my-locale          # 生成 dist/<id>-<version>.axons-plugin.tar.gz
```

无 `node_modules`，无 Python，无构建步骤——打包只是把文件原样归档。

---

## 原型 2：仅前端插件

### 目录结构
```
ui/com.example.my-panel/
├── manifest.json
├── package.json            # 声明 "build": "vite build"
├── tsconfig.json
├── vite.config.js
├── src/                    # 源码（不打入 tarball）
│   └── index.tsx
└── ui/                     # 输出
    ├── icon.svg
    └── index.js            # 预构建产物（需提交 git）
```

### `manifest.json`（关键字段）
```json
{
  "id": "com.example.my-panel",
  "name": "My Panel",
  "version": "0.1.0",
  "icon": "ui/icon.svg",
  "frontend": {
    "entry": "ui/index.js",
    "panels": [{
      "id": "my-panel",
      "title": "My Panel",
      "icon": "ui/icon.svg",
      "location": "right",
      "activator": "activityBar",
      "order": 10
    }]
  }
}
```

### `package.json`（最低要求）
```json
{
  "name": "my-panel",
  "private": true,
  "type": "module",
  "scripts": { "build": "vite build" },
  "dependencies": { "react": "^19.0.0", "react-dom": "^19.0.0" },
  "devDependencies": { "@vitejs/plugin-react": "^4.3.0", "vite": "^5.4.0" }
}
```

### `vite.config.js`
```js
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  build: {
    lib: { entry: 'src/index.tsx', formats: ['es'], fileName: () => 'index.js' },
    rollupOptions: {
    external: ['react', 'react-dom', 'axons-plugin-ui'],
    },
    outDir: 'ui',
    emptyOutDir: false,        // 保留 ui/icon.svg
  },
});
```

### 校验与打包
```bash
bash build.sh com.example.my-panel    # npm ci → vite build → 验证 ui/index.js
bash pack.sh  com.example.my-panel
```

---

## 原型 3：仅后端插件

### 目录结构
```
services/com.example.my-service/
├── manifest.json
├── server.py
├── requirements.txt
├── install.sh
└── uninstall.sh
```

### `manifest.json`（关键字段）
```json
{
  "id": "com.example.my-service",
  "name": "My Service",
  "version": "0.1.0",
  "backend": {
    "command": [".venv/bin/python", "server.py"],
    "port": 0,
    "healthCheck": "/health",
    "readyTimeout": "10s",
    "install":  { "command": ["bash", "install.sh"],  "timeout": "300s" },
    "uninstall":{ "command": ["bash", "uninstall.sh"] }
  },
  "frontend": null
}
```

### `install.sh`（典型模式）
```bash
#!/bin/bash
set -e
cd "$(dirname "$0")"
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
```

### 校验与打包
```bash
bash build.sh com.example.my-service   # py_compile + pip --dry-run + bash -n
bash pack.sh  com.example.my-service
```

---

## 原型 4：全栈插件

把原型 2 + 原型 3 组合在一个插件目录中即可。完整参考实现见 [`huggingface/chat.axons.huggingface`](../../huggingface/chat.axons.huggingface)。

构建流水线自动运行两套：后端校验 **和** 前端构建。

---

## Manifest 字段参考

| 字段 | 类型 | 必需 | 说明 |
|---|---|---|---|
| `id` | string | 是 | 反向 DNS 风格，全小写，全局唯一 |
| `version` | string | 是 | 语义化版本 |
| `name` | string | 推荐 | 人类可读的显示名 |
| `description` | string | 推荐 | 一句话摘要 |
| `author` | string | 推荐 | |
| `icon` | string | 推荐 | 相对插件目录的路径（优先 `.svg`） |
| `category` | string | 推荐 | 自由填写。常用：`localization`、`productivity`、`theme`、`language-server` |
| `minAxonsVersion` | string | 推荐 | 最低兼容 Axons 版本 |
| `permissions` | string[] | 可选 | 如 `project:read`、`model:register`、`panel:create` |
| `backend` | object / null | 可选 | 见原型 3 |
| `frontend` | object / null | 可选 | 见原型 2 / 4 |
| `frontend.panels[].order` | number | 可选 | 活动栏 / Footer 图标排序权重，越小越靠前。内置保留 0–9，插件使用 10–99，省略时默认 `10` |
| `activationEvents` | string[] | 可选 | 如 `onStartup`、`onCommand:my.cmd` |

权威 schema 参见 [Axons 插件协议文档](https://www.axons.chat)。

---

## 命名与版本号

### 插件 ID 约定
- 反向 DNS，全小写：`com.<组织>.<短名>`。
- 单词间用连字符：`com.example.code-formatter`，不要 `com.example.codeFormatter`。
- ID 会出现在错误消息、注册表和导入日志中——跨版本保持稳定。

### 版本号
- 遵循[语义化版本](https://semver.org/lang/zh-CN/)：
  - `主版本号` — 不兼容的 manifest/API 变更。
  - `次版本号` — 新功能，向后兼容。
  - `修订号` — 缺陷修复。
- **打包前**递增版本号。tarball 文件名内嵌版本号：
  `com.example.my-plugin-1.2.3.axons-plugin.tar.gz`

---

## 测试你的插件

1. **本地校验：**
   ```bash
   bash build.sh com.example.my-plugin
   bash pack.sh  com.example.my-plugin
   ```
2. **检查 tarball 内容：**
   ```bash
   tar tzf dist/com.example.my-plugin-0.1.0.axons-plugin.tar.gz | sort
   ```
   注意是否误包含了 `node_modules/` 或 `__pycache__/`。
3. **导入到运行中的 Axons 实例：**
   ```bash
   curl -X POST http://127.0.0.1:9090/v1/plugins/import \
        -F 'file=@dist/com.example.my-plugin-0.1.0.axons-plugin.tar.gz'
   ```
4. **迭代：** 改代码 → `bash build.sh com.example.my-plugin` → `bash pack.sh com.example.my-plugin` → 重新导入（Axons 重新导入时自动重载插件）。

---

## 发布检查清单

提 PR 前确认：

- [ ] `manifest.json` 已递增 `version`，`description` 和 `permissions` 准确完整。
- [ ] `bash build.sh <id>` 退出码 0，无警告。
- [ ] `bash pack.sh  <id>` 生成了 tarball。
- [ ] `tar tzf dist/<id>-<ver>.axons-plugin.tar.gz` **仅**含运行时文件（无 `src/`、`node_modules/`、`__pycache__/`、`.venv/`）。
- [ ] 如有前端：`ui/index.js` 已提交到 git（用户 clone 后无需跑 npm）。
- [ ] [`CHANGELOG.md`](../../CHANGELOG.md) 已更新变更记录。
- [ ] [`README.md`](../../README.md) 插件表已更新（如新增了插件）。
- [ ] 仓库已清理：`bash clean.sh --keep-artifacts`。
- [ ] 提交信息符合项目的 commit-message 规范。