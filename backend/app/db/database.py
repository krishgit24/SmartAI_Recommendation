"""SQLite persistence (Python standard library only).

Tables
- recommendations : one row per decision, with request, response and agent reasoning steps
- audit_events    : append-only event log (decisions, kill-switch changes, errors)
- settings        : key/value store (kill switch state)
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS recommendations (
    id                    TEXT PRIMARY KEY,
    transaction_id        TEXT NOT NULL,
    retry_count           INTEGER NOT NULL,
    request_hash          TEXT NOT NULL,
    correlation_id        TEXT,
    failure_code          TEXT,
    recommendation        TEXT NOT NULL,
    confidence_score      REAL,
    human_review_required INTEGER NOT NULL,
    decided_by            TEXT,
    rule_id               TEXT,
    http_status           INTEGER NOT NULL,
    model_used            TEXT,
    request_json          TEXT NOT NULL,
    response_json         TEXT NOT NULL,
    reasoning_json        TEXT NOT NULL,
    tool_logs_json        TEXT NOT NULL,
    latency_ms            INTEGER,
    created_at            TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_rec_txn_retry ON recommendations(transaction_id, retry_count, request_hash);
CREATE INDEX IF NOT EXISTS idx_rec_txn ON recommendations(transaction_id);
CREATE INDEX IF NOT EXISTS idx_rec_created ON recommendations(created_at);

CREATE TABLE IF NOT EXISTS audit_events (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    transaction_id TEXT,
    correlation_id TEXT,
    event_type     TEXT NOT NULL,
    detail_json    TEXT NOT NULL,
    created_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_txn ON audit_events(transaction_id);

CREATE TABLE IF NOT EXISTS settings (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Database:
    def __init__(self, path: str):
        self.path = path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    # ------------------------------------------------------------ settings
    def get_setting(self, key: str) -> Optional[dict[str, Any]]:
        row = self._conn.execute("SELECT value, updated_at FROM settings WHERE key=?", (key,)).fetchone()
        if not row:
            return None
        return {"value": json.loads(row["value"]), "updated_at": row["updated_at"]}

    def set_setting(self, key: str, value: Any) -> str:
        now = utcnow().isoformat()
        with self._lock:
            self._conn.execute(
                "INSERT INTO settings(key, value, updated_at) VALUES(?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                (key, json.dumps(value), now),
            )
            self._conn.commit()
        return now

    # ------------------------------------------------------------ audit
    def add_audit(self, event_type: str, detail: dict[str, Any], transaction_id: str | None = None,
                  correlation_id: str | None = None) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO audit_events(transaction_id, correlation_id, event_type, detail_json, created_at) "
                "VALUES(?,?,?,?,?)",
                (transaction_id, correlation_id, event_type, json.dumps(detail, default=str), utcnow().isoformat()),
            )
            self._conn.commit()

    def audit_for(self, transaction_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM audit_events WHERE transaction_id=? ORDER BY id", (transaction_id,)
        ).fetchall()
        return [
            {
                "id": r["id"],
                "transaction_id": r["transaction_id"],
                "correlation_id": r["correlation_id"],
                "event_type": r["event_type"],
                "detail": json.loads(r["detail_json"]),
                "created_at": r["created_at"],
            }
            for r in rows
        ]

    # ------------------------------------------------------------ recommendations
    def find_recommendation(self, transaction_id: str, retry_count: int,
                            request_hash: Optional[str] = None) -> Optional[sqlite3.Row]:
        sql = "SELECT * FROM recommendations WHERE transaction_id=? AND retry_count=?"
        args: tuple = (transaction_id, retry_count)
        if request_hash is not None:
            sql += " AND request_hash=?"
            args += (request_hash,)
        return self._conn.execute(sql + " ORDER BY created_at DESC LIMIT 1", args).fetchone()

    def max_retry_seen(self, transaction_id: str) -> Optional[int]:
        row = self._conn.execute(
            "SELECT MAX(retry_count) AS m FROM recommendations WHERE transaction_id=?", (transaction_id,)
        ).fetchone()
        return row["m"] if row and row["m"] is not None else None

    def latest_recommendation(self, transaction_id: str) -> Optional[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM recommendations WHERE transaction_id=? ORDER BY created_at DESC, retry_count DESC LIMIT 1",
            (transaction_id,),
        ).fetchone()

    def insert_recommendation(self, row: dict[str, Any]) -> None:
        cols = ",".join(row.keys())
        marks = ",".join("?" for _ in row)
        with self._lock:
            self._conn.execute(f"INSERT INTO recommendations({cols}) VALUES({marks})", tuple(row.values()))
            self._conn.commit()

    def recent(self, limit: int = 50) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM recommendations ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()

    def all_rows(self, since_iso: str | None = None) -> list[sqlite3.Row]:
        if since_iso:
            return self._conn.execute(
                "SELECT * FROM recommendations WHERE created_at >= ? ORDER BY created_at", (since_iso,)
            ).fetchall()
        return self._conn.execute("SELECT * FROM recommendations ORDER BY created_at").fetchall()

    def close(self) -> None:
        self._conn.close()
