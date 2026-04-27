from __future__ import annotations

import fnmatch
from pathlib import Path

from core.adb_manager import ADBManager
from core.utils import CommandResult


class FileManagerModule:
    def __init__(self, adb: ADBManager) -> None:
        self.adb = adb

    def list_remote(self, serial: str, remote_path: str = "/sdcard") -> list[str]:
        result = self.adb.run(["shell", "ls", "-la", remote_path], serial=serial)
        if not result.ok:
            return []
        return result.stdout.splitlines()

    def pull(self, serial: str, remote_path: str, local_path: Path) -> CommandResult:
        local_path.parent.mkdir(parents=True, exist_ok=True)
        return self.adb.run(["pull", remote_path, str(local_path)], serial=serial, timeout=180)

    def push(self, serial: str, local_path: Path, remote_path: str) -> CommandResult:
        return self.adb.run(["push", str(local_path), remote_path], serial=serial, timeout=180)

    def chmod(self, serial: str, mode: str, remote_path: str) -> CommandResult:
        return self.adb.run(["shell", "chmod", mode, remote_path], serial=serial)

    def search_remote(self, serial: str, base_path: str, pattern: str) -> list[str]:
        result = self.adb.run(["shell", "find", base_path, "-type", "f"], serial=serial, timeout=45)
        if not result.ok:
            return []
        return [line for line in result.stdout.splitlines() if fnmatch.fnmatch(line, f"*{pattern}*")]

