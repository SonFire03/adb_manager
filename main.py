from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from core.utils import ConfigManager, setup_logging
from gui.main_window import MainWindow


def main() -> int:
    base_dir = Path(__file__).resolve().parent
    config = ConfigManager(base_dir / "config" / "settings.json")
    setup_logging(base_dir, config)

    app = QApplication(sys.argv)
    app.setApplicationName(config.get("app.name", "ADB Manager Pro"))

    window = MainWindow(base_dir=base_dir, config=config)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
