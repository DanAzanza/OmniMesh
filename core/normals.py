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
        sharp_attr = mesh.attributes.get("sharp_edge")
        if not sharp_attr:
            try:
                sharp_attr = mesh.attributes.new(name="sharp_edge", type="BOOLEAN", domain="EDGE")
            except (RuntimeError, ValueError) as exc:
                logger.debug("Failed to create sharp_edge attribute: %s", exc)
                sharp_attr = None
        return sharp_attr

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

        if not lod_obj.data or not source_lod0.data:
            return False

        if len(lod_obj.data.vertices) == 0 or len(source_lod0.data.vertices) == 0:
            return False

        if len(lod_obj.data.polygons) == 0 or len(source_lod0.data.polygons) == 0:
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
        existing_mod = lod_obj.modifiers.get(mod_name)
        if existing_mod:
            lod_obj.modifiers.remove(existing_mod)

        dt_mod = lod_obj.modifiers.new(name=mod_name, type="DATA_TRANSFER")
        dt_mod.object = source_lod0
        dt_mod.use_loop_data = True
        dt_mod.data_types_loops = {"CUSTOM_NORMAL"}
        dt_mod.loop_mapping = "POLYINTERP_LNORPROJ"
        d = max(1e-4, delta_world)
        dt_mod.max_distance = max(2.0 * d, 0.05)
        dt_mod.ray_radius = max(d, 0.02)

        try:
            if hasattr(bpy.context, "temp_override"):
                with bpy.context.temp_override(active_object=lod_obj, object=lod_obj, selected_objects=[lod_obj]):
                    bpy.ops.object.modifier_apply(modifier=dt_mod.name)
            else:
                bpy.context.view_layer.objects.active = lod_obj
                bpy.ops.object.modifier_apply(modifier=dt_mod.name)
            cls.ensure_sharp_edge_attribute(lod_obj.data)
            lod_obj.data.update()
            return True
        except (RuntimeError, ValueError) as exc:
            logger.debug("DATA_TRANSFER modifier failed (%s), attempting KDTree normal transfer fallback", exc)
            if dt_mod.name in lod_obj.modifiers:
                lod_obj.modifiers.remove(dt_mod)

            # Fallback: Spatial KDTree nearest-normal transfer
            return cls._kdtree_normal_transfer_fallback(lod_obj, source_lod0)
        finally:
            if arm and orig_pose_pos is not None and hasattr(arm.data, "pose_position"):
                arm.data.pose_position = orig_pose_pos

    @classmethod
    def _kdtree_normal_transfer_fallback(cls, lod_obj: Any, source_lod0: Any) -> bool:
        """Spatial KDTree nearest-vertex surface normal interpolation fallback."""
        if not KDTree or not lod_obj or not source_lod0:
            return False
        try:
            src_mesh = source_lod0.data
            tgt_mesh = lod_obj.data
            num_src_verts = len(src_mesh.vertices)
            if num_src_verts == 0 or len(tgt_mesh.loops) == 0:
                return False

            kd = KDTree(num_src_verts)
            for i, v in enumerate(src_mesh.vertices):
                kd.insert(v.co, i)
            kd.balance()

            # Build custom loop normals from nearest source vertex normals
            custom_normals = []
            for poly in tgt_mesh.polygons:
                for loop_idx in poly.loop_indices:
                    v_idx = tgt_mesh.loops[loop_idx].vertex_index
                    v_co = tgt_mesh.vertices[v_idx].co
                    _, src_idx, _ = kd.find(v_co)
                    src_norm = src_mesh.vertices[src_idx].normal
                    custom_normals.append(src_norm)

            tgt_mesh.normals_split_custom_set(custom_normals)
            cls.ensure_sharp_edge_attribute(tgt_mesh)
            tgt_mesh.update()
            return True
        except (RuntimeError, ValueError, IndexError, AttributeError) as exc:
            logger.error("KDTree normal fallback failed: %s", exc)
            return False
