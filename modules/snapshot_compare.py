from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.adb_manager import ADBManager
from core.utils import DeviceInfo
from modules.app_manager import AppManagerModule
from modules.app_change_tracker import AppChangeTrackerModule
from modules.device_inspector import DeviceInspectorModule


class SnapshotCompareModule:
    def __init__(self, adb: ADBManager, app_module: AppManagerModule, inspector_module: DeviceInspectorModule, snapshots_dir: Path) -> None:
        self.adb = adb
        self.app_module = app_module
        self.inspector_module = inspector_module
        self.app_change_tracker = AppChangeTrackerModule()
        self.snapshots_dir = snapshots_dir
        self.snapshots_dir.mkdir(parents=True, exist_ok=True)

    def capture_snapshot(self, serial: str, device: DeviceInfo | None = None) -> dict[str, Any]:
        ts = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        inspector = self.inspector_module.inspect(serial, device)
        sysinfo = self._system_properties(serial)
        packages = sorted(self.app_module.list_packages(serial, include_system=False))
        versions = self._package_versions(serial)
        risks = self._package_risks(serial, packages)
        monitor = self._monitor(serial)

        snapshot = {
            "snapshot_version": 1,
            "captured_at": ts,
            "serial": serial,
            "device": {
                "model": (device.model if device else inspector.get("model", "unknown")),
                "transport": (device.transport if device else inspector.get("transport", "unknown")),
                "state": (device.state if device else inspector.get("state", "unknown")),
                "root": (device.root if device else str(inspector.get("root", "no")).lower() == "yes"),
                "debug": inspector.get("debug_status", "unknown"),
            },
            "inspector": inspector,
            "system_properties": sysinfo,
            "packages_user": packages,
            "package_versions": versions,
            "package_risks": risks,
            "monitor": monitor,
        }
        name = f"snapshot_{self._sanitize(serial)}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        path = self.snapshots_dir / name
        path.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False), encoding="utf-8")
        snapshot["file"] = str(path)
        return snapshot

    def list_snapshots(self) -> list[Path]:
        return sorted(self.snapshots_dir.glob("snapshot_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)

    def load_snapshot(self, path: Path) -> dict[str, Any]:
        return json.loads(path.read_text(encoding="utf-8"))

    def compare(self, older: dict[str, Any], newer: dict[str, Any]) -> dict[str, Any]:
        old_pkgs = set(self._as_list(older.get("packages_user")))
        new_pkgs = set(self._as_list(newer.get("packages_user")))
        added = sorted(new_pkgs - old_pkgs)
        removed = sorted(old_pkgs - new_pkgs)

        old_ins = self._as_dict(older.get("inspector"))
        new_ins = self._as_dict(newer.get("inspector"))
        old_dev = self._as_dict(older.get("device"))
        new_dev = self._as_dict(newer.get("device"))

        storage_old = self._parse_numberish(old_ins.get("storage_available", ""))
        storage_new = self._parse_numberish(new_ins.get("storage_available", ""))

        props_old = self._as_dict(older.get("system_properties"))
        props_new = self._as_dict(newer.get("system_properties"))
        changed_props: dict[str, dict[str, Any]] = {}
        for key in sorted(set(props_old.keys()) | set(props_new.keys())):
            ov = props_old.get(key)
            nv = props_new.get(key)
            if ov != nv:
                changed_props[key] = {"old": ov, "new": nv}

        mon_old = self._as_dict(older.get("monitor"))
        mon_new = self._as_dict(newer.get("monitor"))
        cpu_old = float(mon_old.get("cpu_total", 0.0) or 0.0)
        cpu_new = float(mon_new.get("cpu_total", 0.0) or 0.0)
        mem_old = int(mon_old.get("mem_available_kb", 0) or 0)
        mem_new = int(mon_new.get("mem_available_kb", 0) or 0)

        device_changes = {}
        for key in ("transport", "state", "root", "debug"):
            ov = old_dev.get(key)
            nv = new_dev.get(key)
            if ov != nv:
                device_changes[key] = {"old": ov, "new": nv}

        summary = {
            "packages_added": len(added),
            "packages_removed": len(removed),
            "storage_available_change": self._delta_text(storage_old, storage_new),
            "cpu_total_delta": round(cpu_new - cpu_old, 2),
            "mem_available_delta_kb": int(mem_new - mem_old),
            "system_properties_changed": len(changed_props),
            "device_state_changed": len(device_changes),
        }
        app_changes = self.app_change_tracker.compare(older, newer)
        summary["apps_updated"] = int(app_changes.get("summary", {}).get("updated", 0))
        summary["apps_risk_changes"] = int(app_changes.get("summary", {}).get("risk_changes", 0))

        return {
            "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "from": {"captured_at": older.get("captured_at", ""), "serial": older.get("serial", "")},
            "to": {"captured_at": newer.get("captured_at", ""), "serial": newer.get("serial", "")},
            "summary": summary,
            "packages": {"added": added, "removed": removed},
            "app_changes": app_changes,
            "storage": {
                "old_available": old_ins.get("storage_available", "n/a"),
                "new_available": new_ins.get("storage_available", "n/a"),
                "delta": self._delta_text(storage_old, storage_new),
            },
            "monitor": {
                "cpu_total_old": cpu_old,
                "cpu_total_new": cpu_new,
                "cpu_total_delta": round(cpu_new - cpu_old, 2),
                "mem_available_kb_old": mem_old,
                "mem_available_kb_new": mem_new,
                "mem_available_kb_delta": int(mem_new - mem_old),
            },
            "system_properties": changed_props,
            "device_changes": device_changes,
        }

    def export_diff_json(self, diff: dict[str, Any], output: Path) -> None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(diff, indent=2, ensure_ascii=False), encoding="utf-8")

    def export_diff_html(self, diff: dict[str, Any], output: Path) -> None:
        summary = self._as_dict(diff.get("summary"))
        packages = self._as_dict(diff.get("packages"))
        added = self._as_list(packages.get("added"))
        removed = self._as_list(packages.get("removed"))
        props = self._as_dict(diff.get("system_properties"))
        dev_changes = self._as_dict(diff.get("device_changes"))
        app_changes = self._as_dict(diff.get("app_changes"))

        html = [
            "<!doctype html>",
            "<html lang='fr'><head><meta charset='utf-8'><title>Snapshot Diff</title>",
            "<style>body{font-family:Arial;background:#0b1220;color:#e5e7eb;margin:20px}h1,h2{color:#93c5fd}pre{white-space:pre-wrap}"
            "table{border-collapse:collapse;width:100%}td,th{border:1px solid #1f2937;padding:6px}th{background:#111827}</style></head><body>",
            "<h1>Snapshot Compare</h1>",
            "<h2>Summary</h2><pre>" + self._esc(json.dumps(summary, indent=2, ensure_ascii=False)) + "</pre>",
            "<h2>Packages Added</h2><pre>" + self._esc("\n".join(added) if added else "None") + "</pre>",
            "<h2>Packages Removed</h2><pre>" + self._esc("\n".join(removed) if removed else "None") + "</pre>",
            "<h2>App Changes</h2><pre>" + self._esc(json.dumps(app_changes, indent=2, ensure_ascii=False)) + "</pre>",
            "<h2>Device Changes</h2><pre>" + self._esc(json.dumps(dev_changes, indent=2, ensure_ascii=False)) + "</pre>",
            "<h2>System Properties Changes</h2><pre>" + self._esc(json.dumps(props, indent=2, ensure_ascii=False)) + "</pre>",
            "</body></html>",
        ]
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text("".join(html), encoding="utf-8")

    def _system_properties(self, serial: str) -> dict[str, str]:
        keys = [
            "ro.build.version.release",
            "ro.build.version.sdk",
            "ro.product.brand",
            "ro.product.model",
            "ro.product.cpu.abi",
            "ro.debuggable",
        ]
        out: dict[str, str] = {}
        for key in keys:
            res = self.adb.run(["shell", "getprop", key], serial=serial, timeout=8)
            out[key] = res.stdout.strip() if res.ok and res.stdout else "n/a"
        return out

    def _monitor(self, serial: str) -> dict[str, Any]:
        cpu = self.adb.run(["shell", "dumpsys", "cpuinfo"], serial=serial, timeout=10)
        mem = self.adb.run(["shell", "cat", "/proc/meminfo"], serial=serial, timeout=8)
        cpu_total = 0.0
        mem_total = 0
        mem_available = 0
        if cpu.ok:
            m = re.search(r"(\d+(?:\.\d+)?)%\s+TOTAL", cpu.stdout)
            if m:
                cpu_total = float(m.group(1))
        if mem.ok:
            mt = re.search(r"MemTotal:\s*(\d+)\s*kB", mem.stdout)
            ma = re.search(r"MemAvailable:\s*(\d+)\s*kB", mem.stdout)
            if mt:
                mem_total = int(mt.group(1))
            if ma:
                mem_available = int(ma.group(1))
        return {
            "cpu_total": cpu_total,
            "mem_total_kb": mem_total,
            "mem_available_kb": mem_available,
        }

    def _package_versions(self, serial: str) -> dict[str, str]:
        res = self.adb.run(["shell", "pm", "list", "packages", "-3", "--show-versioncode"], serial=serial, timeout=40)
        if not res.ok:
            return {}
        out: dict[str, str] = {}
        for line in res.stdout.splitlines():
            text = line.strip()
            m = re.match(r"package:([^\s]+)\s+versionCode:(\d+)", text)
            if not m:
                continue
            out[m.group(1)] = m.group(2)
        return out

    def _package_risks(self, serial: str, packages: list[str]) -> dict[str, str]:
        out: dict[str, str] = {}
        max_apps = 40
        for pkg in packages[:max_apps]:
            try:
                data = self.app_module.analyze_app(serial, pkg)
                risk = str(data.get("risk", "")).strip().upper()
                if risk:
                    out[pkg] = risk
            except Exception:  # noqa: BLE001
                continue
        return out

    def _sanitize(self, text: str) -> str:
        return re.sub(r"[^a-zA-Z0-9._-]", "_", text)

    def _parse_numberish(self, text: Any) -> float:
        m = re.search(r"(\d+(?:\.\d+)?)", str(text))
        return float(m.group(1)) if m else 0.0

    def _delta_text(self, old: float, new: float) -> str:
        delta = new - old
        sign = "+" if delta >= 0 else ""
        return f"{sign}{delta:.2f}"

    def _as_list(self, value: Any) -> list[Any]:
        return value if isinstance(value, list) else []

    def _as_dict(self, value: Any) -> dict[str, Any]:
        return value if isinstance(value, dict) else {}

    def _esc(self, value: Any) -> str:
        text = str(value)
        return (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&#39;")
        )
