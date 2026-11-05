"""Encrypted local persistence for autonomous mission recovery."""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any


def _default_path() -> Path:
    root = os.environ.get("LOCALAPPDATA")
    if not root:
        root = str(Path.home() / "AppData" / "Local")
    return Path(root) / "NIANG IA" / "agent_missions.db"


def _protect(data: bytes) -> bytes:
    if sys.platform != "win32":
        raise RuntimeError("Encrypted mission persistence requires Windows DPAPI.")
    import win32crypt

    encrypted = win32crypt.CryptProtectData(
        data, "NIANG IA mission data", None, None, None, 0
    )
    return encrypted


def _unprotect(data: bytes) -> bytes:
    if sys.platform != "win32":
        raise RuntimeError("Encrypted mission persistence requires Windows DPAPI.")
    import win32crypt

    decrypted = win32crypt.CryptUnprotectData(
        data, None, None, None, 0
    )[1]
    return decrypted.encode("utf-8") if isinstance(decrypted, str) else decrypted


class MissionStore:
    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else _default_path()

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=5)
        connection.execute(
            "CREATE TABLE IF NOT EXISTS missions ("
            "task_id TEXT PRIMARY KEY, status TEXT NOT NULL, "
            "updated_at REAL NOT NULL, payload BLOB NOT NULL)"
        )
        return connection

    @contextmanager
    def _connection(self):
        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def save(self, task_id: str, status: str, payload: dict[str, Any]) -> None:
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        encrypted = _protect(encoded)
        with self._connection() as connection:
            connection.execute(
                "INSERT INTO missions (task_id, status, updated_at, payload) "
                "VALUES (?, ?, ?, ?) ON CONFLICT(task_id) DO UPDATE SET "
                "status=excluded.status, updated_at=excluded.updated_at, "
                "payload=excluded.payload",
                (task_id, status, time.time(), encrypted),
            )

    def load_all(self) -> list[dict[str, Any]]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT task_id, status, payload FROM missions ORDER BY updated_at"
            ).fetchall()
        records = []
        for task_id, status, encrypted in rows:
            payload = json.loads(_unprotect(encrypted).decode("utf-8"))
            records.append({
                "task_id": task_id,
                "status": status,
                "payload": payload,
            })
        return records

    def prune_terminal(self, retention_days: int) -> int:
        cutoff = time.time() - retention_days * 86400
        with self._connection() as connection:
            cursor = connection.execute(
                "DELETE FROM missions WHERE updated_at < ? AND status IN "
                "('completed', 'partial', 'failed', 'cancelled', 'action_unknown', 'interrupted')",
                (cutoff,),
            )
            return cursor.rowcount
