"""
MSFS Camera CST Re-export Facade.
Provides backward compatibility while delegating to the unified core.msfs package.
"""

from __future__ import annotations

from core.msfs.camera_cst import *  # noqa: F403
from core.msfs.camera_cst import (
    MSFSCameraCST,
    detect_file_format,
)

__all__ = [
    "MSFSCameraCST",
    "detect_file_format",
]
