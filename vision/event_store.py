"""Small SQLite store for searchable vision event history."""

from __future__ import annotations

import contextlib
import json
import sqlite3
from pathlib import Path
from typing import Iterable

from .vision_events import VisionEvent

_SCHEMA = """CREATE TABLE IF NOT EXISTS vision_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type TEXT NOT NULL,
    source TEXT NOT NULL,
    timestamp REAL NOT NULL,
    label TEXT,
    confidence REAL,
    payload TEXT NOT NULL
)"""


class VisionEventStore:
    """SQLite-backed history with bounded growth and read-safe access."""

    def __init__(self, path: str | Path, retention: int = 2000):
        self.path = Path(path)
        self.retention = max(10, int(retention))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=10.0)
        db.execute("PRAGMA busy_timeout = 5000")
        db.execute("PRAGMA journal_mode = WAL")
        return db

    def add(self, event: VisionEvent) -> None:
        with contextlib.closing(self._connect()) as db:
            with db:
                db.execute(
                    "INSERT INTO vision_events(type,source,timestamp,label,confidence,payload) "
                    "VALUES(?,?,?,?,?,?)",
                    (event.type, event.source, event.timestamp, event.label, event.confidence,
                     json.dumps(event.to_dict(), default=str)),
                )

    def add_many(self, events: Iterable[VisionEvent]) -> None:
        events = list(events)
        if not events:
            return
        with contextlib.closing(self._connect()) as db:
            with db:
                db.executemany(
                    "INSERT INTO vision_events(type,source,timestamp,label,confidence,payload) "
                    "VALUES(?,?,?,?,?,?)",
                    [
                        (event.type, event.source, event.timestamp, event.label, event.confidence,
                         json.dumps(event.to_dict(), default=str))
                        for event in events
                    ],
                )
            # Bounded retention: purge the oldest rows on every insert batch.
            db.execute(
                "DELETE FROM vision_events WHERE id NOT IN "
                "(SELECT id FROM vision_events ORDER BY id DESC LIMIT ?)",
                (self.retention,),
            )

    def recent(self, limit: int = 50) -> list[dict]:
        limit = max(1, int(limit))
        with contextlib.closing(self._connect()) as db:
            rows = db.execute(
                "SELECT type,source,timestamp,label,confidence,payload FROM vision_events "
                "ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        result: list[dict] = []
        for row in rows:
            try:
                payload = json.loads(row[5])
            except (ValueError, TypeError):
                payload = {"raw": str(row[5])}
            result.append(
                {
                    "type": row[0],
                    "source": row[1],
                    "timestamp": row[2],
                    "label": row[3],
                    "confidence": row[4],
                    "payload": payload,
                }
            )
        return result
