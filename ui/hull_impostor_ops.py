"""
Convex Collision Hull Decomposition and Billboard Impostor Operators.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

try:
    import bpy
    from bpy.props import BoolProperty, EnumProperty, IntProperty
    from bpy.types import Operator
except ImportError:
    bpy = None
    Operator = object
    BoolProperty = None  # type: ignore
    EnumProperty = None  # type: ignore
    IntProperty = None  # type: ignore

try:
    from ..core.collision import CollisionManager
    from ..core.impostor import ImpostorManager, resolve_impostor_export_dir
    from ..core.impostor_baker import ImpostorAtlasBaker
    from ..core.impostor_preview import setup_impostor_preview_rig, teardown_impostor_preview_rig
    from ..exporters.shaders import export_companion_shaders
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
    from core.impostor import ImpostorManager, resolve_impostor_export_dir
    from core.impostor_baker import ImpostorAtlasBaker
    from core.impostor_preview import setup_impostor_preview_rig, teardown_impostor_preview_rig
    from exporters.shaders import export_companion_shaders
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
            scene=context.scene,
        )

        if not res:
            safe_report(self, {"ERROR"}, "Failed to generate impostor billboard.")
            return {"CANCELLED"}

        # Determine output texture directory
        tex_dir = resolve_impostor_export_dir(getattr(props, "export_directory", ""))

        # Execute Cycles GPU selected-to-active baking pass
        baked_maps = ImpostorAtlasBaker.bake_impostor_textures(
            mesh_objs,
            base_name,
            output_dir=tex_dir,
            mode=props.impostor_mode,
            atlas_resolution=calc_res,
            target_engine=getattr(props, "target_engine", "UE5"),
            dilation_iterations=4,
            impostor_obj=res,
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

        # Automatically export engine companion shaders for octahedral impostors
        if props.impostor_mode in {"OCTAHEDRAL_HEMI", "OCTAHEDRAL_SPHERE"} and export_companion_shaders:
            try:
                target_eng = getattr(props, "target_engine", "ALL")
                shader_res = export_companion_shaders(
                    base_name=base_name,
                    output_dir=tex_dir,
                    target_engine=target_eng,
                    grid_size=8,
                    alpha_scissor=0.5,
                )
                if shader_res:
                    props.last_impostor_status += f" (+{len(shader_res)} Shaders)"
            except Exception as sh_err:
                logger.debug("Failed exporting companion shaders: %s", sh_err)

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


class LOD_OT_setup_impostor_preview_rig(Operator):
    """Setup non-destructive In-Blender comparison turntable preview rig for Octahedral Impostor."""

    bl_idname = "lod_tool.setup_impostor_preview_rig"
    bl_label = "Setup Preview Rig"
    bl_options = {"REGISTER", "UNDO"}

    mode: EnumProperty(  # type: ignore
        name="Layout Mode",
        description="Preview layout arrangement",
        items=[
            ("SIDE_BY_SIDE", "Side-by-Side", "Side-by-side comparison with synchronous pedestal rotation"),
            ("CENTER_OVERLAY", "Centered Overlay", "Impostor centered directly over source mesh for A/B inspection"),
        ],
        default="SIDE_BY_SIDE",
    )

    num_frames: IntProperty(  # type: ignore
        name="Turntable Frames",
        description="Number of frames for cyclic 360-degree pedestal turntable",
        default=72,
        min=16,
        max=360,
    )

    create_turntable: BoolProperty(  # type: ignore
        name="Create Turntable Animation",
        description="Keyframe cyclic 360-degree pedestal turntable for timeline playback",
        default=False,
    )

    @classmethod
    def poll(cls, context: Any) -> bool:
        return bool(context and (get_selected_mesh_objects(context) or get_lod0_mesh_objects(context)))

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
            safe_report(self, {"WARNING"}, "No valid mesh objects selected for preview rig.")
            return {"CANCELLED"}

        base_name = resolve_effective_asset_name(context, props)
        if not base_name or base_name in {"AUTO", "NONE"}:
            base_name = resolve_asset_base_name(context, mesh_objs)

        tex_dir = resolve_impostor_export_dir(getattr(props, "export_directory", ""))
        target_engine = getattr(props, "target_engine", "UE5")

        rig_info = setup_impostor_preview_rig(
            context=context,
            mesh_objs=mesh_objs,
            base_name=base_name,
            texture_dir=tex_dir,
            mode=self.mode,
            num_frames=self.num_frames,
            target_engine=target_engine,
            create_turntable=self.create_turntable,
        )

        if not rig_info:
            safe_report(
                self,
                {"WARNING"},
                f"Could not setup preview rig. Ensure octahedral atlas was baked first for '{base_name}'.",
            )
            return {"CANCELLED"}

        msg = f"Preview rig created in collection '{rig_info.get('collection')}'."
        if self.create_turntable:
            msg += " (Press Space to play turntable)."
        else:
            msg += " (Real-time Viewport Tracking active)."
        safe_report(self, {"INFO"}, msg)
        return {"FINISHED"}


class LOD_OT_remove_impostor_preview_rig(Operator):
    """Cleanly delete the Impostor Preview Rig and restore default viewport and camera."""

    bl_idname = "lod_tool.remove_impostor_preview_rig"
    bl_label = "Remove Preview Rig"
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

        success = teardown_impostor_preview_rig(context, base_name)
        if success:
            safe_report(self, {"INFO"}, f"Removed preview rig for '{base_name}'.")
        else:
            safe_report(self, {"INFO"}, f"No active preview rig found for '{base_name}'.")
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
            target_engine=getattr(props, "target_engine", "GENERIC"),
            scene=context.scene,
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
    LOD_OT_setup_impostor_preview_rig,
    LOD_OT_remove_impostor_preview_rig,
    LOD_OT_generate_collision_hulls,
    LOD_OT_remove_collision_hulls,
)
