# Axons 扩展插件包

> [Axons](https://www.axons.chat) 官方扩展插件的 monorepo 仓库，以 `.axons-plugin.tar.gz` 格式分发，支持离线导入。

**[English](README.md) | 简体中文**

## 📦 已有插件

| 插件 | 类型 | 分类 | 说明 |
|---|---|---|---|
| [`chat.axons.locale-zh-cn`](language/chat.axons.locale-zh-cn) | 纯静态 | localization | 简体中文语言包，覆盖 Axons 前端/后端/插件标题 |
| [`chat.axons.huggingface`](huggingface/chat.axons.huggingface) | 后端 + 前端 | productivity | 浏览 HuggingFace GGUF 模型；下载、启停、管理本地 LLM（基于 llama.cpp） |

## 🚀 快速上手

### 前置要求
- **Bash** ≥ 4（macOS / Linux）
- **Python 3**（解析 `manifest.json` 及后端校验）
- **Node.js 18+** & **npm**（仅含前端构建的插件需要）

### 构建并打包所有插件
```bash
bash build.sh          # 校验后端 + 构建前端（自动检测）
bash pack.sh           # 输出 dist/*.axons-plugin.tar.gz
```

### 按插件 ID、目录或分类过滤
```bash
bash build.sh chat.axons.huggingface                # 按 ID
bash pack.sh  language/                              # 按分类目录
bash clean.sh huggingface/chat.axons.huggingface  # 按完整路径
```

### 导入到 Axons
```bash
curl -X POST http://127.0.0.1:9090/v1/plugins/import \
  -F 'file=@dist/chat.axons.huggingface-1.0.0.axons-plugin.tar.gz'
```
或使用 Axons UI：**扩展面板 → 从文件导入**。

## 🛠️ 三个脚本

本仓库遵循 Unix 哲学——每个脚本只做 **一件事**：

| 脚本 | 职责 |
|---|---|
| [`build.sh`](build.sh) | 校验后端（Python/pip/sh）+ 构建前端（npm/vite），按插件特征自动判断 |
| [`pack.sh`](pack.sh) | 将每个插件打包到 `dist/<id>-<version>.axons-plugin.tar.gz` |
| [`clean.sh`](clean.sh) | 清理依赖/缓存；可选参数控制清理粒度 |

三个脚本共享相同的过滤语法（插件 ID / 子目录 / 父目录）。
完整选项请看 `bash <脚本名>.sh -h`。

## 📁 仓库结构

```
axons-extension-packages/
├── build.sh                          # 统一构建/校验入口
├── pack.sh                           # 统一打包入口
├── clean.sh                          # 统一清理入口
├── dist/                             # 输出目录（已 gitignore）
├── docs/                             # 文档
│   ├── zh/                            # 中文文档
│   │   ├── DEVELOPMENT.md             # 中文开发手册
│   │   ├── PLUGIN_AUTHORING.md        # 中文插件作者指南
│   │   └── RELEASING.md              # 中文发布流程
├── language/                         # 分类：本地化插件
│   ├── pack.sh                       # 局部薄封装（转发到根脚本）
│   └── chat.axons.locale-zh-cn/
└── huggingface/                     # 分类：HuggingFace 插件
    ├── build.sh / pack.sh / clean.sh # 局部薄封装
    └── chat.axons.huggingface/
```

## 🎯 插件类型自动识别

根脚本通过检测插件目录内的文件来判断需要做什么：

| 插件目录内的特征 | 触发行为 |
|---|---|
| `package.json` 含 `build` script | 前端构建（npm ci → npm run build → 产物验证） |
| `requirements.txt` 或 `*.py` | 后端校验（py_compile + pip dry-run + bash -n） |
| 两者都有 | 两条流水线都跑 |
| 都没有（如语言包） | 纯静态插件——跳过构建 |

## 🔌 插件级钩子（可选）

当默认流程不够时，在 `<插件>/scripts/` 下放脚本即可：

| 钩子 | 调用时机 | 注入环境变量 |
|---|---|---|
| `scripts/build.sh` | build.sh 处理该插件末尾 | `PLUGIN_DIR / PLUGIN_ID / PLUGIN_VERSION` |
| `scripts/pre-pack.sh` | 打包前 | 同上 |
| `scripts/post-pack.sh` | 打包后 | 同上 + `PACKAGE_PATH` |
| `scripts/clean.sh` | clean.sh 处理该插件末尾 | `PLUGIN_DIR / PLUGIN_ID` |

另有：`.axons-build`（覆盖默认前端产物列表）、`.axons-ignore`（追加 tar 排除规则）。

## 🚢 标准发布流程

```bash
bash build.sh                       # 1. 构建 + 校验
bash pack.sh                        # 2. 生成 dist/*.tar.gz
bash clean.sh --keep-artifacts      # 3. 清理依赖缓存，保留 ui/index.js

git add . && git commit -m "..." && git push
```

详见 [`docs/zh/RELEASING.md`](docs/zh/RELEASING.md)。

## ➕ 新增插件

1. 在合适分类下建目录，如 `theme/chat.axons.my-theme/`。
2. 加 `manifest.json`（至少含 `id` 和 `version`）。
3. 放入源码/资产/后端代码等。
4. `bash build.sh chat.axons.my-theme` 和 `bash pack.sh chat.axons.my-theme`——自动发现，无需写脚本。

完整指南见 [`docs/zh/PLUGIN_AUTHORING.md`](docs/zh/PLUGIN_AUTHORING.md)。

## 📚 文档

- **[开发手册](docs/zh/DEVELOPMENT.md)** — 脚本详解、钩子、插件类型、排错
- **[插件作者指南](docs/zh/PLUGIN_AUTHORING.md)** — 从零创建一个新插件
- **[发布指南](docs/zh/RELEASING.md)** — 完整发布工作流
- **[变更日志](CHANGELOG_zh-CN.md)** — 仓库级变更历史
- **[English docs](docs/)** — 英文版文档

## 📄 许可证

[MIT](LICENSE) © 2026 mengshi 及 axons-community。

## 🤝 参与贡献

欢迎提 Issue 和 PR。提交前请确保：

```bash
bash build.sh                   # 校验 + 构建必须通过
bash clean.sh --keep-artifacts  # 清理依赖缓存后再提交
```

前端产物 `ui/index.js` 应随代码一起提交到 git——用户 clone 后不应需要再跑 `npm install`。