"""
OmniMesh Vehicle Config Preset Anchor Geometry Positioning Engine.
Computes world-space anchor locations from normalized bounding box dimensions and detected wheel contact points.
"""

from __future__ import annotations


from .compat import Vector


def compute_preset_anchor_position(
    anchor_name: str,
    offset_norm: list[float],
    extrema: dict[str, tuple[float, float, float]],
    bbox_min: Vector,
    bbox_max: Vector,
    detected_wheels: dict[str, tuple[float, float, float]] | None = None,
) -> Vector:
    """Computes world-space coordinate for a given named anchor and normalized offset.

    Adapts proportionally to bounding box dimensions and detected wheel contact points.
    """
    half_span = max(0.1, (bbox_max.x - bbox_min.x) * 0.5)
    length = max(0.1, bbox_max.y - bbox_min.y)
    height = max(0.1, bbox_max.z - bbox_min.z)
    bbox_center = (bbox_min + bbox_max) * 0.5

    ox = float(offset_norm[0]) if len(offset_norm) > 0 else 0.0
    oy = float(offset_norm[1]) if len(offset_norm) > 1 else 0.0
    oz = float(offset_norm[2]) if len(offset_norm) > 2 else 0.0

    # 1. Direct detected wheel contact point matching
    if detected_wheels and anchor_name in detected_wheels:
        base = Vector(detected_wheels[anchor_name])
        if not offset_norm or (
            len(offset_norm) >= 3 and offset_norm[0] == 0.0 and offset_norm[1] == 0.0 and offset_norm[2] == 0.0
        ):
            return base
        return Vector((base.x + ox * half_span, base.y + oy * length, base.z + oz * height))

    # 2. Named geometric extrema and archetypes
    if anchor_name == "EXTREMA_NOSE" and "Scrape_Nose" in extrema:
        base = Vector(extrema["Scrape_Nose"])
    elif anchor_name == "EXTREMA_TAIL" and "Scrape_Tail" in extrema:
        base = Vector(extrema["Scrape_Tail"])
    elif anchor_name == "EXTREMA_WING_L" and "Scrape_Wing_L" in extrema:
        base = Vector(extrema["Scrape_Wing_L"])
    elif anchor_name == "EXTREMA_WING_R" and "Scrape_Wing_R" in extrema:
        base = Vector(extrema["Scrape_Wing_R"])
    elif anchor_name == "EXTREMA_FIN" and "Scrape_Fin" in extrema:
        base = Vector(extrema["Scrape_Fin"])
    elif anchor_name in ("COCKPIT_ESTIMATE", "EXTREMA_COCKPIT"):
        base = Vector((bbox_center.x, bbox_center.y + 0.2 * length, bbox_center.z + 0.15 * height))
    elif anchor_name in ("AABB_MIN_Z", "EXTREMA_BELLY"):
        base = Vector((bbox_center.x, bbox_center.y, bbox_min.z))
    # Wheel contact points (proportional fallback when no separate wheel mesh detected)
    elif anchor_name in ("WHEEL_NOSE", "WHEEL_FRONT"):
        base = Vector((bbox_center.x, bbox_center.y + 0.35 * length, bbox_min.z))
    elif anchor_name == "WHEEL_LEFT":
        base = Vector((bbox_center.x - 0.25 * half_span, bbox_center.y - 0.1 * length, bbox_min.z))
    elif anchor_name == "WHEEL_RIGHT":
        base = Vector((bbox_center.x + 0.25 * half_span, bbox_center.y - 0.1 * length, bbox_min.z))
    elif anchor_name == "WHEEL_FRONT_L":
        base = Vector((bbox_center.x - 0.35 * half_span, bbox_center.y + 0.3 * length, bbox_min.z))
    elif anchor_name == "WHEEL_FRONT_R":
        base = Vector((bbox_center.x + 0.35 * half_span, bbox_center.y + 0.3 * length, bbox_min.z))
    elif anchor_name == "WHEEL_REAR_L":
        base = Vector((bbox_center.x - 0.35 * half_span, bbox_center.y - 0.3 * length, bbox_min.z))
    elif anchor_name == "WHEEL_REAR_R":
        base = Vector((bbox_center.x + 0.35 * half_span, bbox_center.y - 0.3 * length, bbox_min.z))
    elif anchor_name == "WHEEL_TAIL":
        base = Vector((bbox_center.x, bbox_center.y - 0.45 * length, bbox_min.z))
    # Ground vehicle anchors
    elif anchor_name == "EXTREMA_BUMPER_F_L":
        base = Vector(extrema.get("Scrape_Bumper_F_L", (bbox_min.x, bbox_max.y, bbox_min.z + 0.05 * height)))
    elif anchor_name == "EXTREMA_BUMPER_F_R":
        base = Vector(extrema.get("Scrape_Bumper_F_R", (bbox_max.x, bbox_max.y, bbox_min.z + 0.05 * height)))
    elif anchor_name == "EXTREMA_BUMPER_R_L":
        base = Vector(extrema.get("Scrape_Bumper_R_L", (bbox_min.x, bbox_min.y, bbox_min.z + 0.05 * height)))
    elif anchor_name == "EXTREMA_BUMPER_R_R":
        base = Vector(extrema.get("Scrape_Bumper_R_R", (bbox_max.x, bbox_min.y, bbox_min.z + 0.05 * height)))
    elif anchor_name == "EXTREMA_ROOF":
        base = Vector(extrema.get("Scrape_Roof", (bbox_center.x, bbox_center.y, bbox_max.z)))
    elif anchor_name == "HEADLIGHT_L":
        base = Vector((bbox_min.x + 0.2 * half_span, bbox_max.y, bbox_min.z + 0.35 * height))
    elif anchor_name == "HEADLIGHT_R":
        base = Vector((bbox_max.x - 0.2 * half_span, bbox_max.y, bbox_min.z + 0.35 * height))
    elif anchor_name == "TAILLIGHT_L":
        base = Vector((bbox_min.x + 0.2 * half_span, bbox_min.y, bbox_min.z + 0.45 * height))
    elif anchor_name == "TAILLIGHT_R":
        base = Vector((bbox_max.x - 0.2 * half_span, bbox_min.y, bbox_min.z + 0.45 * height))
    elif anchor_name == "DRIVER_SEAT":
        base = Vector((bbox_center.x - 0.35 * half_span, bbox_center.y - 0.05 * length, bbox_min.z + 0.55 * height))
    elif anchor_name == "PASSENGER_SEAT":
        base = Vector((bbox_center.x + 0.35 * half_span, bbox_center.y - 0.05 * length, bbox_min.z + 0.55 * height))
    elif anchor_name == "CHASE_CAMERA":
        base = Vector((bbox_center.x, bbox_min.y - 0.4 * length, bbox_max.z + 0.3 * height))
    elif anchor_name == "ROTOR_HUB_MAIN":
        base = Vector((bbox_center.x, bbox_center.y, bbox_max.z))
    elif anchor_name == "ROTOR_HUB_TAIL":
        base = Vector((bbox_center.x, bbox_min.y, bbox_center.z + 0.2 * height))
    elif anchor_name == "FLOAT_LEFT_KEEL":
        base = Vector((bbox_center.x + 0.25 * half_span, bbox_center.y, bbox_min.z))
    elif anchor_name == "FLOAT_RIGHT_KEEL":
        base = Vector((bbox_center.x - 0.25 * half_span, bbox_center.y, bbox_min.z))
    elif anchor_name == "TOW_HOOK":
        base = Vector((bbox_center.x, bbox_max.y, bbox_min.z + 0.1 * height))
    elif anchor_name == "AABB_ORIGIN":
        base = Vector((0.0, 0.0, 0.0))
    elif anchor_name == "AABB_CENTER":
        base = bbox_center
    else:
        base = bbox_center

    return Vector((base.x + ox * half_span, base.y + oy * length, base.z + oz * height))


__all__ = ["compute_preset_anchor_position"]
