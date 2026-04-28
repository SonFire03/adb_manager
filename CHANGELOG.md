# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog and this project follows Semantic Versioning (SemVer) intent.

## [Unreleased]

### Added
- Data Transfer Center module (queue, presets, dry-run, progress, JSON/HTML transfer reports).
- Device Health Checks module (battery/storage/cpu-memory/thermal/connectivity/adb/app hints with global score).
- UI tabs `Transfers` and `Health` with exports and detailed findings rendering.
- Audit trail integration for transfer executions and device health runs.
- Unit tests for transfer and device health modules (`tests/test_transfer_health_modules.py`).

### Changed
- README updated to v2.2 positioning and functional health-check framing.

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
