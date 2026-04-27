from __future__ import annotations

import unittest

from core.commands import COMMAND_CATALOG, all_commands


class CommandsTests(unittest.TestCase):
    def test_catalog_has_text_like_categories(self) -> None:
        labels = {items[0].category.lower() for items in COMMAND_CATALOG.values() if items}
        self.assertIn("connexion", labels)
        self.assertIn("applications", labels)
        self.assertIn("système", labels)

    def test_all_commands_not_empty(self) -> None:
        self.assertGreater(len(all_commands()), 0)

    def test_known_command_present(self) -> None:
        commands = {cmd.command for cmd in all_commands()}
        self.assertIn("devices", commands)
        self.assertIn("shell pm list packages -3", commands)


if __name__ == "__main__":
    unittest.main()
