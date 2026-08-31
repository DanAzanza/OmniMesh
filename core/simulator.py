"""
Core Engine for Live Viewport LOD Simulator & Camera Distance Evaluation.
"""

from __future__ import annotations

import math
from typing import Any

try:
    import bpy
    from mathutils import Matrix, Vector
except ImportError:
    bpy = None
    Vector = None
    Matrix = None


def calculate_effective_distance_pure(
    cam_pos: tuple[float, float, float], center: tuple[float, float, float], radius: float
) -> float:
    """
    Near-point conservative distance solver:
    d_eff = max(0.01, ||P_cam - C_A|| - 0.5 * r_A)
    """
    dx = cam_pos[0] - center[0]
    dy = cam_pos[1] - center[1]
    dz = cam_pos[2] - center[2]
    d_center = math.sqrt(dx * dx + dy * dy + dz * dz)
    return max(0.01, d_center - 0.5 * radius)


def evaluate_lod_tier_index_pure(
    screen_size_pct: float, tier_thresholds_pct: list[float], current_tier: int = 0, hysteresis_pct: float = 2.0
) -> int:
    """
    Selects the active LOD tier index based on descending switch-points.
    LOD 0 is active for S >= threshold[1]
    LOD i is active for threshold[i+1] <= S < threshold[i]
    LOD N-1 is active for S < threshold[N-1]
    """
    if not tier_thresholds_pct or len(tier_thresholds_pct) <= 1:
        return 0

    num_tiers = len(tier_thresholds_pct)

    for i in range(num_tiers - 1):
        switch_threshold = tier_thresholds_pct[i + 1]

        if current_tier == i:
            effective_threshold = switch_threshold * (1.0 - hysteresis_pct / 100.0)
        elif current_tier == i + 1:
            effective_threshold = switch_threshold * (1.0 + hysteresis_pct / 100.0)
        else:
            effective_threshold = switch_threshold

        if screen_size_pct >= effective_threshold:
            return i

    return num_tiers - 1


def extract_viewport_camera_params(space_3d: Any, region_3d: Any, region: Any, scene: Any) -> tuple[Any, float, bool]:
    """
    Extracts camera world position, vertical FOV (rad), and perspective status.
    Supports Perspective Free Viewport, Orthographic Free Viewport, and Scene Camera.
    """
    if not region_3d:
        cam_pos = scene.camera.matrix_world.translation.copy() if (scene and scene.camera) else Vector((0, -5, 2))
        return cam_pos, math.radians(60.0), True

    is_perspective = region_3d.is_perspective

    # Scene Camera View
    if region_3d.view_perspective == "CAMERA" and getattr(space_3d, "use_local_camera", False) is False:
        cam = getattr(space_3d, "camera", None) or (scene.camera if scene else None)
        if cam and cam.type == "CAMERA":
            cam_pos = cam.matrix_world.translation.copy()
            cam_data = cam.data
            render = scene.render
            aspect = (render.resolution_x * render.pixel_aspect_x) / max(
                1.0, (render.resolution_y * render.pixel_aspect_y)
            )
            sensor_fit = cam_data.sensor_fit
            if sensor_fit == "AUTO":
                sensor_fit = "HORIZONTAL" if aspect >= 1.0 else "VERTICAL"

            if cam_data.type == "PERSP":
                if sensor_fit == "VERTICAL":
                    fov_v = cam_data.angle_y if hasattr(cam_data, "angle_y") else cam_data.angle
                else:
                    fov_v = 2.0 * math.atan(math.tan(cam_data.angle / 2.0) / max(1e-4, aspect))
                return cam_pos, max(1e-4, fov_v), True
            else:
                return cam_pos, max(1e-3, cam_data.ortho_scale), False

    # Free Viewport Orbit / Pan View
    cam_pos = region_3d.view_matrix.inverted().translation.copy()

    if is_perspective:
        sensor_height = 24.0
        focal_mm = max(1.0, getattr(space_3d, "lens", 50.0))
        h = max(1.0, float(region.height)) if region else 1080.0
        w = max(1.0, float(region.width)) if region else 1920.0
        aspect = w / h
        fov_v = 2.0 * math.atan((sensor_height / 2.0) / focal_mm)
        if aspect < 1.0:
            fov_v = fov_v / aspect
        return cam_pos, max(1e-4, fov_v), True
    else:
        ortho_extent = region_3d.view_distance * 2.0
        return cam_pos, max(1e-3, ortho_extent), False


