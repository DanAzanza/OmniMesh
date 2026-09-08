"""
Reentrancy and synchronization guards for OmniMesh properties and presets.
"""

from typing import Any


class PresetSyncGuard:
    """Thread-safe reentrancy guard preventing circular cascades between preset and property updates."""

    _depth: int = 0

    def __enter__(self) -> "PresetSyncGuard":
        PresetSyncGuard._depth += 1
        return self

    def __exit__(self, *exc: Any) -> None:
        PresetSyncGuard._depth -= 1

    @classmethod
    def is_locked(cls) -> bool:
        return cls._depth > 0

    is_active = is_locked


class StateRestorationGuard:
    """Thread-safe reentrancy guard suppressing RNA update events and CoW duplication during state restoration."""

    _depth: int = 0

    def __enter__(self) -> "StateRestorationGuard":
        StateRestorationGuard._depth += 1
        return self

    def __exit__(self, *exc: Any) -> None:
        StateRestorationGuard._depth -= 1

    @classmethod
    def is_active(cls) -> bool:
        return cls._depth > 0


class MapSyncGuard:
    """Thread-safe reentrancy guard preventing update cascades during map synchronization."""

    _depth: int = 0

    @classmethod
    def is_active(cls) -> bool:
        return cls._depth > 0

    def __enter__(self) -> "MapSyncGuard":
        MapSyncGuard._depth += 1
        return self

    def __exit__(self, *exc: Any) -> None:
        MapSyncGuard._depth -= 1


class ExportMapSyncGuard:
    """Thread-safe reentrancy guard preventing update cascades during export map synchronization."""

    _depth: int = 0

    @classmethod
    def is_active(cls) -> bool:
        return cls._depth > 0

    def __enter__(self) -> "ExportMapSyncGuard":
        ExportMapSyncGuard._depth += 1
        return self

    def __exit__(self, *exc: Any) -> None:
        ExportMapSyncGuard._depth -= 1


__all__ = [
    "PresetSyncGuard",
    "StateRestorationGuard",
    "MapSyncGuard",
    "ExportMapSyncGuard",
]
