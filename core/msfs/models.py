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
    rotation: Optional[tuple[float, float, float]] = None  # (Pitch, Bank, Heading) in degrees
    suffix_tokens: list[str] = field(default_factory=list)
    raw_tags: dict[str, str] = field(default_factory=dict)
    inline_comment: str = ""
    indentation: str = ""
    is_spatial: bool = False


@dataclass
class SpatialPoint:
    """Represents a resolved 3D spatial marker on an aircraft."""

    point_id: str  # e.g., "CONTACT_POINTS:point.0" or "FUEL:LeftMain"
    section: str
    key: str
    point_type: str  # "CONTACT_POINT", "FUEL_TANK", "DATUM", "CG", "STATION_LOAD", "LIGHT"
    name_tag: str = ""
    point_class: int = 0  # e.g., 1 = Wheel, 2 = Scrape, 3 = Skid, 4 = Float
    coords_msfs_rel_ft: tuple[float, float, float] = (0.0, 0.0, 0.0)  # (Long, Lat, Vert) in feet rel to datum
    coords_msfs_abs_ft: tuple[float, float, float] = (0.0, 0.0, 0.0)  # (Long, Lat, Vert) in feet absolute
    coords_blender_m: tuple[float, float, float] = (0.0, 0.0, 0.0)  # (X_lat, Y_long, Z_vert) in meters
    raw_properties: list[str] = field(default_factory=list)
    line_index: int = -1


@dataclass
class LightPoint(SpatialPoint):
    """Represents an MSFS aircraft light (Nav, Beacon, Strobe, Landing, Taxi, etc.)."""

    light_type: int = 0  # 1=Beacon, 2=Strobe, 3=Nav, 4=Panel, 5=Landing, 6=Taxi, etc.
    light_index: int = 0
    rotation_pbh_deg: tuple[float, float, float] = (0.0, 0.0, 0.0)  # (Pitch, Bank, Heading) in degrees
    effect_file: str = ""
    em_mesh: str = ""  # Mesh or bone node name for node-relative attachment
    is_node_relative: bool = False
    circuit_index: Optional[int] = None
    potentiometer_index: Optional[int] = None
    raw_tags: dict[str, str] = field(default_factory=dict)


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
    lights: list[LightPoint] = field(default_factory=list)
    lines: list[CFGLineRecord] = field(default_factory=list)

    def get_point_by_id(self, point_id: str) -> Optional[SpatialPoint]:
        """Look up a spatial point or light by its unique identifier."""
        for p in self.points:
            if p.point_id == point_id:
                return p
        for lt in self.lights:
            if lt.point_id == point_id:
                return lt
        return None


@dataclass
class CameraDefinition:
    """Represents a single parsed [CAMERADEFINITION.N] section in cameras.cfg."""

    index: int
    title: str = ""
    guid: str = ""
    origin: str = "Virtual Cockpit"  # "Virtual Cockpit" or "Center"
    category: str = "Cockpit"  # "Cockpit", "FixedOnPlane", etc.
    subcategory: str = "Pilot"  # "Pilot", "Instrument", "FixedOnPlaneExtern", etc.
    subcategory_item: str = "None"
    initial_xyz_m: tuple[float, float, float] = (0.0, 0.0, 0.0)  # (Lateral, Vertical, Longitudinal) in METERS
    initial_pbh_deg: tuple[float, float, float] = (0.0, 0.0, 0.0)  # (Pitch, Bank, Heading) in degrees
    initial_zoom: float = 1.0
    nodes_to_hide: str = ""
    clip_mode: str = "0"
    properties: dict[str, str] = field(default_factory=dict)
    property_order: list[str] = field(default_factory=list)
    property_comments: dict[str, str] = field(default_factory=dict)
    header_raw: str = ""


@dataclass
class CameraConfigFile:
    """Container holding parsed [VIEWS] and [CAMERADEFINITION.N] sections from cameras.cfg."""

    source_file: str = ""
    encoding: str = "utf-8"
    has_bom: bool = False
    line_ending: str = "\r\n"
    eyepoint_ft: tuple[float, float, float] = (0.0, 0.0, 0.0)  # (Long, Lat, Vert) in feet
    eyepoint_comment: str = ""
    version_lines: list[str] = field(default_factory=list)
    views_lines: list[str] = field(default_factory=list)
    cameras: list[CameraDefinition] = field(default_factory=list)
    preamble_lines: list[str] = field(default_factory=list)  # Lines before first camera section
