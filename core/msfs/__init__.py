"""
MSFS Subsystem for OmniMesh.
Provides aircraft package scanning, CST parsing/serialization for flight_model.cfg
and cameras.cfg, coordinate transformations, and scrape geometry analysis.
"""

from .models import (
    AircraftSpatialConfig,
    CFGLineRecord,
    CameraConfigFile,
    CameraDefinition,
    LightPoint,
    SpatialPoint,
)
from .transforms import (
    FEET_TO_METERS,
    METERS_TO_FEET,
    blender_focal_length_to_msfs_zoom,
    blender_rotation_to_msfs_pbh,
    blender_to_msfs,
    format_coordinate_float,
    mirror_pbh_rotation,
    mirror_spatial_coords,
    msfs_pbh_to_blender_rotation,
    msfs_to_blender,
    msfs_zoom_to_blender_focal_length,
)
from .camera_cst import MSFSCameraCST, detect_file_format
from .cst_parser import MSFSCSTParser
from .geometry import (
    EXCLUDED_OBJECT_PATTERN,
    SCRAPE_CLASS_2_DEFAULTS,
    collect_airframe_vertices,
    detect_airframe_extrema,
    extract_world_vertices_numpy,
    format_class_2_scrape_tokens,
    is_structural_airframe_object,
)
from .project_scanner import (
    MSFSLODInfo,
    MSFSModelTargetInfo,
    MSFSProjectManifest,
    MSFSProjectScanner,
    find_package_root,
    parse_model_cfg,
    parse_model_xml,
    resolve_path_ci,
    sanitize_asset_name,
)

__all__ = [
    "AircraftSpatialConfig",
    "CFGLineRecord",
    "CameraConfigFile",
    "CameraDefinition",
    "EXCLUDED_OBJECT_PATTERN",
    "LightPoint",
    "MSFSCameraCST",
    "MSFSCSTParser",
    "MSFSLODInfo",
    "MSFSModelTargetInfo",
    "MSFSProjectManifest",
    "MSFSProjectScanner",
    "SCRAPE_CLASS_2_DEFAULTS",
    "SpatialPoint",
    "blender_focal_length_to_msfs_zoom",
    "blender_rotation_to_msfs_pbh",
    "detect_file_format",
    "blender_to_msfs",
    "collect_airframe_vertices",
    "detect_airframe_extrema",
    "extract_world_vertices_numpy",
    "FEET_TO_METERS",
    "METERS_TO_FEET",
    "find_package_root",
    "format_class_2_scrape_tokens",
    "format_coordinate_float",
    "is_structural_airframe_object",
    "mirror_pbh_rotation",
    "mirror_spatial_coords",
    "msfs_pbh_to_blender_rotation",
    "msfs_to_blender",
    "msfs_zoom_to_blender_focal_length",
    "parse_model_cfg",
    "parse_model_xml",
    "resolve_path_ci",
    "sanitize_asset_name",
]
