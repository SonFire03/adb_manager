# ADB Manager Pro

[![CI](https://github.com/SonFire03/adb_manager/actions/workflows/ci.yml/badge.svg)](https://github.com/SonFire03/adb_manager/actions/workflows/ci.yml)
[![Tests](https://github.com/SonFire03/adb_manager/actions/workflows/ci.yml/badge.svg?branch=main&label=tests)](https://github.com/SonFire03/adb_manager/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/SonFire03/adb_manager?display_name=tag)](https://github.com/SonFire03/adb_manager/releases)

Desktop console (PySide6) for **local Android operations** via ADB: device health, guided workflows, transfers, troubleshooting evidence, and traceable reporting.

Current stable release: **v2.4.0**

## Why It Stands Out

- Centraliser les opérations ADB dans une UI claire et productive.
- Réduire les erreurs humaines avec des checks guidés et une exécution traçable.
- Produire des artefacts concrets (audit trail, snapshot compare, support bundles).
- Rester crédible: outil d’admin locale, sans bypass sécurité ni promesse de diagnostic certifié.

## Signature Features

### 1) Health + Support Bundle Workflow
Run functional health checks, collect evidence, and export a structured ZIP dossier for troubleshooting.

### 2) Snapshot Compare + App Change Tracker
Compare before/after states, highlight package additions/removals/updates, and surface risk changes in one diff view.

## Quick Workflows

### Connect a device and run full health
- **Goal**: Validate operational state quickly.
- **Steps**: Refresh devices → run Device Health Checks → review score/timeline.
- **Result**: Clear status + remediation hints + health history.

### Create a support bundle for troubleshooting
- **Goal**: Export portable evidence for analysis/share.
- **Steps**: Open Workflows/Bundle → choose target device → export ZIP.
- **Result**: Dossier with manifest, JSON evidence, optional captures/logs.

### Transfer photos/screenshots safely
- **Goal**: Move media with low risk.
- **Steps**: Use Transfers presets or Smart Sync preview → run queue/sync.
- **Result**: Controlled transfer with progress + audit entries.

### Compare snapshots after changes
- **Goal**: Verify what changed post-install/update/cleanup.
- **Steps**: Capture snapshot A/B → compare.
- **Result**: Added/removed/updated apps, risk deltas, system change summary.

### Run guided onboarding
- **Goal**: Standardize first contact with a new device.
- **Steps**: Launch `Onboard New Device` workflow.
- **Result**: Inspector + health + baseline snapshot in one run.

## Core Capabilities

- Multi-device USB/Wi-Fi detection and pairing (`adb pair`, QR helper).
- Device Inspector + ADB Health Diagnostic.
- Data Transfer Center + Smart Sync preview modes.
- Application inventory + App Risk View.
- Session Audit Trail, Reports, Snapshot Compare.
- Workflow Center + Support Bundle export.
- Notification Center + Fleet Health overview.
- Remote control via scrcpy + ADB fallback actions.

## Architecture (rapide)

```text
adb_manager/
├── main.py
├── core/              # adb runner, parsing commands, device manager, utils
├── modules/           # logique metier (apps, inspector, health, audit, snapshots...)
├── gui/               # fenetre principale, widgets, styles
├── config/            # settings, commandes/scripts perso
├── tests/             # unittest
├── docs/              # docs et templates release
└── .github/           # CI + templates issue/PR
```

## Installation

Pré-requis:
- Python 3.10+
- Android Platform Tools (`adb`) dans le `PATH`
- Débogage USB ou sans fil activé sur l’appareil
- Appareil autorisé (popup RSA validé)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

## Quick Demo

- `docs/quick-demo.md` provides a 5-minute product walkthrough.
- Focused on “connect → health → snapshot compare → support bundle”.

## Screenshots

Only the most demonstrative views are kept here:

![Dashboard](screen/screen-v2-01.png)
![Data Transfer Center](screen/screen-v2-09.png)
![Device Health Checks](screen/screen-v2-10.png)
![Snapshot Compare](screen/screen-v2-08.png)
![Session Reports](screen/screen-v2-07.png)

## Quality & Stability

- CI pipeline runs on every push/PR: lint/test gates in GitHub Actions.
- Unit test suite covers core modules and ops modules (notifications, sync, bundle, app-change logic).
- Current command:

```bash
python3 -m unittest discover -s tests -v
```

For deeper release checks and notes format, see `docs/release/RELEASE_NOTES_TEMPLATE.md`.

## Safe Usage

- Nécessite une autorisation explicite sur le device (RSA / debug).
- Ne fournit **aucun** bypass de sécurité, contournement root, ni exploitation.
- Ne doit être utilisé que sur des appareils possédés ou explicitement autorisés.
- Les fonctionnalités d’analyse (Health Check, App Risk) sont informatives, pas un scanner offensif.
- Les `Device Health Checks` sont des **indicateurs techniques fonctionnels** basés sur ADB/dumpsys/logcat.
  Ce n'est pas un diagnostic matériel certifié constructeur.

## Release engineering

- CI GitHub Actions: `.github/workflows/ci.yml`
- Changelog: `CHANGELOG.md`
- Contribution guide: `CONTRIBUTING.md`
- Security policy: `SECURITY.md`
- Release notes template: `docs/release/RELEASE_NOTES_TEMPLATE.md`

## Roadmap (next)

- enrichir les comparaisons snapshots (granularité process/service),
- packaging release desktop (AppImage/Windows/macOS),
- améliorer la doc opératoire et les quick playbooks.

## Licence

Ajouter une licence explicite (MIT recommandé) avant diffusion plus large.
