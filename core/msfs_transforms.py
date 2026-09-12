"""
MSFS Transforms Re-export Facade.
Provides backward compatibility while delegating to the unified core.msfs package.
"""

from __future__ import annotations

from core.msfs.transforms import *  # noqa: F403
from core.msfs.transforms import (
    FEET_TO_METERS,
    METERS_TO_FEET,
    _euler_xyz_to_matrix,
    _mat_mul,
    _matrix_to_euler_xyz,
    _rot_matrix_x,
    _rot_matrix_y,
    _rot_matrix_z,
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

__all__ = [
    "FEET_TO_METERS",
    "METERS_TO_FEET",
    "_euler_xyz_to_matrix",
    "_mat_mul",
    "_matrix_to_euler_xyz",
    "_rot_matrix_x",
    "_rot_matrix_y",
    "_rot_matrix_z",
    "blender_focal_length_to_msfs_zoom",
    "blender_rotation_to_msfs_pbh",
    "blender_to_msfs",
    "format_coordinate_float",
    "mirror_pbh_rotation",
    "mirror_spatial_coords",
    "msfs_pbh_to_blender_rotation",
    "msfs_to_blender",
    "msfs_zoom_to_blender_focal_length",
]
