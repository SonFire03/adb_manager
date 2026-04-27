from __future__ import annotations

import re
from datetime import datetime

from core.adb_manager import ADBManager
from core.utils import DeviceInfo


class DeviceInspectorModule:
    def __init__(self, adb: ADBManager) -> None:
        self.adb = adb

    def inspect(self, serial: str, device: DeviceInfo | None = None) -> dict[str, str]:
        info: dict[str, str] = {
            "serial": serial,
            "last_refresh": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "state": device.state if device is not None else "unknown",
            "transport": device.transport if device is not None else "unknown",
            "root": "yes" if (device.root if device is not None else self._has_root(serial)) else "no",
        }

        props = {
            "brand": "ro.product.brand",
            "manufacturer": "ro.product.manufacturer",
            "model": "ro.product.model",
            "android_version": "ro.build.version.release",
            "sdk": "ro.build.version.sdk",
            "abi": "ro.product.cpu.abi",
            "abi_list": "ro.product.cpu.abilist",
            "debuggable": "ro.debuggable",
        }
        for key, prop in props.items():
            res = self.adb.run(["shell", "getprop", prop], serial=serial, timeout=8)
            value = res.stdout.strip() if res.ok and res.stdout else "n/a"
            info[key] = value

        adb_enabled = self.adb.run(["shell", "settings", "get", "global", "adb_enabled"], serial=serial, timeout=8)
        if adb_enabled.ok and adb_enabled.stdout.strip() in {"0", "1"}:
            info["debug_status"] = "enabled" if adb_enabled.stdout.strip() == "1" else "disabled"
        else:
            info["debug_status"] = "unknown"

        battery = self.adb.run(["shell", "dumpsys", "battery"], serial=serial, timeout=10)
        info["battery_level"] = "n/a"
        if battery.ok:
            level = re.search(r"level:\s*(\d+)", battery.stdout)
            scale = re.search(r"scale:\s*(\d+)", battery.stdout)
            status = re.search(r"status:\s*(\d+)", battery.stdout)
            if level and scale and scale.group(1).isdigit() and int(scale.group(1)) > 0:
                pct = int(level.group(1)) * 100 / int(scale.group(1))
                info["battery_level"] = f"{pct:.0f}%"
            elif level:
                info["battery_level"] = f"{level.group(1)}%"
            info["battery_status"] = status.group(1) if status else "n/a"

        storage = self.adb.run(["shell", "df", "-k", "/data"], serial=serial, timeout=10)
        total_kb, avail_kb = self._parse_df_kb(storage.stdout) if storage.ok else (0, 0)
        if total_kb > 0:
            info["storage_total"] = self._fmt_bytes(total_kb * 1024)
            info["storage_available"] = self._fmt_bytes(avail_kb * 1024)
        else:
            info["storage_total"] = "n/a"
            info["storage_available"] = "n/a"

        wm_size = self.adb.run(["shell", "wm", "size"], serial=serial, timeout=8)
        wm_density = self.adb.run(["shell", "wm", "density"], serial=serial, timeout=8)
        info["screen_resolution"] = self._parse_wm_size(wm_size.stdout) if wm_size.ok else "n/a"
        info["screen_density"] = self._parse_wm_density(wm_density.stdout) if wm_density.ok else "n/a"

        ip_wifi = self.adb.run(["shell", "ip", "-f", "inet", "addr", "show", "wlan0"], serial=serial, timeout=8)
        info["ip_local"] = self._parse_ipv4(ip_wifi.stdout) if ip_wifi.ok else "n/a"
        if info["ip_local"] == "n/a":
            ip_fallback = self.adb.run(["shell", "ifconfig", "wlan0"], serial=serial, timeout=8)
            if ip_fallback.ok:
                info["ip_local"] = self._parse_ipv4(ip_fallback.stdout)

        return info

    def _has_root(self, serial: str) -> bool:
        res = self.adb.run(["shell", "su", "-c", "id"], serial=serial, timeout=6)
        return res.ok and "uid=0" in res.stdout

    def _parse_wm_size(self, raw: str) -> str:
        for line in raw.splitlines():
            text = line.strip()
            if "Physical size:" in text:
                return text.split(":", 1)[1].strip()
        return "n/a"

    def _parse_wm_density(self, raw: str) -> str:
        for line in raw.splitlines():
            text = line.strip()
            if "Physical density:" in text:
                return text.split(":", 1)[1].strip()
        return "n/a"

    def _parse_ipv4(self, raw: str) -> str:
        m = re.search(r"\binet\s+(\d+\.\d+\.\d+\.\d+)", raw)
        if m:
            return m.group(1)
        return "n/a"

    def _parse_df_kb(self, raw: str) -> tuple[int, int]:
        rows = [line.strip() for line in raw.splitlines() if line.strip()]
        if len(rows) < 2:
            return (0, 0)
        parts = re.split(r"\s+", rows[-1])
        if len(parts) < 4:
            return (0, 0)
        try:
            total = int(parts[1])
            avail = int(parts[3])
            return (total, avail)
        except ValueError:
            return (0, 0)

    def _fmt_bytes(self, value: int) -> str:
        units = ["B", "KB", "MB", "GB", "TB"]
        v = float(max(0, value))
        for unit in units:
            if v < 1024 or unit == units[-1]:
                return f"{v:.1f} {unit}" if unit != "B" else f"{int(v)} {unit}"
            v /= 1024
        return f"{int(value)} B"
