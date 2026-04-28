# Quick Demo (5-10 min)

This guide helps you demo ADB Manager Pro quickly with a strong product story.

## Demo Goal

Show that ADB Manager Pro is a practical Android ops console:
- functional health checks,
- traceable changes,
- actionable export for troubleshooting.

## Prerequisites

- `adb` installed and available in `PATH`
- Android device with USB debugging (or wireless debugging) enabled
- Device authorized (RSA prompt accepted)

## Demo Flow

### 1) Connect and Baseline

1. Open app and click `Actualiser`.
2. Select your device.
3. Run `Device Inspector`.
4. Capture `Snapshot A`.

Expected outcome:
- device metadata visible,
- baseline snapshot saved.

### 2) Run Operational Health

1. Open `Health` tab.
2. Click `Run Device Health Checks`.
3. Review:
  - global score/status,
  - findings with remediation,
  - timeline + mini chart,
  - fleet overview table.

Expected outcome:
- clear reliability indicators,
- health history entry recorded.

### 3) Transfer Safely with Smart Sync

1. Open `Transfers`.
2. Choose a preset (`Screenshots` or `DCIM`).
3. Click `Preview Sync`.
4. Run queue or sync.

Expected outcome:
- preview decisions (`copy`, `update`, `skip`, `conflict`),
- transfer logs and audit trail entries.

### 4) Compare After Change

1. Make a controlled change on device (install/update one app, or cleanup).
2. Capture `Snapshot B`.
3. Compare `A` vs `B` in `Reports`.

Expected outcome:
- package add/remove/update summary,
- app risk change summary,
- system/device deltas.

### 5) Export a Support Bundle

1. Open `Workflows` tab.
2. Click `Export Support Bundle`.
3. Generate ZIP.

Expected outcome:
- bundle with manifest and indexed evidence (`index.html`),
- ready for troubleshooting handoff.

## What to Emphasize in a Portfolio Demo

- Guided workflows reduce operator mistakes.
- Audit trail + snapshots provide traceability.
- Support bundle turns runtime data into portable evidence.
- Product is non-offensive and focused on local administration/debug.
