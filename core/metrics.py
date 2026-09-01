"""
Mathematical & Screen-Space Error Metrics Engine.
Provides projection solvers, PCA bounding extents, and coupled SSE tolerances.
"""

from __future__ import annotations

import math
from typing import Any

try:
    import mathutils
except ImportError:
    # Standalone test fallback without blender mathutils
    mathutils = None


def compute_vertical_fov(camera_angle_rad: float, aspect_ratio: float, sensor_fit: str = "AUTO") -> float:
    """
    Computes the exact vertical field of view (in radians) from camera angle,
    aspect ratio (width / height), and sensor fit setting.
    """
    if aspect_ratio <= 0.0:
        aspect_ratio = 16.0 / 9.0

    angle_clamped = max(1e-4, min(math.pi - 1e-4, camera_angle_rad))

    resolved_fit = sensor_fit
    if resolved_fit == "AUTO":
        resolved_fit = "HORIZONTAL" if aspect_ratio >= 1.0 else "VERTICAL"

    if resolved_fit == "VERTICAL":
        return angle_clamped
    else:  # HORIZONTAL
        # tan(theta_v / 2) = tan(theta_h / 2) / aspect_ratio
        half_h = angle_clamped / 2.0
        tan_v = math.tan(half_h) / aspect_ratio
        return 2.0 * math.atan(max(1e-4, tan_v))


def compute_bounding_sphere(coords: list[Any]) -> tuple[Any, float]:
    """
    Computes the bounding sphere center and radius for a collection of 3D points.
    Works with mathutils.Vector or list/tuple of (x, y, z).
    """
    if not coords:
        if mathutils and hasattr(mathutils, "Vector"):
            return mathutils.Vector((0.0, 0.0, 0.0)), 1.0
        return (0.0, 0.0, 0.0), 1.0

    valid_coords = [c for c in coords if c is not None]
    if not valid_coords:
        if mathutils and hasattr(mathutils, "Vector"):
            return mathutils.Vector((0.0, 0.0, 0.0)), 1.0
        return (0.0, 0.0, 0.0), 1.0

    n = len(valid_coords)
    if mathutils and hasattr(mathutils, "Vector") and isinstance(valid_coords[0], mathutils.Vector):
        center = sum(valid_coords, mathutils.Vector((0.0, 0.0, 0.0))) / n
        radius = max((v - center).length for v in valid_coords)
    else:
        cx = sum(float(c[0]) for c in valid_coords) / n
        cy = sum(float(c[1]) for c in valid_coords) / n
        cz = sum(float(c[2]) for c in valid_coords) / n
        center = (cx, cy, cz) if not (mathutils and hasattr(mathutils, "Vector")) else mathutils.Vector((cx, cy, cz))
        radius = max(
            math.sqrt((float(c[0]) - cx) ** 2 + (float(c[1]) - cy) ** 2 + (float(c[2]) - cz) ** 2) for c in valid_coords
        )

    return center, max(1e-4, radius)


def compute_distance_from_screen_size(radius: float, screen_size_fraction: float, vertical_fov_rad: float) -> float:
    """
    Calculates exact camera Euclidean distance for a given target on-screen size fraction S in (0, 1].
    Formula: d = r / (S * tan(theta_v / 2))
    """
    s_clamped = max(0.001, min(1.0, screen_size_fraction))
    half_fov = max(1e-4, min(math.pi / 2.0 - 1e-4, vertical_fov_rad / 2.0))
    r = max(1e-4, radius)
    return r / (s_clamped * math.tan(half_fov))


def compute_screen_size_from_distance(radius: float, distance: float, vertical_fov_rad: float) -> float:
    """
    Calculates on-screen size fraction S in [0, 1] for a given Euclidean distance.
    Formula: S = r / (d * tan(theta_v / 2))
    """
    dist_clamped = max(1e-4, distance)
    half_fov = max(1e-4, min(math.pi / 2.0 - 1e-4, vertical_fov_rad / 2.0))
    r = max(0.0, radius)
    s = r / (dist_clamped * math.tan(half_fov))
    return max(0.0, min(1.0, s))


def compute_screen_space_error_bound(
    radius: float, screen_size_fraction: float, tau_sse_pixels: float = 1.0, screen_height_px: int = 1080
) -> float:
    """
    Computes the maximum allowable world-space error delta_world (in meters)
    to ensure screen-space deviation <= tau_sse pixels at screen size S.
    Formula: delta_world = (2 * tau_sse * r) / (S * H)
    """
    s_clamped = max(0.001, min(1.0, screen_size_fraction))
    h = max(240, screen_height_px)
    tau = max(0.1, tau_sse_pixels)
    r = max(1e-4, radius)
    return (2.0 * tau * r) / (s_clamped * h)


def compute_coupled_tolerances(
    radius: float,
    screen_size_fraction: float,
    tau_sse_pixels: float = 1.0,
    screen_height_px: int = 1080,
    local_curvature_radius: float = 0.1,
) -> dict[str, float]:
    """
    Derives all decimation and cleanup tolerances from the master Screen-Space Error bound.
    """
    s = max(0.001, min(1.0, screen_size_fraction))
    r = max(1e-4, radius)
    delta_world = compute_screen_space_error_bound(r, s, tau_sse_pixels, screen_height_px)

    # 1. Epsilon Merge Distance (clamped between 1µm and 5% of radius)
    epsilon_merge = max(1e-6, min(r * 0.05, delta_world / 8.0))

    # 2. Sub-pixel Feature Dissolution threshold
    w_crit = delta_world

    # 3. Planar Bevel Angle Limit (degrees, clamped to max 45°)
    r_char = max(1e-3, local_curvature_radius)
    ratio_h = min(1.0, max(0.0, delta_world / r_char))
    cos_val = max(-1.0, min(1.0, 1.0 - ratio_h))
    planar_angle_deg = math.degrees(2.0 * math.acos(cos_val))
    planar_angle_clamped = max(0.5, min(45.0, planar_angle_deg))

    # 4. Critical Surface Area for Material Consolidation (m²)
    area_crit = (math.pi / 4.0) * (delta_world**2)

    # 5. Perceptual Power-Law QEM Decimation Ratio
    gamma = 1.5 * math.sqrt(max(0.2, tau_sse_pixels))
    qem_ratio = max(0.005, min(1.0, math.pow(s, gamma)))

    return {
        "delta_world": delta_world,
        "epsilon_merge": epsilon_merge,
        "w_crit": w_crit,
        "planar_angle_deg": planar_angle_clamped,
        "area_crit": area_crit,
        "qem_ratio": qem_ratio,
        "screen_size_fraction": s,
        "tau_sse": tau_sse_pixels,
    }


def generate_logarithmic_screen_tiers(num_lods: int, cull_screen_size_pct: float = 0.5) -> list[float]:
    """
    Generates geometrically/logarithmically distributed screen percentage thresholds
    from 100% down to cull_screen_size_pct.
    """
    if num_lods <= 1:
        return [100.0]

    cull_pct = max(0.01, min(50.0, cull_screen_size_pct))
    tiers = []
    for k in range(num_lods):
        if k == 0:
            tiers.append(100.0)
        elif k == num_lods - 1:
            tiers.append(round(cull_pct, 2))
        else:
            fraction = k / float(num_lods - 1)
            pct = 100.0 * math.pow(cull_pct / 100.0, fraction)
            tiers.append(round(pct, 2))
    return tiers
