from __future__ import annotations

import os
import re
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.adb_manager import ADBManager


PRESET_FOLDERS = {
    "Photos & Videos": ["/sdcard/DCIM", "/sdcard/Pictures", "/sdcard/Movies"],
    "Documents": ["/sdcard/Documents"],
    "Downloads": ["/sdcard/Download"],
    "DCIM": ["/sdcard/DCIM"],
    "Screenshots": ["/sdcard/Pictures/Screenshots", "/sdcard/DCIM/Screenshots"],
}


@dataclass(slots=True)
class TransferTask:
    task_id: str
    created_at: str
    serial: str
    direction: str  # device_to_host | host_to_device
    source: str
    destination: str
    preset: str = ""
    dry_run: bool = False


class DataTransferModule:
    def __init__(self, adb: ADBManager) -> None:
        self.adb = adb

    def make_task(
        self,
        *,
        serial: str,
        direction: str,
        source: str,
        destination: str,
        preset: str = "",
        dry_run: bool = False,
    ) -> TransferTask:
        return TransferTask(
            task_id=f"tx_{uuid.uuid4().hex[:10]}",
            created_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            serial=serial,
            direction=direction,
            source=source,
            destination=destination,
            preset=preset,
            dry_run=dry_run,
        )

    def preset_sources(self, preset_name: str) -> list[str]:
        if preset_name == "Custom folders":
            return []
        if preset_name == "Export APK only":
            return []
        return PRESET_FOLDERS.get(preset_name, [])

    def estimate_size(self, task: TransferTask) -> dict[str, Any]:
        if task.direction == "host_to_device":
            src = Path(task.source)
            if not src.exists():
                return {"ok": False, "error": f"Source introuvable: {src}", "bytes": 0, "files": 0}
            size, files = self._local_size(src)
            return {"ok": True, "bytes": size, "files": files, "human": self._fmt_bytes(size)}

        # device_to_host
        du = self.adb.run(["shell", "du", "-sk", task.source], serial=task.serial, timeout=20)
        if not du.ok:
            return {"ok": False, "error": du.stderr or "du failed", "bytes": 0, "files": 0}
        kb = self._parse_du_kb(du.stdout)
        count = self.adb.run(["shell", "find", task.source, "-type", "f", "|", "wc", "-l"], serial=task.serial, timeout=30)
        file_count = self._parse_int(count.stdout) if count.ok else 0
        size_bytes = kb * 1024
        return {"ok": True, "bytes": size_bytes, "files": file_count, "human": self._fmt_bytes(size_bytes)}

    def execute_task(self, task: TransferTask) -> dict[str, Any]:
        estimate = self.estimate_size(task)
        if not estimate.get("ok"):
            return {
                "ok": False,
                "task": asdict(task),
                "status": "error",
                "message": str(estimate.get("error", "estimate failed")),
                "estimate": estimate,
            }

        if task.dry_run:
            return {
                "ok": True,
                "task": asdict(task),
                "status": "dry_run",
                "message": "Dry-run uniquement (aucun transfert effectif)",
                "estimate": estimate,
                "verification": {"ok": True, "detail": "not required in dry-run"},
            }

        if task.direction == "host_to_device":
            source_path = Path(task.source)
            if not source_path.exists():
                return {
                    "ok": False,
                    "task": asdict(task),
                    "status": "error",
                    "message": f"Source locale introuvable: {source_path}",
                    "estimate": estimate,
                }
            result = self.adb.run(["push", str(source_path), task.destination], serial=task.serial, timeout=900)
            verify = self._verify_remote_path(task.serial, task.destination)
        else:
            dest_path = Path(task.destination)
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            result = self.adb.run(["pull", task.source, str(dest_path)], serial=task.serial, timeout=900)
            verify = self._verify_local_path(dest_path)

        ok = bool(result.ok) and bool(verify.get("ok", False))
        status = "success" if ok else ("partial" if result.ok else "error")
        message = result.stdout or result.stderr or "(aucune sortie)"
        return {
            "ok": ok,
            "task": asdict(task),
            "status": status,
            "message": message,
            "estimate": estimate,
            "verification": verify,
            "returncode": result.returncode,
        }

    def _verify_remote_path(self, serial: str, path: str) -> dict[str, Any]:
        res = self.adb.run(["shell", "ls", "-ld", path], serial=serial, timeout=10)
        return {"ok": res.ok, "detail": res.stdout or res.stderr}

    def _verify_local_path(self, path: Path) -> dict[str, Any]:
        if path.exists():
            return {"ok": True, "detail": f"exists ({path})"}
        # pull directory may create nested leaf in destination parent.
        parent = path.parent
        if parent.exists() and any(parent.iterdir()):
            return {"ok": True, "detail": f"parent populated ({parent})"}
        return {"ok": False, "detail": f"destination not found ({path})"}

    def _local_size(self, source: Path) -> tuple[int, int]:
        if source.is_file():
            return (source.stat().st_size, 1)
        total = 0
        files = 0
        for root, _dirs, names in os.walk(source):
            root_path = Path(root)
            for name in names:
                p = root_path / name
                try:
                    total += p.stat().st_size
                    files += 1
                except OSError:
                    continue
        return (total, files)

    def _parse_du_kb(self, text: str) -> int:
        line = text.splitlines()[0].strip() if text.strip() else ""
        parts = re.split(r"\s+", line)
        if not parts:
            return 0
        try:
            return int(parts[0])
        except ValueError:
            return 0

    def _parse_int(self, text: str) -> int:
        m = re.search(r"(\d+)", text or "")
        return int(m.group(1)) if m else 0

    def _fmt_bytes(self, value: int) -> str:
        units = ["B", "KB", "MB", "GB", "TB"]
        v = float(max(0, value))
        for unit in units:
            if v < 1024 or unit == units[-1]:
                return f"{v:.1f} {unit}" if unit != "B" else f"{int(v)} {unit}"
            v /= 1024
        return f"{int(value)} B"
