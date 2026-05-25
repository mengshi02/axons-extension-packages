# 开发手册

本手册涵盖在本 monorepo 中开发、校验和维护插件所需的一切知识。

**[English](../DEVELOPMENT.md) | 简体中文**

## 目录
- [环境准备](#环境准备)
- [仓库结构](#仓库结构)
- [三个脚本](#三个脚本)
- [插件类型自动识别](#插件类型自动识别)
- [插件级钩子](#插件级钩子)
- [插件级配置文件](#插件级配置文件)
- [校验流水线](#校验流水线)
- [常见工作流](#常见工作流)
- [常见问题排查](#常见问题排查)

---

## 环境准备

### 必需
- **Bash** >= 4（macOS / Linux）。macOS 默认 `/bin/bash` 是 3.2，可通过 Homebrew 安装新版本，或直接在 `zsh` 里调用 `bash`。
- **Python 3** — 用于解析 `manifest.json` 和后端校验。

### 可选（按插件需要）
- **Node.js 18+** 和 **npm** — 仅含前端构建的插件需要。
- **llama.cpp** — 仅端到端运行 `chat.axons.huggingface` 时需要。

### 验证
```bash
bash --version
python3 --version
node --version           # 可选
```

---

## 仓库结构

```
axons-extension-packages/
├── build.sh             # ←— 统一入口：构建/校验
├── pack.sh              # ←— 统一入口：打包
├── clean.sh             # ←— 统一入口：清理
├── dist/                # 生成的 tarball（已 gitignore）
├── docs/
├── language/            # 分类目录（任意命名）
│   ├── pack.sh          # 薄封装 → 根 pack.sh，作用域为 language/
│   └── chat.axons.locale-zh-cn/
│       └── manifest.json
└── huggingface/
    ├── build.sh         # 薄封装，作用域为 huggingface/
    ├── pack.sh
    ├── clean.sh
    └── chat.axons.huggingface/
        ├── manifest.json
        ├── server.py            # 后端
        ├── requirements.txt
        ├── install.sh
        ├── package.json         # 前端
        ├── src/                 # 前端源码（不打入 tarball）
        ├── ui/index.js          # 预构建前端产物（随 git 提交）
        └── ...
```

### 分类的含义

一级子目录（`language/`、`huggingface/`）只是组织用途。脚本不关心插件放在哪里——它们遍历整个仓库查找 `manifest.json`。按主题分组即可；随时可以新建分类。

---

## 三个脚本

所有脚本自包含、支持 `-h` / `--help`、共享相同的目标过滤语义。

### `build.sh` — 校验与构建

```
bash build.sh [目标...]
```

对每个发现（或过滤到）的插件：
1. **后端校验**（若存在 `*.py` / `requirements.txt` / `*.sh`）
2. **前端构建**（若 `package.json` 声明了 `build` script）
3. **钩子执行**（若存在 `<插件>/scripts/build.sh`）

### `pack.sh` — 打包

```
bash pack.sh [目标...]
```

对每个插件：
1. 可选的 `<插件>/scripts/pre-pack.sh` 先执行。
2. 文件打包到 `dist/<id>-<version>.axons-plugin.tar.gz`，使用默认排除规则 + `.axons-ignore` 追加规则。
3. 可选的 `<插件>/scripts/post-pack.sh` 执行，环境变量含 `PACKAGE_PATH`。
4. 打印大小 + SHA-256。

`pack.sh` 是**纯粹的打包器**——不会自动跑 `build` 或 `clean`，请自行组合（见[常见工作流](#常见工作流)）。

### `clean.sh` — 清理

```
bash clean.sh [选项] [目标...]
```

| 默认删除 | 说明 |
|---|---|
| `node_modules/` | 前端依赖 |
| `.vite/` | 前端缓存 |
| `dist/`（插件目录内） | 插件自己的 dist，不是仓库根的 `dist/` |
| `.venv/` | Python 虚拟环境 |
| `__pycache__/`（递归） | Python 字节码缓存 |
| `*.pyc`（递归） | 编译后的字节码文件 |
| `ui/index.js`（前端产物） | 除非加 `--keep-artifacts` |

| 选项 | 效果 |
|---|---|
| `--keep-artifacts` | 保留 `ui/index.js`（`git commit` 前使用） |
| `--all` | 额外删除仓库根 `dist/` 和残留的 `*.axons-plugin.tar.gz` |

---

## 插件类型自动识别

**没有插件类型配置**——脚本查看插件目录内的文件来决定做什么：

| 插件目录内检测到的 | `build.sh` 行为 |
|---|---|
| `package.json` 含 `build` script | 执行前端构建 |
| `requirements.txt` 或 `*.py`（前 2 层，排除 `.venv` / `node_modules`） | 执行后端校验 |
| `*.sh` 在插件根目录 | 校验 shell 语法（`bash -n`） |
| `scripts/build.sh` | 作为插件钩子执行 |
| 以上都没有 | 视为"纯静态"——跳过 |

语言包不需要特殊处理的原因：它们只有 `manifest.json` + 资产文件，`build.sh` 直接输出"纯静态插件，无需构建/校验"。

---

## 插件级钩子

当标准流程不够时，在 `<插件>/scripts/` 下放脚本即可。根脚本在明确的时间点调用它们，并通过环境变量传入上下文。

| 钩子 | 触发脚本 | 执行时机 | 环境变量 |
|---|---|---|---|
| `scripts/build.sh` | `build.sh` | 默认校验 + 前端构建之后 | `PLUGIN_DIR`、`PLUGIN_ID`、`PLUGIN_VERSION` |
| `scripts/pre-pack.sh` | `pack.sh` | 读取 manifest 后、`tar` 之前 | 同上 |
| `scripts/post-pack.sh` | `pack.sh` | `tar` 生成归档之后 | 同上 **+ `PACKAGE_PATH`** |
| `scripts/clean.sh` | `clean.sh` | 默认清理之后 | `PLUGIN_DIR`、`PLUGIN_ID` |

### 示例：打包前从模板生成 manifest

```bash
# theme/chat.axons.my-theme/scripts/pre-pack.sh
#!/bin/bash
set -e
cd "$PLUGIN_DIR"
envsubst < manifest.template.json > manifest.json
echo "已为 $PLUGIN_ID v$PLUGIN_VERSION 生成 manifest.json"
```

### 示例：打包后自动上传

```bash
# scripts/post-pack.sh
#!/bin/bash
set -e
echo "发布 $PLUGIN_ID v$PLUGIN_VERSION ..."
curl -X POST https://my-registry.example/upload \
     -F "package=@$PACKAGE_PATH" \
     -F "id=$PLUGIN_ID" \
     -F "version=$PLUGIN_VERSION"
```

`scripts/` 默认被排除在 tarball 之外——钩子仅在开发时存在。

---

## 插件级配置文件

### `.axons-build`（可选）

覆盖默认的前端产物列表。每行一个路径，相对于插件目录。

```
# 示例：我的插件有多个产物
ui/index.js
ui/worker.js
ui/styles.css
```

若不存在，`build.sh` 检查 `ui/index.js`。

### `.axons-ignore`（可选）

追加 `tar --exclude` 模式，在默认排除之后生效。类似 `.gitignore` 格式；每行作为 `--exclude=<模式>` 传入。

```
*.bak
__tests__
fixtures/large-data
```

---

## 校验流水线

### 后端（`build.sh`）

```
*.py 文件       →  python3 -m py_compile
requirements.txt →  pip install --dry-run     （PEP 668 下回退到 --break-system-packages）
                                              （最终回退：packaging.requirements 格式校验）
*.sh 文件       →  bash -n
```

pip 降级链存在的原因：macOS Homebrew Python 和最新 Debian 发行版执行 PEP 668，即使 dry-run 模式也会阻止 `pip install`，除非加 `--break-system-packages`。

### 前端（`build.sh`）

```
package.json 必须声明 "build" script
  → npm ci   （若存在 package-lock.json）
  → npm install   （否则）
  → npm run build
  → 验证 .axons-build 列出的产物（或默认 ui/index.js）
```

前端依赖安装使用 `--no-audit --no-fund` 保持输出简洁。

---

## 常见工作流

### 日常迭代单个插件
```bash
bash build.sh chat.axons.huggingface      # 重新构建 + 校验
```

### 发布插件（生成 tarball；完整流程见 RELEASING.md）
```bash
bash build.sh chat.axons.huggingface
bash pack.sh  chat.axons.huggingface
```

### 提交前清理
```bash
bash clean.sh --keep-artifacts             # 删除开发缓存，保留 ui/index.js
```

### 彻底清理（缓存 + 产物 + tarball）
```bash
bash clean.sh --all
```

### CI 中测试所有插件
```bash
bash build.sh && bash pack.sh              # 两者均需退出码 0
```

---

## 常见问题排查

### "Plugin not matched" / 插件未匹配
- 检查传入的过滤器。目标可以是：
  - 插件的 `id`（来自 `manifest.json`，如 `chat.axons.huggingface`）
  - 插件目录相对仓库根的路径（如 `huggingface/chat.axons.huggingface`）
  - 父目录（如 `language/` 匹配所有语言插件）

### 后端校验本地通过但 CI 失败
很可能是 Python 版本差异。`py_compile` 比较宽松——不检查 import 或类型。如果 CI 报 `ModuleNotFoundError`，说明运行时环境缺少 `requirements.txt` 中的依赖。

### `pip install --dry-run` 一直报 "externally-managed-environment"
脚本已处理此情况。若仍失败，安装 `python3-packaging`（或 `pip install packaging --break-system-packages`）使格式校验降级方案能运行。

### `npm ci` 报 "Missing package-lock.json"
先跑一次 `npm install` 生成它，提交 lockfile 后 `npm ci` 即可正常工作。

### 前端构建成功但 `ui/index.js` 缺失
检查 `vite.config.js`（或等效配置）——`outDir` 应为 `ui`，bundle 文件名应解析为 `index.js`。如使用自定义布局，在 `.axons-build` 中声明。

### 打出的 tarball 体积异常大
运行 `tar tzf dist/<你的插件>.axons-plugin.tar.gz` 查看是否误包含了 `node_modules/`、`__pycache__/` 或 `.venv/`。需在 `.axons-ignore` 中追加排除模式；若属通用问题则提 defect 修复默认排除规则。

### 插件导入 Axons 后面板不显示
对照 Axons 插件协议检查 `manifest.json`——确认 `frontend.entry`、面板定义、激活事件。导入后重启 Axons 或使用**重新加载插件**菜单。