from __future__ import annotations

from PySide6.QtCore import QPropertyAnimation, Qt, QTimer
from PySide6.QtWidgets import QLabel, QWidget


class Toast(QLabel):
    def __init__(self, parent: QWidget, text: str, timeout_ms: int = 2500) -> None:
        super().__init__(text, parent)
        self.setWindowFlags(Qt.ToolTip)
        self.setStyleSheet(
            "background:#0f172a; color:#e2e8f0; border:1px solid #334155; border-radius:8px; padding:8px 12px;"
        )
        self.adjustSize()
        self.move(
            max(10, parent.width() - self.width() - 20),
            max(10, parent.height() - self.height() - 40),
        )
        self.setWindowOpacity(0.95)
        self.show()
        QTimer.singleShot(timeout_ms, self.fade_out)

    def fade_out(self) -> None:
        self.anim = QPropertyAnimation(self, b"windowOpacity")
        self.anim.setDuration(400)
        self.anim.setStartValue(0.95)
        self.anim.setEndValue(0.0)
        self.anim.finished.connect(self.close)
        self.anim.start()

