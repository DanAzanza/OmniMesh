"""
OmniMesh LOD Tier and Preset RNA Data Models.
Maintains data structures for LOD level items and template preset tier definitions.
"""

import copy
import logging
from typing import Any

from .guards import PresetSyncGuard, StateRestorationGuard

try:
    from ...core.lod_presets import (
        DEFAULT_LOD_PRESET_ID,
        LODPresetManager,
    )
except (ImportError, ValueError):
    from core.lod_presets import (
        DEFAULT_LOD_PRESET_ID,
        LODPresetManager,
    )

try:
    import bpy
    from bpy.props import (
        BoolProperty,
        EnumProperty,
        FloatProperty,
        IntProperty,
        PointerProperty,
        StringProperty,
    )
    from bpy.types import PropertyGroup
except ImportError:
    bpy = None
    PropertyGroup = object

    def BoolProperty(**kwargs: Any) -> Any:
        return None

    def EnumProperty(**kwargs: Any) -> Any:
        return None

    def FloatProperty(**kwargs: Any) -> Any:
        return None

    def IntProperty(**kwargs: Any) -> Any:
        return None

    def PointerProperty(**kwargs: Any) -> Any:
        return None

    def StringProperty(**kwargs: Any) -> Any:
        return None


logger = logging.getLogger(__name__)


def on_tier_target_pct_updated(self: Any, context: Any) -> None:
    """Synchronizes target_tris when target_tris_pct is modified."""
    if not context or not hasattr(context, "scene"):
        return
    props = getattr(context.scene, "lod_tool", None)
    if props and props.base_triangles > 0:
        val = max(12, int(props.base_triangles * (self.target_tris_pct / 100.0)))
        if self.target_tris != val:
            self["target_tris"] = val
            self["triangle_target"] = val


def on_tier_target_tris_updated(self: Any, context: Any) -> None:
    """Synchronizes target_tris_pct when target_tris is modified."""
    if not context or not hasattr(context, "scene"):
        return
    props = getattr(context.scene, "lod_tool", None)
    if props and props.base_triangles > 0:
        pct = round((self.target_tris / props.base_triangles) * 100.0, 1)
        clamped = max(0.01, min(100.0, pct))
        if abs(self.target_tris_pct - clamped) > 0.05:
            self["target_tris_pct"] = clamped


class LODLevelItem(PropertyGroup):
    """Data model representing a single generated or configured LOD tier."""

    name: StringProperty(name="Tier Name", default="LOD0")
    level_index: IntProperty(name="Level Index", default=0, min=0, max=7)
    lod_index: IntProperty(name="LOD Index", default=0, min=0, max=7)
    screen_size_pct: FloatProperty(
        name="Screen Size %",
        default=100.0,
        min=0.01,
        max=100.0,
        subtype="PERCENTAGE",
        precision=1,
        description="On-screen coverage percentage before transitioning to the next tier",
    )
    distance_m: FloatProperty(
        name="Switch Distance (m)",
        default=0.0,
        min=0.0,
        precision=2,
        description="Calculated camera distance for this tier transition",
    )
    triangle_target: IntProperty(name="Target Tris", default=0, min=0)
    target_tris: IntProperty(name="Target Tris", default=0, min=0, update=on_tier_target_tris_updated)
    actual_triangles: IntProperty(name="Actual Tris", default=0, min=0)
    actual_tris: IntProperty(name="Actual Tris", default=0, min=0)
    reduction_pct: FloatProperty(name="Reduction %", default=0.0, precision=1)
    mat_slots_count: IntProperty(name="Material Slots", default=0, min=0)
    target_tris_pct: FloatProperty(
        name="Target Tris %",
        default=100.0,
        min=0.001,
        max=100.0,
        subtype="PERCENTAGE",
        precision=1,
        description="Target triangle budget percentage relative to LOD0",
        update=on_tier_target_pct_updated,
    )
    is_soloed: BoolProperty(
        name="Solo Viewport",
        default=False,
        description="Whether this tier is currently isolated in the 3D Viewport",
    )
    is_impostor: BoolProperty(
        name="Is Impostor",
        default=False,
        description="Whether this tier is an impostor billboard representation",
    )
    state: EnumProperty(
        name="State",
        items=[
            ("SOURCE", "Source", "Original base mesh source geometry"),
            ("BAKED", "Baked", "Existing in scene and synchronized with configured parameters"),
            ("PLANNED", "Planned", "Projected tier not yet generated in the scene"),
            ("OUT_OF_SYNC", "Out of Sync", "Existing tier modified since last bake"),
        ],
        default="PLANNED",
    )
    last_baked_target_pct: FloatProperty(
        name="Last Baked Target %",
        default=-1.0,
        precision=2,
    )
    last_baked_screen_pct: FloatProperty(
        name="Last Baked Screen %",
        default=-1.0,
        precision=2,
    )
    generated_obj: PointerProperty(name="Mesh Object", type=bpy.types.Object if bpy else object)


