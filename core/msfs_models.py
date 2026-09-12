"""
MSFS Models Re-export Facade.
Provides backward compatibility while delegating to the unified core.msfs package.
"""

from __future__ import annotations

from core.msfs.models import *  # noqa: F403
from core.msfs.models import (
    AircraftSpatialConfig,
    CFGLineRecord,
    CameraConfigFile,
    CameraDefinition,
    LightPoint,
    SpatialPoint,
)

__all__ = [
    "AircraftSpatialConfig",
    "CFGLineRecord",
    "CameraConfigFile",
    "CameraDefinition",
    "LightPoint",
    "SpatialPoint",
]
