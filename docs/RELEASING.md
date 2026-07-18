# Releasing

Releases are cut by creating a GitHub Release, which triggers `.github/workflows/publish.yml` (PyPI OIDC).

## Checklist

1. Bump version in `pyproject.toml` (single source of truth).
2. Move the CHANGELOG `## [Unreleased]` section to `## [X.Y.Z] — <date>` and add a fresh empty `## [Unreleased]` above it.
3. Check for stale hardcoded versions:
   ```bash
   grep -rn '"2\.[0-9]' production/adapters/ production/mcp_server.py
   ```
   This should return nothing (see PKG-10).
4. Verify build and metadata:
   ```bash
   python -m build && pip install twine && twine check --strict dist/*
   ```
5. Commit and tag, following the repo's existing **v-prefixed** tag convention:
   ```bash
   git tag vX.Y.Z && git push origin master --tags
   ```
6. Create the GitHub Release with tag `vX.Y.Z` (triggers `publish.yml`).
7. Confirm the publish workflow went green.

Tag format is **vX.Y.Z** (matching existing tags `v2.6.0` / `v2.7.0`).
