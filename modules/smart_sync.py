from __future__ import annotations

import os
import re
from dataclasses import dataclass
from dataclasses import asdict
from pathlib import Path
from typing import Any

from core.adb_manager import ADBManager


@dataclass(slots=True)
class SyncItem:
    rel_path: str
    source: str
    destination: str
    src_size: int
    dst_size: int
    src_mtime: int
    dst_mtime: int
    decision: str
    reason: str


class SmartSyncModule:
    def __init__(self, adb: ADBManager) -> None:
        self.adb = adb

    def preview(
        self,
        *,
        serial: str,
        direction: str,
        source: str,
        destination: str,
        mode: str,
    ) -> dict[str, Any]:
        src_map = self._scan(serial=serial, direction=direction, root=source, side="src")
        if not src_map.get("ok"):
            return src_map
        dst_map = self._scan(serial=serial, direction=direction, root=destination, side="dst")
        if not dst_map.get("ok"):
            return dst_map
        src_files = src_map.get("files", {})
        dst_files = dst_map.get("files", {})
        plan: list[SyncItem] = []
        all_paths = sorted(set(src_files.keys()) | set(dst_files.keys()))
        for rel in all_paths:
            s = src_files.get(rel)
            d = dst_files.get(rel)
            item = self._decide(rel=rel, src=s, dst=d, mode=mode, direction=direction, source_root=source, dest_root=destination)
            if item is not None:
                plan.append(item)
        return {
            "ok": True,
            "mode": mode,
            "direction": direction,
            "source": source,
            "destination": destination,
            "summary": {
                "total_src": len(src_files),
                "total_dst": len(dst_files),
                "to_copy": sum(1 for i in plan if i.decision in {"copy", "update"}),
                "conflicts": sum(1 for i in plan if i.decision == "conflict"),
                "skipped": sum(1 for i in plan if i.decision == "skip"),
            },
            "items": [asdict(i) for i in plan],
        }

    def execute(self, *, serial: str, preview: dict[str, Any]) -> dict[str, Any]:
        if not preview.get("ok"):
            return {"ok": False, "error": "preview invalid", "executed": 0}
        direction = str(preview.get("direction", "device_to_host"))
        items = preview.get("items", [])
        done = 0
        errors: list[str] = []
        for raw in items:
            item = raw if isinstance(raw, dict) else {}
            if str(item.get("decision", "")) not in {"copy", "update"}:
                continue
            src = str(item.get("source", ""))
            dst = str(item.get("destination", ""))
            if direction == "device_to_host":
                Path(dst).parent.mkdir(parents=True, exist_ok=True)
                res = self.adb.run(["pull", src, dst], serial=serial, timeout=600)
            else:
                res = self.adb.run(["push", src, dst], serial=serial, timeout=600)
            if res.ok:
                done += 1
            else:
                errors.append(f"{src} -> {dst}: {res.stderr or res.stdout}")
        return {"ok": len(errors) == 0, "executed": done, "errors": errors}

    def _decide(
        self,
        *,
        rel: str,
        src: dict[str, Any] | None,
        dst: dict[str, Any] | None,
        mode: str,
        direction: str,
        source_root: str,
        dest_root: str,
    ) -> SyncItem | None:
        src_exists = src is not None
        dst_exists = dst is not None
        src_size = int(src.get("size", 0)) if src else 0
        dst_size = int(dst.get("size", 0)) if dst else 0
        src_mtime = int(src.get("mtime", 0)) if src else 0
        dst_mtime = int(dst.get("mtime", 0)) if dst else 0
        src_abs = self._join(source_root, rel)
        dst_abs = self._join(dest_root, rel)
        if not src_exists and not dst_exists:
            return None
        if mode == "copy_missing_only":
            if src_exists and not dst_exists:
                return SyncItem(rel, src_abs, dst_abs, src_size, dst_size, src_mtime, dst_mtime, "copy", "missing in destination")
            return SyncItem(rel, src_abs, dst_abs, src_size, dst_size, src_mtime, dst_mtime, "skip", "already exists")
        if mode == "update_newer_only":
            if src_exists and not dst_exists:
                return SyncItem(rel, src_abs, dst_abs, src_size, dst_size, src_mtime, dst_mtime, "copy", "missing in destination")
            if src_exists and dst_exists and src_mtime > dst_mtime:
                return SyncItem(rel, src_abs, dst_abs, src_size, dst_size, src_mtime, dst_mtime, "update", "source newer")
            return SyncItem(rel, src_abs, dst_abs, src_size, dst_size, src_mtime, dst_mtime, "skip", "destination newer/equal")
        if mode == "skip_duplicates":
            if src_exists and not dst_exists:
                return SyncItem(rel, src_abs, dst_abs, src_size, dst_size, src_mtime, dst_mtime, "copy", "missing in destination")
            if src_exists and dst_exists and src_size == dst_size and src_mtime == dst_mtime:
                return SyncItem(rel, src_abs, dst_abs, src_size, dst_size, src_mtime, dst_mtime, "skip", "duplicate")
            if src_exists and dst_exists:
                return SyncItem(rel, src_abs, dst_abs, src_size, dst_size, src_mtime, dst_mtime, "conflict", "different content")
            return None
        # mirror_selected (non-destructive in this project: no delete)
        if src_exists and not dst_exists:
            return SyncItem(rel, src_abs, dst_abs, src_size, dst_size, src_mtime, dst_mtime, "copy", "missing in destination")
        if src_exists and dst_exists and (src_size != dst_size or src_mtime != dst_mtime):
            return SyncItem(rel, src_abs, dst_abs, src_size, dst_size, src_mtime, dst_mtime, "update", "mirror update")
        return SyncItem(rel, src_abs, dst_abs, src_size, dst_size, src_mtime, dst_mtime, "skip", "already mirrored")

    def _scan(self, *, serial: str, direction: str, root: str, side: str) -> dict[str, Any]:
        try:
            if (direction == "device_to_host" and side == "src") or (direction == "host_to_device" and side == "dst"):
                return self._scan_remote(serial, root)
            return self._scan_local(root)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc), "files": {}}

    def _scan_local(self, root: str) -> dict[str, Any]:
        base = Path(root)
        if not base.exists():
            return {"ok": False, "error": f"local path not found: {root}", "files": {}}
        files: dict[str, dict[str, Any]] = {}
        for cur, _dirs, names in os.walk(base):
            curp = Path(cur)
            for name in names:
                p = curp / name
                rel = str(p.relative_to(base)).replace("\\", "/")
                st = p.stat()
                files[rel] = {"size": int(st.st_size), "mtime": int(st.st_mtime)}
        return {"ok": True, "files": files}

    def _scan_remote(self, serial: str, root: str) -> dict[str, Any]:
        cmd = f"find {self._q(root)} -type f -exec stat -c '%s|%Y|%n' {{}} \\;"
        res = self.adb.run(["shell", "sh", "-c", cmd], serial=serial, timeout=120)
        if not res.ok:
            return {"ok": False, "error": res.stderr or "remote find failed", "files": {}}
        files: dict[str, dict[str, Any]] = {}
        for line in res.stdout.splitlines():
            text = line.strip()
            m = re.match(r"(\d+)\|(\d+)\|(.+)", text)
            if not m:
                continue
            size = int(m.group(1))
            mtime = int(m.group(2))
            full = m.group(3).strip()
            rel = full[len(root):].lstrip("/") if full.startswith(root) else full.lstrip("/")
            files[rel] = {"size": size, "mtime": mtime}
        return {"ok": True, "files": files}

    def _join(self, root: str, rel: str) -> str:
        if not rel:
            return root
        if root.endswith("/"):
            return root + rel
        return root + "/" + rel

    def _q(self, text: str) -> str:
        return "'" + text.replace("'", "'\"'\"'") + "'"
