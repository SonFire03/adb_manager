from __future__ import annotations

import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class SupportBundleModule:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir

    def create_bundle(
        self,
        *,
        bundle_name: str,
        serial: str,
        include: dict[str, bool],
        data: dict[str, Any],
        output_dir: Path,
    ) -> dict[str, Any]:
        output_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        zip_path = output_dir / f"{bundle_name}_{serial}_{stamp}.zip"
        manifest: dict[str, Any] = {
            "bundle_name": bundle_name,
            "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "serial": serial,
            "include": include,
            "files": [],
        }
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            if include.get("device_inspector"):
                self._write_json(zf, "device/inspector.json", data.get("device_inspector", {}))
                manifest["files"].append("device/inspector.json")
            if include.get("device_health"):
                self._write_json(zf, "health/device_health.json", data.get("device_health", {}))
                manifest["files"].append("health/device_health.json")
            if include.get("audit_session"):
                self._write_json(zf, "audit/session.json", data.get("audit_session", {}))
                manifest["files"].append("audit/session.json")
            if include.get("snapshot_diff"):
                self._write_json(zf, "snapshot/diff.json", data.get("snapshot_diff", {}))
                manifest["files"].append("snapshot/diff.json")
            if include.get("app_risk_summary"):
                self._write_json(zf, "apps/risk_summary.json", data.get("app_risk_summary", {}))
                manifest["files"].append("apps/risk_summary.json")
            if include.get("health_timeline"):
                self._write_json(zf, "health/timeline.json", data.get("health_timeline", {}))
                manifest["files"].append("health/timeline.json")
            if include.get("captures"):
                captures = data.get("captures", [])
                captures = captures if isinstance(captures, list) else []
                for p in captures[:50]:
                    src = Path(str(p))
                    if src.exists() and src.is_file():
                        arc = f"captures/{src.name}"
                        zf.write(src, arc)
                        manifest["files"].append(arc)
            if include.get("logs"):
                logs = data.get("logs", [])
                logs = logs if isinstance(logs, list) else []
                for p in logs[:10]:
                    src = Path(str(p))
                    if src.exists() and src.is_file():
                        arc = f"logs/{src.name}"
                        zf.write(src, arc)
                        manifest["files"].append(arc)
            self._write_json(zf, "manifest.json", manifest)
            self._write_html_index(zf, manifest)
        return {"ok": True, "zip_file": str(zip_path), "file_count": len(manifest["files"])}

    def _write_json(self, zf: zipfile.ZipFile, arcname: str, payload: Any) -> None:
        zf.writestr(arcname, json.dumps(payload, indent=2, ensure_ascii=False))

    def _write_html_index(self, zf: zipfile.ZipFile, manifest: dict[str, Any]) -> None:
        rows = "".join(f"<li>{self._esc(x)}</li>" for x in manifest.get("files", []))
        html = (
            "<!doctype html><html><head><meta charset='utf-8'><title>Support Bundle</title></head><body>"
            f"<h1>Support Bundle: {self._esc(manifest.get('bundle_name', 'bundle'))}</h1>"
            f"<p>Serial: {self._esc(manifest.get('serial', ''))}</p>"
            f"<p>Generated: {self._esc(manifest.get('generated_at', ''))}</p>"
            "<h2>Included files</h2><ul>"
            f"{rows}</ul></body></html>"
        )
        zf.writestr("index.html", html)

    def _esc(self, value: Any) -> str:
        text = str(value)
        return (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&#39;")
        )
