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

try:
    from mathutils import Vector
except ImportError:
    Vector = None

if TYPE_CHECKING:
    import bpy

logger = logging.getLogger(__name__)

# Regex pattern to exclude non-structural elements (antennas, props, wicks, interiors)
EXCLUDED_OBJECT_PATTERN = re.compile(
    r"(?i)(prop|rotor|blade|spinner|antenna|wick|glass|interior|pilot|light|shadow|collider|hitbox)"
)

# Regex patterns for wheel/gear/tire submesh detection and false-positive exclusion
WHEEL_OBJECT_PATTERN = re.compile(r"(?i)(wheel|tire|gear)")
WHEEL_EXCLUDED_PATTERN = re.compile(
    r"(?i)(trim|lever|door|cockpit|indicator|handle|gearbox|prop|bay|well|switch|pedal|brake_disc)"
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
    obj: Any,
    depsgraph: bpy.types.Depsgraph | None = None,
) -> np.ndarray:
    """Extract world-space vertex coordinates of a mesh object using fast NumPy buffers.

    Evaluates modifiers (if depsgraph is provided) and guarantees that temporary
    mesh instances are freed. Can also accept a list/tuple of objects.
    """
    if isinstance(obj, (list, tuple)):
        return collect_airframe_vertices(list(obj), depsgraph=depsgraph, filter_non_structural=False)

    if not hasattr(obj, "type") or getattr(obj, "type", "") != "MESH" or not getattr(obj, "data", None):
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


def detect_wheel_submeshes(
    objects: list[bpy.types.Object],
) -> dict[str, tuple[float, float, float]]:
    """Detects wheel/tire/gear submeshes by name heuristics and calculates tire bottom contact points.

    Excludes interior cockpit wheels (trim wheels, gear levers, doors, etc.).

    Args:
        objects: List of candidate mesh objects (typically from asset's LOD0).

    Returns:
        Dictionary mapping semantic wheel keys to (x, y, z) contact positions in meters.
        Possible keys:
            - 'WHEEL_NOSE' / 'WHEEL_FRONT'
            - 'WHEEL_LEFT' / 'WHEEL_RIGHT'
            - 'WHEEL_FRONT_L' / 'WHEEL_FRONT_R'
            - 'WHEEL_REAR_L' / 'WHEEL_REAR_R'
            - 'WHEEL_TAIL'
    """
    results: dict[str, tuple[float, float, float]] = {}
    if not objects:
        return results

    candidates: list[tuple[str, tuple[float, float, float]]] = []

    for obj in objects:
        if not obj or getattr(obj, "type", "") != "MESH":
            continue
        obj_name = getattr(obj, "name", "")
        if not WHEEL_OBJECT_PATTERN.search(obj_name) or WHEEL_EXCLUDED_PATTERN.search(obj_name):
            continue

        coords = extract_world_vertices_numpy(obj)
        if coords.shape[0] >= 3:
            min_x, max_x = float(coords[:, 0].min()), float(coords[:, 0].max())
            min_y, max_y = float(coords[:, 1].min()), float(coords[:, 1].max())
            min_z = float(coords[:, 2].min())
            center_x = (min_x + max_x) * 0.5
            center_y = (min_y + max_y) * 0.5
            candidates.append((obj_name, (center_x, center_y, min_z)))
        elif hasattr(obj, "bound_box") and hasattr(obj, "matrix_world"):
            try:
                mw = obj.matrix_world
                world_pts = [mw @ Vector(pt) for pt in obj.bound_box] if Vector else list(obj.bound_box)
                min_x = min(float(p[0]) for p in world_pts)
                max_x = max(float(p[0]) for p in world_pts)
                min_y = min(float(p[1]) for p in world_pts)
                max_y = max(float(p[1]) for p in world_pts)
                min_z = min(float(p[2]) for p in world_pts)
                center_x = (min_x + max_x) * 0.5
                center_y = (min_y + max_y) * 0.5
                candidates.append((obj_name, (center_x, center_y, min_z)))
            except (TypeError, ValueError, AttributeError, IndexError) as exc:
                logger.debug("Bounding box extraction failed for wheel candidate: %s", exc)

    if not candidates:
        return results

    for name, pos in candidates:
        n_low = name.lower()
        if "nose" in n_low:
            results["WHEEL_NOSE"] = pos
            results["WHEEL_FRONT"] = pos
        elif "tail" in n_low:
            results["WHEEL_TAIL"] = pos
        elif ("front" in n_low or "f_" in n_low or "_fl" in n_low) and ("left" in n_low or "_l" in n_low):
            results["WHEEL_FRONT_L"] = pos
            results.setdefault("WHEEL_LEFT", pos)
        elif ("front" in n_low or "f_" in n_low or "_fr" in n_low) and ("right" in n_low or "_r" in n_low):
            results["WHEEL_FRONT_R"] = pos
            results.setdefault("WHEEL_RIGHT", pos)
        elif ("rear" in n_low or "back" in n_low or "r_" in n_low or "_rl" in n_low) and (
            "left" in n_low or "_l" in n_low
        ):
            results["WHEEL_REAR_L"] = pos
            results.setdefault("WHEEL_LEFT", pos)
        elif ("rear" in n_low or "back" in n_low or "r_" in n_low or "_rr" in n_low) and (
            "right" in n_low or "_r" in n_low
        ):
            results["WHEEL_REAR_R"] = pos
            results.setdefault("WHEEL_RIGHT", pos)
        elif "left" in n_low or "_l" in n_low:
            results["WHEEL_LEFT"] = pos
        elif "right" in n_low or "_r" in n_low:
            results["WHEEL_RIGHT"] = pos
        else:
            cx, cy, _ = pos
            if abs(cx) < 0.25:
                if cy >= 0:
                    results["WHEEL_NOSE"] = pos
                    results["WHEEL_FRONT"] = pos
                else:
                    results["WHEEL_TAIL"] = pos
            elif cx < 0:
                results["WHEEL_LEFT"] = pos
            else:
                results["WHEEL_RIGHT"] = pos

    return results


