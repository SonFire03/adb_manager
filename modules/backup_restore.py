from __future__ import annotations

from datetime import datetime
from pathlib import Path

from core.adb_manager import ADBManager
from core.utils import CommandResult


class BackupRestoreModule:
    def __init__(self, adb: ADBManager, backup_dir: Path) -> None:
        self.adb = adb
        self.backup_dir = backup_dir
        self.backup_dir.mkdir(parents=True, exist_ok=True)

    def full_backup(self, serial: str, name: str | None = None) -> CommandResult:
        stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        output = self.backup_dir / f"{name or 'android_backup'}_{stamp}.ab"
        return self.adb.run(["backup", "-apk", "-shared", "-all", "-f", str(output)], serial=serial, timeout=600)

    def selective_backup(self, serial: str, packages: list[str], name: str | None = None) -> CommandResult:
        stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        output = self.backup_dir / f"{name or 'android_selective'}_{stamp}.ab"
        cmd = ["backup", "-apk", "-obb", "-f", str(output), *packages]
        return self.adb.run(cmd, serial=serial, timeout=600)

    def restore(self, serial: str, backup_file: Path) -> CommandResult:
        return self.adb.run(["restore", str(backup_file)], serial=serial, timeout=600)

