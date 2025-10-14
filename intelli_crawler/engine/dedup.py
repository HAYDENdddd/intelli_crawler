"""Deduplication layer utilising SQLite fingerprint store."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Tuple

from ..infra.storage import SQLiteManager


@dataclass
class DeduplicationResult:
    url_duplicate: bool
    content_duplicate: bool

    @property
    def is_duplicate(self) -> bool:
        return self.url_duplicate or self.content_duplicate


class DeduplicationStore:
    """Provide URL/content hash deduplication."""

    def __init__(
        self,
        manager: SQLiteManager,
        db_path: Path,
        enable_url: bool = True,
        enable_content: bool = True,
    ) -> None:
        self.manager = manager
        self.db_path = db_path
        self.enable_url = enable_url
        self.enable_content = enable_content
        self._lock = Lock()
        self._conn = self.manager.connect(db_path)

    def check_and_store(self, url: str, content: str, source_name: str) -> DeduplicationResult:
        url_dup = False
        content_dup = False
        content_hash = self._hash(content)
        with self._lock:
            if self.enable_url:
                cur = self._conn.execute(
                    "SELECT 1 FROM crawl_history WHERE url = ?", (url,)
                )
                url_dup = cur.fetchone() is not None
            if self.enable_content:
                cur = self._conn.execute(
                    "SELECT 1 FROM crawl_history WHERE content_hash = ?", (content_hash,)
                )
                content_dup = cur.fetchone() is not None
            if not (url_dup or content_dup):
                self._conn.execute(
                    "INSERT OR REPLACE INTO crawl_history(url, content_hash, timestamp, source_name) VALUES (?, ?, datetime('now'), ?)",
                    (url, content_hash, source_name),
                )
                self._conn.commit()
        return DeduplicationResult(url_dup, content_dup)

    def has_url(self, url: str) -> bool:
        if not self.enable_url:
            return False
        with self._lock:
            cur = self._conn.execute("SELECT 1 FROM crawl_history WHERE url = ?", (url,))
            return cur.fetchone() is not None

    def reset(self) -> None:
        self.manager.reset(self.db_path)
        self._conn = self.manager.connect(self.db_path)

    @staticmethod
    def _hash(content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()


__all__ = ["DeduplicationResult", "DeduplicationStore"]
