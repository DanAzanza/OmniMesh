# pyright: reportInvalidTypeForm=none
"""
Convex Collision Hull Decomposition and Billboard Impostor Operators.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    import bpy
    from bpy.types import Operator
else:
    try:
        import bpy
        from bpy.types import Operator
    except ImportError:
        bpy = None
        Operator = object


try:
    from ..core.collision import CollisionManager
    from ..core.exceptions import OmniMeshError
    from ..core.impostor import ImpostorManager, resolve_impostor_export_dir
    from ..core.impostor_baker import ImpostorAtlasBaker
    from ..core.impostor_math import (
        compute_impostor_atlas_resolution,
        normalize_impostor_grid_size,
        resolve_effective_impostor_mode,
    )
    from ..exporters.shaders import export_companion_shaders
    from .impostor_viewport_ops import start_impostor_viewport_timer
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
    from core.exceptions import OmniMeshError
    from core.impostor import ImpostorManager, resolve_impostor_export_dir
    from core.impostor_baker import ImpostorAtlasBaker
    from core.impostor_math import (
        compute_impostor_atlas_resolution,
        normalize_impostor_grid_size,
        resolve_effective_impostor_mode,
    )
    from exporters.shaders import export_companion_shaders
    from ui.impostor_viewport_ops import start_impostor_viewport_timer
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
        return bool(context and (get_selected_mesh_objects(context) or get_lod0_mesh_objects(context)))

    def execute(self, context: Any) -> set[Any]:
        if not bpy or not context:
            return {"FINISHED"}
        props, _, _ = resolve_lod_context(context)
        if not props:
            props = context.scene.lod_tool

        mesh_objs = get_lod0_mesh_objects(context) or get_selected_mesh_objects(context)
        if not mesh_objs:
            safe_report(self, {"WARNING"}, "No valid mesh objects found for impostor generation.")
            return {"CANCELLED"}
        base_name = resolve_effective_asset_name(context, props)
        if not base_name or base_name in {"AUTO", "NONE"}:
            base_name = resolve_asset_base_name(context, mesh_objs)

        target_coll_name = f"{base_name}_LOD_Impostor"
        bdata = getattr(context, "blend_data", None) or (bpy.data if bpy and hasattr(bpy, "data") else None)
        if bdata is None:
            safe_report(self, {"ERROR"}, "Missing BlendData context for impostor generation.")
            return {"CANCELLED"}

        # Resolution & projection settings
        s_pct = props.lods[-1].screen_size_pct if props and len(props.lods) > 0 else 5.0
        calc_res = compute_impostor_atlas_resolution(
            auto_resolution=bool(getattr(props, "auto_impostor_resolution", True)),
            configured_resolution=getattr(props, "impostor_resolution", "2048"),
            final_screen_size_pct=s_pct,
        )
        effective_mode = resolve_effective_impostor_mode(
            str(getattr(props, "impostor_mode", "ORTHO_3_AXES")),
            bool(getattr(props, "impostor_render_underside", False)),
        )
        raw_grid = getattr(props, "impostor_grid_size", 8)
        grid_size = (
            normalize_impostor_grid_size(raw_grid)
            if isinstance(raw_grid, int) and not isinstance(raw_grid, bool)
            else 8
        )

        res = ImpostorManager.generate_impostor_for_objects(
            mesh_objs,
            base_name,
            mode=effective_mode,
            target_engine="CANONICAL",
            target_collection_name=target_coll_name,
            atlas_resolution=calc_res,
            scene=context.scene,
            context=context,
            grid_size=grid_size,
            blend_data=bdata,
        )

        if not res:
            safe_report(self, {"ERROR"}, "Failed to generate impostor billboard.")
            return {"CANCELLED"}

        # Determine output texture directory and clear any stale *_Master backups before fresh Cycles bake
        tex_dir = resolve_impostor_export_dir(getattr(props, "export_directory", ""), blend_data=bdata)
        for master_sfx in ("_BaseColor_Master.png", "_Normal_Master.png", "_ORM_Master.png"):
            stale_master = os.path.join(tex_dir, f"T_{base_name}_Impostor{master_sfx}")
            if os.path.isfile(stale_master):
                os.remove(stale_master)

        # Execute Cycles GPU selected-to-active canonical Metalness baking pass
        try:
            baked_maps = ImpostorAtlasBaker.bake_impostor_textures(
                mesh_objs,
                base_name,
                output_dir=tex_dir,
                mode=effective_mode,
                atlas_resolution=calc_res,
                target_engine="CANONICAL",
                dilation_iterations=4,
                impostor_obj=res,
                context=context,
                grid_size=grid_size,
                blend_data=bdata,
            )
        except OmniMeshError as bake_err:
            safe_report(self, {"ERROR"}, f"Impostor baking failed: {bake_err}")
            return {"CANCELLED"}

        _store_impostor_metadata(res, base_name, baked_maps)

        res_mesh: Any = getattr(res, "data", None)
        if baked_maps and res_mesh and res_mesh.materials:
            imp_mat = res_mesh.materials[0]
            ImpostorManager.bind_baked_textures_to_material(
                imp_mat,
                base_color_path=baked_maps.get("BaseColor", ""),
                normal_path=baked_maps.get("Normal", ""),
                orm_path=baked_maps.get("ORM", ""),
                blend_data=bdata,
            )
            props.last_impostor_status = (
                f"Baked {calc_res}px Canonical Impostor ({len(baked_maps)} maps) in '{target_coll_name}'"
            )
        else:
            props.last_impostor_status = f"Generated {props.impostor_mode} in '{target_coll_name}'"

        # Attach live viewport tracking billboard helper and export companion HLSL shaders for Octahedral mode
        if effective_mode in {"OCTAHEDRAL_HEMI", "OCTAHEDRAL_SPHERE"}:
            _attach_octahedral_viewport_billboard(res, base_name, context, bdata)
            if export_companion_shaders:
                try:
                    shader_res = export_companion_shaders(
                        base_name=base_name,
                        output_dir=tex_dir,
                        target_engine="ALL",
                        grid_size=grid_size,
                        alpha_scissor=0.5,
                        mode=effective_mode,
                    )
                    if shader_res:
                        props.last_impostor_status += f" (+{len(shader_res)} Shaders)"
                except Exception as sh_err:
                    logger.debug("Failed exporting companion shaders: %s", sh_err)

        safe_report(self, {"INFO"}, props.last_impostor_status)
        return {"FINISHED"}


def _store_impostor_metadata(impostor_obj: Any, base_name: str, baked_maps: dict[str, str] | None) -> None:
    """Persists canonical base name and bounding sphere metadata onto the generated impostor object."""
    meta: dict[str, Any] = {"_impostor_base_name": base_name}
    if baked_maps:
        if "sphere_radius" in baked_maps:
            try:
                meta["_impostor_sphere_radius"] = float(baked_maps["sphere_radius"])
            except (TypeError, ValueError):
                pass
        if "sphere_center" in baked_maps:
            meta["_impostor_sphere_center"] = str(baked_maps["sphere_center"])
    for key, val in meta.items():
        try:
            impostor_obj[key] = val
        except TypeError:
            pass


def _attach_octahedral_viewport_billboard(
    impostor_obj: Any,
    base_name: str,
    context: Any,
    bdata: Any,
) -> None:
    """Attaches a viewport-facing TRACK_TO helper for live Octahedral viewport preview (muted on export)."""
    if not bpy or getattr(bpy.app, "background", False) or not bdata or not impostor_obj:
        return

    helpers_name = f"{base_name}_Helpers"
    helpers_coll = bdata.collections.get(helpers_name)
    if not helpers_coll:
        helpers_coll = bdata.collections.new(helpers_name)
        sc = getattr(context, "scene", None)
        if sc and sc.collection and helpers_coll.name not in sc.collection.children:
            sc.collection.children.link(helpers_coll)

    target_name = f"{base_name}_Impostor_ViewTarget"
    target_empty = bdata.objects.get(target_name)
    if not target_empty:
        target_empty = bdata.objects.new(target_name, None)
        target_empty.empty_display_type = "PLAIN_AXES"
        target_empty.empty_display_size = 0.2
        if helpers_coll and target_empty.name not in helpers_coll.objects:
            helpers_coll.objects.link(target_empty)

    loc = impostor_obj.location
    target_empty.location = (float(loc[0]), float(loc[1]) - 10.0, float(loc[2]))
    target_empty.hide_render = True

    constraints = impostor_obj.constraints
    track_c = next((c for c in constraints if c.name == "OmniMesh_Viewport_Billboard"), None)
    if not track_c:
        track_c = constraints.new(type="TRACK_TO")
        track_c.name = "OmniMesh_Viewport_Billboard"
    track_c.target = target_empty
    track_c.track_axis = "TRACK_NEGATIVE_Y"
    track_c.up_axis = "UP_Z"
    start_impostor_viewport_timer(base_name)


class LOD_OT_generate_collision_hulls(Operator):
    """Generate multi-convex collision decomposition hulls in sibling collection {BaseName}_Colliders."""

    bl_idname = "lod_tool.generate_collision_hulls"
    bl_label = "Generate Collision Hulls"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context: Any) -> bool:
        return bool(context and (get_selected_mesh_objects(context) or get_lod0_mesh_objects(context)))

    def execute(self, context: Any) -> set[Any]:
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

        bdata = getattr(context, "blend_data", None)
        if bdata is None:
            safe_report(self, {"ERROR"}, "Missing BlendData context for collision generation.")
            return {"CANCELLED"}
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
            blend_data=bdata,
        )

        props.last_generated_collider_count = len(created_hulls)
        safe_report(self, {"INFO"}, f"Generated {len(created_hulls)} collision hulls in '{base_name}_Colliders'")
        return {"FINISHED"}


HULL_IMPOSTOR_OPERATOR_CLASSES = (
    LOD_OT_generate_impostor,
    LOD_OT_generate_collision_hulls,
)
