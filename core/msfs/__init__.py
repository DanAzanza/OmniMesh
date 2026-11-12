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
from .xml_merger import ModelXMLMerger

__all__ = [
    "AircraftSpatialConfig",
    "CFGLineRecord",
    "CameraConfigFile",
    "CameraDefinition",
    "ModelXMLMerger",
    "LightPoint",
    "MSFSCameraCST",
    "MSFSCSTParser",
    "MSFSLODInfo",
    "MSFSModelTargetInfo",
    "MSFSProjectManifest",
    "MSFSProjectScanner",
    "SpatialPoint",
    "blender_focal_length_to_msfs_zoom",
    "blender_rotation_to_msfs_pbh",
    "detect_file_format",
    "blender_to_msfs",
    "FEET_TO_METERS",
    "METERS_TO_FEET",
    "find_package_root",
    "format_coordinate_float",
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
