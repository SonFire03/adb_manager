from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class WorkflowVariable:
    key: str
    label: str
    description: str
    default: str = ""
    required: bool = False


@dataclass(slots=True)
class WorkflowStep:
    key: str
    title: str
    action: str
    kind: str = "action"
    optional: bool = False
    notes: str = ""


@dataclass(slots=True)
class WorkflowDefinition:
    workflow_id: str
    title: str
    description: str
    impact: str
    supports_dry_run: bool = True
    variables: list[WorkflowVariable] = field(default_factory=list)
    steps: list[WorkflowStep] = field(default_factory=list)


class WorkflowCenterModule:
    def definitions(self) -> list[WorkflowDefinition]:
        return [
            WorkflowDefinition(
                "onboard_device",
                "Onboard New Device",
                "Verifier connexion, inspector, health de base et snapshot initial.",
                "low",
                True,
                [
                    WorkflowVariable(
                        "baseline_label",
                        "Baseline label",
                        "Libelle court pour identifier la capture initiale.",
                        "baseline",
                    ),
                    WorkflowVariable(
                        "include_snapshot",
                        "Include snapshot",
                        "Active la capture de reference initiale.",
                        "true",
                    ),
                ],
                [
                    WorkflowStep(
                        "poll",
                        "Refresh devices",
                        "refresh_devices",
                        notes="Met a jour la liste des appareils avant le reste du flux.",
                    ),
                    WorkflowStep(
                        "inspector", "Run Device Inspector", "device_inspector"
                    ),
                    WorkflowStep("health", "Run Device Health Checks", "device_health"),
                    WorkflowStep(
                        "snapshot", "Capture baseline snapshot", "capture_snapshot"
                    ),
                ],
            ),
            WorkflowDefinition(
                "full_health",
                "Run Full Health Assessment",
                "Executer health checks + timeline refresh + rapport.",
                "low",
                True,
                [
                    WorkflowVariable(
                        "target_serial",
                        "Target serial",
                        "Laisser vide pour utiliser l'appareil selectionne.",
                        "",
                    )
                ],
                [
                    WorkflowStep("health", "Run Device Health Checks", "device_health"),
                    WorkflowStep(
                        "timeline", "Refresh health timeline", "refresh_health_timeline"
                    ),
                    WorkflowStep(
                        "export", "Export health JSON", "export_health_json_auto"
                    ),
                ],
            ),
            WorkflowDefinition(
                "collect_debug_bundle",
                "Collect Debug Bundle",
                "Collecter health, inspector, audit et captures dans un support bundle.",
                "low",
                True,
                [
                    WorkflowVariable(
                        "bundle_name",
                        "Bundle name",
                        "Nom de l'archive de support generee.",
                        "support_bundle",
                    ),
                    WorkflowVariable(
                        "include_logs",
                        "Include logs",
                        "Inclut les logs recents si disponibles.",
                        "false",
                    ),
                ],
                [
                    WorkflowStep(
                        "inspector", "Run Device Inspector", "device_inspector"
                    ),
                    WorkflowStep("health", "Run Device Health Checks", "device_health"),
                    WorkflowStep("bundle", "Create support bundle", "support_bundle"),
                ],
            ),
            WorkflowDefinition(
                "backup_media",
                "Backup Photos & Screenshots",
                "Transfert guide des dossiers DCIM et Screenshots vers l'hote.",
                "low",
                True,
                [
                    WorkflowVariable(
                        "destination_root",
                        "Destination root",
                        "Racine locale des sauvegardes media.",
                        "./transfers",
                    )
                ],
                [
                    WorkflowStep(
                        "queue_dcim", "Queue DCIM transfer", "queue_transfer_dcim"
                    ),
                    WorkflowStep(
                        "queue_shots",
                        "Queue Screenshots transfer",
                        "queue_transfer_screenshots",
                    ),
                    WorkflowStep(
                        "run_queue", "Run transfer queue", "run_transfer_queue"
                    ),
                ],
            ),
            WorkflowDefinition(
                "prepare_troubleshooting",
                "Prepare Troubleshooting Session",
                "Preparer environnement debug avec checks connexion + logcat.",
                "medium",
                True,
                [
                    WorkflowVariable(
                        "logcat_lines",
                        "Logcat lines",
                        "Nombre de lignes recuperees pour le diagnostic.",
                        "250",
                    )
                ],
                [
                    WorkflowStep("health", "Run Device Health Checks", "device_health"),
                    WorkflowStep("adb_health", "Run ADB Health Check", "adb_health"),
                    WorkflowStep("logcat", "Load recent logcat", "load_logcat_recent"),
                ],
            ),
            WorkflowDefinition(
                "quick_inventory",
                "Quick Device Inventory",
                "Inventaire rapide multi-device avec inspector et snapshot.",
                "low",
                True,
                [],
                [
                    WorkflowStep("poll", "Refresh devices", "refresh_devices"),
                    WorkflowStep(
                        "inspector", "Run Device Inspector", "device_inspector"
                    ),
                    WorkflowStep("snapshot", "Capture snapshot", "capture_snapshot"),
                ],
            ),
            WorkflowDefinition(
                "pre_transfer_check",
                "Pre-Transfer Device Check",
                "Verifier batterie, stockage et connectivite avant transfert.",
                "low",
                True,
                [],
                [
                    WorkflowStep("health", "Run Device Health Checks", "device_health"),
                    WorkflowStep(
                        "timeline", "Refresh health timeline", "refresh_health_timeline"
                    ),
                ],
            ),
            WorkflowDefinition(
                "post_transfer_validation",
                "Post-Transfer Validation",
                "Valider transfert + health check final + rapport.",
                "low",
                True,
                [
                    WorkflowVariable(
                        "report_name",
                        "Report name",
                        "Nom du rapport de validation a generer.",
                        "post_transfer_validation",
                    )
                ],
                [
                    WorkflowStep("health", "Run Device Health Checks", "device_health"),
                    WorkflowStep(
                        "timeline", "Refresh health timeline", "refresh_health_timeline"
                    ),
                    WorkflowStep(
                        "transfer_report",
                        "Export transfer report",
                        "export_transfer_report_auto",
                    ),
                ],
            ),
        ]

    def as_dicts(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for w in self.definitions():
            out.append(
                {
                    "workflow_id": w.workflow_id,
                    "title": w.title,
                    "description": w.description,
                    "impact": w.impact,
                    "supports_dry_run": w.supports_dry_run,
                    "variables": [
                        {
                            "key": v.key,
                            "label": v.label,
                            "description": v.description,
                            "default": v.default,
                            "required": v.required,
                        }
                        for v in w.variables
                    ],
                    "steps": [
                        {
                            "key": s.key,
                            "title": s.title,
                            "action": s.action,
                            "kind": s.kind,
                            "optional": s.optional,
                            "notes": s.notes,
                        }
                        for s in w.steps
                    ],
                }
            )
        return out
