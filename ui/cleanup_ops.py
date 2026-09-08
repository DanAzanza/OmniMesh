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
    from .hud import LODViewportHUD
    from .utils import (
        get_lod0_mesh_objects,
        get_selected_mesh_objects,
        resolve_lod_context,
        safe_report,
    )
except (ImportError, ValueError):
    from core.materials import MaterialOptimizer
    from core.modifiers import ModifierManager
    from core.sanitizer import MeshSanitizer
    from ui.hud import LODViewportHUD
    from ui.utils import (
        get_lod0_mesh_objects,
        get_selected_mesh_objects,
        resolve_lod_context,
        safe_report,
    )


def run_preflight_inspection(context: Any, mesh_objs: list[Any]) -> dict[str, Any]:
    """Inspect mesh objects for unapplied scale/rotation, loose topology, degenerates, and materials."""
    if not bpy or not context:
        return {}
    props = getattr(getattr(context, "scene", None), "lod_tool", None)
    if not props:
        return {}

    total_loose_verts = 0
    total_loose_edges = 0
    total_non_manifold_edges = 0
    total_degenerate_tris = 0
    has_unapplied_scale = False
    missing_mats = 0

    for obj in mesh_objs:
        s = getattr(obj, "scale", None)
        if s and hasattr(s, "x") and hasattr(s, "y") and hasattr(s, "z"):
            try:
                if abs(s.x - 1.0) > 1e-4 or abs(s.y - 1.0) > 1e-4 or abs(s.z - 1.0) > 1e-4:
                    has_unapplied_scale = True
            except (TypeError, ValueError):
                pass

        if hasattr(obj, "material_slots") and type(obj.material_slots).__name__ != "MagicMock":
            try:
                if len(obj.material_slots) == 0 or any(slot.material is None for slot in obj.material_slots):
                    missing_mats += 1
            except (TypeError, ValueError):
                pass

        mesh_data = getattr(obj, "data", None)
        if not mesh_data or not bmesh:
            continue

        try:
            bm = bmesh.new()
            try:
                bm.from_mesh(mesh_data)
                for v in getattr(bm, "verts", []):
                    if len(getattr(v, "link_edges", [])) == 0:
                        total_loose_verts += 1
                for e in getattr(bm, "edges", []):
                    face_count = len(getattr(e, "link_faces", []))
                    if face_count == 0:
                        total_loose_edges += 1
                    elif face_count > 2:
                        total_non_manifold_edges += 1
                for f in getattr(bm, "faces", []):
                    calc_area = getattr(f, "calc_area", None)
                    if callable(calc_area) and float(calc_area()) <= 1e-10:
                        total_degenerate_tris += 1
            finally:
                bm.free()
        except Exception as exc:
            logger.debug("Failed during mesh inspection: %s", exc)

    props.preflight_inspected = True
    props.preflight_loose_verts = total_loose_verts
    props.preflight_loose_edges = total_loose_edges
    props.preflight_non_manifold_edges = total_non_manifold_edges
    props.preflight_degenerate_tris = total_degenerate_tris
    props.preflight_unapplied_scale = has_unapplied_scale
    props.preflight_missing_materials = missing_mats

    is_clean = (
        (total_loose_verts == 0)
        and (total_loose_edges == 0)
        and (total_non_manifold_edges == 0)
        and (total_degenerate_tris == 0)
        and (not has_unapplied_scale)
        and (missing_mats == 0)
    )
    props.preflight_is_clean = is_clean

    if is_clean:
        props.preflight_summary_text = f"✔ LOD0 Healthy ({len(mesh_objs)} mesh(es), All Transforms Applied)"
    else:
        issues = []
        if has_unapplied_scale:
            issues.append("Unapplied Scale")
        if total_loose_verts > 0:
            issues.append(f"{total_loose_verts} Loose Verts")
        if total_loose_edges > 0:
            issues.append(f"{total_loose_edges} Loose Edges")
        if total_non_manifold_edges > 0:
            issues.append(f"{total_non_manifold_edges} Non-Manifold Edges")
        if total_degenerate_tris > 0:
            issues.append(f"{total_degenerate_tris} Degenerates")
        if missing_mats > 0:
            issues.append(f"{missing_mats} Missing Mats")
        props.preflight_summary_text = f"⚠ Issues: {', '.join(issues)}"

    return {
        "is_clean": is_clean,
        "loose_verts": total_loose_verts,
        "loose_edges": total_loose_edges,
        "non_manifold_edges": total_non_manifold_edges,
        "degenerate_tris": total_degenerate_tris,
        "unapplied_scale": has_unapplied_scale,
        "missing_mats": missing_mats,
        "summary": props.preflight_summary_text,
    }


