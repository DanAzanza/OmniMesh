"""
Convex Collision Hull Decomposition and Billboard Impostor Operators.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

try:
    import bpy
    from bpy.types import Operator
except ImportError:
    bpy = None
    Operator = object

try:
    from core.collision import CollisionManager
    from core.impostor import ImpostorManager
    from ui.utils import get_selected_mesh_objects, resolve_lod_context, safe_report
except (ImportError, ValueError):
    from ..core.collision import CollisionManager
    from ..core.impostor import ImpostorManager
    from .utils import get_selected_mesh_objects, resolve_lod_context, safe_report


class LOD_OT_generate_impostor(Operator):
    """Generate camera-facing or octahedral billboard impostor representation for distant LOD."""

    bl_idname = "lod_tool.generate_impostor"
    bl_label = "Generate Impostor"
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
        base_name = props.export_base_name or (
            context.active_object.name if context.active_object else mesh_objs[0].name
        )
        base_name = base_name.split("_LOD")[0]

        target_coll_name = f"{base_name}_LOD_Impostor"

        res = ImpostorManager.generate_impostor_for_objects(
            mesh_objs,
            base_name,
            mode=props.impostor_mode,
            target_engine=getattr(props, "target_engine", "UE5"),
            target_collection_name=target_coll_name,
        )

        if not res:
            safe_report(self, {"ERROR"}, "Failed to generate impostor billboard.")
            return {"CANCELLED"}

        props.last_impostor_status = f"Generated {props.impostor_mode} in '{target_coll_name}'"
        safe_report(self, {"INFO"}, props.last_impostor_status)
        return {"FINISHED"}


class LOD_OT_remove_impostor(Operator):
    """Remove generated Impostor collection."""

    bl_idname = "lod_tool.remove_impostor"
    bl_label = "Remove Impostor"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context: Any) -> bool:
        return bool(context)

    def execute(self, context: Any) -> set[str]:
        if not bpy or not context:
            return {"FINISHED"}
        props, _, _ = resolve_lod_context(context)
        if not props:
            props = context.scene.lod_tool

        base_name = props.export_base_name or (context.active_object.name if context.active_object else "Asset")
        base_name = base_name.split("_LOD")[0]

        target_coll = bpy.data.collections.get(f"{base_name}_LOD_Impostor")
        if target_coll:
            for obj in list(target_coll.objects):
                bpy.data.objects.remove(obj, do_unlink=True)
            bpy.data.collections.remove(target_coll)
            props.last_impostor_status = "Removed impostor collection"
            safe_report(self, {"INFO"}, "Removed impostor collection.")
        return {"FINISHED"}


class LOD_OT_generate_collision_hulls(Operator):
    """Generate multi-convex collision decomposition hulls in sibling collection {BaseName}_Colliders."""

    bl_idname = "lod_tool.generate_collision_hulls"
    bl_label = "Generate Collision Hulls"
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
        base_name = props.export_base_name or (
            context.active_object.name if context.active_object else mesh_objs[0].name
        )
        base_name = base_name.split("_LOD")[0]

        created_hulls = CollisionManager.generate_colliders_for_objects(
            mesh_objs,
            base_name,
            mode=props.collision_decomposition_mode,
            hull_count=props.collision_hull_count,
            max_verts_per_hull=props.collision_max_verts_per_hull,
            concavity_threshold=props.collision_concavity_threshold,
            target_collection_name=f"{base_name}_Colliders",
        )

        props.last_generated_collider_count = len(created_hulls)
        safe_report(self, {"INFO"}, f"Generated {len(created_hulls)} collision hulls in '{base_name}_Colliders'")
        return {"FINISHED"}


class LOD_OT_remove_collision_hulls(Operator):
    """Remove generated collision hulls from scene."""

    bl_idname = "lod_tool.remove_collision_hulls"
    bl_label = "Remove Colliders"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context: Any) -> set[str]:
        if not bpy or not context:
            return {"FINISHED"}
        props, _, _ = resolve_lod_context(context)
        if not props:
            props = context.scene.lod_tool

        mesh_objs = get_selected_mesh_objects(context)
        base_name = props.export_base_name or (context.active_object.name if context.active_object else "Asset")
        base_name = base_name.split("_LOD")[0]

        removed = CollisionManager.remove_colliders_for_objects(mesh_objs, base_name)
        props.last_generated_collider_count = 0
        safe_report(self, {"INFO"}, f"Removed {removed} collision hulls.")
        return {"FINISHED"}


HULL_IMPOSTOR_OPERATOR_CLASSES = (
    LOD_OT_generate_impostor,
    LOD_OT_remove_impostor,
    LOD_OT_generate_collision_hulls,
    LOD_OT_remove_collision_hulls,
)
