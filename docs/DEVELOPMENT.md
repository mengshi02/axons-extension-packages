# Development Manual

This manual covers everything you need to know to develop, validate, and maintain plugins in this monorepo.

## Table of Contents
- [Environment Setup](#environment-setup)
- [Repository Layout](#repository-layout)
- [The Three Scripts](#the-three-scripts)
- [Plugin Type Auto-Detection](#plugin-type-auto-detection)
- [Per-Plugin Hooks](#per-plugin-hooks)
- [Per-Plugin Configuration Files](#per-plugin-configuration-files)
- [Validation Pipeline](#validation-pipeline)
- [Common Workflows](#common-workflows)
- [Troubleshooting](#troubleshooting)

---

## Environment Setup

### Required
- **Bash** ≥ 4 (macOS / Linux). On macOS, the default `/bin/bash` is 3.2 — install a newer bash via Homebrew or just use `bash` from `zsh`.
- **Python 3** — used by every script for parsing `manifest.json` and validating backend code.

### Optional (per plugin needs)
- **Node.js 18+** and **npm** — required only for plugins that have a `package.json` with a `build` script.
- **llama.cpp** — only when running `chat.axons.huggingface` end-to-end.

### Verification
```bash
bash --version
python3 --version
node --version           # optional
```

---

## Repository Layout

```
axons-extension-packages/
├── build.sh             # ←— UNIFIED entry: build/validate
├── pack.sh              # ←— UNIFIED entry: produce tarballs
├── clean.sh             # ←— UNIFIED entry: clean caches/products
├── dist/                # generated tarballs (gitignored)
├── docs/
├── language/            # category directory (anything you like)
│   ├── pack.sh          # thin wrapper → root pack.sh, scoped to language/
│   └── chat.axons.locale-zh-cn/
│       └── manifest.json
└── huggingface/
    ├── build.sh         # thin wrappers, scoped to huggingface/
    ├── pack.sh
    ├── clean.sh
    └── chat.axons.huggingface/
        ├── manifest.json
        ├── server.py            # backend
        ├── requirements.txt
        ├── install.sh
        ├── package.json         # frontend
        ├── src/                 # frontend source (excluded from tarball)
        ├── ui/index.js          # pre-built frontend artifact (kept in git)
        └── ...
```

### What categorisation means

The first-level subdirectories (`language/`, `huggingface/`) are simply organisational. The scripts don't care where a plugin lives — they walk the entire repo looking for `manifest.json`. Group plugins by theme; create new categories whenever it makes sense.

---

## The Three Scripts

All scripts are self-contained, support `-h` / `--help`, and share the same target-filter semantics.

### `build.sh` — Validate & Build

```
bash build.sh [TARGETS...]
```

For each plugin discovered (or filtered):
1. **Backend validation** (if any `*.py` / `requirements.txt` / `*.sh` exists)
2. **Frontend build** (if `package.json` declares a `build` script)
3. **Hook execution** (if `<plugin>/scripts/build.sh` exists)

### `pack.sh` — Package

```
bash pack.sh [TARGETS...]
```

For each plugin:
1. Optional `<plugin>/scripts/pre-pack.sh` runs first.
2. Files are tarred to `dist/<id>-<version>.axons-plugin.tar.gz` with standard excludes plus any from `.axons-ignore`.
3. Optional `<plugin>/scripts/post-pack.sh` runs with `PACKAGE_PATH` in env.
4. Size + SHA-256 printed.

`pack.sh` is **purely a packager** — it does not run `build` or `clean`. Compose them yourself (see [Common Workflows](#common-workflows)).

### `clean.sh` — Clean

```
bash clean.sh [OPTIONS] [TARGETS...]
```

| Removes by default | Notes |
|---|---|
| `node_modules/` | Frontend deps |
| `.vite/` | Frontend cache |
| `dist/` (inside plugin) | Plugin's own dist dir, not the repo's `dist/` |
| `.venv/` | Python venv |
| `__pycache__/` (recursive) | Python bytecode cache |
| `*.pyc` (recursive) | Compiled bytecode files |
| `ui/index.js` (frontend artifact) | Unless `--keep-artifacts` |

| Flag | Effect |
|---|---|
| `--keep-artifacts` | Keep `ui/index.js` (use this before `git commit`) |
| `--all` | Additionally delete `dist/` and any stray `*.axons-plugin.tar.gz` |

---

## Plugin Type Auto-Detection

There is **no plugin-type config** — the scripts look at the files inside each plugin and decide what to do:

| Detected in plugin dir | `build.sh` behavior |
|---|---|
| `package.json` with `build` script | Run frontend build |
| `requirements.txt` or any `*.py` (top 2 levels, excluding `.venv` / `node_modules`) | Run backend validation |
| `*.sh` at plugin root | Validate shell syntax via `bash -n` |
| `scripts/build.sh` | Execute as a per-plugin hook |
| None of the above | Treated as "pure static" — skipped |

This is why language packs need no special handling: they have only `manifest.json` + asset files, so `build.sh` just prints "pure static plugin, nothing to build".

---

## Per-Plugin Hooks

When the standard pipeline isn't enough, drop a script in `<plugin>/scripts/`. The root scripts call them at well-defined points and pass context via environment variables.

| Hook | Triggered by | Runs after | Env vars |
|---|---|---|---|
| `scripts/build.sh` | `build.sh` | default validation + frontend build for that plugin | `PLUGIN_DIR`, `PLUGIN_ID`, `PLUGIN_VERSION` |
| `scripts/pre-pack.sh` | `pack.sh` | reading manifest, before `tar` | same |
| `scripts/post-pack.sh` | `pack.sh` | `tar` has produced the archive | same **plus `PACKAGE_PATH`** |
| `scripts/clean.sh` | `clean.sh` | default removals for that plugin | `PLUGIN_DIR`, `PLUGIN_ID` |

### Example: Generating a manifest from a template before packing

```bash
# theme/chat.axons.my-theme/scripts/pre-pack.sh
#!/bin/bash
set -e
cd "$PLUGIN_DIR"
envsubst < manifest.template.json > manifest.json
echo "Generated manifest.json for $PLUGIN_ID v$PLUGIN_VERSION"
```

### Example: Uploading the tarball after a successful pack

```bash
# scripts/post-pack.sh
#!/bin/bash
set -e
echo "Publishing $PLUGIN_ID v$PLUGIN_VERSION..."
curl -X POST https://my-registry.example/upload \
     -F "package=@$PACKAGE_PATH" \
     -F "id=$PLUGIN_ID" \
     -F "version=$PLUGIN_VERSION"
```

`scripts/` is excluded from the tarball by default — hooks only exist at development time.

---

## Per-Plugin Configuration Files

### `.axons-build` (optional)

Override the default expected frontend artifact list. One path per line, relative to the plugin directory.

```
# example: my plugin has multiple bundles
ui/index.js
ui/worker.js
ui/styles.css
```

If absent, `build.sh` checks for `ui/index.js`.

### `.axons-ignore` (optional)

Additional `tar --exclude` patterns appended after the built-in excludes. Same format as `.gitignore`-ish patterns; each line passed as `--exclude=<pattern>`.

```
*.bak
__tests__
fixtures/large-data
```

---

## Validation Pipeline

### Backend (`build.sh`)

```
*.py files       →  python3 -m py_compile
requirements.txt →  pip install --dry-run     (falls back to --break-system-packages on PEP 668)
                                              (final fallback: packaging.requirements format check)
*.sh files       →  bash -n
```

The pip fallback chain exists because macOS Homebrew Python and recent Debian distros enforce PEP 668, which blocks `pip install` even in dry-run mode without `--break-system-packages`.

### Frontend (`build.sh`)

```
package.json must declare a "build" script
  → npm ci   (if package-lock.json exists)
  → npm install   (otherwise)
  → npm run build
  → verify artifacts listed in .axons-build (or default ui/index.js)
```

Frontend dependencies are installed with `--no-audit --no-fund` to keep output tidy.

---

## Common Workflows

### Daily development on one plugin
```bash
bash build.sh chat.axons.huggingface      # rebuild + validate
```

### Release a plugin (creates a tarball; see RELEASING.md for full process)
```bash
bash build.sh chat.axons.huggingface
bash pack.sh  chat.axons.huggingface
```

### Pre-commit cleanup
```bash
bash clean.sh --keep-artifacts             # remove dev caches, keep ui/index.js
```

### Wipe everything (caches + artifacts + tarballs)
```bash
bash clean.sh --all
```

### Test all plugins in CI
```bash
bash build.sh && bash pack.sh              # both must exit 0
```

---

## Troubleshooting

### "Plugin not matched"
- Check the filter you passed. Targets can be:
  - The plugin's `id` from `manifest.json` (e.g. `chat.axons.huggingface`)
  - The plugin's directory relative to the repo root (e.g. `huggingface/chat.axons.huggingface`)
  - A parent directory (e.g. `language/` matches all language plugins)

### Backend validation passes locally but fails in CI
Most likely a Python version difference. `py_compile` is permissive — it doesn't check imports or types. If your CI fails with `ModuleNotFoundError`, your runtime environment is missing a dependency listed in `requirements.txt`.

### `pip install --dry-run` keeps printing "externally-managed-environment"
The script already handles this. If it still fails, install `python3-packaging` (or `pip install packaging --break-system-packages`) so the format-check fallback can run.

### `npm ci` fails with "Missing package-lock.json"
Run `npm install` once to generate it, commit the lockfile, then `npm ci` will work.

### Frontend build succeeds but `ui/index.js` is missing
Check your `vite.config.js` (or equivalent) — `outDir` should be `ui` and the bundle filename should resolve to `index.js`. If you use a custom layout, declare it in `.axons-build`.

### Packaged tarball is suspiciously large
Run `tar tzf dist/<your-plugin>.tar.gz` and look for accidentally-included `node_modules/`, `__pycache__/`, or `.venv/`. Add patterns to `.axons-ignore` if needed; report a defect on the default excludes if it should be universal.

### Plugin imports into Axons but the panel doesn't appear
Cross-check `manifest.json` against the Axons plugin protocol — verify `frontend.entry`, panel definitions, and activation events. Restart Axons after import or use the **Reload Plugins** menu.