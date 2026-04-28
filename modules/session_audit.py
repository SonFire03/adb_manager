from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any


class SessionAuditModule:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._setup()

    def _setup(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    started_at TEXT NOT NULL,
                    ended_at TEXT,
                    status TEXT NOT NULL,
                    device_count INTEGER DEFAULT 0,
                    summary_json TEXT DEFAULT '{}'
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    ts TEXT NOT NULL,
                    device_serial TEXT,
                    transport TEXT,
                    event_type TEXT NOT NULL,
                    action TEXT NOT NULL,
                    status TEXT NOT NULL,
                    message TEXT,
                    payload_json TEXT DEFAULT '{}'
                )
                """
            )
            conn.commit()

    def start_session(self, session_id: str) -> None:
        now = self._iso_now()
        with self._lock, sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO sessions(session_id, started_at, status) VALUES (?, ?, ?)",
                (session_id, now, "running"),
            )
            conn.commit()

    def end_session(self, session_id: str, summary: dict[str, Any] | None = None, status: str = "completed") -> None:
        now = self._iso_now()
        summary_text = json.dumps(summary or {}, ensure_ascii=False)
        with self._lock, sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE sessions SET ended_at=?, status=?, summary_json=? WHERE session_id=?",
                (now, status, summary_text, session_id),
            )
            conn.commit()

    def log_event(
        self,
        session_id: str,
        *,
        event_type: str,
        action: str,
        status: str,
        device_serial: str = "",
        transport: str = "",
        message: str = "",
        payload: dict[str, Any] | None = None,
    ) -> None:
        with self._lock, sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO events(session_id, ts, device_serial, transport, event_type, action, status, message, payload_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    self._iso_now(),
                    device_serial,
                    transport,
                    event_type,
                    action,
                    status,
                    message,
                    json.dumps(payload or {}, ensure_ascii=False),
                ),
            )
            conn.commit()

    def list_sessions(self, limit: int = 100) -> list[dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT session_id, started_at, ended_at, status, summary_json FROM sessions ORDER BY started_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        out: list[dict[str, Any]] = []
        for sid, started, ended, status, summary_json in rows:
            out.append(
                {
                    "session_id": sid,
                    "started_at": started,
                    "ended_at": ended or "",
                    "status": status,
                    "summary": self._parse_json(summary_json),
                }
            )
        return out

    def list_events(
        self,
        *,
        session_id: str | None = None,
        device_serial: str | None = None,
        event_type: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        where: list[str] = []
        params: list[Any] = []

        if session_id:
            where.append("session_id = ?")
            params.append(session_id)
        if device_serial:
            where.append("device_serial = ?")
            params.append(device_serial)
        if event_type:
            where.append("event_type = ?")
            params.append(event_type)
        if date_from:
            where.append("substr(ts,1,10) >= ?")
            params.append(date_from)
        if date_to:
            where.append("substr(ts,1,10) <= ?")
            params.append(date_to)

        clause = f"WHERE {' AND '.join(where)}" if where else ""
        query = (
            "SELECT id, session_id, ts, device_serial, transport, event_type, action, status, message, payload_json "
            "FROM events "
            f"{clause} "
            "ORDER BY id DESC LIMIT ?"
        )
        params.append(limit)

        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(query, params).fetchall()

        out: list[dict[str, Any]] = []
        for row in rows:
            out.append(
                {
                    "id": row[0],
                    "session_id": row[1],
                    "ts": row[2],
                    "device_serial": row[3] or "",
                    "transport": row[4] or "",
                    "event_type": row[5],
                    "action": row[6],
                    "status": row[7],
                    "message": row[8] or "",
                    "payload": self._parse_json(row[9]),
                }
            )
        return out

    def export_session_json(self, session_id: str, output_path: Path) -> dict[str, Any]:
        sessions = [s for s in self.list_sessions(limit=1000) if s.get("session_id") == session_id]
        session = sessions[0] if sessions else {"session_id": session_id}
        events = self.list_events(session_id=session_id, limit=5000)
        payload = {
            "exported_at": self._iso_now(),
            "session": session,
            "events": events,
        }
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        return payload

    def export_session_html(self, session_id: str, output_path: Path) -> None:
        payload = self.export_session_json(session_id, output_path.with_suffix(".json"))
        session = payload.get("session", {})
        events = payload.get("events", [])

        rows = []
        for event in events:
            payload_text = json.dumps(event.get("payload", {}), ensure_ascii=False)
            rows.append(
                "<tr>"
                f"<td>{self._esc(event.get('ts', ''))}</td>"
                f"<td>{self._esc(event.get('device_serial', ''))}</td>"
                f"<td>{self._esc(event.get('event_type', ''))}</td>"
                f"<td>{self._esc(event.get('action', ''))}</td>"
                f"<td>{self._esc(event.get('status', ''))}</td>"
                f"<td>{self._esc(event.get('message', ''))}</td>"
                f"<td><pre>{self._esc(payload_text)}</pre></td>"
                "</tr>"
            )

        html = f"""
