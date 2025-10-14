"""Exporter Service Provider Interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterable


class BaseExporter(ABC):
    """Uniform exporter contract enabling plug-and-play outputs."""

    @abstractmethod
    def export(self, record: dict) -> None:
        """Persist a single record."""

    def export_many(self, records: Iterable[dict]) -> None:
        for record in records:
            self.export(record)

    @abstractmethod
    def flush(self) -> None:
        """Flush buffered data to destination."""

    @abstractmethod
    def close(self) -> None:
        """Release underlying resources."""


__all__ = ["BaseExporter"]
