from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from core.adb_manager import ADBManager


@dataclass(slots=True)
class ScriptTask:
    name: str
    serial: str
    steps: list[str]
    created_at: str


class AutomationModule:
    def __init__(self, adb: ADBManager, storage: Path) -> None:
        self.adb = adb
        self.storage = storage
        self.storage.mkdir(parents=True, exist_ok=True)
        self.script_library = self.storage / "scripts.json"
        if not self.script_library.exists():
            self.script_library.write_text("[]", encoding="utf-8")

    def list_scripts(self) -> list[dict[str, str]]:
        return json.loads(self.script_library.read_text(encoding="utf-8"))

    def save_script(self, name: str, steps: list[str]) -> None:
        scripts = self.list_scripts()
        scripts.append({"name": name, "steps": steps, "created_at": datetime.utcnow().isoformat()})
        self.script_library.write_text(json.dumps(scripts, indent=2, ensure_ascii=False), encoding="utf-8")

    def run_script(self, serial: str, steps: list[str]) -> list[tuple[str, bool, str]]:
        results: list[tuple[str, bool, str]] = []
        for step in steps:
            res = self.adb.run(step, serial=serial, timeout=45)
            msg = res.stdout if res.ok else res.stderr
            results.append((step, res.ok, msg[:500]))
            if not res.ok:
                break
        return results

