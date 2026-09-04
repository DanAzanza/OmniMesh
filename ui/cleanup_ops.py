"""
Mesh Preflight Inspection, Topology Repair, and Material Cleanup Operators.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

try:
    import bmesh
    import bpy
    from bpy.types import Operator
except ImportError:
    bpy = None
    bmesh = None
    Operator = object

try:
    from ..core.materials import MaterialOptimizer
    from ..core.modifiers import ModifierManager
    from ..core.sanitizer import MeshSanitizer
    from .utils import get_selected_mesh_objects, resolve_lod_context
except (ImportError, ValueError):
    from core.materials import MaterialOptimizer
    from core.modifiers import ModifierManager
    from core.sanitizer import MeshSanitizer
    from ui.utils import get_selected_mesh_objects, resolve_lod_context


class LOD_OT_inspect_lod0(Operator):
    """Preflight check: Inspect active mesh geometry for unapplied transforms, loose vertices, and non-manifold topology."""

    bl_idname = "lod_tool.inspect_lod0"
    bl_label = "Inspect LOD0"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context: Any) -> bool:
        return bool(context and get_selected_mesh_objects(context))

    def execute(self, context: Any) -> set[str]:
        if not bpy or not context:
            return {"FINISHED"}
        props = context.scene.lod_tool
        mesh_objs = get_selected_mesh_objects(context)
        if not mesh_objs:
            self.report({"WARNING"}, "No mesh objects selected.")
            return {"CANCELLED"}

        total_loose_verts = 0
        total_degenerate_tris = 0
        has_unapplied_scale = False
        missing_mats = 0

        for obj in mesh_objs:
            s = obj.scale
            if abs(s.x - 1.0) > 1e-4 or abs(s.y - 1.0) > 1e-4 or abs(s.z - 1.0) > 1e-4:
                has_unapplied_scale = True

            if len(obj.material_slots) == 0 or any(slot.material is None for slot in obj.material_slots):
                missing_mats += 1

            bm = bmesh.new()
            try:
                bm.from_mesh(obj.data)
                for v in bm.verts:
                    if len(v.link_edges) == 0:
                        total_loose_verts += 1
                for f in bm.faces:
                    if f.calc_area() <= 1e-10:
                        total_degenerate_tris += 1
            finally:
                bm.free()

        props.preflight_inspected = True
        props.preflight_loose_verts = total_loose_verts
        props.preflight_degenerate_tris = total_degenerate_tris
        props.preflight_unapplied_scale = has_unapplied_scale
        props.preflight_missing_materials = missing_mats

        is_clean = (total_loose_verts == 0) and (total_degenerate_tris == 0) and (not has_unapplied_scale)
        props.preflight_is_clean = is_clean

        if is_clean:
            props.preflight_summary_text = f"✔ LOD0 Healthy ({len(mesh_objs)} mesh(es), All Transforms Applied)"
            if hasattr(self, "report"):
                self.report({"INFO"}, props.preflight_summary_text)
        else:
            issues = []
            if has_unapplied_scale:
                issues.append("Unapplied Scale")
            if total_loose_verts > 0:
                issues.append(f"{total_loose_verts} Loose Verts")
            if total_degenerate_tris > 0:
                issues.append(f"{total_degenerate_tris} Degenerates")
            if missing_mats > 0:
                issues.append(f"{missing_mats} Missing Mats")
            props.preflight_summary_text = f"⚠ Issues: {', '.join(issues)}"
            if hasattr(self, "report"):
                self.report({"WARNING"}, f"LOD0 Inspection: {', '.join(issues)}")

        return {"FINISHED"}


class LOD_OT_clean_and_repair_mesh(Operator):
    """Execute topology repair, hygiene, and normal healing on selected meshes."""

    bl_idname = "lod_tool.clean_and_repair_mesh"
    bl_label = "Clean & Repair Mesh"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context: Any) -> bool:
        return bool(context and get_selected_mesh_objects(context))

    def execute(self, context: Any) -> set[str]:
        if not bpy or not context:
            return {"FINISHED"}
        props, _, _ = resolve_lod_context(context)
        if not props:
            props = context.scene.lod_tool

        mesh_objs = get_selected_mesh_objects(context)
        total_loose = 0
        total_deg = 0
        total_welded = 0
        total_bowties = 0
        total_split_nm = 0
        total_holes = 0
        total_ngons = 0

        weld_dist = props.cleanup_weld_distance if props.cleanup_enable_weld else 0.0

        total_mods_baked = 0
        apply_mods = getattr(props, "cleanup_apply_modifiers", False) or (
            hasattr(context, "scene")
            and hasattr(context.scene, "lod_tool")
            and getattr(context.scene.lod_tool, "cleanup_apply_modifiers", False)
        )
        sync_vp = getattr(props, "cleanup_sync_viewport_settings", True)
        if (
            hasattr(context, "scene")
            and hasattr(context.scene, "lod_tool")
            and not getattr(props, "cleanup_apply_modifiers", False)
        ):
            sync_vp = getattr(context.scene.lod_tool, "cleanup_sync_viewport_settings", sync_vp)

        if apply_mods:
            for obj in mesh_objs:
                if ModifierManager.has_unapplied_modifiers(obj):
                    if sync_vp:
                        ModifierManager.sync_viewport_to_render_settings(obj)
                    if ModifierManager.apply_all_modifiers_in_place(obj, preserve_armature=True):
                        total_mods_baked += 1

        for obj in mesh_objs:
            bm = bmesh.new()
            try:
                bm.from_mesh(obj.data)
                res = MeshSanitizer.sanitize_mesh_full(
                    bm,
                    epsilon_merge=weld_dist,
                    w_crit=0.0,
                    enable_weld=props.cleanup_enable_weld,
                    enable_split_non_manifold=props.cleanup_enable_split_non_manifold,
                    enable_fill_holes=props.cleanup_enable_fill_holes,
                    hole_max_edges=props.cleanup_hole_max_edges,
                    enable_triangulate_ngons=props.cleanup_enable_triangulate_ngons,
                    enable_cull_micro_islands=False,
                    normal_recalc_policy=props.cleanup_normal_policy,
                )
                total_loose += res.get("loose_verts_deleted", res.get("loose_verts", 0))
                total_deg += res.get("degenerate_faces_deleted", res.get("zero_faces", 0))
                total_welded += res.get("welded_verts", 0)
                total_bowties += res.get("split_bowties", 0)
                total_split_nm += res.get("split_non_manifold_edges", 0)
                total_holes += res.get("filled_holes", 0)
                total_ngons += res.get("triangulated_ngons", 0)
                bm.to_mesh(obj.data)
            finally:
                bm.free()
            obj.data.update()

        summary_parts = []
        if total_mods_baked > 0:
            summary_parts.append(f"{total_mods_baked} obj modifier(s) baked")
        if total_loose > 0:
            summary_parts.append(f"{total_loose} loose verts")
        if total_deg > 0:
            summary_parts.append(f"{total_deg} degenerate faces")
        if total_welded > 0:
            summary_parts.append(f"{total_welded} welded verts")
        if total_bowties > 0:
            summary_parts.append(f"{total_bowties} bowties split")
        if total_split_nm > 0:
            summary_parts.append(f"{total_split_nm} non-manifold edges split")
        if total_holes > 0:
            summary_parts.append(f"{total_holes} holes filled")
        if total_ngons > 0:
            summary_parts.append(f"{total_ngons} n-gons triangulated")

        if summary_parts:
            props.last_cleanup_summary = f"Cleaned: {', '.join(summary_parts)}."
        else:
            props.last_cleanup_summary = "Cleaned: 0 issues found (Mesh Already Clean)."

        if hasattr(self, "report"):
            self.report({"INFO"}, props.last_cleanup_summary)
        return {"FINISHED"}


class LOD_OT_clean_and_repair_materials(Operator):
    """Execute material slot deduplication, orphan purge, and shader node cleanup."""

    bl_idname = "lod_tool.clean_and_repair_materials"
    bl_label = "Clean Materials & Slots"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context: Any) -> bool:
        return bool(context and get_selected_mesh_objects(context))

    def execute(self, context: Any) -> set[str]:
        if not bpy or not context:
            return {"FINISHED"}
        props, _, _ = resolve_lod_context(context)
        if not props:
            props = context.scene.lod_tool

        mesh_objs = get_selected_mesh_objects(context)
        purged_slots = 0
        merged_blocks = 0

        for obj in mesh_objs:
            if props.mat_cleanup_purge_unused_slots:
                res_purge = MaterialOptimizer.purge_unused_materials(obj)
                purged_slots += res_purge.get("purged_slots", 0)
            if props.mat_cleanup_merge_duplicate_datablocks:
                merged_blocks += MaterialOptimizer.merge_duplicate_materials_scene()
            if props.mat_cleanup_remove_orphan_nodes:
                MaterialOptimizer.clean_orphan_shader_nodes()

        props.last_material_cleanup_summary = f"Purged {purged_slots} unused slots, merged {merged_blocks} materials."
        if hasattr(self, "report"):
            self.report({"INFO"}, props.last_material_cleanup_summary)
        return {"FINISHED"}


class LOD_OT_apply_all_modifiers(Operator):
    """Applies all non-armature modifiers in-place, baking procedural stacks into raw mesh data."""

    bl_idname = "lod_tool.apply_all_modifiers"
    bl_label = "Apply All Modifiers"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context: Any) -> bool:
        return bool(context and get_selected_mesh_objects(context))

    def execute(self, context: Any) -> set[str]:
        if not bpy or not context:
            return {"FINISHED"}

        mesh_objs = get_selected_mesh_objects(context)
        if not mesh_objs:
            if hasattr(self, "report"):
                self.report({"WARNING"}, "No mesh objects selected.")
            return {"CANCELLED"}

        applied_count = 0
        for obj in mesh_objs:
            if ModifierManager.apply_all_modifiers_in_place(obj, preserve_armature=True):
                applied_count += 1

        msg = f"Applied modifiers on {applied_count} object(s)."
        if hasattr(self, "report"):
            self.report({"INFO"}, msg)
        return {"FINISHED"}


class LOD_OT_apply_transforms(Operator):
    """Applies object rotation and scale transforms to normalize base mesh orientation."""

    bl_idname = "lod_tool.apply_transforms"
    bl_label = "Apply Scale & Rotation"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context: Any) -> bool:
        return bool(context and get_selected_mesh_objects(context))

    def execute(self, context: Any) -> set[str]:
        if not bpy or not context:
            return {"FINISHED"}

        mesh_objs = get_selected_mesh_objects(context)
        if not mesh_objs:
            if hasattr(self, "report"):
                self.report({"WARNING"}, "No mesh objects selected.")
            return {"CANCELLED"}

        applied_count = 0
        for obj in mesh_objs:
            try:
                if hasattr(context, "temp_override"):
                    with context.temp_override(active_object=obj, object=obj, selected_objects=[obj]):
                        bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
                elif hasattr(context, "view_layer") and hasattr(context.view_layer, "objects"):
                    context.view_layer.objects.active = obj
                    bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
                applied_count += 1
            except Exception as exc:
                logger.warning("Failed applying transforms on %s: %s", getattr(obj, "name", "obj"), exc)

        msg = f"Applied rotation & scale on {applied_count} object(s)."
        if hasattr(self, "report"):
            self.report({"INFO"}, msg)
        return {"FINISHED"}


CLEANUP_OPERATOR_CLASSES = (
    LOD_OT_inspect_lod0,
    LOD_OT_clean_and_repair_mesh,
    LOD_OT_clean_and_repair_materials,
    LOD_OT_apply_all_modifiers,
    LOD_OT_apply_transforms,
)
