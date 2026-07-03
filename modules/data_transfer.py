from __future__ import annotations

import hashlib
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
    verify_integrity: bool = True
    checksum_algorithm: str = "sha256"
    retry_count: int = 0
    retry_delay_s: float = 0.0


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
        verify_integrity: bool = True,
        checksum_algorithm: str = "sha256",
        retry_count: int = 0,
        retry_delay_s: float = 0.0,
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
            verify_integrity=verify_integrity,
            checksum_algorithm=checksum_algorithm,
            retry_count=max(0, int(retry_count)),
            retry_delay_s=max(0.0, float(retry_delay_s)),
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
                return {
                    "ok": False,
                    "error": f"Source introuvable: {src}",
                    "bytes": 0,
                    "files": 0,
                }
            size, files = self._local_size(src)
            return {
                "ok": True,
                "bytes": size,
                "files": files,
                "human": self._fmt_bytes(size),
            }

        # device_to_host
        du = self.adb.run(
            ["shell", "du", "-sk", task.source], serial=task.serial, timeout=20
        )
        if not du.ok:
            return {
                "ok": False,
                "error": du.stderr or "du failed",
                "bytes": 0,
                "files": 0,
            }
        kb = self._parse_du_kb(du.stdout)
        count = self.adb.run(
            ["shell", "find", task.source, "-type", "f", "|", "wc", "-l"],
            serial=task.serial,
            timeout=30,
        )
        file_count = self._parse_int(count.stdout) if count.ok else 0
        size_bytes = kb * 1024
        return {
            "ok": True,
            "bytes": size_bytes,
            "files": file_count,
            "human": self._fmt_bytes(size_bytes),
        }

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
                "verification": {
                    "ok": True,
                    "detail": "not required in dry-run",
                    "integrity": {
                        "requested": task.verify_integrity,
                        "checked": False,
                        "ok": True,
                        "detail": "skipped in dry-run",
                    },
                },
            }

        integrity: dict[str, Any] = {
            "requested": bool(task.verify_integrity),
            "checked": False,
            "ok": True,
            "algorithm": task.checksum_algorithm,
            "detail": "",
        }

        def _attempt_once() -> tuple[Any, dict[str, Any], dict[str, Any]]:
            if task.direction == "host_to_device":
                source_path = Path(task.source)
                if not source_path.exists():
                    return (
                        None,
                        {"ok": False, "detail": f"missing source ({source_path})"},
                        {
                            "requested": bool(task.verify_integrity),
                            "checked": False,
                            "ok": False,
                            "algorithm": task.checksum_algorithm,
                            "detail": "source missing",
                        },
                    )
                result_local = self.adb.run(
                    ["push", str(source_path), task.destination],
                    serial=task.serial,
                    timeout=900,
                )
                target_path = self._resolve_device_target(task.destination, source_path)
                verify_local = self._verify_remote_path(task.serial, target_path)
                integrity_local = integrity
                if task.verify_integrity:
                    integrity_local = self._verify_remote_integrity(
                        serial=task.serial,
                        local_source=source_path,
                        remote_target=target_path,
                        preferred_algorithm=task.checksum_algorithm,
                    )
                return result_local, verify_local, integrity_local
            dest_path = Path(task.destination)
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            result_local = self.adb.run(
                ["pull", task.source, str(dest_path)], serial=task.serial, timeout=900
            )
            target_path = self._resolve_local_target(task.source, dest_path)
            verify_local = self._verify_local_path(target_path)
            integrity_local = integrity
            if task.verify_integrity:
                integrity_local = self._verify_local_integrity(
                    serial=task.serial,
                    remote_source=task.source,
                    local_target=target_path,
                    preferred_algorithm=task.checksum_algorithm,
                )
            return result_local, verify_local, integrity_local

        result = None
        verify: dict[str, Any] = {"ok": False, "detail": "transfer not executed"}
        attempts = max(0, int(task.retry_count)) + 1
        for attempt in range(attempts):
            result, verify, integrity = _attempt_once()
            if result is None:
                break
            ok = bool(result.ok) and bool(verify.get("ok", False))
            if task.verify_integrity and integrity["checked"] and not integrity["ok"]:
                ok = False
            if ok:
                break
            if attempt < attempts - 1 and task.retry_delay_s > 0:
                import time

                time.sleep(task.retry_delay_s)

        if result is None:
            return {
                "ok": False,
                "task": asdict(task),
                "status": "error",
                "message": f"Source locale introuvable: {task.source}",
                "estimate": estimate,
                "verification": verify,
                "integrity": integrity,
                "returncode": 1,
            }

        ok = bool(result.ok) and bool(verify.get("ok", False))
        if task.verify_integrity and integrity["checked"] and not integrity["ok"]:
            ok = False
        status = "success" if ok else ("partial" if result.ok else "error")
        message = result.stdout or result.stderr or "(aucune sortie)"
        return {
            "ok": ok,
            "task": asdict(task),
            "status": status,
            "message": message,
            "estimate": estimate,
            "verification": verify,
            "integrity": integrity,
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

    def _verify_remote_integrity(
        self,
        *,
        serial: str,
        local_source: Path,
        remote_target: str,
        preferred_algorithm: str,
    ) -> dict[str, Any]:
        if not local_source.is_file():
            return {
                "requested": True,
                "checked": False,
                "ok": True,
                "algorithm": preferred_algorithm,
                "detail": "directory transfer not hashed",
            }
        local_hash = self._checksum_file(local_source, preferred_algorithm)
        remote_hash = self._remote_checksum(serial, remote_target, preferred_algorithm)
        if not local_hash["ok"] or not remote_hash["ok"]:
            return {
                "requested": True,
                "checked": False,
                "ok": True,
                "algorithm": preferred_algorithm,
                "detail": local_hash.get("detail") or remote_hash.get("detail"),
            }
        if str(local_hash.get("algorithm", "")).lower() != str(
            remote_hash.get("algorithm", "")
        ).lower():
            local_hash = self._checksum_file(
                local_source, str(remote_hash.get("algorithm", preferred_algorithm))
            )
        match = (
            str(local_hash.get("value", "")) == str(remote_hash.get("value", ""))
            and str(local_hash.get("algorithm", "")).lower()
            == str(remote_hash.get("algorithm", "")).lower()
        )
        return {
            "requested": True,
            "checked": True,
            "ok": match,
            "algorithm": str(local_hash.get("algorithm", preferred_algorithm)),
            "detail": (
                f"{local_hash.get('value', '')[:12]}... vs {remote_hash.get('value', '')[:12]}..."
                if match
                else "checksum mismatch"
            ),
        }

    def _verify_local_integrity(
        self,
        *,
        serial: str,
        remote_source: str,
        local_target: Path,
        preferred_algorithm: str,
    ) -> dict[str, Any]:
        if not local_target.is_file():
            return {
                "requested": True,
                "checked": False,
                "ok": True,
                "algorithm": preferred_algorithm,
                "detail": "directory transfer not hashed",
            }
        local_hash = self._checksum_file(local_target, preferred_algorithm)
        remote_hash = self._remote_checksum(serial, remote_source, preferred_algorithm)
        if not local_hash["ok"] or not remote_hash["ok"]:
            return {
                "requested": True,
                "checked": False,
                "ok": True,
                "algorithm": preferred_algorithm,
                "detail": local_hash.get("detail") or remote_hash.get("detail"),
            }
        if str(local_hash.get("algorithm", "")).lower() != str(
            remote_hash.get("algorithm", "")
        ).lower():
            local_hash = self._checksum_file(
                local_target, str(remote_hash.get("algorithm", preferred_algorithm))
            )
        match = (
            str(local_hash.get("value", "")) == str(remote_hash.get("value", ""))
            and str(local_hash.get("algorithm", "")).lower()
            == str(remote_hash.get("algorithm", "")).lower()
        )
        return {
            "requested": True,
            "checked": True,
            "ok": match,
            "algorithm": str(local_hash.get("algorithm", preferred_algorithm)),
            "detail": (
                f"{local_hash.get('value', '')[:12]}... vs {remote_hash.get('value', '')[:12]}..."
                if match
                else "checksum mismatch"
            ),
        }

    def _checksum_file(self, path: Path, preferred_algorithm: str) -> dict[str, Any]:
        algorithm = preferred_algorithm.lower()
        if algorithm not in {"sha256", "md5"}:
            algorithm = "sha256"
        try:
            hasher = hashlib.new(algorithm)
        except ValueError:
            algorithm = "sha256"
            hasher = hashlib.sha256()
        try:
            with path.open("rb") as fh:
                for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                    hasher.update(chunk)
        except OSError as exc:
            return {"ok": False, "detail": str(exc), "algorithm": algorithm}
        return {"ok": True, "value": hasher.hexdigest(), "algorithm": algorithm}

    def _remote_checksum(
        self, serial: str, path: str, preferred_algorithm: str
    ) -> dict[str, Any]:
        commands = []
        alg = preferred_algorithm.lower()
        if alg == "md5":
            commands = ["md5sum", "sha256sum"]
        else:
            commands = ["sha256sum", "md5sum"]
        for cmd in commands:
            res = self.adb.run(["shell", cmd, path], serial=serial, timeout=20)
            if not res.ok or not res.stdout.strip():
                continue
            token = res.stdout.strip().split()[0]
            if re.fullmatch(r"[0-9a-fA-F]+", token or ""):
                return {"ok": True, "value": token.lower(), "algorithm": cmd.removesuffix("sum")}
        return {
            "ok": False,
            "detail": f"checksum unavailable for {path}",
            "algorithm": preferred_algorithm,
        }

    def _resolve_device_target(self, destination: str, source_path: Path) -> str:
        dest = destination.rstrip("/")
        if source_path.is_dir():
            return f"{dest}/{source_path.name}"
        if Path(dest).suffix:
            return dest
        return f"{dest}/{source_path.name}"

    def _resolve_local_target(self, source: str, destination: Path) -> Path:
        if destination.exists() and destination.is_dir():
            return destination / Path(source).name
        if destination.suffix:
            return destination
        return destination / Path(source).name

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
        if not line:
            return 0
        parts = re.split(r"\s+", line)
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
        return "0 B"  # pragma: no cover
