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
- **Breaking:** the admin API / web UI dependencies (fastapi, uvicorn, passlib,
  pyjwt, aiohttp) moved to the `taskflows[server]` extra and grafanalib to
  `taskflows[grafana]`; 17 unused dependencies were dropped entirely.
- **Breaking:** Docker containers no longer force the fluentd log driver.
  Logging is now opt-in via `DockerContainer.log_driver`/`log_options` or the
  `TASKFLOWS_DOCKER_LOG_DRIVER` setting; fluentd options default to
  `TASKFLOWS_FLUENT_BIT` instead of a hardcoded localhost address.
- **Breaking:** `tf api api-start/api-restart/api-stop` renamed to
  `tf api start/restart/stop` (matching the documentation).
- The API systemd service no longer hardcodes a personal conda environment;
  it runs `_start_srv_api` from the installing environment by default, with
  `TASKFLOWS_API_ENV` as an opt-in conda/mamba environment override.
- The CLI debug log path moved from `/opt/taskflows/data/logs` to
  `~/.taskflows/data/logs`.
- **Breaking:** importing taskflows no longer creates `~/.taskflows`, mutates
  environment variables, registers Prometheus collectors, or configures
  structlog. No log files are written unless `TASKFLOWS_FILE_DIR` is set.
  `taskflows.metrics` now exposes a `get_metrics()` factory instead of
  module-level collectors.
- **Breaking:** the top-level namespace is now lazy (PEP 562) and intentional;
  Grafana `Dashboard`/logs-panel types must be imported from
  `taskflows.dashboard` (requires the `grafana` extra).
- Alert config moved to `taskflows.alerts` (`from taskflows import Alerts`
  still works). `Alerts.send_to` accepts any msgflows `MsgDst` destination
  instead of a hardcoded set of three. Alert sending is now best-effort — a
  failing alert send is logged and never fails the task — and Grafana/Loki
  log links are only embedded when Grafana is actually configured
  (`TASKFLOWS_GRAFANA`, `TASKFLOWS_LOKI_URL`, or an API key), so alerts no
  longer contain dead localhost links by default.

- `service.py` decomposed: D-Bus connection management and unit query/lifecycle
  functions now live in `taskflows.systemd` (`start_units`, `stop_units`, …;
  the old underscored names remain as aliases), `Venv` lives in
  `taskflows.environments`, and `Service.render_unit_files()` exposes unit-file
  rendering as pure data (`{filename: content}`) separate from writing.

### Removed
- Committed personal artifacts (`data/`, `.codigote/`, coverage files).
- The deprecated `task_history` stub, `tf history` command, and `/history`
  API endpoint (run history is delegated to Loki/Grafana).
- Legacy dead code: `exec._run_function`, `exec._migrate_unsigned_pickle`,
  `CgroupConfig._parse_device_bandwidth_limits`.

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
