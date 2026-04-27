from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass
from logging.handlers import RotatingFileHandler
from pathlib import Path
from threading import Lock
from typing import Any


@dataclass(slots=True)
class DeviceInfo:
    serial: str
    state: str
    model: str = "unknown"
    transport: str = "usb"
    android_version: str = "unknown"
    root: bool = False


@dataclass(slots=True)
class CommandResult:
    ok: bool
    command: list[str]
    stdout: str
    stderr: str
    returncode: int


class ConfigManager:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._data: dict[str, Any] = {}
        self.load()

    def load(self) -> None:
        if self.path.exists():
            self._data = json.loads(self.path.read_text(encoding="utf-8"))
        else:
            self._data = {}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._data, indent=2, ensure_ascii=False), encoding="utf-8")

    def get(self, dotted_key: str, default: Any = None) -> Any:
        node: Any = self._data
        for key in dotted_key.split("."):
            if not isinstance(node, dict) or key not in node:
                return default
            node = node[key]
        return node

    def set(self, dotted_key: str, value: Any) -> None:
        keys = dotted_key.split(".")
        node = self._data
        for key in keys[:-1]:
            node = node.setdefault(key, {})
        node[keys[-1]] = value


class HistoryDB:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._setup()

    def _setup(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS device_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    serial TEXT NOT NULL,
                    model TEXT,
                    event TEXT NOT NULL,
                    ts DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS command_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    serial TEXT,
                    command TEXT NOT NULL,
                    ok INTEGER NOT NULL,
                    stdout TEXT,
                    stderr TEXT,
                    ts DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.commit()

    def add_device_event(self, serial: str, model: str, event: str) -> None:
        with self._lock, sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO device_history(serial, model, event) VALUES (?, ?, ?)",
                (serial, model, event),
            )
            conn.commit()

    def add_command_event(self, serial: str | None, command: str, ok: bool, stdout: str, stderr: str) -> None:
        with self._lock, sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO command_history(serial, command, ok, stdout, stderr) VALUES (?, ?, ?, ?, ?)",
                (serial, command, 1 if ok else 0, stdout[:4000], stderr[:4000]),
            )
            conn.commit()

    def recent_device_history(self, limit: int = 50) -> list[tuple[Any, ...]]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT serial, model, event, ts FROM device_history ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return rows


def setup_logging(base_dir: Path, config: ConfigManager) -> None:
    level_name = str(config.get("logging.level", "INFO")).upper()
    level = getattr(logging, level_name, logging.INFO)
    file_name = str(config.get("logging.file", "adb_manager.log"))
    max_bytes = int(config.get("logging.max_bytes", 1024 * 1024))
    backup_count = int(config.get("logging.backup_count", 3))
    log_file = base_dir / file_name

    handlers: list[logging.Handler] = [
        RotatingFileHandler(log_file, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"),
        logging.StreamHandler(),
    ]
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        handlers=handlers,
    )

