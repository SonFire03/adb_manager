from __future__ import annotations

import subprocess
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from core.adb_manager import ADBManager
from core.commands import (
    _auto_description,
    _normalize_external_command,
    _parse_reference_line,
    load_command_catalog,
)
from core.utils import ConfigManager, HistoryDB


class ADBManagerRuntimeTests(unittest.TestCase):
    def _make_adb(self) -> ADBManager:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name)
        cfg_path = base / "settings.json"
        cfg_path.write_text(
            '{"app":{"safe_mode":false},"adb":{"binary":"adb","default_timeout":1}}',
            encoding="utf-8",
        )
        cfg = ConfigManager(cfg_path)
        db = HistoryDB(base / "history.db")
        return ADBManager(cfg, db)

    def test_run_timeout_result(self) -> None:
        adb = self._make_adb()
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("adb", 1)):
            res = adb.run(["shell", "echo", "ok"], serial="ABC", timeout=1)
        self.assertFalse(res.ok)
        self.assertEqual(res.returncode, 124)
        self.assertIn("Timeout", res.stderr)

    def test_run_file_not_found_result(self) -> None:
        adb = self._make_adb()
        with patch("subprocess.run", side_effect=FileNotFoundError()):
            res = adb.run("devices -l")
        self.assertFalse(res.ok)
        self.assertEqual(res.returncode, 127)
        self.assertIn("introuvable", res.stderr.lower())

    def test_run_async_callback(self) -> None:
        adb = self._make_adb()

        def fake_run(*_args, **_kwargs):  # noqa: ANN002, ANN003
            return types.SimpleNamespace(returncode=0, stdout="ok", stderr="")

        got: list[str] = []
        with patch("subprocess.run", side_effect=fake_run):
            fut = adb.run_async(["shell", "echo", "ok"], callback=lambda r: got.append(r.stdout))
            res = fut.result(timeout=3)
        self.assertTrue(res.ok)
        self.assertEqual(got, ["ok"])
        adb.shutdown()


class CommandsParserTests(unittest.TestCase):
    def test_normalize_external_command_cases(self) -> None:
        self.assertEqual(
            _normalize_external_command("adb shell ls -la /sdcard"),
            "shell ls -la /sdcard",
        )
        self.assertIsNone(_normalize_external_command("echo hello"))
        self.assertIsNone(_normalize_external_command("adb shell a && adb shell b"))
        self.assertEqual(
            _normalize_external_command("adb shell ls /sdcard | wc -l"),
            'shell sh -c "ls /sdcard | wc -l"',
        )

    def test_parse_reference_line_and_auto_description(self) -> None:
        line = "Lister | adb shell pm list packages -3 | Applications | Non | N/A"
        parsed = _parse_reference_line(line)
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed.category, "Applications")
        self.assertIn("packages", parsed.description.lower())
        self.assertEqual(parsed.placeholders, ())
        self.assertIn("shell Android", _auto_description("shell id", "Ops"))

    def test_load_command_catalog_external_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ref = Path(tmp) / "adb_commands_complete.txt"
            ref.write_text(
                "NOM | COMMANDE | CATÉGORIE | ROOT_REQUIS | DESCRIPTION\n"
                "Ping | adb shell echo ok | Tests | Non | -\n",
                encoding="utf-8",
            )
            cat = load_command_catalog(ref)
            self.assertIn("tests", cat)
            self.assertGreaterEqual(len(cat["tests"]), 1)


if __name__ == "__main__":
    unittest.main()
