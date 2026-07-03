# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog and this project follows Semantic Versioning (SemVer) intent.

## [Unreleased]

### Added
- Refonte globale des couleurs de l'UI avec un accent ambre.
- Contours renforcés sur le thème clair pour mieux distinguer les panneaux et tableaux.
- Contraste renforcé des tableaux en mode sombre.
- Rapport global HTML plus lisible.
- Index HTML enrichi pour les support bundles.
- Export/import dédié pour les profils appareils.
- Export/import dédié pour les presets de transfert.
- Réordonnancement de la file batch.
- Résumé produit sur le dashboard.
- Bundle de configuration exportable/importable pour settings, profils et favoris commandes.
- Import bundle plus robuste avec resynchronisation des contrôles UI principaux.
- Deep `DeviceHealthModule` tests to cover scoring, sections, parsing, and failure branches.

### Changed
- CI now enforces a critical-modules aggregate gate (`device_health`, `smart_sync`, `data_transfer`).

## [2.5.6] - 2026-05-07

### Added
- New `SmartSyncModule` tests for decision/scan/execute branches.

### Changed
- CI now enforces a module-specific gate for `modules/smart_sync.py` (minimum 90% coverage).
- Added a fast smoke CI job on Python 3.12 for quick PR feedback.

## [2.5.5] - 2026-05-07

### Added
- New `DataTransferModule` tests to cover failure, partial-success, and helper branches.

### Changed
- CI now enforces a module-specific gate for `modules/data_transfer.py` (minimum 90% coverage).
- `modules/data_transfer.py` coverage raised to 100% for the v2.5.5 kickoff.

## [2.5.4] - 2026-05-07

### Added
- `.github/CODEOWNERS` to protect critical paths (`core/*`, `modules/*`, workflows).
- New `DeviceManager` tests for error notification, listener-fault tolerance, async poll, and Wi-Fi subnet scan paths.

### Changed
- `core/device_manager.py` coverage increased through targeted test scenarios (v2.5.4 quality sprint kickoff).

## [2.5.3] - 2026-05-07

### Added
- MIT `LICENSE` and minimal `NOTICE` file.
- New tests for `core/utils.py` (ConfigManager, HistoryDB, setup_logging paths).

### Changed
- CI now enforces an additional core coverage gate (`coverage report --include="core/*" --fail-under=85`).
- `scripts/release_check.sh` and `Makefile` include the core coverage gate.

## [2.5.2] - 2026-05-07

### Added
- `scripts/release_check.sh` helper to run lint, formatting, tests+coverage, and basic release-document checks.
- `Makefile` targets for standard local workflows: `deps`, `check`, `coverage`, `release-check`.
- New tests for `core/adb_manager.py` and `core/commands.py` (`tests/test_core_runtime.py`).

### Changed
- Replaced deprecated `datetime.utcnow()` usage in modules with timezone-aware UTC timestamps.
- UTC migration adjusted for Python 3.10 compatibility (`timezone.utc` instead of `datetime.UTC`).
- Expanded tests for `data_transfer`, `smart_sync`, and `support_bundle` edge paths.

## [2.5.1] - 2026-05-07

### Added
- `.gitignore` now ignores `*.log.*` and `config/notifications.db` local runtime artifacts.
- README now includes a measurable `v2.5.1` Quality Sprint roadmap (CI gates, coverage, reliability, docs, release checks).
- Coverage configuration file `.coveragerc` for unit-test scope on `core/` and `modules/`.
- New infrastructure-oriented test suite `tests/test_infra_modules.py` (device manager, plugin manager, automation, file manager, backup/restore).
- Operations playbook: `docs/operations-playbook.md`.
- Coverage badge in README (`>=80%` target gate).

### Changed
- CI now installs `pytest-cov` and enforces `pytest --cov --cov-fail-under=80`.
- CI workflow migrated to Node 24-compatible action majors (`checkout@v6`, `setup-python@v6`).

## [2.5.0] - 2026-05-07

### Added
- Workflow Center with guided playbooks and execution history.
- Support Bundle export (ZIP + manifest + HTML index).
- Notification Center with severity/device/unread filters and read/delete actions.
- Smart Sync module and transfer preview/execution modes.
- App Change Tracker integrated into Snapshot Compare.
- New module tests: `tests/test_ops_modules.py`.
- Test bootstrap file `tests/conftest.py` to ensure local package imports work in `pytest`.
- Regression tests for invalid JSON config fallback and profile upsert by serial.

### Changed
- README updated for v2.4 guided ops feature set.
- README rewritten for v2.5-quality product narrative (quick workflows, signature features, reduced visual density).
- Added `docs/quick-demo.md` for a fast product walkthrough.
- Release notes template refined for cleaner release readiness.
- `ConfigManager` now handles corrupted JSON settings safely (fallback defaults instead of crash).
- `setup_logging` now recreates parent log directory and resets previous handlers to avoid duplicate logs.
- `DeviceProfilesModule.save_profile()` now upserts by `serial` when no `profile_id` is provided.
- README stable version bumped to `v2.5.0`, fixed broken screenshot reference, and test command switched to `pytest`.

## [2.3.0] - 2026-04-28

### Added
- Data Transfer Center module (queue, presets, dry-run, progress, JSON/HTML transfer reports).
- Device Health Checks module (battery/storage/cpu-memory/thermal/connectivity/adb/app hints with global score).
- UI tabs `Transfers` and `Health` with exports and detailed findings rendering.
- Audit trail integration for transfer executions and device health runs.
- Unit tests for transfer and device health modules (`tests/test_transfer_health_modules.py`).
- Health timeline in UI (historical device health scores, trend, CSV export) powered by audit trail.
- `SessionAuditModule.list_health_timeline()` helper API + test coverage.
- Health timeline mini chart embedded in UI.
- Fleet health overview table with per-device latest score/status/check.
- Run-all health checks action for connected authorized devices.
- Health timeline filters (device + date range).
- Persistent transfer presets in UI (save/load/delete custom presets).

### Changed
- README updated to v2.2 positioning and functional health-check framing.
- README updated to v2.3 feature set and product framing.

## [2.2.0] - 2026-04-28

### Added
- Data Transfer Center and Device Health Checks initial release.
- JSON/HTML transfer and health exports.
- Initial health timeline with CSV export.

### Changed
- README updated for v2.2 operations update.

## [2.1.0] - 2026-04-27

### Added
- Session Reports / Audit Trail with session/event history, filters, JSON/HTML export.
- Snapshot Compare with package/storage/system-state diff and JSON/HTML export.
- Reports tab in UI to consult audit trails and compare snapshots.
- Repo maturity assets: CI workflow, issue templates, PR template, contributing/security docs.

### Changed
- README reframed for product maturity, safe usage, release/testing guidance.
- `.gitignore` hardened for audit DB and generated report artifacts.

## [2.0.0] - 2026-04-27

### Added
- Device Inspector module and dashboard panel.
- ADB Health Check / Diagnostic with remediation hints.
- App Risk View with sensitive permission analysis and risk scoring.
- Device Profiles (save/load/delete + auto-load by serial).
- Remote multi-device control improvements.
