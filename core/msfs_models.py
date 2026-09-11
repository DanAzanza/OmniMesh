"""
MSFS Spatial Configuration Domain Models.
Defines pure Python dataclasses representing parsed aircraft spatial definitions
without any Blender (bpy) dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class CFGLineRecord:
    """Represents a single parsed line in an MSFS configuration file."""

    raw_line: str
    section: str = ""
    key: str = ""
    prefix_metadata: str = ""
    coordinates: Optional[tuple[float, float, float]] = None  # (Longitudinal, Lateral, Vertical) in feet
    suffix_tokens: list[str] = field(default_factory=list)
    inline_comment: str = ""
    indentation: str = ""
    is_spatial: bool = False


@dataclass
class SpatialPoint:
    """Represents a resolved 3D spatial marker on an aircraft."""

    point_id: str  # e.g., "CONTACT_POINTS:point.0" or "FUEL:LeftMain"
    section: str
    key: str
    point_type: str  # "CONTACT_POINT", "FUEL_TANK", "DATUM", "CG", "STATION_LOAD"
    name_tag: str = ""
    point_class: int = 0  # e.g., 1 = Wheel, 2 = Scrape, 3 = Skid, 4 = Float
    coords_msfs_rel_ft: tuple[float, float, float] = (0.0, 0.0, 0.0)  # (Long, Lat, Vert) in feet rel to datum
    coords_msfs_abs_ft: tuple[float, float, float] = (0.0, 0.0, 0.0)  # (Long, Lat, Vert) in feet absolute
    coords_blender_m: tuple[float, float, float] = (0.0, 0.0, 0.0)  # (X_lat, Y_long, Z_vert) in meters
    raw_properties: list[str] = field(default_factory=list)
    line_index: int = -1


@dataclass
class AircraftSpatialConfig:
    """Container holding parsed spatial points and metadata for round-trip synchronization."""

    source_file: str = ""
    encoding: str = "utf-8"
    has_bom: bool = False
    line_ending: str = "\r\n"
    reference_datum_ft: tuple[float, float, float] = (0.0, 0.0, 0.0)  # (Long, Lat, Vert) in feet
    empty_weight_cg_ft: tuple[float, float, float] = (0.0, 0.0, 0.0)  # (Long, Lat, Vert) in feet
    points: list[SpatialPoint] = field(default_factory=list)
    lines: list[CFGLineRecord] = field(default_factory=list)

    def get_point_by_id(self, point_id: str) -> Optional[SpatialPoint]:
        """Look up a spatial point by its unique identifier."""
        for p in self.points:
            if p.point_id == point_id:
                return p
        return None
