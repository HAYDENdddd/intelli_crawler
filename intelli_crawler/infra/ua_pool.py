"""User-Agent pool abstraction."""

from __future__ import annotations

import random
from pathlib import Path
from threading import Lock
from typing import Iterable, List, Optional


class UserAgentPool:
    """Return random user agents from configured pool."""

    def __init__(self, user_agents: Iterable[str] | None = None, file_path: Path | None = None) -> None:
        self._lock = Lock()
        self._uas: List[str] = []
        if user_agents:
            self._uas.extend(ua.strip() for ua in user_agents if ua.strip())
        if file_path and file_path.exists():
            lines = file_path.read_text(encoding="utf-8").splitlines()
            self._uas.extend(line.strip() for line in lines if line.strip())

    def get(self) -> Optional[str]:
        with self._lock:
            if not self._uas:
                return None
            return random.choice(self._uas)

    def refresh(self, user_agents: Iterable[str]) -> None:
        with self._lock:
            self._uas = [ua.strip() for ua in user_agents if ua.strip()]


__all__ = ["UserAgentPool"]
