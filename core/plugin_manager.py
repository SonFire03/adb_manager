from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType


class PluginManager:
    def __init__(self, plugin_dir: Path) -> None:
        self.plugin_dir = plugin_dir
        self.plugin_dir.mkdir(parents=True, exist_ok=True)

    def discover(self) -> list[Path]:
        return sorted(self.plugin_dir.glob("*.py"))

    def load(self, plugin_file: Path) -> ModuleType:
        spec = importlib.util.spec_from_file_location(plugin_file.stem, plugin_file)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Impossible de charger {plugin_file}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

