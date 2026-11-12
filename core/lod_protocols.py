"""
Structural protocols for OmniMesh LOD Generation.
Decouples UI properties and headless mock doubles from core generator algorithms.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, Sequence

if TYPE_CHECKING:
    import bpy


class LODTierProtocol(Protocol):
    """Structural protocol for an individual LOD tier."""

    screen_size_pct: float
    target_tris_pct: float
    distance_m: float
    last_baked_target_pct: float
    last_baked_screen_pct: float
    actual_tris: int
    actual_triangles: int
    mat_slots_count: int
    generated_obj: bpy.types.Object | None
    state: str
    target_tris: int


class LODSettingsProtocol(Protocol):
    """Structural protocol for LOD tool settings across UI properties and headless doubles."""

    enable_slender_culling: bool
    tau_sse: float
    enable_occlusion_culling: bool
    occlusion_lod_start: int
    occlusion_ray_density: int
    occlusion_evaluate_alpha: bool
    pin_uv_seams: bool
    pin_material_borders: bool
    msfs_preserve_decals: bool
    purge_shape_keys: bool
    preserve_slot_indexing: bool
    enable_bone_pruning: bool
    max_bone_influences: int
    hierarchy_mode: str
    consolidate_hierarchy: bool
    merge_start_tier: int
    enable_impostor_lod: bool
    lods: Sequence[LODTierProtocol]
    last_culled_slender_count: int
    last_generated_base_tris: int
    last_generated_final_tris: int
    last_generated_reduction_pct: float
    last_generated_tier_count: int


__all__ = [
    "LODTierProtocol",
    "LODSettingsProtocol",
]
