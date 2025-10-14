"""Storage abstractions for history/dedup/outputs."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from threading import Lock
from typing import Dict


class SQLiteManager:
    """Manage SQLite connections with basic schema guarantees."""

    def __init__(self) -> None:
        self._connections: Dict[Path, sqlite3.Connection] = {}
        self._lock = Lock()

    def connect(self, path: Path) -> sqlite3.Connection:
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            if path not in self._connections:
                conn = sqlite3.connect(path, check_same_thread=False)
                conn.row_factory = sqlite3.Row
                self._connections[path] = conn
                self._ensure_schema(conn)
            return self._connections[path]

    def _ensure_schema(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS crawl_history (
                url TEXT PRIMARY KEY,
                content_hash TEXT,
                timestamp TEXT,
                source_name TEXT
            )
            """
        )
        conn.commit()

    def reset(self, path: Path) -> None:
        if path.exists():
            path.unlink()
        with self._lock:
            if path in self._connections:
                self._connections[path].close()
                del self._connections[path]

    def close_all(self) -> None:
        with self._lock:
            for conn in self._connections.values():
                conn.close()
            self._connections.clear()


__all__ = ["SQLiteManager"]
