# -----------------------------------------------------------------------------
# OmniMesh - MSFS Geometry Analysis & Feature Extraction
# -----------------------------------------------------------------------------

"""Geometry processing routines for MSFS aircraft models.

Provides vectorized NumPy vertex extraction, semantic object filtering to ignore
propellers, antennas, and static wicks, extreme airframe boundary detection
(wingtips, nose, tail, keel, vertical fin), and Class 2 scrape point formatting.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:
    import bpy

logger = logging.getLogger(__name__)

# Regex pattern to exclude non-structural elements (antennas, props, wicks, interiors)
EXCLUDED_OBJECT_PATTERN = re.compile(
    r"(?i)(prop|rotor|blade|spinner|antenna|wick|glass|interior|pilot|light|shadow|collider|hitbox)"
)

# Standard default parameter template for MSFS Class 2 (Scrape) contact points:
# (class, long, lat, vert, crash_impact_speed, sound_type, wheel_type, steer_angle,
#  static_comp, max_static_ratio, dynamic_damp_ratio, dynamic_damp_comp_ratio,
#  rot_time, retraction_time, sound_index, airframe_type)
SCRAPE_CLASS_2_DEFAULTS = (
    2,  # Class: 2 = Scrape point
    0.0,  # Longitudinal (feet) - to be overwritten
    0.0,  # Lateral (feet) - to be overwritten
    0.0,  # Vertical (feet) - to be overwritten
    1500.0,  # Crash impact speed (feet/min)
    0,  # Sound type: 0 = None / Standard scrape
    0.0,  # Wheel type / unused for scrape
    0.0,  # Max steer angle (deg)
    0.0,  # Static compression
    1.0,  # Max / static ratio
    0.5,  # Dynamic damping ratio
    0.0,  # Dynamic damping compression ratio
    0.0,  # Rotational time
    0.0,  # Retraction time
    0,  # Sound index
    1,  # Airframe type: 1 = Fuselage/Wing
)


def is_structural_airframe_object(obj_name: str) -> bool:
    """Check whether an object is considered structural airframe geometry.

    Excludes spinners, blades, pitot tubes, antennas, and interior geometry
    based on naming conventions.

    Args:
        obj_name: Name of the Blender object.

    Returns:
        True if the object is likely structural airframe skin, False otherwise.
    """
    return not bool(EXCLUDED_OBJECT_PATTERN.search(obj_name))


def extract_world_vertices_numpy(
    obj: bpy.types.Object,
    depsgraph: bpy.types.Depsgraph | None = None,
) -> np.ndarray:
    """Extract world-space vertex coordinates of a mesh object using fast NumPy buffers.

    Evaluates modifiers (if depsgraph is provided) and guarantees that temporary
    mesh instances are freed.

    Args:
        obj: Blender mesh object.
        depsgraph: Optional dependency graph to evaluate modifiers.

    Returns:
        NumPy array of shape (N, 3) containing world-space vertex positions (float32),
        or an empty array of shape (0, 3) if object has no vertices.
    """
    if obj.type != "MESH" or not obj.data:
        return np.empty((0, 3), dtype=np.float32)

    eval_obj = obj.evaluated_get(depsgraph) if depsgraph is not None else obj
    eval_mesh = None

    try:
        # If depsgraph is supplied, create evaluated mesh copy with modifier stack
        if depsgraph is not None:
            eval_mesh = eval_obj.to_mesh(preserve_all_data_layers=False, depsgraph=depsgraph)
            mesh_data = eval_mesh
        else:
            mesh_data = eval_obj.data

        num_verts = len(mesh_data.vertices)
        if num_verts == 0:
            return np.empty((0, 3), dtype=np.float32)

        local_coords = np.empty(num_verts * 3, dtype=np.float32)
        mesh_data.vertices.foreach_get("co", local_coords)
        local_coords = local_coords.reshape((num_verts, 3))

        # Convert to world coordinates using 4x4 matrix
        world_matrix = np.array(eval_obj.matrix_world, dtype=np.float32)
        rotation_scale = world_matrix[:3, :3]
        translation = world_matrix[:3, 3]

        # Vectorized world transform: P_world = P_local @ R.T + T
        world_coords = local_coords @ rotation_scale.T + translation
        return world_coords

    finally:
        if eval_mesh is not None and depsgraph is not None:
            eval_obj.to_mesh_clear()


def collect_airframe_vertices(
    objects: list[bpy.types.Object],
    depsgraph: bpy.types.Depsgraph | None = None,
    filter_non_structural: bool = True,
) -> np.ndarray:
    """Collect all world-space vertices across given airframe objects into a single NumPy array.

    Args:
        objects: List of Blender mesh objects.
        depsgraph: Optional dependency graph for modifier evaluation.
        filter_non_structural: Whether to exclude antennas, propellers, etc.

    Returns:
        Combined NumPy array of shape (Total_N, 3).
    """
    coord_arrays: list[np.ndarray] = []

    for obj in objects:
        if filter_non_structural and not is_structural_airframe_object(obj.name):
            logger.debug("Excluding non-structural object: %s", obj.name)
            continue

        coords = extract_world_vertices_numpy(obj, depsgraph=depsgraph)
        if coords.shape[0] > 0:
            coord_arrays.append(coords)

    if not coord_arrays:
        return np.empty((0, 3), dtype=np.float32)

    return np.vstack(coord_arrays)


def detect_airframe_extrema(
    vertices: np.ndarray,
    fuselage_width_tol_m: float = 0.4,
    percentile_clamp: float = 99.9,
) -> dict[str, tuple[float, float, float]]:
    """Detect key extreme spatial positions for MSFS scrape points.

    In Blender coordinate frame:
    - X: Lateral (Right > 0, Left < 0)
    - Y: Longitudinal (Forward > 0, Aft < 0)
    - Z: Vertical (Up > 0, Down < 0)

    Args:
        vertices: NumPy array of shape (N, 3) in world or datum-relative meters.
        fuselage_width_tol_m: Lateral threshold (|X| <= tol) for centerline features (nose, tail, keel).
        percentile_clamp: Percentile used to reject rogue stray vertices/wicks (e.g. 99.9).

    Returns:
        Dictionary mapping point identifier to (x, y, z) in meters:
        - "Scrape_Wing_L": Extreme left wingtip
        - "Scrape_Wing_R": Extreme right wingtip
        - "Scrape_Nose": Extreme front nose point
        - "Scrape_Tail": Extreme aft tail point
        - "Scrape_Keel": Lowest point along fuselage belly
        - "Scrape_Fin": Highest point on vertical stabilizer
    """
    if vertices.shape[0] < 4:
        raise ValueError(f"Insufficient vertices to detect airframe extrema: {vertices.shape[0]}")

    results: dict[str, tuple[float, float, float]] = {}

    # 1. Left and Right Wingtips (Lateral X extremes)
    # Clamp to avoid single rogue disconnected verts or static discharge wicks
    x_min_threshold = float(np.percentile(vertices[:, 0], 100.0 - percentile_clamp))
    x_max_threshold = float(np.percentile(vertices[:, 0], percentile_clamp))

    # Left wingtip: Minimum X (Left)
    left_candidates = vertices[vertices[:, 0] <= x_min_threshold]
    if left_candidates.shape[0] > 0:
        min_idx = np.argmin(left_candidates[:, 0])
        results["Scrape_Wing_L"] = (
            float(left_candidates[min_idx, 0]),
            float(left_candidates[min_idx, 1]),
            float(left_candidates[min_idx, 2]),
        )
    else:
        min_idx = np.argmin(vertices[:, 0])
        results["Scrape_Wing_L"] = (
            float(vertices[min_idx, 0]),
            float(vertices[min_idx, 1]),
            float(vertices[min_idx, 2]),
        )

    # Right wingtip: Maximum X (Right)
    right_candidates = vertices[vertices[:, 0] >= x_max_threshold]
    if right_candidates.shape[0] > 0:
        max_idx = np.argmax(right_candidates[:, 0])
        results["Scrape_Wing_R"] = (
            float(right_candidates[max_idx, 0]),
            float(right_candidates[max_idx, 1]),
            float(right_candidates[max_idx, 2]),
        )
    else:
        max_idx = np.argmax(vertices[:, 0])
        results["Scrape_Wing_R"] = (
            float(vertices[max_idx, 0]),
            float(vertices[max_idx, 1]),
            float(vertices[max_idx, 2]),
        )

    # 2. Centerline Filter for Fuselage Features (|X| <= fuselage_width_tol_m)
    centerline_mask = np.abs(vertices[:, 0]) <= fuselage_width_tol_m
    centerline_verts = vertices[centerline_mask]

    # Fallback if fuselage is unusually wide or offset: use full vertex set
    if centerline_verts.shape[0] < 4:
        centerline_verts = vertices

    # Nose: Foremost point (Max Y)
    nose_idx = np.argmax(centerline_verts[:, 1])
    results["Scrape_Nose"] = (
        float(centerline_verts[nose_idx, 0]),
        float(centerline_verts[nose_idx, 1]),
        float(centerline_verts[nose_idx, 2]),
    )

    # Tail: Aft-most point (Min Y)
    tail_idx = np.argmin(centerline_verts[:, 1])
    results["Scrape_Tail"] = (
        float(centerline_verts[tail_idx, 0]),
        float(centerline_verts[tail_idx, 1]),
        float(centerline_verts[tail_idx, 2]),
    )

    # Belly / Keel: Lowest point on fuselage (Min Z)
    keel_idx = np.argmin(centerline_verts[:, 2])
    results["Scrape_Keel"] = (
        float(centerline_verts[keel_idx, 0]),
        float(centerline_verts[keel_idx, 1]),
        float(centerline_verts[keel_idx, 2]),
    )

    # Vertical Fin: Highest point (Max Z)
    fin_idx = np.argmax(centerline_verts[:, 2])
    results["Scrape_Fin"] = (
        float(centerline_verts[fin_idx, 0]),
        float(centerline_verts[fin_idx, 1]),
        float(centerline_verts[fin_idx, 2]),
    )

    return results


def format_class_2_scrape_tokens(
    name_tag: str,
    coords_ft: tuple[float, float, float],
    margin_ft: float = 0.0,
) -> list[str]:
    """Format a 16-parameter Class 2 contact point token list for MSFS flight_model.cfg.

    Args:
        name_tag: Semantic name tag (e.g. "Scrape_Wing_L").
        coords_ft: Coordinates in MSFS feet (Long, Lat, Vert).
        margin_ft: Optional offset in feet (positive expands outward).

    Returns:
        List of 16 string tokens matching the Class 2 MSFS schema.
    """
    long_ft, lat_ft, vert_ft = coords_ft

    # Adjust coordinates based on semantic position
    if "Wing_L" in name_tag:
        lat_ft -= margin_ft
    elif "Wing_R" in name_tag:
        lat_ft += margin_ft
    elif "Nose" in name_tag:
        long_ft += margin_ft
    elif "Tail" in name_tag:
        long_ft -= margin_ft
    elif "Keel" in name_tag:
        vert_ft -= margin_ft
    elif "Fin" in name_tag:
        vert_ft += margin_ft

    tokens: list[Any] = list(SCRAPE_CLASS_2_DEFAULTS)
    tokens[1] = f"{long_ft:.2f}"
    tokens[2] = f"{lat_ft:.2f}"
    tokens[3] = f"{vert_ft:.2f}"

    return [str(t) for t in tokens]
