"""
MSFS Geometry Re-export Facade.
Provides backward compatibility while delegating to the unified core.msfs package.
"""

from __future__ import annotations

from core.msfs.geometry import *  # noqa: F403
from core.msfs.geometry import (
    EXCLUDED_OBJECT_PATTERN,
    SCRAPE_CLASS_2_DEFAULTS,
    collect_airframe_vertices,
    detect_airframe_extrema,
    extract_world_vertices_numpy,
    format_class_2_scrape_tokens,
    is_structural_airframe_object,
)

__all__ = [
    "EXCLUDED_OBJECT_PATTERN",
    "SCRAPE_CLASS_2_DEFAULTS",
    "collect_airframe_vertices",
    "detect_airframe_extrema",
    "extract_world_vertices_numpy",
    "format_class_2_scrape_tokens",
    "is_structural_airframe_object",
]
