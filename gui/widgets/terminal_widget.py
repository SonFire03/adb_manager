from __future__ import annotations

from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QCompleter, QHBoxLayout, QLineEdit, QPushButton, QTextEdit, QVBoxLayout, QWidget


class TerminalWidget(QWidget):
    command_submitted = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.output = QTextEdit()
        self.output.setReadOnly(True)
        self.input = QLineEdit()
        self.input.setPlaceholderText("Commande ADB (ex: shell getprop)")
        self.run_btn = QPushButton("Executer")
        self._completer = QCompleter()
        self._completer.setCaseSensitivity(Qt.CaseInsensitive)
        self._completer.setCompletionMode(QCompleter.PopupCompletion)
        self._model = QStandardItemModel(self)
        self._completer.setModel(self._model)
        self.input.setCompleter(self._completer)

        row = QHBoxLayout()
        row.addWidget(self.input)
        row.addWidget(self.run_btn)

        layout = QVBoxLayout(self)
        layout.addWidget(self.output)
        layout.addLayout(row)

        self.input.returnPressed.connect(self._submit)
        self.run_btn.clicked.connect(self._submit)

    def _submit(self) -> None:
        cmd = self.input.text().strip()
        if not cmd:
            return
        self.command_submitted.emit(cmd)
        self.input.clear()

    def append_line(self, text: str) -> None:
        self.output.append(text)

    def set_suggestions(self, commands: list[str]) -> None:
        self._model.clear()
        for cmd in sorted(set(commands)):
            self._model.appendRow(QStandardItem(cmd))
