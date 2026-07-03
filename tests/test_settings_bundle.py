from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.utils import ConfigManager
from modules.settings_bundle import export_settings_bundle, import_settings_bundle


class SettingsBundleTests(unittest.TestCase):
    def test_bundle_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle_path = Path(tmp) / "adb_manager_bundle.zip"
            settings = {
                "app": {"theme": "light", "language": "en"},
                "ui": {"batch_workers": 4, "sidebar_collapsed": True},
                "profiles": {"devices": [{"profile_id": "p1", "alias": "Lab"}]},
            }
            commands = {
                "favorites": [{"name": "Reboot", "command": "reboot"}],
                "custom": [],
            }

            export_settings_bundle(bundle_path, settings, commands)
            payload = import_settings_bundle(bundle_path)

            self.assertEqual(payload["settings"], settings)
            self.assertEqual(payload["commands"], commands)
            self.assertIn("generated_at", payload["manifest"])

    def test_config_manager_replace_and_copy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg = ConfigManager(Path(tmp) / "settings.json")
            cfg.set("app.theme", "dark")
            copied = cfg.to_dict()
            copied["app"]["theme"] = "light"

            self.assertEqual(cfg.get("app.theme"), "dark")

            cfg.replace({"app": {"theme": "light"}})
            self.assertEqual(cfg.get("app.theme"), "light")


if __name__ == "__main__":
    unittest.main()
