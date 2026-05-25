# 变更日志

本仓库工具链与插件集的所有重要变更均记录于此。
格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
项目遵循[语义化版本](https://semver.org/lang/zh-CN/)。

> 各插件版本在各自的 `manifest.json` 中维护。
> 本文件追踪仓库级变更（工具链、结构、约定）。

**[English](CHANGELOG.md) | 简体中文**

## [未发布]

### 新增
- 根目录统一脚本 `build.sh` / `pack.sh` / `clean.sh`，自动通过 `manifest.json` 发现所有插件。
- 插件级钩子协议：`<插件>/scripts/` 下支持 `build.sh`、`pre-pack.sh`、`post-pack.sh`、`clean.sh`。
- 插件级配置文件：`.axons-build`（产物列表）和 `.axons-ignore`（tar 排除规则）。
- 三个脚本均支持按插件 ID、子目录、父目录过滤。
- `build.sh` 后端校验：Python `py_compile`、`pip install --dry-run`（含 PEP 668 兼容降级）、`bash -n` 语法检查。
- `build.sh` 前端构建：`npm ci` / `npm install` → `npm run build` → 产物验证。
- 每个脚本均支持 `-h` / `--help`。
- `clean.sh` 额外清理 `.venv/`、`__pycache__/`、`*.pyc`。
- 仓库根 `dist/` 目录作为 `.axons-plugin.tar.gz` 的统一输出位置。
- `docs/` 下新增文档套件（开发手册、插件作者指南、发布指南），中英双语。

### 变更
- 打包产物输出到 `<repo_root>/dist/`，不再放在各插件目录内。
- `language/pack.sh` 和 `huggingface/{build,pack,clean}.sh` 改为薄封装，转发到根脚本并以子目录名限定作用域。
- `pack.sh` 默认排除增加 `src/`、`scripts/`、`package*.json`、`tsconfig.json`、`vite.config.*`，前端源码不再打入运行时 tarball。

### 修复
- `pip install --dry-run` 在 PEP 668 环境（macOS Homebrew Python、Debian）下的兼容降级处理。

## [0.1.0] – 2026-05-15

初始仓库搭建，包含两个插件：

### 新增
- `chat.axons.locale-zh-cn` v1.0.0 — 简体中文语言包。
- `chat.axons.huggingface` v1.0.0 — 通过 Ollama 和 HuggingFace Hub 浏览/管理本地 LLM。
- 按分类的打包脚本（`language/pack.sh`、`huggingface/pack.sh`）。
- MIT 许可证。

---

## 插件版本历史

单个插件的变更请查看其 `manifest.json` 的 `version` 字段及目录内的 `CHANGELOG.md`。

| 插件 | 当前版本 |
|---|---|
| `chat.axons.locale-zh-cn` | 1.0.0 |
| `chat.axons.huggingface` | 1.0.0 |

[未发布]: ../../compare/v0.1.0...HEAD
[0.1.0]: ../../releases/tag/v0.1.0