"""Lightweight proxy pool implementation."""

from __future__ import annotations

import random
from pathlib import Path
from threading import Lock
from typing import Iterable, List, Optional


class ProxyPool:
    """Circular proxy provider with optional backing file."""

    def __init__(self, proxies: Iterable[str] | None = None, file_path: Path | None = None) -> None:
        self._lock = Lock()
        self._index = 0
        self._proxies: List[str] = []
        if proxies:
            self._proxies.extend(p.strip() for p in proxies if p.strip())
        if file_path and file_path.exists():
            lines = file_path.read_text(encoding="utf-8").splitlines()
            self._proxies.extend(line.strip() for line in lines if line.strip())
        random.shuffle(self._proxies)

    @property
    def empty(self) -> bool:
        return not self._proxies

    def get_proxy(self) -> Optional[str]:
        with self._lock:
            if not self._proxies:
                return None
            proxy = self._proxies[self._index % len(self._proxies)]
            self._index += 1
            return proxy

    def add_proxy(self, proxy: str) -> None:
        if not proxy:
            return
        with self._lock:
            self._proxies.append(proxy)

    def refresh(self, proxies: Iterable[str]) -> None:
        with self._lock:
            self._proxies = [p.strip() for p in proxies if p.strip()]
            random.shuffle(self._proxies)


__all__ = ["ProxyPool"]
