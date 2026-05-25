# Axons Extension Packages

> A monorepo of official extensions for [Axons](https://www.axons.chat), distributed as offline-importable `.axons-plugin.tar.gz` packages.

**English | [简体中文](README_zh-CN.md)**

## 📦 Available Plugins

| Plugin | Type | Category | Description |
|---|---|---|---|
| [`chat.axons.locale-zh-cn`](language/chat.axons.locale-zh-cn) | Static | localization | Simplified Chinese language pack for Axons UI/backend/plugin titles |
| [`chat.axons.huggingface`](huggingface/chat.axons.huggingface) | Backend + Frontend | productivity | Browse HuggingFace GGUF models; download, start/stop, and manage local LLMs via llama.cpp |

## 🚀 Quick Start

### Prerequisites
- **Bash** 4+ (macOS / Linux)
- **Python 3** (for `manifest.json` parsing and backend validation)
- **Node.js 18+** & **npm** (only for plugins with frontend builds)

### Build & Pack All Plugins
```bash
bash build.sh          # validate backend + build frontend (auto-detected)
bash pack.sh           # produce dist/*.axons-plugin.tar.gz
```

### Filter by Plugin ID, Directory, or Category
```bash
bash build.sh chat.axons.huggingface       # by plugin id
bash pack.sh  language/                     # by category folder
bash clean.sh huggingface/chat.axons.huggingface   # by full path
```

### Import into Axons
```bash
curl -X POST http://127.0.0.1:9090/v1/plugins/import \
  -F 'file=@dist/chat.axons.huggingface-1.0.0.axons-plugin.tar.gz'
```
Or use the Axons UI: **Extensions panel → Import from File**.

## 🛠️ The Three Scripts

This repo follows the Unix philosophy — each script does **one thing**:

| Script | Responsibility |
|---|---|
| [`build.sh`](build.sh) | Validate backend (Python/pip/shell) + build frontend (npm/vite). Auto-detects per-plugin needs. |
| [`pack.sh`](pack.sh) | Package each plugin into `dist/<id>-<version>.axons-plugin.tar.gz`. |
| [`clean.sh`](clean.sh) | Remove dependencies/caches; optional flags control granularity. |

All three accept the same target filters (plugin ID / sub-directory / parent directory).
See `bash <script>.sh -h` for full options.

## 📁 Repository Layout

```
axons-extension-packages/
├── build.sh                          # unified build/validate entry
├── pack.sh                           # unified packaging entry
├── clean.sh                          # unified cleanup entry
├── dist/                             # output: *.axons-plugin.tar.gz (gitignored)
├── docs/                             # documentation
│   ├── DEVELOPMENT.md                # developer manual
│   ├── PLUGIN_AUTHORING.md           # how to author a new plugin
│   └── RELEASING.md                  # release workflow
├── language/                         # category: localization plugins
│   ├── pack.sh                       # local wrapper (forwards to root)
│   └── chat.axons.locale-zh-cn/       # the plugin itself
└── huggingface/                     # category: HuggingFace plugins
    ├── build.sh / pack.sh / clean.sh # local wrappers
    └── chat.axons.huggingface/      # the plugin itself
```

## 🎯 Plugin Type Auto-Detection

The root scripts detect what each plugin needs by inspecting its files:

| Feature in plugin dir | Triggers |
|---|---|
| `package.json` with a `build` script | Frontend build (npm ci → npm run build → artifact validation) |
| `requirements.txt` or any `*.py` | Backend validation (py_compile + pip dry-run + bash -n) |
| Both of the above | Both pipelines run |
| Neither (e.g., language packs) | Static plugin — skipped during `build.sh` |

## 🔌 Per-Plugin Hooks (Optional)

For plugin-specific build steps that the defaults don't cover, drop a script under `<plugin>/scripts/`:

| Hook | When | Env vars provided |
|---|---|---|
| `scripts/build.sh` | End of `build.sh` per plugin | `PLUGIN_DIR / PLUGIN_ID / PLUGIN_VERSION` |
| `scripts/pre-pack.sh` | Before `tar` runs | same |
| `scripts/post-pack.sh` | After `tar` finishes | same + `PACKAGE_PATH` |
| `scripts/clean.sh` | End of `clean.sh` per plugin | `PLUGIN_DIR / PLUGIN_ID` |

Also supported per-plugin: `.axons-build` (override expected frontend artifacts) and `.axons-ignore` (extra tar exclude rules).

## 🚢 Standard Release Workflow

```bash
bash build.sh                       # 1. build + validate
bash pack.sh                        # 2. produce dist/*.tar.gz
bash clean.sh --keep-artifacts      # 3. clean dev caches but keep ui/index.js

git add . && git commit -m "..." && git push
```

See [`docs/RELEASING.md`](docs/RELEASING.md) for full details.

## ➕ Adding a New Plugin

1. Create a directory under an appropriate category (or a new one), e.g. `theme/chat.axons.my-theme/`.
2. Add a `manifest.json` with at least `id` and `version`.
3. Add your assets, source, backend code, etc.
4. Run `bash build.sh chat.axons.my-theme` and `bash pack.sh chat.axons.my-theme` — they will pick it up automatically.

Full guide: [`docs/PLUGIN_AUTHORING.md`](docs/PLUGIN_AUTHORING.md).

## 📚 Documentation

- **[Development Manual](docs/DEVELOPMENT.md)** — scripts, hooks, plugin types, troubleshooting
- **[Plugin Authoring Guide](docs/PLUGIN_AUTHORING.md)** — create a new plugin from scratch
- **[Release Guide](docs/RELEASING.md)** — end-to-end publishing workflow
- **[Changelog](CHANGELOG.md)** — repository-level change history

## 📄 License

[MIT](LICENSE) © 2026 mengshi and the axons-community.

## 🤝 Contributing

Issues and PRs are welcome. Before submitting:

```bash
bash build.sh                   # must pass (backend validation + frontend build)
bash clean.sh --keep-artifacts  # remove node_modules/.venv/__pycache__/ before commit
```

Keep `ui/index.js` (the pre-built frontend artifact) checked into git — end users should not need to run `npm install` after cloning a plugin.