from __future__ import annotations

from PySide6.QtGui import QColor, QTextCharFormat, QTextDocument
from PySide6.QtWidgets import QPlainTextEdit


class ScriptEditor(QPlainTextEdit):
    KEYWORDS = ("shell", "pm", "am", "input", "install", "uninstall", "pull", "push", "reboot")

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setPlaceholderText("Une commande par ligne...")
        self.setTabStopDistance(24)

    def highlight_keywords(self) -> None:
        # Minimal highlighter pass; can be replaced by QSyntaxHighlighter if needed.
        doc: QTextDocument = self.document()
        cursor = self.textCursor()
        cursor.beginEditBlock()
        default = QTextCharFormat()
        default.setForeground(QColor("#d1d5db"))
        all_text = self.toPlainText()
        cursor.select(cursor.SelectionType.Document)
        cursor.setCharFormat(default)

        for keyword in self.KEYWORDS:
            start = 0
            while True:
                idx = all_text.find(keyword, start)
                if idx == -1:
                    break
                cursor.setPosition(idx)
                cursor.setPosition(idx + len(keyword), cursor.MoveMode.KeepAnchor)
                fmt = QTextCharFormat()
                fmt.setForeground(QColor("#38bdf8"))
                cursor.setCharFormat(fmt)
                start = idx + len(keyword)
        cursor.endEditBlock()

