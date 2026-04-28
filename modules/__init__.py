"""Feature modules for ADB Manager Pro."""

from .app_manager import AppManagerModule
from .automation import AutomationModule
from .backup_restore import BackupRestoreModule
from .app_change_tracker import AppChangeTrackerModule
from .notification_center import NotificationCenterModule
from .device_inspector import DeviceInspectorModule
from .device_profiles import DeviceProfile, DeviceProfilesModule
from .device_health import DeviceHealthModule
from .data_transfer import DataTransferModule, TransferTask
from .file_manager import FileManagerModule
from .health_check import HealthCheckModule
from .session_audit import SessionAuditModule
from .smart_sync import SmartSyncModule
from .snapshot_compare import SnapshotCompareModule
from .support_bundle import SupportBundleModule
from .system_info import SystemInfoModule
from .workflow_center import WorkflowCenterModule

__all__ = [
    "AppManagerModule",
    "AutomationModule",
    "BackupRestoreModule",
    "AppChangeTrackerModule",
    "NotificationCenterModule",
    "DeviceInspectorModule",
    "DeviceProfile",
    "DeviceProfilesModule",
    "DeviceHealthModule",
    "DataTransferModule",
    "TransferTask",
    "FileManagerModule",
    "HealthCheckModule",
    "SessionAuditModule",
    "SmartSyncModule",
    "SnapshotCompareModule",
    "SupportBundleModule",
    "SystemInfoModule",
    "WorkflowCenterModule",
]
