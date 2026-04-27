"""Feature modules for ADB Manager Pro."""

from .app_manager import AppManagerModule
from .automation import AutomationModule
from .backup_restore import BackupRestoreModule
from .device_inspector import DeviceInspectorModule
from .device_profiles import DeviceProfile, DeviceProfilesModule
from .file_manager import FileManagerModule
from .health_check import HealthCheckModule
from .session_audit import SessionAuditModule
from .snapshot_compare import SnapshotCompareModule
from .system_info import SystemInfoModule

__all__ = [
    "AppManagerModule",
    "AutomationModule",
    "BackupRestoreModule",
    "DeviceInspectorModule",
    "DeviceProfile",
    "DeviceProfilesModule",
    "FileManagerModule",
    "HealthCheckModule",
    "SessionAuditModule",
    "SnapshotCompareModule",
    "SystemInfoModule",
]