<!doctype html>
<html lang=\"fr\">
<head>
  <meta charset=\"utf-8\" />
  <title>ADB Manager Pro - Session Report {self._esc(session.get('session_id', ''))}</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 20px; background: #0b1220; color: #e5e7eb; }}
    h1, h2 {{ color: #93c5fd; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
    th, td {{ border: 1px solid #1f2937; padding: 6px; vertical-align: top; }}
    th {{ background: #111827; }}
    tr:nth-child(even) {{ background: #0f172a; }}
    pre {{ margin: 0; white-space: pre-wrap; word-break: break-word; }}
    .meta {{ margin-bottom: 16px; padding: 10px; background: #111827; border: 1px solid #1f2937; }}
  </style>
</head>
<body>
  <h1>Session Report</h1>
  <div class=\"meta\">
    <div><strong>Session ID:</strong> {self._esc(session.get('session_id', ''))}</div>
    <div><strong>Started:</strong> {self._esc(session.get('started_at', ''))}</div>
    <div><strong>Ended:</strong> {self._esc(session.get('ended_at', ''))}</div>
    <div><strong>Status:</strong> {self._esc(session.get('status', ''))}</div>
  </div>
  <h2>Events ({len(events)})</h2>
  <table>
    <thead>
      <tr>
        <th>Timestamp</th>
        <th>Device</th>
        <th>Type</th>
        <th>Action</th>
        <th>Status</th>
        <th>Message</th>
        <th>Payload</th>
      </tr>
    </thead>
    <tbody>
      {''.join(rows)}
    </tbody>
  </table>
</body>
</html>
"""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(html, encoding="utf-8")

    def summarize_session(self, session_id: str) -> dict[str, Any]:
        events = self.list_events(session_id=session_id, limit=10000)
        by_type: dict[str, int] = {}
        ok = 0
        error = 0
        devices: set[str] = set()
        for event in events:
            et = str(event.get("event_type", "unknown"))
            by_type[et] = by_type.get(et, 0) + 1
            status = str(event.get("status", "")).lower()
            if status in {"ok", "success"}:
                ok += 1
            if status in {"error", "failed"}:
                error += 1
            serial = str(event.get("device_serial", "")).strip()
            if serial:
                devices.add(serial)
        return {
            "events_total": len(events),
            "events_ok": ok,
            "events_error": error,
            "device_count": len(devices),
            "devices": sorted(devices),
            "by_type": by_type,
        }

    def list_health_timeline(self, device_serial: str | None = None, limit: int = 300) -> list[dict[str, Any]]:
        events = self.list_events(
            device_serial=device_serial or None,
            event_type="system",
            limit=max(1, limit * 4),
        )
        rows: list[dict[str, Any]] = []
        for event in events:
            if str(event.get("action", "")) != "device_health_checks":
                continue
            payload = event.get("payload", {})
            payload = payload if isinstance(payload, dict) else {}
            score_raw = payload.get("score", "")
            try:
                score = int(score_raw)
            except Exception:  # noqa: BLE001
                score = -1
            rows.append(
                {
                    "timestamp": str(event.get("ts", "")),
                    "device_serial": str(event.get("device_serial", "")),
                    "score": score,
                    "status": str(payload.get("status", "")),
                    "summary": str(event.get("message", "")),
                    "payload": payload,
                }
            )
            if len(rows) >= limit:
                break
        return rows

    def _iso_now(self) -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    def _parse_json(self, text: str | None) -> dict[str, Any]:
        if not text:
            return {}
        try:
            value = json.loads(text)
            return value if isinstance(value, dict) else {"value": value}
        except Exception:  # noqa: BLE001
            return {}

    def _esc(self, value: Any) -> str:
        text = str(value)
        return (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&#39;")
        )
