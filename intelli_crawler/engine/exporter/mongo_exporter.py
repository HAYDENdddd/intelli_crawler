"""MongoDB exporter implementation."""

from __future__ import annotations

from typing import Any

from .base import BaseExporter

try:  # noqa: SIM105
    from pymongo import MongoClient
except Exception as exc:  # noqa: BLE001
    MongoClient = None  # type: ignore[assignment]
    _IMPORT_ERROR = exc
else:
    _IMPORT_ERROR = None


class MongoExporter(BaseExporter):
    """Write records into a MongoDB collection."""

    def __init__(self, uri: str, database: str, collection: str) -> None:
        if MongoClient is None:  # pragma: no cover - import guard
            raise RuntimeError(f"pymongo is required for MongoExporter: {_IMPORT_ERROR}")
        self.client = MongoClient(uri)
        self.collection = self.client[database][collection]

    def export(self, record: dict) -> None:
        self.collection.insert_one(record)

    def flush(self) -> None:
        # MongoDB writes are immediate in default write concern
        return

    def close(self) -> None:
        self.client.close()


__all__ = ["MongoExporter"]
