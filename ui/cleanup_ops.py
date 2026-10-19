# pyright: reportInvalidTypeForm=none
"""
Mesh Preflight Inspection, Topology Repair, and Material Cleanup Operators.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    import bmesh
    import bpy
    from bpy.types import Operator
else:
    try:
        import bmesh
        import bpy
        from bpy.types import Operator
    except ImportError:
        bpy = None
        bmesh = None
        Operator = object

try:
    from ..core.exceptions import OmniMeshError
    from ..core.hierarchy import LayerCollectionGuard
    from ..core.materials import MaterialOptimizer
    from ..core.modifiers import ModifierManager
    from ..core.sanitizer import MeshSanitizer, SanitizeOptions
    from .hud import LODViewportHUD
    from .utils import (
        get_lod0_mesh_objects,
        get_or_create_engine_import_collection,
        get_selected_mesh_objects,
        resolve_effective_asset_name,
        resolve_lod_context,
        safe_report,
    )
except (ImportError, ValueError):
    from core.exceptions import OmniMeshError
    from core.hierarchy import LayerCollectionGuard
    from core.materials import MaterialOptimizer
    from core.modifiers import ModifierManager
    from core.sanitizer import MeshSanitizer, SanitizeOptions
    from ui.hud import LODViewportHUD
    from ui.utils import (
        get_lod0_mesh_objects,
        get_or_create_engine_import_collection,
        get_selected_mesh_objects,
        resolve_effective_asset_name,
        resolve_lod_context,
        safe_report,
    )


def run_preflight_inspection(context: Any, mesh_objs: list[Any]) -> dict[str, Any]:
    """Inspect mesh objects for unapplied scale/rotation, loose topology, degenerates, and materials."""
    return MeshSanitizer.run_preflight_inspection(context, mesh_objs)


class LOD_OT_inspect_lod0(Operator):
    """Preflight check: Inspect active mesh geometry for unapplied transforms, loose vertices, and non-manifold topology."""

    bl_idname = "lod_tool.inspect_lod0"
    bl_label = "Inspect LOD0"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context: Any) -> bool:
        return bool(context and (get_lod0_mesh_objects(context) or get_selected_mesh_objects(context)))

    def execute(self, context: Any) -> set[Any]:
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

    @staticmethod
    def _object_needs_transform_apply(obj: Any) -> bool:
        mesh_data = getattr(obj, "data", None)
        if not mesh_data:
            return False
        users = getattr(mesh_data, "users", 1)
        if isinstance(users, int) and users > 1:
            logger.warning("Skipping transform apply on %s: multi-user mesh", getattr(obj, "name", ""))
            return False
        if getattr(mesh_data, "shape_keys", None):
            logger.warning("Skipping transform apply on %s: mesh has shape keys", getattr(obj, "name", ""))
            return False
        anim_data = getattr(obj, "animation_data", None)
        if anim_data and getattr(anim_data, "action", None):
            logger.warning("Skipping transform apply on %s: animated object", getattr(obj, "name", ""))
            return False

        s = getattr(obj, "scale", None)
        r = getattr(obj, "rotation_euler", None)
        needs_scale = False
        if s and hasattr(s, "x") and hasattr(s, "y") and hasattr(s, "z"):
            try:
                needs_scale = abs(s.x - 1.0) > 1e-4 or abs(s.y - 1.0) > 1e-4 or abs(s.z - 1.0) > 1e-4
            except (TypeError, ValueError) as e:
                logger.debug("Failed checking scale threshold on %s: %s", getattr(obj, "name", ""), e)
        needs_rot = False
        if r and hasattr(r, "x") and hasattr(r, "y") and hasattr(r, "z"):
            try:
                needs_rot = abs(r.x) > 1e-4 or abs(r.y) > 1e-4 or abs(r.z) > 1e-4
            except (TypeError, ValueError) as e:
                logger.debug("Failed checking rotation threshold on %s: %s", getattr(obj, "name", ""), e)

        return needs_scale or needs_rot

    @classmethod
    def _apply_transforms_if_needed(cls, context: Any, props: Any, mesh_objs: list[Any]) -> int:
        if not bool(getattr(props, "cleanup_auto_apply_transforms", False)) or not bpy:
            return 0
        applied_count = 0
        for obj in mesh_objs:
            if not cls._object_needs_transform_apply(obj):
                continue
            try:
                if hasattr(context, "temp_override"):
                    with context.temp_override(active_object=obj, object=obj, selected_objects=[obj]):
                        bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
                else:
                    bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
                applied_count += 1
            except Exception as e:
                logger.warning("Could not apply transform on %s: %s", getattr(obj, "name", ""), e)
        return applied_count

    @staticmethod
    def _bake_modifiers_if_requested(context: Any, props: Any, mesh_objs: list[Any]) -> int:
        apply_mods = getattr(props, "cleanup_apply_modifiers", False) or (
            hasattr(context, "scene")
            and hasattr(context.scene, "lod_tool")
            and getattr(context.scene.lod_tool, "cleanup_apply_modifiers", False)
        )
        if not apply_mods:
            return 0

        sync_vp = getattr(props, "cleanup_sync_viewport_settings", True)
        if (
            hasattr(context, "scene")
            and hasattr(context.scene, "lod_tool")
            and not getattr(props, "cleanup_apply_modifiers", False)
        ):
            sync_vp = getattr(context.scene.lod_tool, "cleanup_sync_viewport_settings", sync_vp)

        baked_count = 0
        for obj in mesh_objs:
            if ModifierManager.has_unapplied_modifiers(obj):
                if sync_vp:
                    ModifierManager.sync_viewport_to_render_settings(obj)
                if ModifierManager.apply_all_modifiers_in_place(obj, preserve_armature=True):
                    baked_count += 1
        return baked_count

    def _sanitize_mesh_objects(
        self,
        mesh_objs: list[Any],
        props: Any,
        weld_dist: float,
    ) -> dict[str, int] | None:
        counts = {
            "loose": 0,
            "deg": 0,
            "welded": 0,
            "bowties": 0,
            "split_nm": 0,
            "holes": 0,
            "ngons": 0,
        }
        for obj in mesh_objs:
            if not getattr(obj, "data", None) or not bmesh:
                continue
            bm = bmesh.new()
            try:
                bm.from_mesh(obj.data)
                res = MeshSanitizer.sanitize_mesh_full(
                    bm,
                    options=SanitizeOptions(
                        epsilon_merge=weld_dist,
                        w_crit=0.0,
                        enable_weld=props.cleanup_enable_weld,
                        enable_split_non_manifold=props.cleanup_enable_split_non_manifold,
                        enable_fill_holes=props.cleanup_enable_fill_holes,
                        hole_max_edges=props.cleanup_hole_max_edges,
                        enable_triangulate_ngons=props.cleanup_enable_triangulate_ngons,
                        enable_cull_micro_islands=False,
                        normal_recalc_policy=props.cleanup_normal_policy,
                    ),
                )
                counts["loose"] += res.get("loose_verts_deleted", res.get("loose_verts", 0))
                counts["deg"] += res.get("degenerate_faces_deleted", res.get("zero_faces", 0))
                counts["welded"] += res.get("welded_verts", 0)
                counts["bowties"] += res.get("split_bowties", 0)
                counts["split_nm"] += res.get("split_non_manifold_edges", 0)
                counts["holes"] += res.get("filled_holes", 0)
                counts["ngons"] += res.get("triangulated_ngons", 0)
                bm.to_mesh(obj.data)
            except OmniMeshError as err:
                safe_report(self, {"ERROR"}, f"Topology repair failed on {getattr(obj, 'name', 'mesh')}: {err}")
                return None
            finally:
                bm.free()
            obj.data.update()

        return counts

    @staticmethod
    def _build_cleanup_summary(counts: dict[str, int]) -> str:
        parts: list[str] = []
        labels = [
            ("transforms_applied", "{n} transform(s) applied"),
            ("mods_baked", "{n} obj modifier(s) baked"),
            ("loose", "{n} loose verts"),
            ("deg", "{n} degenerate faces"),
            ("welded", "{n} welded verts"),
            ("bowties", "{n} bowties split"),
            ("split_nm", "{n} non-manifold edges split"),
            ("holes", "{n} holes filled"),
            ("ngons", "{n} n-gons triangulated"),
        ]
        for key, template in labels:
            n = counts.get(key, 0)
            if n > 0:
                parts.append(template.format(n=n))
        if parts:
            return f"Cleaned: {', '.join(parts)}."
        return "Cleaned: 0 issues found (Mesh Already Clean)."

    def execute(self, context: Any) -> set[Any]:
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

        weld_dist = props.cleanup_weld_distance if getattr(props, "cleanup_enable_weld", False) else 0.0

        target_cols = [c for obj in mesh_objs for c in getattr(obj, "users_collection", [])]
        with LayerCollectionGuard(getattr(context, "view_layer", None), target_cols):
            total_transforms_applied = self._apply_transforms_if_needed(context, props, mesh_objs)
            total_mods_baked = self._bake_modifiers_if_requested(context, props, mesh_objs)

        counts = self._sanitize_mesh_objects(mesh_objs, props, weld_dist)
        if counts is None:
            return {"CANCELLED"}
        counts["transforms_applied"] = total_transforms_applied
        counts["mods_baked"] = total_mods_baked

        summary = self._build_cleanup_summary(counts)
        props.last_cleanup_summary = summary

        # Refresh preflight diagnostic properties so popovers never display stale defects
        run_preflight_inspection(context, mesh_objs)

        # Trigger transient viewport HUD toast notification
        try:
            LODViewportHUD.show_toast(summary)
        except Exception as exc:
            logger.debug("Could not show HUD toast: %s", exc)

        safe_report(self, {"INFO"}, summary)
        return {"FINISHED"}


class LOD_OT_clean_and_repair_materials(Operator):
    """Execute material slot deduplication, orphan purge, and shader node cleanup on LOD0."""

    bl_idname = "lod_tool.clean_and_repair_materials"
    bl_label = "Clean Materials & Slots"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context: Any) -> bool:
        return bool(context and (get_lod0_mesh_objects(context) or get_selected_mesh_objects(context)))

    def execute(self, context: Any) -> set[Any]:
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
                purged_slots += res_purge.get("slots_removed", 0)

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

    def execute(self, context: Any) -> set[Any]:
        if not bpy or not context:
            return {"FINISHED"}

        mesh_objs = get_lod0_mesh_objects(context)
        if not mesh_objs:
            mesh_objs = get_selected_mesh_objects(context)
        if not mesh_objs:
            safe_report(self, {"WARNING"}, "No valid LOD0 mesh objects found.")
            return {"CANCELLED"}

        applied_count = 0
        target_cols = [c for obj in mesh_objs for c in getattr(obj, "users_collection", [])]
        with LayerCollectionGuard(getattr(context, "view_layer", None), target_cols):
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

    def execute(self, context: Any) -> set[Any]:
        if not bpy or not context:
            return {"FINISHED"}

        mesh_objs = get_lod0_mesh_objects(context)
        if not mesh_objs:
            mesh_objs = get_selected_mesh_objects(context)
        if not mesh_objs:
            safe_report(self, {"WARNING"}, "No valid LOD0 mesh objects found.")
            return {"CANCELLED"}

        applied_count = 0
        skipped_reasons: list[str] = []
        target_cols = [c for obj in mesh_objs for c in getattr(obj, "users_collection", [])]
        with LayerCollectionGuard(getattr(context, "view_layer", None), target_cols):
            for obj in mesh_objs:
                mesh_data = getattr(obj, "data", None)
                if not mesh_data:
                    continue
                users = getattr(mesh_data, "users", 1)
                if isinstance(users, int) and users > 1:
                    skipped_reasons.append(f"{getattr(obj, 'name', 'obj')} (multi-user)")
                    continue
                if getattr(mesh_data, "shape_keys", None):
                    skipped_reasons.append(f"{getattr(obj, 'name', 'obj')} (shape keys)")
                    continue
                anim_data = getattr(obj, "animation_data", None)
                if anim_data and getattr(anim_data, "action", None):
                    skipped_reasons.append(f"{getattr(obj, 'name', 'obj')} (animated)")
                    continue

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
        if skipped_reasons:
            msg += f" Skipped: {', '.join(skipped_reasons)}."
        safe_report(self, {"INFO"}, msg)
        return {"FINISHED"}


class LOD_OT_create_helpers_collection(Operator):
    """Creates a dedicated {AssetName}_Helpers collection for reference blueprints, booleans, and guides."""

    bl_idname = "lod_tool.create_helpers_collection"
    bl_label = "Create Helpers Collection"
    bl_description = "Creates a dedicated {AssetName}_Helpers collection for reference meshes and auxiliary objects that are strictly excluded from engine export"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context: Any) -> bool:
        return bool(bpy and context)

    def execute(self, context: Any) -> set[Any]:
        if not bpy or not context:
            return {"FINISHED"}

        props = getattr(getattr(context, "scene", None), "lod_tool", None)
        asset_name = resolve_effective_asset_name(context, props)
        if not asset_name or asset_name == "AUTO":
            asset_name = "Asset"

        helper_col = get_or_create_engine_import_collection(context, asset_name, "HELPERS")
        if helper_col:
            safe_report(self, {"INFO"}, f"Created/Located helper collection '{helper_col.name}'.")
            # Set active layer collection if possible
            vl = getattr(context, "view_layer", None)
            if vl and hasattr(vl, "layer_collection"):

                def _find_lc(lc: Any, target: Any) -> Any:
                    if getattr(lc, "collection", None) == target:
                        return lc
                    for child in getattr(lc, "children", []):
                        res = _find_lc(child, target)
                        if res:
                            return res
                    return None

                matched_lc = _find_lc(vl.layer_collection, helper_col)
                if matched_lc:
                    vl.active_layer_collection = matched_lc
            return {"FINISHED"}

        safe_report(self, {"WARNING"}, "Failed creating helper collection.")
        return {"CANCELLED"}


CLEANUP_OPERATOR_CLASSES = (
    LOD_OT_inspect_lod0,
    LOD_OT_clean_and_repair_mesh,
    LOD_OT_clean_and_repair_materials,
    LOD_OT_apply_all_modifiers,
    LOD_OT_apply_transforms,
    LOD_OT_create_helpers_collection,
)
