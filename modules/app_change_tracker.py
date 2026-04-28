from __future__ import annotations

from typing import Any


class AppChangeTrackerModule:
    def compare(self, older: dict[str, Any], newer: dict[str, Any]) -> dict[str, Any]:
        old_pkgs = set(self._as_list(older.get("packages_user")))
        new_pkgs = set(self._as_list(newer.get("packages_user")))
        added = sorted(new_pkgs - old_pkgs)
        removed = sorted(old_pkgs - new_pkgs)

        old_versions = self._as_dict(older.get("package_versions"))
        new_versions = self._as_dict(newer.get("package_versions"))
        old_risk = self._as_dict(older.get("package_risks"))
        new_risk = self._as_dict(newer.get("package_risks"))

        updated: list[dict[str, Any]] = []
        risk_changes: list[dict[str, Any]] = []
        for pkg in sorted(old_pkgs & new_pkgs):
            ov = str(old_versions.get(pkg, ""))
            nv = str(new_versions.get(pkg, ""))
            if ov and nv and ov != nv:
                updated.append({"package": pkg, "old_version": ov, "new_version": nv})
            orisk = str(old_risk.get(pkg, ""))
            nrisk = str(new_risk.get(pkg, ""))
            if orisk and nrisk and orisk != nrisk:
                risk_changes.append({"package": pkg, "old_risk": orisk, "new_risk": nrisk})

        return {
            "summary": {
                "added": len(added),
                "removed": len(removed),
                "updated": len(updated),
                "risk_changes": len(risk_changes),
            },
            "added": added,
            "removed": removed,
            "updated": updated,
            "risk_changes": risk_changes,
        }

    def _as_list(self, value: Any) -> list[Any]:
        return value if isinstance(value, list) else []

    def _as_dict(self, value: Any) -> dict[str, Any]:
        return value if isinstance(value, dict) else {}
