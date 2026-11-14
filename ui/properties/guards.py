"""Thread-safe reentrancy and synchronization guards for OmniMesh properties and presets."""

from __future__ import annotations

import threading
from typing import Any, Self


class _ReentrancyGuard:
    """Base reentrant lock + depth-tracking context manager for RNA update suppression."""

    _lock: threading.RLock
    _depth: int

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        cls._lock = threading.RLock()
        cls._depth = 0

    def __enter__(self) -> Self:
        cls = type(self)
        cls._lock.acquire()
        cls._depth += 1
        return self

    def __exit__(self, *_exc: Any) -> None:
        cls = type(self)
        try:
            cls._depth = max(0, cls._depth - 1)
        finally:
            cls._lock.release()

    @classmethod
    def is_locked(cls) -> bool:
        """Return True while this guard is actively held."""
        with cls._lock:
            return cls._depth > 0

    @classmethod
    def is_active(cls) -> bool:
        """Alias for ``is_locked`` matching callback call sites."""
        return cls.is_locked()


class PresetSyncGuard(_ReentrancyGuard):
    """Thread-safe reentrancy guard preventing circular cascades between preset and property updates."""


class StateRestorationGuard(_ReentrancyGuard):
    """Thread-safe reentrancy guard suppressing RNA update events and CoW duplication during state restoration."""


class MapSyncGuard(_ReentrancyGuard):
    """Thread-safe reentrancy guard preventing update cascades during map synchronization."""


class ExportMapSyncGuard(_ReentrancyGuard):
    """Thread-safe reentrancy guard preventing update cascades during export map synchronization."""


__all__ = [
    "PresetSyncGuard",
    "StateRestorationGuard",
    "MapSyncGuard",
    "ExportMapSyncGuard",
]