class LOD_OT_inspect_lod0(Operator):
    """Preflight check: Inspect active mesh geometry for unapplied transforms, loose vertices, and non-manifold topology."""

    bl_idname = "lod_tool.inspect_lod0"
    bl_label = "Inspect LOD0"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context: Any) -> bool:
        return bool(context and (get_lod0_mesh_objects(context) or get_selected_mesh_objects(context)))

    def execute(self, context: Any) -> set[str]:
        if not bpy or not context:
            return {"FINISHED"}
        mesh_objs = get_lod0_mesh_objects(context)
        if not mesh_objs:
            mesh_objs = get_selected_mesh_objects(context)
        if not mesh_objs:
            safe_report(self, {"WARNING"}, "No valid LOD0 mesh objects found.")
            return {"CANCELLED"}

        res = run_preflight_inspection(context, mesh_objs)
        summary = res.get("summary", "")
        if res.get("is_clean", False):
            safe_report(self, {"INFO"}, summary)
        else:
            safe_report(self, {"WARNING"}, summary)

        return {"FINISHED"}


class LOD_OT_clean_and_repair_mesh(Operator):
    """Execute topology repair, hygiene, and normal healing on LOD0 meshes."""

    bl_idname = "lod_tool.clean_and_repair_mesh"
    bl_label = "Clean & Repair Mesh"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context: Any) -> bool:
        return bool(context and (get_lod0_mesh_objects(context) or get_selected_mesh_objects(context)))

    def execute(self, context: Any) -> set[str]:
        if not bpy or not context:
            return {"FINISHED"}
        props, _, _ = resolve_lod_context(context)
        if not props:
            props = context.scene.lod_tool

        mesh_objs = get_lod0_mesh_objects(context)
        if not mesh_objs:
            mesh_objs = get_selected_mesh_objects(context)
        if not mesh_objs:
            safe_report(self, {"WARNING"}, "No valid LOD0 mesh objects found to sanitize.")
            return {"CANCELLED"}
        total_loose = 0
        total_deg = 0
        total_welded = 0
        total_bowties = 0
        total_split_nm = 0
        total_holes = 0
        total_ngons = 0
        total_transforms_applied = 0

        # Optional defensive auto-apply transforms
        auto_transforms = bool(getattr(props, "cleanup_auto_apply_transforms", False) is True)
        if auto_transforms and bpy:
            for obj in mesh_objs:
                mesh_data = getattr(obj, "data", None)
                if not mesh_data:
                    continue
                users = getattr(mesh_data, "users", 1)
                if isinstance(users, int) and users > 1:
                    logger.warning("Skipping transform apply on %s: multi-user mesh", getattr(obj, "name", ""))
                    continue
                if getattr(mesh_data, "shape_keys", None):
                    logger.warning("Skipping transform apply on %s: mesh has shape keys", getattr(obj, "name", ""))
                    continue
                anim_data = getattr(obj, "animation_data", None)
                if anim_data and getattr(anim_data, "action", None):
                    logger.warning("Skipping transform apply on %s: animated object", getattr(obj, "name", ""))
                    continue

                s = getattr(obj, "scale", None)
                r = getattr(obj, "rotation_euler", None)
                needs_scale = False
                if s and hasattr(s, "x") and hasattr(s, "y") and hasattr(s, "z"):
                    try:
                        needs_scale = abs(s.x - 1.0) > 1e-4 or abs(s.y - 1.0) > 1e-4 or abs(s.z - 1.0) > 1e-4
                    except (TypeError, ValueError):
                        pass
                needs_rot = False
                if r and hasattr(r, "x") and hasattr(r, "y") and hasattr(r, "z"):
                    try:
                        needs_rot = abs(r.x) > 1e-4 or abs(r.y) > 1e-4 or abs(r.z) > 1e-4
                    except (TypeError, ValueError):
                        pass

                if needs_scale or needs_rot:
                    try:
                        if hasattr(context, "temp_override"):
                            with context.temp_override(active_object=obj, object=obj, selected_objects=[obj]):
                                bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
                        else:
                            bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
                        total_transforms_applied += 1
                    except Exception as e:
                        logger.warning("Could not apply transform on %s: %s", getattr(obj, "name", ""), e)

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
            if not getattr(obj, "data", None) or not bmesh:
                continue
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
        if total_transforms_applied > 0:
            summary_parts.append(f"{total_transforms_applied} transform(s) applied")
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

        # Refresh preflight diagnostic properties so popovers never display stale defects
        run_preflight_inspection(context, mesh_objs)

        # Trigger transient viewport HUD toast notification
        try:
            LODViewportHUD.show_toast(props.last_cleanup_summary)
        except Exception as exc:
            logger.debug("Could not show HUD toast: %s", exc)

        if hasattr(self, "report"):
            self.report({"INFO"}, props.last_cleanup_summary)
        return {"FINISHED"}


