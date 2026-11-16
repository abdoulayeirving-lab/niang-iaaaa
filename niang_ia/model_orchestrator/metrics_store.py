from __future__ import annotations

import json
import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any


def _default_metrics_path() -> Path:
    root = os.environ.get("LOCALAPPDATA")
    if not root:
        root = str(Path.home() / "AppData" / "Local")
    return Path(root) / "NIANG IA" / "model_orchestrator_metrics.db"


class MetricsEventStore:
    """Local persistence for routing metrics and failover events.

    Phase 1 foundation: stores non-secret, structured records only. Not wired to
    runtime execution paths. Data is local; callers must not store credentials.
    """

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else _default_metrics_path()

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=5)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS model_metrics ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "timestamp REAL NOT NULL,"
            "provider_id TEXT NOT NULL,"
            "model_id TEXT NOT NULL,"
            "origin TEXT NOT NULL,"
            "payload TEXT NOT NULL)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS orchestration_events ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "timestamp REAL NOT NULL,"
            "event_type TEXT NOT NULL,"
            "origin TEXT NOT NULL,"
            "payload TEXT NOT NULL)"
        )
        return conn

    @contextmanager
    def _connection(self):
        conn = self._connect()
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def record_metric(self, provider_id: str, model_id: str, origin: str, payload: dict[str, Any]) -> int:
        if origin not in {"simule", "reel"}:
            raise ValueError("origin must be 'simule' or 'reel'")
        ts = float(payload.get("timestamp", time.time()))
        with self._connection() as conn:
            cur = conn.execute(
                "INSERT INTO model_metrics (timestamp, provider_id, model_id, origin, payload) VALUES (?,?,?,?,?)",
                (ts, provider_id, model_id, origin, json.dumps(payload, ensure_ascii=False)),
            )
            return int(cur.lastrowid)

    def record_event(self, event_type: str, origin: str, payload: dict[str, Any]) -> int:
        if origin not in {"simule", "reel"}:
            raise ValueError("origin must be 'simule' or 'reel'")
        ts = float(payload.get("timestamp", time.time()))
        with self._connection() as conn:
            cur = conn.execute(
                "INSERT INTO orchestration_events (timestamp, event_type, origin, payload) VALUES (?,?,?,?)",
                (ts, event_type, origin, json.dumps(payload, ensure_ascii=False)),
            )
            return int(cur.lastrowid)

    def list_metrics(self, provider_id: str | None = None, model_id: str | None = None,
                     origin: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT id, timestamp, provider_id, model_id, origin, payload FROM model_metrics WHERE 1=1"
        params: list[Any] = []
        if provider_id:
            query += " AND provider_id=?"
            params.append(provider_id)
        if model_id:
            query += " AND model_id=?"
            params.append(model_id)
        if origin:
            query += " AND origin=?"
            params.append(origin)
        query += " ORDER BY id"
        with self._connection() as conn:
            rows = conn.execute(query, params).fetchall()
        return [
            {
                "id": r[0], "timestamp": r[1], "provider_id": r[2], "model_id": r[3],
                "origin": r[4], "payload": json.loads(r[5]),
            }
            for r in rows
        ]

    def list_events(self, event_type: str | None = None, origin: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT id, timestamp, event_type, origin, payload FROM orchestration_events WHERE 1=1"
        params: list[Any] = []
        if event_type:
            query += " AND event_type=?"
            params.append(event_type)
        if origin:
            query += " AND origin=?"
            params.append(origin)
        query += " ORDER BY id"
        with self._connection() as conn:
            rows = conn.execute(query, params).fetchall()
        return [
            {"id": r[0], "timestamp": r[1], "event_type": r[2], "origin": r[3], "payload": json.loads(r[4])}
            for r in rows
        ]