def on_preset_tier_item_updated(self: Any, context: Any) -> None:
    """Flags active preset as modified when a tier setting is changed."""
    if not context or not hasattr(context, "scene"):
        return
    if PresetSyncGuard.is_locked() or StateRestorationGuard.is_active():
        return
    props = getattr(context.scene, "lod_tool", None)
    if props:
        props.lod_preset_is_dirty = True


def on_lod_preset_property_modified(self: Any, context: Any) -> None:
    """Flags active LOD preset as modified when any preset-backed setting changes."""
    if not context or not hasattr(context, "scene"):
        return
    if PresetSyncGuard.is_locked() or StateRestorationGuard.is_active():
        return
    props = getattr(context.scene, "lod_tool", None)
    if props:
        props.lod_preset_is_dirty = True


def on_split_preview_updated(self: Any, context: Any) -> None:
    """Forces 3D viewport redraw when split preview ratio or comparison tier changes."""
    if not bpy or not context:
        return
    wm = getattr(context, "window_manager", None)
    if not wm:
        return
    for window in getattr(wm, "windows", []):
        screen = getattr(window, "screen", None)
        if screen:
            for area in getattr(screen, "areas", []):
                if getattr(area, "type", "") == "VIEW_3D":
                    area.tag_redraw()


class LODPresetTierItem(PropertyGroup):
    """Data model representing a template tier within a configurable LOD preset."""

    name: StringProperty(name="Tier Name", default="LOD0", update=on_preset_tier_item_updated)
    screen_size_pct: FloatProperty(
        name="Screen Size %",
        default=100.0,
        min=0.01,
        max=100.0,
        subtype="PERCENTAGE",
        precision=1,
        update=on_preset_tier_item_updated,
    )
    target_tris_pct: FloatProperty(
        name="Target Tris %",
        default=100.0,
        min=0.001,
        max=100.0,
        subtype="PERCENTAGE",
        precision=2,
        update=on_preset_tier_item_updated,
    )
    target_tris: IntProperty(
        name="Target Tris",
        default=100000,
        min=1,
        update=on_preset_tier_item_updated,
    )


def sync_preset_tiers_from_preset(props: Any, preset: dict[str, Any]) -> None:
    """Populates ephemeral LOD preset tiers, chunking, impostor, culling, and pinning from preset under sync guard."""
    if not hasattr(props, "lod_preset_active_tiers"):
        return
    preset_id = preset.get("id", "") or preset.get("_id", "") or getattr(props, "lod_preset", "")
    with PresetSyncGuard():
        props.lod_preset_active_tiers.clear()
        props.lod_preset_active_id = str(preset_id)
        props.lod_preset_budget_mode = str(preset.get("budget_mode", "PERCENTAGE"))

        for t in preset.get("tiers", []):
            item = props.lod_preset_active_tiers.add()
            item.name = str(t.get("name", "LOD"))
            item.screen_size_pct = float(t.get("screen_size_pct", 100.0))
            item.target_tris_pct = float(t.get("target_tris_pct", 100.0))
            if "target_tris" in t:
                item.target_tris = int(t.get("target_tris", 1000))
            else:
                base = getattr(props, "base_triangles", 0) or 100000
                item.target_tris = max(1, int(base * (item.target_tris_pct / 100.0)))
        props.lod_preset_active_tier_index = 0

        # Hydrate chunking settings
        chunk_cfg = preset.get("chunking", {})
        if isinstance(chunk_cfg, dict):
            if hasattr(props, "enable_spatial_chunking"):
                props.enable_spatial_chunking = bool(chunk_cfg.get("enabled", False))
            if hasattr(props, "chunk_cell_size"):
                props.chunk_cell_size = float(chunk_cfg.get("cell_size", 32.0))
            if hasattr(props, "chunk_split_z"):
                props.chunk_split_z = bool(chunk_cfg.get("split_z", False))
            if hasattr(props, "chunk_cell_size_z"):
                props.chunk_cell_size_z = float(chunk_cfg.get("cell_size_z", 32.0))
            if hasattr(props, "chunk_partitioning_mode"):
                props.chunk_partitioning_mode = str(chunk_cfg.get("partitioning_mode", "UNIFORM_GRID"))
            if hasattr(props, "adaptive_cluster_target_polys"):
                props.adaptive_cluster_target_polys = int(chunk_cfg.get("adaptive_target_polys", 50000))
            if hasattr(props, "enable_hlod"):
                props.enable_hlod = bool(chunk_cfg.get("enable_hlod", True))
            if hasattr(props, "hlod_start_tier"):
                props.hlod_start_tier = int(chunk_cfg.get("hlod_start_tier", 2))

        # Hydrate impostor settings
        imp_cfg = preset.get("impostor", {})
        if isinstance(imp_cfg, dict):
            if hasattr(props, "enable_impostor_lod"):
                props.enable_impostor_lod = bool(imp_cfg.get("enabled", False))
            if hasattr(props, "impostor_mode"):
                props.impostor_mode = str(imp_cfg.get("mode", "CROSS_QUADS"))
            if hasattr(props, "impostor_resolution"):
                props.impostor_resolution = str(imp_cfg.get("resolution", "2048"))
            if hasattr(props, "impostor_replace_last_lod"):
                props.impostor_replace_last_lod = bool(imp_cfg.get("replace_last_lod", True))

        # Hydrate culling settings
        cull_cfg = preset.get("culling", {})
        if isinstance(cull_cfg, dict):
            if hasattr(props, "enable_occlusion_culling"):
                props.enable_occlusion_culling = bool(cull_cfg.get("occlusion_enabled", True))
            if hasattr(props, "occlusion_lod_start"):
                props.occlusion_lod_start = int(cull_cfg.get("occlusion_lod_start", 1))
            if hasattr(props, "occlusion_ray_density"):
                props.occlusion_ray_density = int(cull_cfg.get("occlusion_ray_density", 16))
            if hasattr(props, "occlusion_evaluate_alpha"):
                props.occlusion_evaluate_alpha = bool(cull_cfg.get("occlusion_evaluate_alpha", True))
            if hasattr(props, "enable_slender_culling"):
                props.enable_slender_culling = bool(cull_cfg.get("slender_enabled", True))

        # Hydrate seam pinning settings
        pin_cfg = preset.get("pinning", {})
        if isinstance(pin_cfg, dict):
            if hasattr(props, "pin_uv_seams"):
                props.pin_uv_seams = bool(pin_cfg.get("pin_uv_seams", True))
            if hasattr(props, "pin_material_borders"):
                props.pin_material_borders = bool(pin_cfg.get("pin_material_borders", True))

        # Hydrate tau_sse
        if "tau_sse" in preset and hasattr(props, "tau_sse"):
            props.tau_sse = float(preset["tau_sse"])

        # Guarantee pristine dirty state at end of hydration
        props.lod_preset_is_dirty = False


