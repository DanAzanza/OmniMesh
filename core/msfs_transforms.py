"""
MSFS Mathematical Coordinate Transformations.
Handles unit conversions (Feet <-> Meters) and axis permutations between
MSFS aircraft body frame and Blender coordinate space without bpy dependencies.
"""

from __future__ import annotations

FEET_TO_METERS: float = 0.3048
METERS_TO_FEET: float = 1.0 / 0.3048


def msfs_to_blender(
    long_ft: float,
    lat_ft: float,
    vert_ft: float,
    datum_ft: tuple[float, float, float] = (0.0, 0.0, 0.0),
) -> tuple[float, float, float]:
    """
    Transforms MSFS coordinate triplet (Longitudinal, Lateral, Vertical) in feet
    relative to reference datum into Blender world coordinates (X, Y, Z) in meters.

    MSFS Frame:
        Longitudinal: + Forward, - Aft
        Lateral:      + Right,   - Left
        Vertical:     + Up,      - Down

    Blender Frame:
        X: Lateral Right (Starboard)
        Y: Longitudinal Forward (Nose)
        Z: Vertical Up (Dorsal)
    """
    abs_long = long_ft + datum_ft[0]
    abs_lat = lat_ft + datum_ft[1]
    abs_vert = vert_ft + datum_ft[2]

    blender_x = abs_lat * FEET_TO_METERS
    blender_y = abs_long * FEET_TO_METERS
    blender_z = abs_vert * FEET_TO_METERS

    return (blender_x, blender_y, blender_z)


def blender_to_msfs(
    x_m: float,
    y_m: float,
    z_m: float,
    datum_ft: tuple[float, float, float] = (0.0, 0.0, 0.0),
) -> tuple[float, float, float]:
    """
    Transforms Blender world coordinates (X, Y, Z) in meters into MSFS
    coordinate triplet (Longitudinal, Lateral, Vertical) in feet relative to datum.
    """
    abs_lat = x_m * METERS_TO_FEET
    abs_long = y_m * METERS_TO_FEET
    abs_vert = z_m * METERS_TO_FEET

    rel_long = abs_long - datum_ft[0]
    rel_lat = abs_lat - datum_ft[1]
    rel_vert = abs_vert - datum_ft[2]

    return (rel_long, rel_lat, rel_vert)


def format_coordinate_float(val: float, precision: int = 4) -> str:
    """
    Formats a floating-point coordinate cleanly to prevent floating-point
    precision drift and git churn (e.g. 4.0 instead of 4.000000000000001).
    """
    if abs(val) < 1e-6:
        return "0"

    formatted = f"{val:.{precision}f}"
    if "." in formatted:
        formatted = formatted.rstrip("0").rstrip(".")
    if formatted == "-0":
        return "0"
    return formatted
