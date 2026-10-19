"""
OmniMesh Popover Panels for Blender 4.2+ and 5.2 LTS.
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

try:
    from .utils import _get_popover_props
except (ImportError, ValueError):
    from ui.utils import _get_popover_props

# Re-export preset popovers from ui.popover_presets
try:
    from .popover_presets import (
        OMNIMESH_PT_popover_config_preset,
        OMNIMESH_PT_popover_engine_import_preset,
        OMNIMESH_PT_popover_export_preset,
        OMNIMESH_PT_popover_import_preset,
        OMNIMESH_PT_popover_lod_preset,
    )
except (ImportError, ValueError):
    from ui.popover_presets import (
        OMNIMESH_PT_popover_config_preset,
        OMNIMESH_PT_popover_engine_import_preset,
        OMNIMESH_PT_popover_export_preset,
        OMNIMESH_PT_popover_import_preset,
        OMNIMESH_PT_popover_lod_preset,
    )


# =========================================================================
# 0. SCENE & VIEWPORT SETUP POPOVER
# =========================================================================


class OMNIMESH_PT_popover_scene_setup(Panel):
    """Popover for scene initialization, viewport overlays, and helper collection creation."""

    bl_idname = "OMNIMESH_PT_popover_scene_setup"
    bl_label = "Scene & Viewport Setup"
    bl_space_type = "VIEW_3D"
    bl_region_type = "HEADER"
    bl_ui_units_x = 16

    def draw(self, context: Any) -> None:
        if not bpy or not context or not self.layout:
            return
        layout = self.layout

        layout.label(text="Game Scene Setup", icon="SCENE_DATA")
        row_sc = layout.row(align=True)
        row_sc.scale_y = 1.15
        row_sc.operator("omnimesh.quick_scene_setup", text="Game Scene", icon="SCENE_DATA")

        layout.separator()
        layout.label(text="Viewport Overlays", icon="OVERLAY")
        row_ov = layout.row(align=True)
        row_ov.scale_y = 1.1
        op_st = row_ov.operator("omnimesh.toggle_viewport_overlay", text="Stats", icon="VIEW_CAMERA")
        op_st.mode = "STATS"
        op_cav = row_ov.operator("omnimesh.toggle_viewport_overlay", text="Cavity", icon="SHADING_SOLID")
        op_cav.mode = "CAVITY"
        op_fo = row_ov.operator("omnimesh.toggle_viewport_overlay", text="Face Orientation", icon="NORMALS_FACE")
        op_fo.mode = "FACE_ORIENTATION"

        layout.separator()
        layout.label(text="Helper Collections", icon="HELP")
        row_help = layout.row(align=True)
        row_help.scale_y = 1.15
        row_help.operator("lod_tool.create_helpers_collection", text="Add Helpers Collection", icon="COLLECTION_NEW")


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
        row_t = layout.row(align=True)
        row_t.operator("lod_tool.apply_transforms", text="Apply Transforms", icon="CHECKMARK")
        row_t.operator("lod_tool.apply_all_modifiers", text="Apply Modifiers", icon="MODIFIER")

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

        # Consolidated Multi-Engine Shader Presets
        mat_props = getattr(props, "material_preset", None)
        if mat_props:
            layout.separator()
            layout.label(text="Shader Presets", icon="MATERIAL")
            row_m = layout.row(align=True)
            row_m.use_property_split = False
            row_m.prop(mat_props, "preset_type", text="")
            row_m.operator("omnimesh.assign_material_preset", text="Assign Preset", icon="SHADING_TEXTURE")


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
# 2. LODs POPOVERS: CONFIGURE, GENERATE & IMPOSTOR
# =========================================================================


class OMNIMESH_PT_popover_configure(Panel):
    """Popover for LOD auto-configuration and target engine rules."""

    bl_idname = "OMNIMESH_PT_popover_configure"
    bl_label = "LOD Tier Configuration"
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

        layout.label(text="Target Engine & Asset Role", icon="SCENE_DATA")
        layout.prop(props, "target_engine", text="Engine")
        layout.prop(props, "asset_category", text="Role")
        layout.prop(props, "export_base_name", text="Asset Name")

        layout.separator()
        layout.label(text="Quality & Screen Tolerances", icon="RESTRICT_VIEW_OFF")
        layout.prop(props, "tau_sse", slider=True, text="Visual Stability (SSE)")
        layout.prop(props, "cull_screen_size_pct", slider=True, text="Cull Screen Size (%)")
        if props.target_engine != "MSFS_2024":
            layout.prop(props, "num_lods", text="LOD Tier Count")


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

        layout.separator()
        row_act = layout.row(align=True)
        row_act.scale_y = 1.25
        row_act.operator("lod_tool.generate_impostor", text="Generate", icon="IMAGE_PLANE")
        row_act.operator("lod_tool.remove_impostor", text="Remove", icon="X")

        row_prev = layout.row(align=True)
        row_prev.operator("lod_tool.setup_impostor_preview_rig", text="Preview Rig", icon="CAMERA_DATA")
        row_prev.operator("lod_tool.impostor_viewport_tracker", text="Track View", icon="VIEW_CAMERA")
        row_prev.operator("lod_tool.remove_impostor_preview_rig", text="", icon="TRASH")


# =========================================================================
# 3. EXPORT POPOVERS: PACKAGE EXPORT
# =========================================================================


class OMNIMESH_PT_popover_export(Panel):
    """Popover for single asset export packaging, texture packing, and animation baking."""

    bl_idname = "OMNIMESH_PT_popover_export"
    bl_label = "Package Export Settings"
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

        layout.label(text="PBR Texture Export & Packing", icon="NODE_MATERIAL")
        layout.prop(props, "export_packed_textures", text="Pack PBR Textures")
        if props.export_packed_textures:
            box = layout.box()
            box.prop(props, "pbr_export_preset", text="Preset")
            box.prop(props, "pbr_export_texture_strategy", text="Strategy")
            box.prop(props, "texture_max_resolution", text="Resolution")
            box.prop(props, "pbr_export_bit_depth", text="Bit Depth")
            box.prop(props, "pbr_export_naming_pattern", text="Naming")
            box.operator("lod_tool.pack_pbr_textures", text="Pack Textures Now", icon="IMAGE_DATA")

        layout.separator()
        layout.label(text="Rig Animations", icon="ACTION")
        layout.prop(props, "bake_animations", text="Bake Skeletal Animations")


WORKFLOW_POPOVER_CLASSES = (
    OMNIMESH_PT_popover_scene_setup,
    OMNIMESH_PT_popover_sanitize,
    OMNIMESH_PT_popover_materials,
    OMNIMESH_PT_popover_collision,
    OMNIMESH_PT_popover_configure,
    OMNIMESH_PT_popover_generate,
    OMNIMESH_PT_popover_impostor,
    OMNIMESH_PT_popover_export,
)

POPOVER_CLASSES = (
    OMNIMESH_PT_popover_config_preset,
    OMNIMESH_PT_popover_engine_import_preset,
    OMNIMESH_PT_popover_import_preset,
    OMNIMESH_PT_popover_sanitize,
    OMNIMESH_PT_popover_materials,
    OMNIMESH_PT_popover_collision,
    OMNIMESH_PT_popover_configure,
    OMNIMESH_PT_popover_generate,
    OMNIMESH_PT_popover_lod_preset,
    OMNIMESH_PT_popover_impostor,
    OMNIMESH_PT_popover_export,
    OMNIMESH_PT_popover_export_preset,
    OMNIMESH_PT_popover_scene_setup,
)

__all__ = [
    "OMNIMESH_PT_popover_config_preset",
    "OMNIMESH_PT_popover_engine_import_preset",
    "OMNIMESH_PT_popover_import_preset",
    "OMNIMESH_PT_popover_sanitize",
    "OMNIMESH_PT_popover_materials",
    "OMNIMESH_PT_popover_collision",
    "OMNIMESH_PT_popover_configure",
    "OMNIMESH_PT_popover_generate",
    "OMNIMESH_PT_popover_lod_preset",
    "OMNIMESH_PT_popover_impostor",
    "OMNIMESH_PT_popover_export",
    "OMNIMESH_PT_popover_export_preset",
    "OMNIMESH_PT_popover_scene_setup",
    "WORKFLOW_POPOVER_CLASSES",
    "POPOVER_CLASSES",
]