class LODAssetRecord:
    def __init__(self, collection_name: str, root_name: str):
        self.collection_name = collection_name
        self.root_name = root_name
        self.tier_objects: dict[int, list[Any]] = {}
        self.center: Any = Vector((0, 0, 0)) if Vector else (0.0, 0.0, 0.0)
        self.radius: float = 1.0
        self.tier_screen_pcts: list[float] = []
        self.tier_distances: list[float] = []
        self.current_tier: int = 0
        self.is_valid: bool = False

    def update_bounds_and_tiers(self):
        if not bpy:
            return
        coll = bpy.data.collections.get(self.collection_name)
        if not coll or len(coll.objects) == 0:
            self.is_valid = False
            return

        self.tier_objects.clear()
        all_coords = []

        for obj in coll.objects:
            if obj.type != "MESH":
                continue
            tier_idx = 0
            for i in range(10):
                if f"_LOD{i}" in obj.name:
                    tier_idx = i
                    break

            if tier_idx not in self.tier_objects:
                self.tier_objects[tier_idx] = []
            self.tier_objects[tier_idx].append(obj)

            m_w = obj.matrix_world
            all_coords.extend([m_w @ v.co for v in obj.data.vertices])

        if not all_coords:
            self.is_valid = False
            return

        center = sum(all_coords, Vector()) / len(all_coords)
        radius = max((co - center).length for co in all_coords)
        self.center = center
        self.radius = max(0.01, radius)
        self.is_valid = True


class LODSimulatorEngine:
    _tracked_assets: dict[str, LODAssetRecord] = {}

    @classmethod
    def index_scene_assets(cls, scene: Any) -> int:
        if not bpy:
            return 0
        cls._tracked_assets.clear()

        default_tiers_pct = [100.0, 50.0, 25.0, 10.0, 5.0, 2.0, 0.5]
        if hasattr(scene, "lod_tool") and len(scene.lod_tool.lods) > 0:
            default_tiers_pct = [t.screen_size_pct for t in scene.lod_tool.lods]

        for coll in bpy.data.collections:
            if coll.name.endswith("_LODs"):
                root_name = coll.name[:-5]
                record = LODAssetRecord(coll.name, root_name)
                record.update_bounds_and_tiers()
                record.tier_screen_pcts = list(default_tiers_pct)
                if record.is_valid:
                    cls._tracked_assets[coll.name] = record

        return len(cls._tracked_assets)

    @classmethod
    def get_tracked_assets(cls) -> dict[str, LODAssetRecord]:
        return cls._tracked_assets

    @classmethod
    def update_simulation_tick(
        cls,
        context: Any,
        cam_pos: Any,
        fov_v_rad: float,
        is_perspective: bool,
        virtual_override_pct: float | None = None,
    ) -> list[dict[str, Any]]:
        if not bpy or not context:
            return []

        view_layer = context.view_layer
        updates = []

        for _coll_name, record in cls._tracked_assets.items():
            if not record.is_valid:
                continue

            if virtual_override_pct is not None:
                target_tier = evaluate_lod_tier_index_pure(
                    virtual_override_pct, record.tier_screen_pcts, current_tier=record.current_tier
                )
                eff_dist = record.radius / max(0.001, (virtual_override_pct / 100.0) * math.tan(fov_v_rad / 2.0))
                screen_pct = virtual_override_pct
            else:
                c = record.center
                cp = cam_pos
                d_eff = calculate_effective_distance_pure((cp.x, cp.y, cp.z), (c.x, c.y, c.z), record.radius)
                eff_dist = d_eff

                if is_perspective:
                    s_frac = record.radius / max(0.001, d_eff * math.tan(fov_v_rad / 2.0))
                    screen_pct = min(100.0, s_frac * 100.0)
                else:
                    s_frac = (2.0 * record.radius) / max(0.01, fov_v_rad)
                    screen_pct = min(100.0, s_frac * 100.0)

                target_tier = evaluate_lod_tier_index_pure(
                    screen_pct, record.tier_screen_pcts, current_tier=record.current_tier
                )

            record.current_tier = target_tier
            for tier_idx, objs in record.tier_objects.items():
                is_active = tier_idx == target_tier
                should_hide = not is_active

                for obj in objs:
                    if obj.hide_get(view_layer=view_layer) != should_hide:
                        obj.hide_set(should_hide, view_layer=view_layer)

            active_objs = record.tier_objects.get(target_tier, [])
            active_tris = sum(len(o.data.polygons) for o in active_objs if o.type == "MESH")

            updates.append(
                {
                    "root_name": record.root_name,
                    "current_tier": target_tier,
                    "distance_m": eff_dist,
                    "screen_pct": screen_pct,
                    "active_tris": active_tris,
                }
            )

        return updates

    @classmethod
    def restore_all_visibility(cls, context: Any):
        if not bpy or not context:
            return
        view_layer = context.view_layer
        for record in cls._tracked_assets.values():
            for objs in record.tier_objects.values():
                for obj in objs:
                    if obj.hide_get(view_layer=view_layer):
                        obj.hide_set(False, view_layer=view_layer)
