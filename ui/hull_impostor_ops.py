"""
Convex Collision Hull Decomposition and Billboard Impostor Operators.
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

try:
    import bpy
    from bpy.types import Operator
except ImportError:
    bpy = None
    Operator = object

try:
    from ..core.collision import CollisionManager
    from ..core.impostor import ImpostorManager
    from ..core.impostor_baker import ImpostorAtlasBaker
    from .utils import (
        get_lod0_mesh_objects,
        get_selected_mesh_objects,
        resolve_asset_base_name,
        resolve_effective_asset_name,
        resolve_lod_context,
        safe_report,
    )
except (ImportError, ValueError):
    from core.collision import CollisionManager
    from core.impostor import ImpostorManager
    from core.impostor_baker import ImpostorAtlasBaker
    from ui.utils import (
        get_lod0_mesh_objects,
        get_selected_mesh_objects,
        resolve_asset_base_name,
        resolve_effective_asset_name,
        resolve_lod_context,
        safe_report,
    )


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
        base_name = resolve_effective_asset_name(context, props)
        if not base_name or base_name in {"AUTO", "NONE"}:
            base_name = resolve_asset_base_name(context, mesh_objs)

        target_coll_name = f"{base_name}_LOD_Impostor"

        # Resolution calculation
        if getattr(props, "auto_impostor_resolution", True):
            # Derive resolution from screen size (nominal ~10% screen size -> 1024, clamp 256..4096 next pow 2)
            s_pct = props.lods[-1].screen_size_pct if props and len(props.lods) > 0 else 5.0
            target_px = max(256, min(4096, int(2048 * (s_pct / 10.0))))
            # Next power of 2
            calc_res = 1 << (target_px - 1).bit_length()
            calc_res = max(256, min(4096, calc_res))
        else:
            try:
                calc_res = int(getattr(props, "impostor_resolution", "2048"))
            except (ValueError, TypeError):
                calc_res = 2048

        res = ImpostorManager.generate_impostor_for_objects(
            mesh_objs,
            base_name,
            mode=props.impostor_mode,
            target_engine=getattr(props, "target_engine", "UE5"),
            target_collection_name=target_coll_name,
            atlas_resolution=calc_res,
        )

        if not res:
            safe_report(self, {"ERROR"}, "Failed to generate impostor billboard.")
            return {"CANCELLED"}

        # Determine output texture directory
        export_dir = getattr(props, "export_directory", "") or "//Textures/"
        if export_dir.startswith("//") and bpy and hasattr(bpy.data, "filepath") and bpy.data.filepath:
            export_dir = bpy.path.abspath(export_dir)
        elif not os.path.isabs(export_dir):
            export_dir = os.path.abspath(export_dir)
        tex_dir = os.path.join(export_dir, "Textures") if not export_dir.endswith("Textures") else export_dir

        # Execute unlit multi-angle baking pass
        baked_maps = ImpostorAtlasBaker.bake_impostor_textures(
            mesh_objs,
            base_name,
            output_dir=tex_dir,
            mode=props.impostor_mode,
            atlas_resolution=calc_res,
            target_engine=getattr(props, "target_engine", "UE5"),
            dilation_iterations=4,
        )

        if baked_maps and hasattr(res, "data") and res.data.materials:
            imp_mat = res.data.materials[0]
            ImpostorManager.bind_baked_textures_to_material(
                imp_mat,
                base_color_path=baked_maps.get("BaseColor", ""),
                normal_path=baked_maps.get("Normal", ""),
                orm_path=baked_maps.get("ORM", ""),
            )
            props.last_impostor_status = (
                f"Baked {calc_res}px Impostor Atlas ({len(baked_maps)} maps) in '{target_coll_name}'"
            )
        else:
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

        mesh_objs = get_selected_mesh_objects(context)
        base_name = resolve_effective_asset_name(context, props)
        if not base_name or base_name in {"AUTO", "NONE"}:
            base_name = resolve_asset_base_name(context, mesh_objs) if mesh_objs else "Asset"

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
        return bool(context and (get_selected_mesh_objects(context) or get_lod0_mesh_objects(context)))

    def execute(self, context: Any) -> set[str]:
        if not bpy or not context:
            return {"FINISHED"}
        props, _, _ = resolve_lod_context(context)
        if not props:
            props = context.scene.lod_tool

        # Always resolve all true LOD0 source meshes for the asset/collection
        mesh_objs = get_lod0_mesh_objects(context)
        if not mesh_objs:
            mesh_objs = get_selected_mesh_objects(context)

        if not mesh_objs:
            safe_report(self, {"WARNING"}, "No valid LOD0 mesh objects found for collision generation.")
            return {"CANCELLED"}

        base_name = resolve_effective_asset_name(context, props)
        if not base_name or base_name in {"AUTO", "NONE"}:
            base_name = resolve_asset_base_name(context, mesh_objs)

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

        mesh_objs = get_lod0_mesh_objects(context)
        if not mesh_objs:
            mesh_objs = get_selected_mesh_objects(context)

        base_name = resolve_effective_asset_name(context, props)
        if not base_name or base_name in {"AUTO", "NONE"}:
            base_name = resolve_asset_base_name(context, mesh_objs)

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
