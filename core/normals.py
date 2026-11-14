"""
Blender 5.2+ Normal Management Module.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, cast

from .compat import ensure_unique_mesh_data

if TYPE_CHECKING:
    import bpy
    import mathutils
    from mathutils import Vector
    from mathutils.kdtree import KDTree
else:
    try:
        import bpy
        import mathutils
        from mathutils import Vector
        from mathutils.kdtree import KDTree
    except ImportError:
        bpy = None
        mathutils = None
        Vector = None
        KDTree = None

logger = logging.getLogger(__name__)


class NormalManager:
    @staticmethod
    def ensure_sharp_edge_attribute(mesh: bpy.types.Mesh | None) -> bpy.types.Attribute | None:
        """
        Ensures the 'sharp_edge' boolean edge attribute exists on the mesh data-block,
        which is required in Blender 4.1+ and 5.x for custom normal and auto-smooth shading.
        """
        if not bpy or not mesh or mesh.attributes is None:
            return None
        try:
            sharp_attr = mesh.attributes.get("sharp_edge")
            if not sharp_attr:
                sharp_attr = mesh.attributes.new(name="sharp_edge", type="BOOLEAN", domain="EDGE")
            return sharp_attr
        except (RuntimeError, ValueError, AttributeError) as exc:
            logger.debug("Failed to create sharp_edge attribute: %s", exc)
            return None

    @classmethod
    def reproject_custom_split_normals(
        cls,
        lod_obj: bpy.types.Object | None,
        source_lod0: bpy.types.Object | None,
        delta_world: float = 0.1,
        armature_obj: bpy.types.Object | None = None,
        context: bpy.types.Context | None = None,
    ) -> bool:
        """
        Transfers custom split normals from LOD0 source to decimated LOD using Data Transfer modifier
        with POLYINTERP_LNORPROJ loop mapping in Blender 5.2+.
        If ray projection misses on degenerate corners, seamlessly falls back to spatial KDTree normal interpolation.
        Safely locks any associated armature to REST pose during transfer in a try/finally block.
        """
        if not bpy or not source_lod0 or not lod_obj or source_lod0 == lod_obj:
            return False

        if lod_obj.type != "MESH" or source_lod0.type != "MESH":
            return False

        if lod_obj.data is None or source_lod0.data is None:
            return False

        src_mesh = cast("bpy.types.Mesh", source_lod0.data)
        tgt_mesh = cast("bpy.types.Mesh", lod_obj.data)

        src_verts = src_mesh.vertices
        tgt_verts = tgt_mesh.vertices
        if len(src_verts) == 0 or len(tgt_verts) == 0:
            return False

        src_polys = src_mesh.polygons
        tgt_polys = tgt_mesh.polygons
        if len(src_polys) == 0 or len(tgt_polys) == 0:
            return False

        ensure_unique_mesh_data(lod_obj)

        # Detect armature if not explicitly passed
        arm = armature_obj
        if not arm:
            arm = source_lod0.find_armature()
        if not arm:
            arm = lod_obj.find_armature()

        orig_pose_pos = None
        arm_data = cast("bpy.types.Armature | None", arm.data if arm else None)
        if arm_data:
            orig_pose_pos = arm_data.pose_position
            arm_data.pose_position = "REST"

        mod_name = "__LOD_NORMAL_TRANSFER__"
        dt_mod: bpy.types.DataTransferModifier | None = None
        if lod_obj.modifiers is not None:
            existing_mod = lod_obj.modifiers.get(mod_name)
            if existing_mod:
                lod_obj.modifiers.remove(existing_mod)

            try:
                dt_mod = cast(
                    "bpy.types.DataTransferModifier", lod_obj.modifiers.new(name=mod_name, type="DATA_TRANSFER")
                )
                dt_mod.object = source_lod0
                dt_mod.use_loop_data = True
                dt_mod.data_types_loops = {"CUSTOM_NORMAL"}
                dt_mod.loop_mapping = "POLYINTERP_LNORPROJ"
                d = max(1e-4, delta_world)
                dt_mod.max_distance = max(2.0 * d, 0.05)
                dt_mod.ray_radius = 0.0
            except (RuntimeError, ValueError, AttributeError) as exc:
                logger.debug("Failed to initialize DATA_TRANSFER modifier: %s", exc)
                return cls._kdtree_normal_transfer_fallback(lod_obj, source_lod0)

        if dt_mod is None:
            return cls._kdtree_normal_transfer_fallback(lod_obj, source_lod0)

        try:
            ctx = context
            vl = ctx.view_layer if ctx else None
            vl_objects = vl.objects if vl else None

            # Move modifier to top of stack so reprojection evaluates against undeformed geometry
            try:
                if ctx:
                    with cast(Any, ctx).temp_override(active_object=lod_obj, object=lod_obj):
                        bpy.ops.object.modifier_move_to_index(modifier=dt_mod.name, index=0)
                elif vl_objects is not None:
                    vl_objects.active = lod_obj
                    bpy.ops.object.modifier_move_to_index(modifier=dt_mod.name, index=0)
            except (RuntimeError, ValueError, AttributeError) as exc:
                logger.debug("Failed moving DATA_TRANSFER modifier to index 0: %s", exc)

            if ctx:
                with cast(Any, ctx).temp_override(active_object=lod_obj, object=lod_obj, selected_objects=[lod_obj]):
                    bpy.ops.object.modifier_apply(modifier=dt_mod.name)
            elif vl_objects is not None:
                vl_objects.active = lod_obj
                bpy.ops.object.modifier_apply(modifier=dt_mod.name)
            else:
                bpy.ops.object.modifier_apply(modifier=dt_mod.name)
            lod_data = cast("bpy.types.Mesh | None", lod_obj.data)
            cls.ensure_sharp_edge_attribute(lod_data)
            if lod_data:
                lod_data.update()
            return True
        except (RuntimeError, ValueError, AttributeError) as exc:
            logger.debug("DATA_TRANSFER modifier failed (%s), attempting KDTree normal transfer fallback", exc)
            if lod_obj.modifiers is not None and dt_mod.name in lod_obj.modifiers:
                lod_obj.modifiers.remove(dt_mod)

            # Fallback: Spatial KDTree nearest-normal transfer
            return cls._kdtree_normal_transfer_fallback(lod_obj, source_lod0)
        finally:
            if arm_data and orig_pose_pos is not None:
                arm_data.pose_position = orig_pose_pos

    @classmethod
    def _kdtree_normal_transfer_fallback(
        cls, lod_obj: bpy.types.Object | None, source_lod0: bpy.types.Object | None
    ) -> bool:
        """Spatial KDTree nearest-vertex surface normal interpolation fallback in world space."""
        if not KDTree or not lod_obj or not source_lod0:
            return False
        try:
            if source_lod0.data is None or lod_obj.data is None:
                return False

            src_mesh = cast("bpy.types.Mesh", source_lod0.data)
            tgt_mesh = cast("bpy.types.Mesh", lod_obj.data)

            src_verts = src_mesh.vertices
            tgt_loops = tgt_mesh.loops
            tgt_verts = tgt_mesh.vertices

            num_src_verts = len(src_verts)
            if num_src_verts == 0 or len(tgt_loops) == 0:
                return False

            src_mat = source_lod0.matrix_world
            tgt_mat = lod_obj.matrix_world

            kd = KDTree(num_src_verts)
            for i, v in enumerate(src_verts):
                world_co = src_mat @ v.co if src_mat is not None else v.co
                kd.insert((float(world_co[0]), float(world_co[1]), float(world_co[2])), i)
            kd.balance()

            src_rot = src_mat.to_3x3() if src_mat is not None else None
            tgt_rot = tgt_mat.to_3x3() if tgt_mat is not None else None

            src_norm_to_world = None
            if src_rot is not None and abs(src_rot.determinant()) > 1e-9:
                try:
                    src_norm_to_world = src_rot.inverted().transposed()
                except (ValueError, AttributeError, ReferenceError):
                    src_norm_to_world = None

            # Build custom loop normals directly in loop order transformed into target local space
            custom_normals = []
            for loop in tgt_loops:
                v_idx = loop.vertex_index
                v_co = tgt_verts[v_idx].co
                world_tgt_co = tgt_mat @ v_co if tgt_mat is not None else v_co
                _, src_idx, _ = kd.find((float(world_tgt_co[0]), float(world_tgt_co[1]), float(world_tgt_co[2])))
                if src_idx is not None:
                    src_norm = src_verts[int(src_idx)].normal
                    v_src = Vector((float(src_norm[0]), float(src_norm[1]), float(src_norm[2]))) if Vector else src_norm
                    if src_norm_to_world:
                        world_norm = src_norm_to_world @ v_src
                    else:
                        world_norm = v_src

                    if tgt_rot:
                        tgt_norm = tgt_rot.transposed() @ world_norm
                    else:
                        tgt_norm = world_norm

                    if Vector is not None and not isinstance(tgt_norm, tuple):
                        tgt_norm = tgt_norm.normalized()
                else:
                    tgt_norm = Vector((0.0, 0.0, 1.0)) if Vector else (0.0, 0.0, 1.0)
                custom_normals.append(tgt_norm)

            try:
                tgt_mesh.normals_split_custom_set(custom_normals)
                cls.ensure_sharp_edge_attribute(tgt_mesh)
                tgt_mesh.update()
                return True
            except (AttributeError, RuntimeError) as exc:
                logger.debug("Failed setting custom normals: %s", exc)
            return False
        except (RuntimeError, ValueError, AttributeError, TypeError) as exc:
            logger.error("KDTree normal fallback failed: %s", exc)
            return False

    @classmethod
    def transfer_boundary_loop_normals_kdtree(
        cls, chunk_obj: bpy.types.Object | None, source_obj: bpy.types.Object | None
    ) -> bool:
        """Transfers custom normals to chunk mesh by world-space KDTree sampling from source."""
        return cls._kdtree_normal_transfer_fallback(chunk_obj, source_obj)
