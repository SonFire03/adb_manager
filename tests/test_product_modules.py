from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.utils import ConfigManager
from modules.app_manager import AppManagerModule
from modules.device_profiles import DeviceProfile, DeviceProfilesModule


class _DummyADB:
    pass


class AppRiskTests(unittest.TestCase):
    def setUp(self) -> None:
        self.mod = AppManagerModule(_DummyADB())  # type: ignore[arg-type]

    def test_risk_low_for_small_permissions(self) -> None:
        risk, score = self.mod.compute_risk_level(
            permissions=["android.permission.INTERNET"],
            app_type="user",
            code_path="/data/app/com.demo/base.apk",
        )
        self.assertEqual(risk, "LOW")
        self.assertGreaterEqual(score, 0)

    def test_risk_high_for_sensitive_and_many_permissions(self) -> None:
        perms = [
            "android.permission.INTERNET",
            "android.permission.READ_SMS",
            "android.permission.SEND_SMS",
            "android.permission.RECORD_AUDIO",
            "android.permission.CAMERA",
            "android.permission.ACCESS_FINE_LOCATION",
            "android.permission.READ_CONTACTS",
            "android.permission.READ_CALL_LOG",
            "android.permission.WRITE_SETTINGS",
            "android.permission.PACKAGE_USAGE_STATS",
        ] + [f"android.permission.DUMMY_{i}" for i in range(20)]
        risk, score = self.mod.compute_risk_level(
            permissions=perms,
            app_type="system",
            code_path="/data/app/~~something/base.apk",
        )
        self.assertEqual(risk, "HIGH")
        self.assertGreaterEqual(score, 8)


class DeviceProfilesTests(unittest.TestCase):
    def test_profile_roundtrip_and_delete(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg = ConfigManager(Path(tmp) / "settings.json")
            mod = DeviceProfilesModule(cfg)

            created = mod.save_profile(
                DeviceProfile(
                    profile_id="",
                    alias="Pixel USB",
                    serial="ABC123",
                    wifi_endpoint="",
                    favorite_local_path="/tmp",
                    favorite_remote_path="/sdcard",
                    tags=["lab"],
                )
            )
            self.assertTrue(created.profile_id)

            all_profiles = mod.list_profiles()
            self.assertEqual(len(all_profiles), 1)
            self.assertEqual(all_profiles[0].alias, "Pixel USB")

            match = mod.find_match("ABC123")
            self.assertIsNotNone(match)
            self.assertEqual(match.alias, "Pixel USB")  # type: ignore[union-attr]

            mod.delete_profile(created.profile_id)
            self.assertEqual(mod.list_profiles(), [])


if __name__ == "__main__":
    unittest.main()
