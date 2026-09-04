"""
Blender 5.2+ Normal Management Module.
"""

from __future__ import annotations

import logging
from typing import Any

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
    def ensure_sharp_edge_attribute(mesh: Any) -> Any:
        """
        Ensures the 'sharp_edge' boolean edge attribute exists on the mesh data-block,
        which is required in Blender 4.1+ and 5.x for custom normal and auto-smooth shading.
        """
        if not bpy or not mesh or not hasattr(mesh, "attributes"):
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
        cls, lod_obj: Any, source_lod0: Any, delta_world: float = 0.1, armature_obj: Any = None
    ) -> bool:
        """
        Transfers custom split normals from LOD0 source to decimated LOD using Data Transfer modifier
        with POLYINTERP_LNORPROJ loop mapping in Blender 5.2+.
        If ray projection misses on degenerate corners, seamlessly falls back to spatial KDTree normal interpolation.
        Safely locks any associated armature to REST pose during transfer in a try/finally block.
        """
        if not bpy or not source_lod0 or not lod_obj or source_lod0 == lod_obj:
            return False

        if getattr(lod_obj, "type", "") != "MESH" or getattr(source_lod0, "type", "") != "MESH":
            return False

        if not hasattr(lod_obj, "data") or not lod_obj.data or not hasattr(source_lod0, "data") or not source_lod0.data:
            return False

        src_verts = getattr(source_lod0.data, "vertices", [])
        tgt_verts = getattr(lod_obj.data, "vertices", [])
        if len(src_verts) == 0 or len(tgt_verts) == 0:
            return False

        src_polys = getattr(source_lod0.data, "polygons", [])
        tgt_polys = getattr(lod_obj.data, "polygons", [])
        if len(src_polys) == 0 or len(tgt_polys) == 0:
            return False

        # Detect armature if not explicitly passed
        arm = armature_obj
        if not arm and hasattr(source_lod0, "find_armature"):
            arm = source_lod0.find_armature()
        if not arm and hasattr(lod_obj, "find_armature"):
            arm = lod_obj.find_armature()

        orig_pose_pos = None
        if arm and hasattr(arm, "data") and hasattr(arm.data, "pose_position"):
            orig_pose_pos = arm.data.pose_position
            arm.data.pose_position = "REST"

        mod_name = "__LOD_NORMAL_TRANSFER__"
        dt_mod: Any = None
        if hasattr(lod_obj, "modifiers"):
            existing_mod = lod_obj.modifiers.get(mod_name)
            if existing_mod:
                lod_obj.modifiers.remove(existing_mod)

            try:
                dt_mod = lod_obj.modifiers.new(name=mod_name, type="DATA_TRANSFER")
                dt_mod.object = source_lod0
                dt_mod.use_loop_data = True
                dt_mod.data_types_loops = {"CUSTOM_NORMAL"}
                dt_mod.loop_mapping = "POLYINTERP_LNORPROJ"
                d = max(1e-4, delta_world)
                dt_mod.max_distance = max(2.0 * d, 0.05)
                dt_mod.ray_radius = max(d, 0.02)
            except Exception as exc:
                logger.debug("Failed to initialize DATA_TRANSFER modifier: %s", exc)
                return cls._kdtree_normal_transfer_fallback(lod_obj, source_lod0)

        if dt_mod is None:
            return cls._kdtree_normal_transfer_fallback(lod_obj, source_lod0)

        try:
            if hasattr(bpy.context, "temp_override"):
                with bpy.context.temp_override(active_object=lod_obj, object=lod_obj, selected_objects=[lod_obj]):
                    bpy.ops.object.modifier_apply(modifier=dt_mod.name)
            elif hasattr(bpy.context, "view_layer") and hasattr(bpy.context.view_layer, "objects"):
                bpy.context.view_layer.objects.active = lod_obj
                bpy.ops.object.modifier_apply(modifier=dt_mod.name)
            cls.ensure_sharp_edge_attribute(lod_obj.data)
            lod_obj.data.update()
            return True
        except Exception as exc:
            logger.debug("DATA_TRANSFER modifier failed (%s), attempting KDTree normal transfer fallback", exc)
            if hasattr(lod_obj, "modifiers") and dt_mod.name in lod_obj.modifiers:
                lod_obj.modifiers.remove(dt_mod)

            # Fallback: Spatial KDTree nearest-normal transfer
            return cls._kdtree_normal_transfer_fallback(lod_obj, source_lod0)
        finally:
            if arm and orig_pose_pos is not None and hasattr(arm.data, "pose_position"):
                arm.data.pose_position = orig_pose_pos

    @classmethod
    def _kdtree_normal_transfer_fallback(cls, lod_obj: Any, source_lod0: Any) -> bool:
        """Spatial KDTree nearest-vertex surface normal interpolation fallback in world space."""
        if not KDTree or not lod_obj or not source_lod0:
            return False
        try:
            src_mesh = getattr(source_lod0, "data", None)
            tgt_mesh = getattr(lod_obj, "data", None)
            if not src_mesh or not tgt_mesh:
                return False

            src_verts = getattr(src_mesh, "vertices", [])
            tgt_loops = getattr(tgt_mesh, "loops", [])
            tgt_verts = getattr(tgt_mesh, "vertices", [])

            num_src_verts = len(src_verts)
            if num_src_verts == 0 or len(tgt_loops) == 0:
                return False

            src_mat = getattr(source_lod0, "matrix_world", None)
            tgt_mat = getattr(lod_obj, "matrix_world", None)

            kd = KDTree(num_src_verts)
            for i, v in enumerate(src_verts):
                world_co = src_mat @ v.co if src_mat is not None else v.co
                kd.insert(world_co, i)
            kd.balance()

            # Build custom loop normals directly in loop order in world space
            custom_normals = []
            for loop in tgt_loops:
                v_idx = loop.vertex_index
                v_co = tgt_verts[v_idx].co
                world_tgt_co = tgt_mat @ v_co if tgt_mat is not None else v_co
                _, src_idx, _ = kd.find(world_tgt_co)
                src_norm = src_verts[src_idx].normal
                custom_normals.append(src_norm)

            if hasattr(tgt_mesh, "normals_split_custom_set"):
                tgt_mesh.normals_split_custom_set(custom_normals)
                cls.ensure_sharp_edge_attribute(tgt_mesh)
                tgt_mesh.update()
                return True
            return False
        except Exception as exc:
            logger.error("KDTree normal fallback failed: %s", exc)
            return False

    @classmethod
    def transfer_boundary_loop_normals_kdtree(cls, chunk_obj: Any, source_obj: Any) -> bool:
        """Transfers custom normals to chunk mesh by world-space KDTree sampling from source."""
        return cls._kdtree_normal_transfer_fallback(chunk_obj, source_obj)
