# Plugin Authoring Guide

Build a new Axons plugin from scratch in three steps: scaffold → develop → package.

## Table of Contents
- [The Bare Minimum](#the-bare-minimum)
- [Choose a Plugin Archetype](#choose-a-plugin-archetype)
- [Archetype 1: Static Plugin](#archetype-1-static-plugin)
- [Archetype 2: Frontend-Only Plugin](#archetype-2-frontend-only-plugin)
- [Archetype 3: Backend-Only Plugin](#archetype-3-backend-only-plugin)
- [Archetype 4: Full-Stack Plugin](#archetype-4-full-stack-plugin)
- [Manifest Reference](#manifest-reference)
- [Naming & Versioning](#naming--versioning)
- [Testing Your Plugin](#testing-your-plugin)
- [Publishing Checklist](#publishing-checklist)

---

## The Bare Minimum

A valid plugin is **any directory containing a `manifest.json`** with at least `id` and `version`:

```json
{
  "id": "com.example.hello",
  "name": "Hello",
  "version": "0.1.0"
}
```

That's it. Run `bash build.sh com.example.hello` to confirm the scripts discover it. The directory will be picked up regardless of where it lives in the repository — the scripts walk the entire tree.

---

## Choose a Plugin Archetype

| Archetype | Has frontend? | Has backend? | Examples |
|---|---|---|---|
| **Static** | ❌ | ❌ | Language packs, icon themes, snippet libraries |
| **Frontend-only** | ✅ | ❌ | UI panels that talk to existing APIs |
| **Backend-only** | ❌ | ✅ | Headless services, daemons exposing HTTP |
| **Full-stack** | ✅ | ✅ | Most non-trivial plugins (e.g. huggingface) |

Pick the simplest archetype that fits — you can always grow into a more complex one later.

---

## Archetype 1: Static Plugin

**Example:** `chat.axons.locale-zh-cn`

### Layout
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

### Validate & Package
```bash
bash build.sh com.example.my-locale          # prints "pure static, nothing to build"
bash pack.sh  com.example.my-locale          # produces dist/<id>-<version>.axons-plugin.tar.gz
```

No `node_modules`, no Python, no build step — pack just snapshots the files.

---

## Archetype 2: Frontend-Only Plugin

### Layout
```
ui/com.example.my-panel/
├── manifest.json
├── package.json            # declares "build": "vite build"
├── tsconfig.json
├── vite.config.js
├── src/                    # source (excluded from tarball)
│   └── index.tsx
└── ui/                     # output
    ├── icon.svg
    └── index.js            # pre-built artifact (committed)
```

### `manifest.json` (key fields)
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

### `package.json` (the bare minimum)
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
    emptyOutDir: false,        // preserve ui/icon.svg
  },
});
```

### Validate & Package
```bash
bash build.sh com.example.my-panel    # runs npm ci → vite build → verifies ui/index.js
bash pack.sh  com.example.my-panel
```

---

## Archetype 3: Backend-Only Plugin

### Layout
```
services/com.example.my-service/
├── manifest.json
├── server.py
├── requirements.txt
├── install.sh
└── uninstall.sh
```

### `manifest.json` (key fields)
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

### `install.sh` (typical pattern)
```bash
#!/bin/bash
set -e
cd "$(dirname "$0")"
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
```

### Validate & Package
```bash
bash build.sh com.example.my-service   # py_compile + pip --dry-run + bash -n
bash pack.sh  com.example.my-service
```

---

## Archetype 4: Full-Stack Plugin

Combine archetypes 2 + 3 in one plugin directory. See [`huggingface/chat.axons.huggingface`](../huggingface/chat.axons.huggingface) for a complete reference implementation.

The build pipeline automatically does both: backend validation **and** frontend build.

---

## Manifest Reference

| Field | Type | Required | Notes |
|---|---|---|---|
| `id` | string | ✅ | Reverse-DNS style, lowercase. Globally unique. |
| `version` | string | ✅ | SemVer. |
| `name` | string | recommended | Human display name. |
| `description` | string | recommended | One-line summary. |
| `author` | string | recommended | |
| `icon` | string | recommended | Path relative to plugin dir (`.svg` preferred). |
| `category` | string | recommended | Free-form. Standard: `localization`, `productivity`, `theme`, `language-server`. |
| `minAxonsVersion` | string | recommended | Minimum compatible Axons version. |
| `permissions` | string[] | optional | E.g. `project:read`, `model:register`, `panel:create`. |
| `backend` | object \| null | optional | See Archetype 3. |
| `frontend` | object \| null | optional | See Archetypes 2 / 4. |
| `frontend.panels[].order` | number | optional | Sort weight for activity bar / footer icons. Lower = earlier. Built-in reserves 0–9, plugins use 10–99. Defaults to `10` if omitted. |
| `activationEvents` | string[] | optional | E.g. `onStartup`, `onCommand:my.cmd`. |

Refer to the [Axons plugin protocol documentation](https://www.axons.chat) for the authoritative schema.

---

## Naming & Versioning

### Plugin ID convention
- Reverse-DNS, all lowercase: `com.<org>.<short-name>`.
- Use hyphens between words: `com.example.code-formatter`, not `com.example.codeFormatter`.
- The ID is what users see in error messages, registries, and import logs — keep it stable across versions.

### Versioning
- Follow [SemVer](https://semver.org/):
  - `MAJOR` — incompatible manifest/API changes.
  - `MINOR` — new features, backward compatible.
  - `PATCH` — bug fixes.
- Bump the version **before** packaging. The tarball filename embeds it:
  `com.example.my-plugin-1.2.3.axons-plugin.tar.gz`

---

## Testing Your Plugin

1. **Validate locally:**
   ```bash
   bash build.sh com.example.my-plugin
   bash pack.sh  com.example.my-plugin
   ```
2. **Inspect the tarball:**
   ```bash
   tar tzf dist/com.example.my-plugin-0.1.0.axons-plugin.tar.gz | sort
   ```
   Look out for accidentally-included `node_modules/` or `__pycache__/`.
3. **Import into a running Axons instance:**
   ```bash
   curl -X POST http://127.0.0.1:9090/v1/plugins/import \
        -F 'file=@dist/com.example.my-plugin-0.1.0.axons-plugin.tar.gz'
   ```
4. **Iterate:** edit code → `bash build.sh com.example.my-plugin` → `bash pack.sh com.example.my-plugin` → re-import (Axons UI reloads the plugin automatically on re-import).

---

## Publishing Checklist

Before opening a pull request:

- [ ] `manifest.json` has bumped `version`, accurate `description`, and complete `permissions`.
- [ ] `bash build.sh <id>` exits 0 with no warnings.
- [ ] `bash pack.sh  <id>` produces a tarball.
- [ ] `tar tzf dist/<id>-<ver>.axons-plugin.tar.gz` contains **only** runtime files (no `src/`, `node_modules/`, `__pycache__/`, `.venv/`).
- [ ] If frontend: `ui/index.js` is committed to git (end-users don't need npm).
- [ ] [`CHANGELOG.md`](../CHANGELOG.md) updated with the change.
- [ ] [`README.md`](../README.md) plugin table updated if you added a new plugin.
- [ ] Repository cleaned: `bash clean.sh --keep-artifacts`.
- [ ] Commits sign-off and follow the project's commit-message convention.