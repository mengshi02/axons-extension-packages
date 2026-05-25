# Changelog

All notable changes to this repository's tooling and plugin set are recorded here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

> Individual plugins maintain their own version in their `manifest.json`.
> This file tracks repository-level changes (tooling, structure, conventions).

## [Unreleased]

### Added
- Unified root-level scripts: `build.sh` / `pack.sh` / `clean.sh` that auto-discover all plugins via `manifest.json`.
- Per-plugin hook protocol under `<plugin>/scripts/` (`build.sh`, `pre-pack.sh`, `post-pack.sh`, `clean.sh`).
- Per-plugin configuration files: `.axons-build` (artifact list) and `.axons-ignore` (tar excludes).
- Filtering by plugin ID, sub-directory, or parent directory across all three scripts.
- Backend validation in `build.sh`: Python `py_compile`, `pip install --dry-run` (with PEP 668 fallback), and `bash -n` syntax checks.
- Frontend build pipeline in `build.sh`: `npm ci` / `npm install` → `npm run build` → artifact verification.
- Help text (`-h` / `--help`) on every script.
- `clean.sh` removes `.venv/`, `__pycache__/`, and `*.pyc` in addition to `node_modules/` / `.vite/`.
- `dist/` directory at repository root as the canonical output location for `.axons-plugin.tar.gz`.
- Documentation suite under `docs/` (development manual, plugin authoring guide, release guide).

### Changed
- Packaged tarballs now land in `<repo_root>/dist/` instead of inside each plugin directory.
- `language/pack.sh` and `huggingface/{build,pack,clean}.sh` are now thin wrappers that forward to the root scripts with their directory as the default filter.
- Default `pack.sh` excludes now drop `src/`, `scripts/`, `package*.json`, `tsconfig.json`, and `vite.config.*` so frontend source files do not ship in the runtime tarball.

### Fixed
- `pip install --dry-run` validation now degrades gracefully on PEP 668 environments (macOS Homebrew Python, Debian-managed Python).

## [0.1.0] – 2026-05-15

Initial repository scaffolding with two plugins:

### Added
- `chat.axons.locale-zh-cn` v1.0.0 — Simplified Chinese language pack.
- `chat.axons.huggingface` v1.0.0 — Local LLM browser/manager via Ollama and HuggingFace Hub.
- Per-category packaging scripts (`language/pack.sh`, `huggingface/pack.sh`).
- MIT License.

---

## Plugin Version History

For changes scoped to a single plugin, see the plugin's own `manifest.json` `version` field and any `CHANGELOG.md` inside its directory.

| Plugin | Current Version |
|---|---|
| `chat.axons.locale-zh-cn` | 1.0.0 |
| `chat.axons.huggingface` | 1.0.0 |

[Unreleased]: ../../compare/v0.1.0...HEAD
[0.1.0]: ../../releases/tag/v0.1.0