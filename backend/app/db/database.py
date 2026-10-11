"""SQLite persistence for the Smart Recommendation gateway."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
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

CREATE INDEX IF NOT EXISTS idx_rec_txn_retry
    ON recommendations(transaction_id, retry_count, request_hash);

CREATE INDEX IF NOT EXISTS idx_rec_txn
    ON recommendations(transaction_id);

CREATE INDEX IF NOT EXISTS idx_rec_created
    ON recommendations(created_at);

CREATE TABLE IF NOT EXISTS audit_events (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    transaction_id TEXT,
    correlation_id TEXT,
    event_type     TEXT NOT NULL,
    detail_json    TEXT NOT NULL,
    created_at     TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_audit_txn
    ON audit_events(transaction_id);

CREATE TABLE IF NOT EXISTS settings (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Database:
    """SQLite adapter matching the gateway persistence interface."""

    def __init__(self, path: str):
        self.path = path
        self._lock = threading.RLock()

        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)

        self._conn = sqlite3.connect(
            path,
            timeout=30,
            check_same_thread=False,
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")

        with self._lock:
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    def get_setting(self, key: str) -> Optional[dict[str, Any]]:
        with self._lock:
            row = self._conn.execute(
                "SELECT value, updated_at FROM settings WHERE key = ?",
                (key,),
            ).fetchone()

        if row is None:
            return None

        return {
            "value": json.loads(row["value"]),
            "updated_at": row["updated_at"],
        }

    def set_setting(self, key: str, value: Any) -> str:
        now = utcnow().isoformat()

        with self._lock:
            self._conn.execute(
                """
                INSERT INTO settings(key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at
                """,
                (key, json.dumps(value, default=str), now),
            )
            self._conn.commit()

        return now

    def add_audit(
        self,
        event_type: str,
        detail: dict[str, Any],
        transaction_id: str | None = None,
        correlation_id: str | None = None,
    ) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO audit_events(
                    transaction_id, correlation_id,
                    event_type, detail_json, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    transaction_id,
                    correlation_id,
                    event_type,
                    json.dumps(detail, default=str),
                    utcnow().isoformat(),
                ),
            )
            self._conn.commit()

    def audit_for(self, transaction_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT * FROM audit_events
                WHERE transaction_id = ?
                ORDER BY id
                """,
                (transaction_id,),
            ).fetchall()

        return [
            {
                "id": row["id"],
                "transaction_id": row["transaction_id"],
                "correlation_id": row["correlation_id"],
                "event_type": row["event_type"],
                "detail": json.loads(row["detail_json"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def find_recommendation(
        self,
        transaction_id: str,
        retry_count: int,
        request_hash: Optional[str] = None,
    ) -> Optional[sqlite3.Row]:
        sql = """
            SELECT * FROM recommendations
            WHERE transaction_id = ? AND retry_count = ?
        """
        args: tuple[Any, ...] = (transaction_id, retry_count)

        if request_hash is not None:
            sql += " AND request_hash = ?"
            args += (request_hash,)

        sql += " ORDER BY created_at DESC LIMIT 1"

        with self._lock:
            return self._conn.execute(sql, args).fetchone()

    def max_retry_seen(self, transaction_id: str) -> Optional[int]:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT MAX(retry_count) AS max_retry
                FROM recommendations
                WHERE transaction_id = ?
                """,
                (transaction_id,),
            ).fetchone()

        return row["max_retry"] if row and row["max_retry"] is not None else None

    def latest_recommendation(
        self, transaction_id: str
    ) -> Optional[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(
                """
                SELECT * FROM recommendations
                WHERE transaction_id = ?
                ORDER BY created_at DESC, retry_count DESC
                LIMIT 1
                """,
                (transaction_id,),
            ).fetchone()

    def insert_recommendation(self, row: dict[str, Any]) -> None:
        if not row:
            raise ValueError("Recommendation row cannot be empty")

        columns = list(row.keys())
        if any(not column.replace("_", "").isalnum() for column in columns):
            raise ValueError("Invalid recommendation column name")

        sql = (
            f"INSERT INTO recommendations ({','.join(columns)}) "
            f"VALUES ({','.join('?' for _ in columns)})"
        )

        with self._lock:
            self._conn.execute(sql, tuple(row[column] for column in columns))
            self._conn.commit()

    def recent(self, limit: int = 50) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(
                """
                SELECT * FROM recommendations
                ORDER BY created_at DESC LIMIT ?
                """,
                (max(1, min(limit, 500)),),
            ).fetchall()

    def all_rows(
        self, since_iso: str | None = None
    ) -> list[sqlite3.Row]:
        with self._lock:
            if since_iso:
                return self._conn.execute(
                    """
                    SELECT * FROM recommendations
                    WHERE created_at >= ?
                    ORDER BY created_at
                    """,
                    (since_iso,),
                ).fetchall()

            return self._conn.execute(
                "SELECT * FROM recommendations ORDER BY created_at"
            ).fetchall()

    def close(self) -> None:
        with self._lock:
            self._conn.close()
