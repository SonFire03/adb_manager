# Operations Playbook

Operational runbooks for recurring ADB Manager workflows.

## Prerequisites

- Device connected by USB or paired over Wi-Fi.
- Device authorized for ADB (RSA prompt accepted).
- `adb` available in `PATH`.
- App started with:

```bash
python main.py
```

## Runbook 1: Device Health Triage

Goal: quickly validate a device and decide if escalation is required.

1. Open `Health`.
2. Click `Refresh devices`.
3. Select target serial.
4. Run full checks.
5. Export JSON/HTML report.

Expected output:
- Global score and per-check findings.
- Timeline entry in session audit.

Escalate when:
- score < 60,
- repeated thermal/connectivity failures,
- storage or ADB integrity checks fail repeatedly.

## Runbook 2: Smart Sync (Safe Copy)

Goal: transfer files with preview and low overwrite risk.

1. Open `Transfers` -> `Smart Sync`.
2. Select direction and source/destination.
3. Choose `copy_missing_only`.
4. Run preview and validate planned operations.
5. Execute sync.

Expected output:
- Preview includes copy/update/skip actions.
- Transfer audit entries are created.

Rollback:
- Re-run in inverse direction when a mirrored backup exists.

## Runbook 3: Support Bundle Collection

Goal: package evidence for troubleshooting.

1. Open `Workflows` and run `collect_debug_bundle`.
2. Include at least inspector + health data.
3. Export ZIP to `reports/`.

Expected output:
- ZIP archive with manifest and structured artifacts.
- Reproducible folder layout for analyst handoff.

## Runbook 4: Post-Change Snapshot Validation

Goal: verify impact after app install/update/cleanup.

1. Capture snapshot A (before change).
2. Perform the change.
3. Capture snapshot B (after change).
4. Open `Snapshot Compare`.
5. Review added/removed/updated apps and risk deltas.

Expected output:
- Clear diff summary.
- Exportable JSON/HTML comparison report.

## Incident Notes Template

Use this short template in tickets:

- Device serial:
- Date/time:
- Triggering event:
- Health score:
- Key findings:
- Actions performed:
- Artifact paths:
- Next decision:
