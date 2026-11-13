# pyright: reportInvalidTypeForm=none
"""
OmniMesh Mesh & Material Cleanup PropertyGroup Mixin.
"""

from typing import TYPE_CHECKING, Any

from . import enums

if TYPE_CHECKING:
    from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty
else:
    try:
        from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty
    except ImportError:

        def _mock_prop(**kwargs: Any) -> Any:
            return None

        BoolProperty = EnumProperty = FloatProperty = IntProperty = _mock_prop


class LODToolCleanupSettingsMixin:
    """Mesh sanitization and material cleanup properties mixed into LODToolSettings."""

    # Mesh Cleanup & Topology Repair Settings
    auto_sanitize_before_lod: BoolProperty(
        name="Auto-Sanitize Before LOD",
        default=True,
        description="Run automatic base mesh sanitization when generating LODs",
    )
    cleanup_auto_apply_transforms: BoolProperty(
        name="Auto-Apply Scale & Rotation",
        default=False,
        description="Apply pending rotation and scale transforms before running mesh cleanup",
    )
    cleanup_apply_modifiers: BoolProperty(
        name="Apply Modifiers (Bake Viewport)",
        default=False,
        description="Bake and apply non-armature modifiers before running mesh cleanup",
    )
    cleanup_sync_viewport_settings: BoolProperty(
        name="Sync Viewport to Render Settings",
        default=True,
        description="Sync modifier viewport settings to render quality before baking modifiers",
    )
    cleanup_enable_weld: BoolProperty(
        name="Merge Close Vertices",
        default=False,
        description="Merge vertices closer than the weld distance threshold during cleanup",
    )
    cleanup_weld_distance: FloatProperty(
        name="Weld Distance",
        default=0.0005,
        min=0.00001,
        max=0.05,
        precision=5,
        unit="LENGTH",
        description="Maximum distance between vertices to merge when welding during cleanup",
    )
    cleanup_enable_split_non_manifold: BoolProperty(
        name="Repair Non-Manifold & Bowties",
        default=True,
        description="Split non-manifold edges and bowtie vertices during cleanup",
    )
    cleanup_enable_fill_holes: BoolProperty(
        name="Fill Small Holes",
        default=False,
        description="Automatically fill small open boundary holes during cleanup",
    )
    cleanup_hole_max_edges: IntProperty(
        name="Max Hole Edges",
        default=4,
        min=3,
        max=16,
        description="Maximum number of boundary edges allowed when automatically filling holes",
    )
    cleanup_enable_triangulate_ngons: BoolProperty(
        name="Triangulate N-Gons",
        default=False,
        description="Triangulate polygons with more than 4 vertices during cleanup",
    )
    cleanup_cull_interior_faces: BoolProperty(
        name="Remove Interior Polygons",
        default=False,
        description="Also remove enclosed interior polygons and internal shells during cleanup",
    )
    cleanup_normal_policy: EnumProperty(
        name="Normal Alignment",
        items=enums.CLEANUP_NORMAL_POLICY_ITEMS,
        default="MANIFOLD_ONLY",
        description="How face normals are reoriented during mesh cleanup",
    )

    # Material Cleanup & Slot Consolidation Settings
    mat_cleanup_purge_unused_slots: BoolProperty(
        name="Purge Empty & Unused Slots",
        default=True,
        description="Remove empty material slots and slots not assigned to any polygon",
    )
    mat_cleanup_deduplicate_slots: BoolProperty(
        name="Deduplicate Repeated Slots",
        default=True,
        description="Collapse repeated slots pointing to the same material on an object and remap polygon indices",
    )
    mat_cleanup_merge_duplicate_datablocks: BoolProperty(
        name="Merge Duplicate Materials (AST Hash)",
        default=True,
        description="Hash shader node graphs via AST and merge identical material datablocks across the scene",
    )
    mat_cleanup_remove_orphan_nodes: BoolProperty(
        name="Remove Dead Shader Nodes",
        default=True,
        description="Remove disconnected image texture nodes with zero linked outputs",
    )
    mat_cleanup_enable_micro_consolidation: BoolProperty(
        name="Consolidate Micro-Materials",
        default=False,
        description="Reassign tiny non-protected material regions below the area threshold to the dominant material",
    )
    mat_cleanup_micro_area_pct: FloatProperty(
        name="Micro Threshold %",
        default=0.5,
        min=0.01,
        max=5.0,
        precision=2,
        description="Surface area percentage below which a minor non-protected material is merged into the dominant material",
    )
    mat_cleanup_repair_missing_textures: BoolProperty(
        name="Repair Missing Textures",
        default=False,
        description="Unlink missing image texture nodes and restore neutral Principled BSDF defaults",
    )
    mat_cleanup_purge_orphans_blendfile: BoolProperty(
        name="Purge Orphan Materials from .blend",
        default=False,
        description="Delete unused zero-user material datablocks from the current .blend file",
    )


__all__ = ["LODToolCleanupSettingsMixin"]