def detect_ground_vehicle_extrema(
    vertices: np.ndarray,
) -> dict[str, tuple[float, float, float]]:
    """Detects bumper, roof, and rocker boundary extrema for ground vehicles.

    Args:
        vertices: NumPy array of shape (N, 3).

    Returns:
        Dictionary mapping point tags to (x, y, z) in meters.
    """
    if vertices.shape[0] < 4:
        raise ValueError(f"Insufficient vertices for ground vehicle extrema: {vertices.shape[0]}")

    min_x, max_x = float(vertices[:, 0].min()), float(vertices[:, 0].max())
    min_y, max_y = float(vertices[:, 1].min()), float(vertices[:, 1].max())
    min_z, max_z = float(vertices[:, 2].min()), float(vertices[:, 2].max())
    center_x = (min_x + max_x) * 0.5
    center_y = (min_y + max_y) * 0.5
    height = max(0.1, max_z - min_z)

    return {
        "Scrape_Bumper_F_L": (min_x, max_y, min_z + 0.05 * height),
        "Scrape_Bumper_F_R": (max_x, max_y, min_z + 0.05 * height),
        "Scrape_Bumper_R_L": (min_x, min_y, min_z + 0.05 * height),
        "Scrape_Bumper_R_R": (max_x, min_y, min_z + 0.05 * height),
        "Scrape_Roof": (center_x, center_y, max_z),
        "Scrape_Nose": (center_x, max_y, min_z + 0.08 * height),
        "Scrape_Tail": (center_x, min_y, min_z + 0.08 * height),
        "Scrape_Wing_L": (min_x, center_y, min_z + 0.15 * height),
        "Scrape_Wing_R": (max_x, center_y, min_z + 0.15 * height),
        "Scrape_Keel": (center_x, center_y, min_z),
        "Scrape_Fin": (center_x, center_y, max_z),
    }
