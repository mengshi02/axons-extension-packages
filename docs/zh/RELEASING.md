# 发布指南

端到端的发布工作流：校验 → 打包 → 发布 → 打标签。

**[English](../RELEASING.md) | 简体中文**

## 目录
- [发布节奏](#发布节奏)
- [版本号策略](#版本号策略)
- [分步工作流](#分步工作流)
- [提交前清理（重要）](#提交前清理重要)
- [标签命名约定](#标签命名约定)
- [发布 tarball](#发布-tarball)
- [热修复流程](#热修复流程)
- [常见错误](#常见错误)

---

## 发布节奏

本仓库不强制固定发布计划。各插件可独立发布：

- **修订版**（缺陷修复）：随时。
- **次版本**（新功能）：功能完成并通过校验后。
- **主版本**（破坏性变更）：与下游 Axons 用户协调，在插件 changelog 中记录迁移说明。

仓库级变更（脚本变更、约定、新增分类）记录在 [`CHANGELOG.md`](../../CHANGELOG.md) 的 `[未发布]` 下，维护者切快照时合入标签。

---

## 版本号策略

| 组件 | 存放位置 | 版本规则 |
|---|---|---|
| 各插件 | `<插件>/manifest.json` → `version` 字段 | 语义化版本 |
| 仓库工具链 | Git 标签（`v0.x.y`）和 `CHANGELOG.md` | 工具链的语义化版本 |

两个版本命名空间独立。插件的 `1.2.3` 不随仓库工具链从 `v0.1.0` 升到 `v0.2.0` 而变动。

---

## 分步工作流

### 1. 递增插件版本号

编辑 `<插件>/manifest.json`：
```diff
- "version": "1.0.0",
+ "version": "1.1.0",
```

### 2. 构建与校验

```bash
bash build.sh <插件-id>
```

必须退出码 0。前端插件：验证 `ui/index.js` 已生成。后端插件：验证 Python 语法 + 依赖声明 + shell 脚本。

### 3. 打包

```bash
bash pack.sh <插件-id>
```

生成 `dist/<id>-<version>.axons-plugin.tar.gz`。注意 SHA-256 行——发布说明中需要。

### 4. 冒烟测试 tarball

检查内容：
```bash
tar tzf dist/<id>-<version>.axons-plugin.tar.gz | sort
```

然后导入运行中的 Axons 实例：
```bash
curl -X POST http://127.0.0.1:9090/v1/plugins/import \
     -F 'file=@dist/<id>-<version>.axons-plugin.tar.gz'
```

打开 Axons 并走一遍插件主要路径。如有问题，修复后从步骤 2 重新来。

### 5. 更新变更日志

在 [`CHANGELOG.md`](../../CHANGELOG.md) 的 `[未发布]` 下添加条目。切工具链标签时移入版本标题下。

### 6. 提交前清理

```bash
bash clean.sh --keep-artifacts <插件-id>
```

删除 `node_modules/`、`.venv/`、`__pycache__/`、`*.pyc`、`.vite/`，但**保留 `ui/index.js`**（预构建产物必须留在 git 中）。

### 7. 提交

```bash
git add <插件目录> CHANGELOG.md
git commit -m "release(<插件-id>): v<版本号>"
```

### 8. 打标签

```bash
git tag <插件-id>/v<版本号>
# 例如
git tag chat.axons.huggingface/v1.1.0
```

### 9. 推送

```bash
git push origin main --tags
```

### 10. 发布产物

将 `dist/` 中的 tarball 附加到发布页面（GitHub Releases、内部 registry 等）。详见[发布 tarball](#发布-tarball)。

---

## 提交前清理（重要）

最常见的错误就是把 `node_modules/` 或 `.venv/` 一起提交了。工作流最后一步始终是：

```bash
bash clean.sh --keep-artifacts
```

保留什么：
- 源码
- `ui/index.js`（预构建产物——必须在 git 中）
- `manifest.json` 及其他静态资产

删除什么：
- `node_modules/`
- `.venv/`
- `__pycache__/` 和 `*.pyc`
- `.vite/` 缓存

已被 gitignore 的（所以怎么都安全）：
- `dist/`（生成的 tarball）
- `*.axons-plugin.tar.gz`

---

## 标签命名约定

两种标签风格：

| 标签模式 | 含义 |
|---|---|
| `<插件-id>/v<版本号>` | 单个插件发布（如 `chat.axons.huggingface/v1.1.0`） |
| `tooling/v<版本号>` | 工具链发布（build.sh / pack.sh / clean.sh 约定变更） |

GitHub 将标签名中的 `/` 视为嵌套引用——浏览时正常展示，且避免插件标签和工具链标签冲突。

---

## 发布 tarball

选择适合你受众的分发渠道：

### GitHub Releases（开源项目推荐）
1. 从标签创建新 release。
2. 将 `dist/` 中的 tarball 拖入附件。
3. 将 `pack.sh` 输出的 SHA-256 粘贴到 release notes。
4. 引用 changelog 条目。

### 内部 HTTPS registry
使用 `scripts/post-pack.sh` 钩子实现打包后自动上传：

```bash
#!/bin/bash
set -e
curl --fail \
     -X POST https://registry.internal/plugins \
     -F "package=@$PACKAGE_PATH" \
     -F "id=$PLUGIN_ID" \
     -F "version=$PLUGIN_VERSION" \
     -H "Authorization: Bearer $REGISTRY_TOKEN"
```

### 通过 curl 直接安装
最终用户随时可以：
```bash
curl -X POST http://127.0.0.1:9090/v1/plugins/import \
     -F 'file=@<下载的-tarball>'
```

---

## 热修复流程

对已发布版本的紧急缺陷修复：

1. 从已有标签建分支：
   ```bash
   git checkout -b hotfix/<插件-id>-<新版本号> <插件-id>/v<旧版本号>
   ```
2. 修复问题。
3. 递增 `manifest.json` 修订号（如 `1.1.0` → `1.1.1`）。
4. 跑常规发布流程（步骤 2–10）。
5. 将热修复分支合并回 `main`，确保后续发布包含此修复。

---

## 常见错误

| 错误 | 症状 | 修复 |
|---|---|---|
| 忘记递增 `manifest.json` 中的 `version` | 新 tarball 以相同文件名覆盖旧版 | 打标签前 `git diff <插件>/manifest.json` |
| 误提交 `node_modules/` | PR 体积巨大（几百 MB） | 跑 `bash clean.sh --keep-artifacts`，修正提交 |
| git 中缺少 `ui/index.js` | 插件安装后前端面板空白 | 重跑 `bash build.sh <id>`，提交 `ui/index.js` |
| `pack.sh` 产出的 tarball 特别小（几 KB） | 前端从未构建，没有 `ui/index.js` 可打包 | 先跑 `bash build.sh <id>` 再 `bash pack.sh` |
| 标签已打但还没推送产物 | Release 页面缺文件 | 事后编辑 release，从 `dist/` 上传 |
| 忘记更新 `CHANGELOG.md` | Release notes 为空 | 打标签前更新 `CHANGELOG.md` 并修正提交 |