"""Thread pool abstraction ensuring per-source isolation when needed."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from typing import Dict


class ThreadPoolManager:
    """Manage the shared and per-source thread pools."""

    def __init__(self, default_workers: int = 8) -> None:
        self.default_workers = default_workers
        self._default_executor = ThreadPoolExecutor(max_workers=default_workers, thread_name_prefix="crawler")
        self._executors: Dict[str, ThreadPoolExecutor] = {}
        self._lock = Lock()

    def get(self, source_name: str | None = None, max_workers: int | None = None) -> ThreadPoolExecutor:
        if source_name is None:
            return self._default_executor
        with self._lock:
            if source_name not in self._executors:
                workers = max_workers or self.default_workers
                self._executors[source_name] = ThreadPoolExecutor(
                    max_workers=workers, thread_name_prefix=f"crawler-{source_name}"
                )
            return self._executors[source_name]

    def shutdown(self) -> None:
        self._default_executor.shutdown(wait=False)
        with self._lock:
            for executor in self._executors.values():
                executor.shutdown(wait=False)
            self._executors.clear()


__all__ = ["ThreadPoolManager"]
