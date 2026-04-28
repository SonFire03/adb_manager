from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any


class NotificationCenterModule:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._setup()

    def _setup(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS notifications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    category TEXT NOT NULL,
                    title TEXT NOT NULL,
                    message TEXT NOT NULL,
                    device_serial TEXT DEFAULT '',
                    link_type TEXT DEFAULT '',
                    link_value TEXT DEFAULT '',
                    is_read INTEGER DEFAULT 0
                )
                """
            )
            conn.commit()

    def add(
        self,
        *,
        severity: str,
        category: str,
        title: str,
        message: str,
        device_serial: str = "",
        link_type: str = "",
        link_value: str = "",
    ) -> int:
        with self._lock, sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                """
                INSERT INTO notifications(created_at, severity, category, title, message, device_serial, link_type, link_value, is_read)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)
                """,
                (
                    self._iso_now(),
                    severity.strip().lower() or "info",
                    category.strip().lower() or "general",
                    title.strip(),
                    message.strip(),
                    device_serial.strip(),
                    link_type.strip(),
                    link_value.strip(),
                ),
            )
            conn.commit()
            return int(cur.lastrowid or 0)

    def list(
        self,
        *,
        severity: str = "",
        device_serial: str = "",
        unread_only: bool = False,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        where: list[str] = []
        params: list[Any] = []
        if severity:
            where.append("severity = ?")
            params.append(severity.strip().lower())
        if device_serial:
            where.append("device_serial = ?")
            params.append(device_serial.strip())
        if unread_only:
            where.append("is_read = 0")
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        query = (
            "SELECT id, created_at, severity, category, title, message, device_serial, link_type, link_value, is_read "
            f"FROM notifications {clause} ORDER BY id DESC LIMIT ?"
        )
        params.append(limit)
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(query, params).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            out.append(
                {
                    "id": int(row[0]),
                    "created_at": str(row[1]),
                    "severity": str(row[2]),
                    "category": str(row[3]),
                    "title": str(row[4]),
                    "message": str(row[5]),
                    "device_serial": str(row[6] or ""),
                    "link_type": str(row[7] or ""),
                    "link_value": str(row[8] or ""),
                    "is_read": bool(int(row[9] or 0)),
                }
            )
        return out

    def unread_count(self) -> int:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute("SELECT COUNT(*) FROM notifications WHERE is_read = 0").fetchone()
        return int(row[0]) if row else 0

    def mark_read(self, notification_id: int) -> None:
        with self._lock, sqlite3.connect(self.db_path) as conn:
            conn.execute("UPDATE notifications SET is_read = 1 WHERE id = ?", (notification_id,))
            conn.commit()

    def mark_all_read(self) -> None:
        with self._lock, sqlite3.connect(self.db_path) as conn:
            conn.execute("UPDATE notifications SET is_read = 1 WHERE is_read = 0")
            conn.commit()

    def delete(self, notification_id: int) -> None:
        with self._lock, sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM notifications WHERE id = ?", (notification_id,))
            conn.commit()

    def clear(self) -> None:
        with self._lock, sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM notifications")
            conn.commit()

    def _iso_now(self) -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
