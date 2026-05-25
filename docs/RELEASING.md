# Release Guide

End-to-end workflow for cutting a release: validate → package → publish → tag.

## Table of Contents
- [Release Cadence](#release-cadence)
- [Versioning Strategy](#versioning-strategy)
- [Step-by-Step Workflow](#step-by-step-workflow)
- [Pre-Commit Cleanup (Important)](#pre-commit-cleanup-important)
- [Tagging Convention](#tagging-convention)
- [Publishing the Tarballs](#publishing-the-tarballs)
- [Hotfix Procedure](#hotfix-procedure)
- [Common Mistakes](#common-mistakes)

---

## Release Cadence

This repository does not enforce a fixed release schedule. Each plugin can release independently when ready:

- **Patch releases** (bug fixes): as needed.
- **Minor releases** (new features): when a feature is complete and validated.
- **Major releases** (breaking changes): coordinate with downstream Axons users and document migration in the plugin's changelog.

Repository-level changes (script changes, conventions, new categories) are tracked in [`CHANGELOG.md`](../CHANGELOG.md) under `[Unreleased]` and rolled into a tag whenever the maintainer cuts a snapshot.

---

## Versioning Strategy

| Component | Where it lives | Versioned how |
|---|---|---|
| Each plugin | `<plugin>/manifest.json` → `version` field | SemVer |
| The repo's tooling | Git tags (`v0.x.y`) and `CHANGELOG.md` | SemVer of the build/pack/clean toolchain |

The two version namespaces are independent. A plugin's `1.2.3` does not move when the repo's tooling moves from `v0.1.0` to `v0.2.0`.

---

## Step-by-Step Workflow

### 1. Bump the plugin version

Edit `<plugin>/manifest.json`:
```diff
- "version": "1.0.0",
+ "version": "1.1.0",
```

### 2. Build & validate

```bash
bash build.sh <plugin-id>
```

Must exit `0`. If frontend: verifies `ui/index.js` was produced. If backend: validates Python syntax + dependency declarations + shell scripts.

### 3. Package

```bash
bash pack.sh <plugin-id>
```

Produces `dist/<id>-<version>.axons-plugin.tar.gz`. Note the SHA-256 line — you'll want it for the release notes.

### 4. Smoke test the tarball

Inspect the contents:
```bash
tar tzf dist/<id>-<version>.axons-plugin.tar.gz | sort
```

Then import into a running Axons instance:
```bash
curl -X POST http://127.0.0.1:9090/v1/plugins/import \
     -F 'file=@dist/<id>-<version>.axons-plugin.tar.gz'
```

Open Axons and exercise the plugin's main paths. If anything looks wrong, fix it and re-run from step 2.

### 5. Update the changelog

Add an entry under `[Unreleased]` in [`CHANGELOG.md`](../CHANGELOG.md) describing the change. Move it under a versioned heading when you tag the toolchain.

### 6. Pre-commit cleanup

```bash
bash clean.sh --keep-artifacts <plugin-id>
```

This removes `node_modules/`, `.venv/`, `__pycache__/`, `*.pyc`, `.vite/` but **keeps `ui/index.js`** (the pre-built artifact that must stay in git).

### 7. Commit

```bash
git add <plugin-dir> CHANGELOG.md
git commit -m "release(<plugin-id>): v<version>"
```

### 8. Tag the plugin release

```bash
git tag <plugin-id>/v<version>
# e.g.
git tag chat.axons.huggingface/v1.1.0
```

### 9. Push

```bash
git push origin main --tags
```

### 10. Publish the artifact

Attach the tarball from `dist/` to your release page (GitHub Releases, internal registry, etc.). See [Publishing the Tarballs](#publishing-the-tarballs).

---

## Pre-Commit Cleanup (Important)

The single most common mistake is committing `node_modules/` or `.venv/` along with the release. The workflow always ends with:

```bash
bash clean.sh --keep-artifacts
```

What it preserves:
- ✅ Source files
- ✅ `ui/index.js` (the pre-built artifact — must be in git)
- ✅ `manifest.json` and other static assets

What it removes:
- ❌ `node_modules/`
- ❌ `.venv/`
- ❌ `__pycache__/` and `*.pyc`
- ❌ `.vite/` cache

What is already gitignored (so it's safe either way):
- `dist/` (the produced tarballs)
- `*.axons-plugin.tar.gz`

---

## Tagging Convention

Two tag styles:

| Tag pattern | Meaning |
|---|---|
| `<plugin-id>/v<version>` | A single-plugin release (e.g. `chat.axons.huggingface/v1.1.0`) |
| `tooling/v<version>` | A toolchain release (build.sh / pack.sh / clean.sh contracts changed) |

GitHub treats `/` in tag names as nested refs — fine for browsing, and avoids collisions between plugin tags and tooling tags.

---

## Publishing the Tarballs

Choose the distribution channel that makes sense for your audience:

### GitHub Releases (recommended for open source)
1. Create a new release from the tag.
2. Drag the tarball from `dist/` into the assets.
3. Paste the SHA-256 from `pack.sh`'s output into the release notes.
4. Reference the changelog entry.

### Internal HTTPS registry
Use a `scripts/post-pack.sh` hook to auto-upload after a successful pack:

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

### Direct install via curl
End users can always:
```bash
curl -X POST http://127.0.0.1:9090/v1/plugins/import \
     -F 'file=@<downloaded-tarball>'
```

---

## Hotfix Procedure

For an urgent bug fix on an already-released plugin version:

1. Branch from the existing tag:
   ```bash
   git checkout -b hotfix/<plugin-id>-<new-version> <plugin-id>/v<old-version>
   ```
2. Apply the fix.
3. Bump `manifest.json` PATCH version (e.g. `1.1.0` → `1.1.1`).
4. Run the regular release workflow (steps 2–10 above).
5. Merge the hotfix branch back into `main` so subsequent releases include the fix.

---

## Common Mistakes

| Mistake | Symptom | Fix |
|---|---|---|
| Forgot to bump `version` in `manifest.json` | New tarball overwrites the old one with the same filename | `git diff <plugin>/manifest.json` before tagging |
| Committed `node_modules/` | PR is huge (hundreds of MB) | Run `bash clean.sh --keep-artifacts`, amend the commit |
| Missing `ui/index.js` in git | Plugin installs but frontend panel is blank | Rerun `bash build.sh <id>`, commit `ui/index.js` |
| `pack.sh` produced tiny tarball (~few KB) | Frontend was never built, so no `ui/index.js` to package | Run `bash build.sh <id>` before `bash pack.sh` |
| Tag created before pushing the artifact | Release page is missing the file | Edit the release after the fact, upload from `dist/` |
| Forgot to update `CHANGELOG.md` | Release notes are empty | Update `CHANGELOG.md` and amend the commit before tagging |