def sync_preset_tiers_to_preset(props: Any, preset_id: str | None = None) -> str:
    """Serializes active LOD preset tiers, chunking, impostor, culling, and pinning to JSON on disk."""
    target_id: str = str(preset_id or getattr(props, "lod_preset", "") or DEFAULT_LOD_PRESET_ID)

    preset_data = copy.deepcopy(LODPresetManager.get_preset(target_id))
    preset_data["budget_mode"] = getattr(props, "lod_preset_budget_mode", "PERCENTAGE")
    preset_data["version"] = 2
    if hasattr(props, "tau_sse"):
        preset_data["tau_sse"] = round(float(props.tau_sse), 3)

    new_tiers: list[dict[str, Any]] = []
    for item in props.lod_preset_active_tiers:
        tier_dict: dict[str, Any] = {
            "name": item.name,
            "screen_size_pct": round(item.screen_size_pct, 2),
            "target_tris_pct": round(item.target_tris_pct, 2),
            "is_pinned": bool(getattr(item, "is_pinned", False)),
            "is_impostor": bool(getattr(item, "is_impostor", False)),
        }
        new_tiers.append(tier_dict)
    preset_data["tiers"] = new_tiers

    # Serialize chunking block
    preset_data["spatial_chunking"] = {
        "enabled": bool(getattr(props, "enable_spatial_chunking", False)),
        "max_chunk_size_m": float(getattr(props, "spatial_chunk_size", 50.0)),
        "max_tris_per_chunk": int(getattr(props, "spatial_chunk_max_tris", 15000)),
        "generation_mode": str(getattr(props, "spatial_chunk_mode", "AUTOMATIC")),
    }

    # Serialize impostor block
    preset_data["impostor"] = {
        "enabled": bool(getattr(props, "enable_impostor_lod", False)),
        "texture_resolution": int(getattr(props, "impostor_texture_resolution", 1024)),
        "angle_steps": int(getattr(props, "impostor_angle_steps", 16)),
    }

    # Serialize slender culling block
    preset_data["slender_feature_culling"] = {
        "enabled": bool(getattr(props, "enable_slender_culling", False)),
        "threshold_px": float(getattr(props, "slender_culling_threshold_px", 1.5)),
    }

    # Serialize seam pinning block
    preset_data["pinning"] = {
        "pin_uv_seams": bool(getattr(props, "pin_uv_seams", True)),
        "pin_material_borders": bool(getattr(props, "pin_material_borders", True)),
    }

    # Direct unrestricted save to preset
    LODPresetManager.save_custom_preset(preset_data, custom_id=target_id)
    props.lod_preset_active_id = target_id
    props.lod_preset_is_dirty = False
    return target_id


__all__ = [
    "LODLevelItem",
    "LODPresetTierItem",
    "on_tier_target_pct_updated",
    "on_tier_target_tris_updated",
    "on_preset_tier_item_updated",
    "on_lod_preset_property_modified",
    "on_split_preview_updated",
    "sync_preset_tiers_from_preset",
    "sync_preset_tiers_to_preset",
]
