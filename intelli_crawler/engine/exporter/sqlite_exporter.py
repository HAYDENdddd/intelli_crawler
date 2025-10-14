"""Export parsed records to SQLite tables."""

from __future__ import annotations

import json
from pathlib import Path

import sqlite3

from .base import BaseExporter


class SQLiteExporter(BaseExporter):
    """Persist records as JSON blobs in SQLite."""

    def __init__(self, path: Path, table: str = "records") -> None:
        self.path = path
        self.table = table
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {self.table} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                payload TEXT NOT NULL
            )
            """
        )
        self.conn.commit()

    def export(self, record: dict) -> None:
        self.conn.execute(
            f"INSERT INTO {self.table}(payload) VALUES (?)",
            (json.dumps(record, ensure_ascii=False),),
        )

    def flush(self) -> None:
        self.conn.commit()

    def close(self) -> None:
        self.conn.commit()
        self.conn.close()


__all__ = ["SQLiteExporter"]
