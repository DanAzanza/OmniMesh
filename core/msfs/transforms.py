"""
MSFS Mathematical Coordinate Transformations.
Handles unit conversions (Feet <-> Meters) and axis permutations between
MSFS aircraft body frame and Blender coordinate space without bpy dependencies.
"""

from __future__ import annotations

import math

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


# =========================================================================
# ROTATION KINEMATICS & SYMMETRY MIRRORING
# =========================================================================


def _rot_matrix_x(angle_rad: float) -> list[list[float]]:
    c, s = math.cos(angle_rad), math.sin(angle_rad)
    return [[1.0, 0.0, 0.0], [0.0, c, -s], [0.0, s, c]]


def _rot_matrix_y(angle_rad: float) -> list[list[float]]:
    c, s = math.cos(angle_rad), math.sin(angle_rad)
    return [[c, 0.0, s], [0.0, 1.0, 0.0], [-s, 0.0, c]]


def _rot_matrix_z(angle_rad: float) -> list[list[float]]:
    c, s = math.cos(angle_rad), math.sin(angle_rad)
    return [[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]]


def _mat_mul(a: list[list[float]], b: list[list[float]]) -> list[list[float]]:
    return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]


def _matrix_to_euler_xyz(m: list[list[float]]) -> tuple[float, float, float]:
    """Extracts standard Blender XYZ Euler angles (in radians) from a 3x3 rotation matrix M = Rz * Ry * Rx."""
    m20 = max(-1.0, min(1.0, m[2][0]))
    ry = math.asin(-m20)
    cos_y = math.cos(ry)
    if abs(cos_y) > 1e-6:
        rx = math.atan2(m[2][1], m[2][2])
        rz = math.atan2(m[1][0], m[0][0])
    else:
        # Gimbal lock at ry = +/- 90 deg
        rx = math.atan2(-m[0][1], m[1][1])
        rz = 0.0
    return (rx, ry, rz)


def _euler_xyz_to_matrix(rx: float, ry: float, rz: float) -> list[list[float]]:
    """Constructs 3x3 rotation matrix from Blender XYZ Euler angles (in radians).

    In Blender, an XYZ Euler applies local X first, then local Y, then local Z,
    which corresponds to matrix product: M = Rz * Ry * Rx.
    """
    return _mat_mul(_rot_matrix_z(rz), _mat_mul(_rot_matrix_y(ry), _rot_matrix_x(rx)))


def msfs_pbh_to_blender_rotation(
    pitch_deg: float,
    bank_deg: float,
    heading_deg: float,
) -> tuple[float, float, float]:
    """
    Transforms MSFS Light/Camera orientation (Pitch, Bank, Heading in degrees)
    into Blender standard XYZ Euler angles (in radians) for a spotlight.

    MSFS Light Orientation:
        - At (0,0,0), light points along longitudinal flight vector (+Y).
        - Pitch > 0 points downward (e.g. landing lights angled down).
        - Heading > 0 turns to starboard (right).
        - Bank > 0 rolls right wing down.

    Blender Lamp Basis:
        - Spotlights emit along local -Z axis.
        - Applies basis transformation R_basis (X rot +90 deg) so zero-rotation
          spotlight shines forward (+Y) instead of downward (-Z).
    """
    p_rad = math.radians(pitch_deg)
    b_rad = math.radians(bank_deg)
    h_rad = math.radians(heading_deg)

    # Intrinsic aerospace rotation: Heading around Z, Pitch around X, Bank around Y
    # Heading right is negative Z in Blender right-handed system
    r_heading = _rot_matrix_z(-h_rad)
    r_pitch = _rot_matrix_x(-p_rad)
    r_bank = _rot_matrix_y(b_rad)

    r_msfs = _mat_mul(_mat_mul(r_heading, r_pitch), r_bank)

    # R_basis: maps local -Z to +Y (X rot +90 deg)
    r_basis = _rot_matrix_x(math.pi / 2.0)
    m_composite = _mat_mul(r_msfs, r_basis)

    return _matrix_to_euler_xyz(m_composite)


def blender_rotation_to_msfs_pbh(
    rx_rad: float,
    ry_rad: float,
    rz_rad: float,
) -> tuple[float, float, float]:
    """
    Inverts Blender spotlight/camera XYZ Euler angles (radians) back to MSFS
    aerospace orientation (Pitch, Bank, Heading in degrees).

    MSFS Aerospace Intrinsic Sequence:
        R_msfs = R_z(-heading) * R_x(-pitch) * R_y(bank)

    Blender Camera/Spot Basis:
        R_blender = R_msfs * R_basis
        R_msfs = R_blender * R_basis^-1
    """
    m_blender = _euler_xyz_to_matrix(rx_rad, ry_rad, rz_rad)
    r_basis_inv = _rot_matrix_x(-math.pi / 2.0)
    r_msfs = _mat_mul(m_blender, r_basis_inv)

    # Closed-form decomposition of R_z(-h) * R_x(-p) * R_y(b)
    # R[2][1] = -sin(p)
    m21 = max(-1.0, min(1.0, r_msfs[2][1]))
    pitch_rad = math.asin(-m21)
    pitch_deg = math.degrees(pitch_rad)
    cos_p = math.cos(pitch_rad)

    if abs(cos_p) > 1e-5:
        # Heading around Z (yaw right is positive): atan2(sin(h)*cos(p), cos(h)*cos(p))
        heading_deg = math.degrees(math.atan2(r_msfs[0][1], r_msfs[1][1]))
        # Bank around Y (roll right is positive): atan2(sin(b)*cos(p), cos(b)*cos(p))
        bank_deg = math.degrees(math.atan2(-r_msfs[2][0], r_msfs[2][2]))
    else:
        # Gimbal lock at Pitch = +/- 90 deg
        heading_deg = math.degrees(math.atan2(-r_msfs[1][0], r_msfs[0][0]))
        bank_deg = 0.0

    return (pitch_deg, bank_deg, heading_deg)


def msfs_zoom_to_blender_focal_length(zoom: float, base_focal_mm: float = 35.0) -> float:
    """Converts MSFS InitialZoom scalar to Blender camera focal length (mm).

    Uses a standard 35mm base lens for a 1.0 zoom level.
    Clamps zoom between 0.1 and 10.0.
    """
    clamped_zoom = max(0.1, min(10.0, zoom))
    return float(base_focal_mm * clamped_zoom)


def blender_focal_length_to_msfs_zoom(focal_mm: float, base_focal_mm: float = 35.0) -> float:
    """Converts Blender camera focal length (mm) back to MSFS InitialZoom scalar."""
    if base_focal_mm <= 0:
        return 1.0
    raw_zoom = focal_mm / base_focal_mm
    return float(round(max(0.1, min(10.0, raw_zoom)), 3))


def mirror_pbh_rotation(
    pitch_deg: float,
    bank_deg: float,
    heading_deg: float,
) -> tuple[float, float, float]:
    """
    Reflects an aerospace orientation across the aircraft sagittal symmetry plane (X = 0).
    Pitch remains identical, while Heading and Bank are reflected.
    """
    return (pitch_deg, -bank_deg, -heading_deg)


def mirror_spatial_coords(
    long_ft: float,
    lat_ft: float,
    vert_ft: float,
) -> tuple[float, float, float]:
    """Reflects an MSFS relative coordinate triplet across the sagittal symmetry plane (X = 0)."""
    return (long_ft, -lat_ft, vert_ft)
