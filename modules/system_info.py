from __future__ import annotations

import re

from core.adb_manager import ADBManager


class SystemInfoModule:
    def __init__(self, adb: ADBManager) -> None:
        self.adb = adb

    def gather(self, serial: str) -> dict[str, str]:
        fields = {
            "model": "ro.product.model",
            "manufacturer": "ro.product.manufacturer",
            "android": "ro.build.version.release",
            "sdk": "ro.build.version.sdk",
            "security_patch": "ro.build.version.security_patch",
        }
        info: dict[str, str] = {}
        for key, prop in fields.items():
            res = self.adb.run(["shell", "getprop", prop], serial=serial)
            info[key] = res.stdout.strip() if res.ok else "n/a"
        battery = self.adb.run(["shell", "dumpsys", "battery"], serial=serial)
        if battery.ok:
            level = re.search(r"level:\s*(\d+)", battery.stdout)
            status = re.search(r"status:\s*(\d+)", battery.stdout)
            info["battery_level"] = level.group(1) if level else "n/a"
            info["battery_status"] = status.group(1) if status else "n/a"
        storage = self.adb.run(["shell", "df", "-h", "/data"], serial=serial)
        info["storage"] = storage.stdout.splitlines()[-1] if storage.ok and storage.stdout else "n/a"
        return info

    def monitor_snapshot(self, serial: str) -> dict[str, str]:
        top = self.adb.run(["shell", "top", "-n", "1", "-b"], serial=serial)
        mem = self.adb.run(["shell", "cat", "/proc/meminfo"], serial=serial)
        return {
            "top": top.stdout if top.ok else top.stderr,
            "meminfo": mem.stdout if mem.ok else mem.stderr,
        }

