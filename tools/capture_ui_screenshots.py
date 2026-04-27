from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from core.utils import ConfigManager
from gui.main_window import MainWindow


def main() -> int:
    base_dir = Path(__file__).resolve().parents[1]
    out_dir = base_dir / "docs" / "screenshots"
    out_dir.mkdir(parents=True, exist_ok=True)

    app = QApplication([])
    config = ConfigManager(base_dir / "config" / "settings.json")
    window = MainWindow(base_dir=base_dir, config=config)
    window.resize(1580, 980)
    window.show()

    shots: list[tuple[str, int]] = [
        ("dashboard.png", 0),
        ("files.png", 1),
        ("applications.png", 2),
        ("system.png", 3),
        ("debug.png", 5),
        ("captures.png", 7),
    ]

    def grab_next(index: int = 0) -> None:
        if index >= len(shots):
            window.close()
            app.quit()
            return

        name, tab_idx = shots[index]
        window.tabs.setCurrentIndex(tab_idx)
        app.processEvents()
        window.grab().save(str(out_dir / name))
        QTimer.singleShot(180, lambda: grab_next(index + 1))

    QTimer.singleShot(500, lambda: grab_next(0))
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