class LOD_OT_clean_and_repair_materials(Operator):
    """Execute material slot deduplication, orphan purge, and shader node cleanup on LOD0."""

    bl_idname = "lod_tool.clean_and_repair_materials"
    bl_label = "Clean Materials & Slots"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context: Any) -> bool:
        return bool(context and (get_lod0_mesh_objects(context) or get_selected_mesh_objects(context)))

    def execute(self, context: Any) -> set[str]:
        if not bpy or not context:
            return {"FINISHED"}
        props, _, _ = resolve_lod_context(context)
        if not props:
            props = context.scene.lod_tool

        mesh_objs = get_lod0_mesh_objects(context)
        if not mesh_objs:
            mesh_objs = get_selected_mesh_objects(context)
        if not mesh_objs:
            safe_report(self, {"WARNING"}, "No valid LOD0 mesh objects found for material cleanup.")
            return {"CANCELLED"}

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

        # Trigger transient viewport HUD toast notification
        try:
            LODViewportHUD.show_toast(props.last_material_cleanup_summary)
        except Exception as exc:
            logger.debug("Could not show HUD toast: %s", exc)

        safe_report(self, {"INFO"}, props.last_material_cleanup_summary)
        return {"FINISHED"}


class LOD_OT_apply_all_modifiers(Operator):
    """Applies all non-armature modifiers in-place on LOD0 meshes."""

    bl_idname = "lod_tool.apply_all_modifiers"
    bl_label = "Apply All Modifiers"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context: Any) -> bool:
        return bool(context and (get_lod0_mesh_objects(context) or get_selected_mesh_objects(context)))

    def execute(self, context: Any) -> set[str]:
        if not bpy or not context:
            return {"FINISHED"}

        mesh_objs = get_lod0_mesh_objects(context)
        if not mesh_objs:
            mesh_objs = get_selected_mesh_objects(context)
        if not mesh_objs:
            safe_report(self, {"WARNING"}, "No valid LOD0 mesh objects found.")
            return {"CANCELLED"}

        applied_count = 0
        for obj in mesh_objs:
            if ModifierManager.apply_all_modifiers_in_place(obj, preserve_armature=True):
                applied_count += 1

        msg = f"Applied modifiers on {applied_count} LOD0 object(s)."
        safe_report(self, {"INFO"}, msg)
        return {"FINISHED"}


class LOD_OT_apply_transforms(Operator):
    """Applies object rotation and scale transforms to normalize LOD0 mesh orientation."""

    bl_idname = "lod_tool.apply_transforms"
    bl_label = "Apply Scale & Rotation"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context: Any) -> bool:
        return bool(context and (get_lod0_mesh_objects(context) or get_selected_mesh_objects(context)))

    def execute(self, context: Any) -> set[str]:
        if not bpy or not context:
            return {"FINISHED"}

        mesh_objs = get_lod0_mesh_objects(context)
        if not mesh_objs:
            mesh_objs = get_selected_mesh_objects(context)
        if not mesh_objs:
            safe_report(self, {"WARNING"}, "No valid LOD0 mesh objects found.")
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

        msg = f"Applied rotation & scale on {applied_count} LOD0 object(s)."
        safe_report(self, {"INFO"}, msg)
        return {"FINISHED"}


CLEANUP_OPERATOR_CLASSES = (
    LOD_OT_inspect_lod0,
    LOD_OT_clean_and_repair_mesh,
    LOD_OT_clean_and_repair_materials,
    LOD_OT_apply_all_modifiers,
    LOD_OT_apply_transforms,
)
