# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- MIT license, CHANGELOG, and a CI workflow (lint, 3.11–3.13 test matrix,
  wheel install smoke test) that gates PyPI releases.
- Characterization tests pinning rendered systemd unit files and Docker
  container config ahead of internal refactors.

### Changed
- Lint/format tooling migrated from black + isort + flake8 to ruff.
- `requires-python` relaxed from `>=3.12` to `>=3.11`.

### Removed
- Committed personal artifacts (`data/`, `.codigote/`, coverage files).

## [0.19.1] - 2026-07-16

### Fixed
- Restored installability: the 0.19.0 sdist/wheel could not `import taskflows`
  on a clean install. The `alerts`/`files`/`dynamic_imports` subpackages were
  extracted to the external `msgflows`, `fileflows`, and `dynamic-imports`
  packages, but the new dependencies were never declared and several modules
  still imported the deleted paths (breaking the `tf` CLI and API server).
- `Alerts` and `RestartPolicy` are now exported from the top-level `taskflows`
  namespace, matching the documented API.

## [0.19.0] and earlier

No changelog was kept; see the git history.
