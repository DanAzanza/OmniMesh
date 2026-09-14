"""
MSFS Models Re-export Facade.
Provides backward compatibility while delegating to the unified core.msfs package.
"""

from __future__ import annotations

from .msfs.models import *  # noqa: F403
from .msfs.models import (
    AircraftSpatialConfig,
    CameraConfigFile,
    CameraDefinition,
    CFGLineRecord,
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
