from __future__ import annotations

import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


BUNDLE_SCHEMA_VERSION = 1


def _json_text(payload: Any) -> str:
    return json.dumps(payload, indent=2, ensure_ascii=False)


def _read_json_member(zf: zipfile.ZipFile, member: str) -> dict[str, Any]:
    try:
        raw = zf.read(member)
    except KeyError as exc:
        raise ValueError(f"Missing bundle member: {member}") from exc
    try:
        data = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {member}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"Bundle member {member} must contain a JSON object")
    return data


def export_settings_bundle(
    output_path: Path,
    settings: dict[str, Any],
    commands: dict[str, Any],
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema_version": BUNDLE_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "files": ["manifest.json", "settings.json", "commands.json"],
    }
    with zipfile.ZipFile(output_path, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", _json_text(manifest))
        zf.writestr("settings.json", _json_text(settings))
        zf.writestr("commands.json", _json_text(commands))


def import_settings_bundle(bundle_path: Path) -> dict[str, Any]:
    with zipfile.ZipFile(bundle_path, mode="r") as zf:
        manifest = _read_json_member(zf, "manifest.json")
        schema_version = int(manifest.get("schema_version", 0))
        if schema_version != BUNDLE_SCHEMA_VERSION:
            raise ValueError(
                f"Unsupported bundle schema version: {schema_version}"
            )
        settings = _read_json_member(zf, "settings.json")
        commands = _read_json_member(zf, "commands.json")
    return {
        "manifest": manifest,
        "settings": settings,
        "commands": commands,
    }
