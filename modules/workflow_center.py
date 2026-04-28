from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class WorkflowStep:
    key: str
    title: str
    action: str


@dataclass(slots=True)
class WorkflowDefinition:
    workflow_id: str
    title: str
    description: str
    impact: str
    steps: list[WorkflowStep]


class WorkflowCenterModule:
    def definitions(self) -> list[WorkflowDefinition]:
        return [
            WorkflowDefinition(
                "onboard_device",
                "Onboard New Device",
                "Verifier connexion, inspector, health de base et snapshot initial.",
                "low",
                [
                    WorkflowStep("poll", "Refresh devices", "refresh_devices"),
                    WorkflowStep("inspector", "Run Device Inspector", "device_inspector"),
                    WorkflowStep("health", "Run Device Health Checks", "device_health"),
                    WorkflowStep("snapshot", "Capture baseline snapshot", "capture_snapshot"),
                ],
            ),
            WorkflowDefinition(
                "full_health",
                "Run Full Health Assessment",
                "Executer health checks + timeline refresh + rapport.",
                "low",
                [
                    WorkflowStep("health", "Run Device Health Checks", "device_health"),
                    WorkflowStep("timeline", "Refresh health timeline", "refresh_health_timeline"),
                    WorkflowStep("export", "Export health JSON", "export_health_json_auto"),
                ],
            ),
            WorkflowDefinition(
                "collect_debug_bundle",
                "Collect Debug Bundle",
                "Collecter health, inspector, audit et captures dans un support bundle.",
                "low",
                [
                    WorkflowStep("inspector", "Run Device Inspector", "device_inspector"),
                    WorkflowStep("health", "Run Device Health Checks", "device_health"),
                    WorkflowStep("bundle", "Create support bundle", "support_bundle"),
                ],
            ),
            WorkflowDefinition(
                "backup_media",
                "Backup Photos & Screenshots",
                "Transfert guide des dossiers DCIM et Screenshots vers l'hote.",
                "low",
                [
                    WorkflowStep("queue_dcim", "Queue DCIM transfer", "queue_transfer_dcim"),
                    WorkflowStep("queue_shots", "Queue Screenshots transfer", "queue_transfer_screenshots"),
                    WorkflowStep("run_queue", "Run transfer queue", "run_transfer_queue"),
                ],
            ),
            WorkflowDefinition(
                "prepare_troubleshooting",
                "Prepare Troubleshooting Session",
                "Preparer environnement debug avec checks connexion + logcat.",
                "medium",
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
                [
                    WorkflowStep("poll", "Refresh devices", "refresh_devices"),
                    WorkflowStep("inspector", "Run Device Inspector", "device_inspector"),
                    WorkflowStep("snapshot", "Capture snapshot", "capture_snapshot"),
                ],
            ),
            WorkflowDefinition(
                "pre_transfer_check",
                "Pre-Transfer Device Check",
                "Verifier batterie, stockage et connectivite avant transfert.",
                "low",
                [
                    WorkflowStep("health", "Run Device Health Checks", "device_health"),
                    WorkflowStep("timeline", "Refresh health timeline", "refresh_health_timeline"),
                ],
            ),
            WorkflowDefinition(
                "post_transfer_validation",
                "Post-Transfer Validation",
                "Valider transfert + health check final + rapport.",
                "low",
                [
                    WorkflowStep("health", "Run Device Health Checks", "device_health"),
                    WorkflowStep("timeline", "Refresh health timeline", "refresh_health_timeline"),
                    WorkflowStep("transfer_report", "Export transfer report", "export_transfer_report_auto"),
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
                    "steps": [{"key": s.key, "title": s.title, "action": s.action} for s in w.steps],
                }
            )
        return out
