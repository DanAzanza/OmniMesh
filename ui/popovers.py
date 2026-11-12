"""
OmniMesh Popover Panels for Blender 5.0+ and 5.2 LTS.
Declares secondary configuration popovers invoked via gear icons (`layout.popover`).

Design Invariants:
- Omit `bl_category` to prevent ghost tabs in the N-Panel.
- Omit `bl_parent_id` to prevent accordion collision.
- Declare `bl_ui_units_x = 16` (or 18) to prevent label/slider truncation in popups.
- Preset popovers are maintained in ui.popover_presets and re-exported here for unified registration.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    import bpy
    from bpy.types import Panel
else:
    try:
        import bpy
        from bpy.types import Panel
    except ImportError:
        bpy = None
        Panel = object

from .utils import _get_popover_props

# Re-export preset popovers from ui.popover_presets
from .popover_presets import (
    OMNIMESH_PT_popover_config_preset,
    OMNIMESH_PT_popover_engine_import_preset,
    OMNIMESH_PT_popover_export_preset,
    OMNIMESH_PT_popover_import_preset,
    OMNIMESH_PT_popover_lod_preset,
)


# =========================================================================
# 1. MODIFY POPOVERS: SANITIZE, MATERIALS & COLLISION
# =========================================================================


class OMNIMESH_PT_popover_sanitize(Panel):
    """Popover for mesh sanitization, transform normalization, and geometry repair settings."""

    bl_idname = "OMNIMESH_PT_popover_sanitize"
    bl_label = "Sanitization Settings"
    bl_space_type = "VIEW_3D"
    bl_region_type = "HEADER"
    bl_ui_units_x = 16

    def draw(self, context: Any) -> None:
        if not bpy or not context or not self.layout:
            return
        layout = self.layout
        props = _get_popover_props(context)
        if not props:
            return

        # 1. Transform & Modifiers
        layout.label(text="Transform & Modifiers", icon="OBJECT_ORIGIN")
        layout.prop(props, "cleanup_auto_apply_transforms", text="Auto-Apply Transforms")
        layout.prop(props, "cleanup_apply_modifiers", text="Bake / Apply Modifiers")

        layout.separator()

        # 2. Topology Repair Options
        layout.label(text="Topology Repair Options", icon="PREFERENCES")
        layout.prop(props, "cleanup_enable_split_non_manifold", text="Repair Non-Manifold & Bowties")
        layout.prop(props, "cleanup_normal_policy", text="Normals")

        row_w = layout.row(align=True)
        row_w.prop(props, "cleanup_enable_weld", text="Merge Close")
        if props.cleanup_enable_weld:
            row_w.prop(props, "cleanup_weld_distance", text="Dist")

        row_h = layout.row(align=True)
        row_h.prop(props, "cleanup_enable_fill_holes", text="Fill Holes")
        if props.cleanup_enable_fill_holes:
            row_h.prop(props, "cleanup_hole_max_edges", text="Max Edges")

        layout.prop(props, "cleanup_enable_triangulate_ngons", text="Triangulate N-Gons")

        layout.separator()
        layout.label(text="Interior Occlusion Culling", icon="XRAY")
        layout.prop(props, "cleanup_cull_interior_faces", text="Remove Interior Polygons on Clean")
        row_occ = layout.row(align=True)
        row_occ.prop(props, "occlusion_ray_density", text="Rays")
        row_occ.prop(props, "occlusion_evaluate_alpha", text="Alpha")


class OMNIMESH_PT_popover_materials(Panel):
    """Popover for material cleanup, AST-hash deduplication, and micro-material consolidation."""

    bl_idname = "OMNIMESH_PT_popover_materials"
    bl_label = "Material Cleanup Settings"
    bl_space_type = "VIEW_3D"
    bl_region_type = "HEADER"
    bl_ui_units_x = 16

    def draw(self, context: Any) -> None:
        if not bpy or not context or not self.layout:
            return
        layout = self.layout
        props = _get_popover_props(context)
        if not props:
            return

        layout.label(text="Safe Operations (Default ON)", icon="CHECKMARK")
        layout.prop(props, "mat_cleanup_purge_unused_slots", text="Purge Unused Slots")
        layout.prop(props, "mat_cleanup_deduplicate_slots", text="Deduplicate Repeated Slots")
        layout.prop(props, "mat_cleanup_merge_duplicate_datablocks", text="Merge Duplicate Materials (AST Hash)")
        layout.prop(props, "mat_cleanup_remove_orphan_nodes", text="Remove Dead Shader Nodes")

        layout.separator()
        layout.label(text="Critical Operations (Opt-In)", icon="ERROR")
        layout.prop(props, "mat_cleanup_enable_micro_consolidation", text="Consolidate Micro-Materials")
        if props.mat_cleanup_enable_micro_consolidation:
            layout.prop(props, "mat_cleanup_micro_area_pct", text="Threshold %")
        layout.prop(props, "mat_cleanup_repair_missing_textures", text="Repair Missing Textures")
        layout.prop(props, "mat_cleanup_purge_orphans_blendfile", text="Purge Orphan Materials from .blend")


class OMNIMESH_PT_popover_collision(Panel):
    """Popover for convex collision hull generation and physics decomposition settings."""

    bl_idname = "OMNIMESH_PT_popover_collision"
    bl_label = "Collision Hull Settings"
    bl_space_type = "VIEW_3D"
    bl_region_type = "HEADER"
    bl_ui_units_x = 16

    def draw(self, context: Any) -> None:
        if not bpy or not context or not self.layout:
            return
        layout = self.layout
        props = _get_popover_props(context)
        if not props:
            return

        layout.label(text="Physics Decomposition", icon="MOD_PHYSICS")
        layout.prop(props, "collision_decomposition_mode", text="Mode")

        if props.collision_decomposition_mode in {"PER_OBJECT", "CONSOLIDATED"}:
            layout.prop(props, "collision_hull_count", text="Hull Count")
            layout.prop(props, "collision_concavity_threshold", text="Concavity (m)")

        layout.separator()
        layout.label(text="Engine Constraints", icon="PREFERENCES")
        layout.prop(props, "collision_max_verts_per_hull", text="Max Verts / Hull")


# =========================================================================
# 2. LODs POPOVERS: GENERATE & IMPOSTOR
# =========================================================================


class OMNIMESH_PT_popover_generate(Panel):
    """Popover for advanced LOD generation heuristics (Rigging, Draw-Calls, Chunking)."""

    bl_idname = "OMNIMESH_PT_popover_generate"
    bl_label = "Generation & Optimization Settings"
    bl_space_type = "VIEW_3D"
    bl_region_type = "HEADER"
    bl_ui_units_x = 16

    def draw(self, context: Any) -> None:
        if not bpy or not context or not self.layout:
            return
        layout = self.layout
        props = _get_popover_props(context)
        if not props:
            return

        layout.label(text="Hierarchy & Draw-Calls", icon="OUTLINER_OB_GROUP_INSTANCE")
        layout.prop(props, "hierarchy_mode", text="Mode")
        if props.hierarchy_mode == "MERGE_AT_TIER":
            layout.prop(props, "merge_start_tier", text="Merge From Tier")
        layout.prop(props, "preserve_slot_indexing", text="Preserve Slot Indexing")

        layout.separator()
        layout.label(text="Rigging & Deform Kinematics", icon="ARMATURE_DATA")
        layout.prop(props, "max_bone_influences", text="Max Bone Influences")
        layout.prop(props, "enable_bone_pruning", text="Leaf Bone Pruning")
        layout.prop(props, "purge_shape_keys", text="Purge Distant Shape Keys")


class OMNIMESH_PT_popover_impostor(Panel):
    """Dedicated Quick Configuration Popover for Billboard Impostors."""

    bl_label = "Billboard Impostor Settings"
    bl_idname = "OMNIMESH_PT_popover_impostor"
    bl_space_type = "VIEW_3D"
    bl_region_type = "HEADER"
    bl_ui_units_x = 18

    def draw(self, context: Any) -> None:
        if not bpy or not context or not self.layout:
            return
        layout = self.layout
        props = _get_popover_props(context)
        if not props:
            return

        layout.label(text="Billboard Impostor Settings", icon="IMAGE_PLANE")
        box = layout.box()
        box.use_property_split = True
        box.use_property_decorate = False
        box.prop(props, "impostor_mode", text="Mode")
        box.prop(props, "impostor_resolution", text="Resolution")
        box.prop(props, "impostor_replace_last_lod", text="Final LOD Tier")


WORKFLOW_POPOVER_CLASSES = (
    OMNIMESH_PT_popover_sanitize,
    OMNIMESH_PT_popover_materials,
    OMNIMESH_PT_popover_collision,
    OMNIMESH_PT_popover_generate,
    OMNIMESH_PT_popover_impostor,
)

POPOVER_CLASSES = (
    OMNIMESH_PT_popover_config_preset,
    OMNIMESH_PT_popover_engine_import_preset,
    OMNIMESH_PT_popover_import_preset,
    OMNIMESH_PT_popover_sanitize,
    OMNIMESH_PT_popover_materials,
    OMNIMESH_PT_popover_collision,
    OMNIMESH_PT_popover_generate,
    OMNIMESH_PT_popover_lod_preset,
    OMNIMESH_PT_popover_impostor,
    OMNIMESH_PT_popover_export_preset,
)

__all__ = [
    "OMNIMESH_PT_popover_config_preset",
    "OMNIMESH_PT_popover_engine_import_preset",
    "OMNIMESH_PT_popover_import_preset",
    "OMNIMESH_PT_popover_sanitize",
    "OMNIMESH_PT_popover_materials",
    "OMNIMESH_PT_popover_collision",
    "OMNIMESH_PT_popover_generate",
    "OMNIMESH_PT_popover_lod_preset",
    "OMNIMESH_PT_popover_impostor",
    "OMNIMESH_PT_popover_export_preset",
    "WORKFLOW_POPOVER_CLASSES",
    "POPOVER_CLASSES",
]
