"""
Multi-Convex Collision Hull Generator & Physics Hierarchy Manager for OmniMesh.

Provides Blender scene integration, collection linking, transform hierarchy synchronization,
and engine-specific collider naming (UE5, Unity, Godot, MSFS).
"""

from __future__ import annotations

import logging
from typing import Any, List

from .collision_decomposer import CollisionDecomposer

try:
    import bmesh
    import bpy
except ImportError:
    bpy = None  # type: ignore
    bmesh = None  # type: ignore

logger = logging.getLogger(__name__)

# Re-export for backward compatibility
__all__ = ["CollisionDecomposer", "CollisionManager"]


class CollisionManager:
    """
    Manages creation, removal, hierarchy synchronization, and engine name mapping
    for collision hull objects in Blender.
    """

    @classmethod
    def generate_colliders_for_objects(
        cls,
        mesh_objs: List[Any],
        base_name: str,
        hull_count: int = 4,
        max_verts_per_hull: int = 32,
        concavity_threshold: float = 0.05,
        mode: str = "PER_OBJECT",
        target_collection_name: str = "",
        target_engine: str = "",
    ) -> List[Any]:
        if not bpy or not mesh_objs:
            return []

        # Remove pre-existing colliders for clean regeneration first
        cls.remove_colliders_for_objects(mesh_objs, base_name)

        coll_name = target_collection_name or f"{base_name}_Colliders"
        target_coll = bpy.data.collections.get(coll_name)
        if not target_coll:
            target_coll = bpy.data.collections.new(coll_name)

        root_coll = bpy.data.collections.get(base_name)
        if root_coll and hasattr(root_coll, "children"):
            c_children = root_coll.children
            already_in = False
            try:
                already_in = (
                    target_coll.name in c_children if not isinstance(c_children, list) else target_coll in c_children
                )
            except Exception as e:
                logger.debug("Failed checking target collection membership: %s", e)
            if not already_in:
                if hasattr(c_children, "link"):
                    c_children.link(target_coll)
                elif hasattr(c_children, "append"):
                    c_children.append(target_coll)
            # Unlink from scene root if nested under root_coll
            if (
                hasattr(bpy.context, "scene")
                and hasattr(bpy.context.scene, "collection")
                and hasattr(bpy.context.scene.collection, "children")
                and hasattr(bpy.context.scene.collection.children, "unlink")
            ):
                try:
                    if target_coll.name in bpy.context.scene.collection.children:
                        bpy.context.scene.collection.children.unlink(target_coll)
                except Exception as e:
                    logger.debug("Failed unlinking target collection from scene root: %s", e)
        elif (
            hasattr(bpy.context, "scene")
            and hasattr(bpy.context.scene, "collection")
            and hasattr(bpy.context.scene.collection, "children")
            and target_coll.name not in bpy.context.scene.collection.children
        ):
            bpy.context.scene.collection.children.link(target_coll)

        # Resolve target engine for naming if not explicitly passed
        resolved_engine = target_engine
        if not resolved_engine and hasattr(bpy.context, "scene"):
            props = getattr(bpy.context.scene, "lod_tool", None)
            if props:
                resolved_engine = getattr(props, "target_engine", "")

        created_collider_objs: List[Any] = []
        hull_index = 1

        if mode == "CONSOLIDATED" and len(mesh_objs) > 1:
            # Combine all objects into single temporary BMesh in world coordinates
            bm_unified = bmesh.new()
            temp_meshes_to_clean: list[Any] = []
            try:
                for obj in mesh_objs:
                    bm_temp = bmesh.new()
                    try:
                        bm_temp.from_mesh(obj.data)
                        bmesh.ops.transform(bm_temp, matrix=obj.matrix_world, verts=bm_temp.verts[:])
                        temp_m = bpy.data.meshes.new("_om_temp_sub")
                        bm_temp.to_mesh(temp_m)
                        temp_meshes_to_clean.append(temp_m)
                        bm_unified.from_mesh(temp_m)
                    finally:
                        bm_temp.free()

                for temp_m in temp_meshes_to_clean:
                    if temp_m in bpy.data.meshes.values():
                        bpy.data.meshes.remove(temp_m)
                temp_meshes_to_clean.clear()

                # Decompose unified geometry
                hulls = CollisionDecomposer.decompose_mesh_to_hulls(
                    k_target=hull_count,
                    max_verts_per_hull=max_verts_per_hull,
                    concavity_threshold=concavity_threshold,
                    bm_source=bm_unified,
                )
            finally:
                bm_unified.free()
                for temp_m in temp_meshes_to_clean:
                    if temp_m in bpy.data.meshes.values():
                        bpy.data.meshes.remove(temp_m)

            try:
                for bm_hull in hulls:
                    c_name = cls.map_collider_name_for_engine(base_name, hull_index, resolved_engine)
                    c_mesh = bpy.data.meshes.new(f"{c_name}_Mesh")
                    bm_hull.to_mesh(c_mesh)

                    c_obj = bpy.data.objects.new(c_name, c_mesh)
                    c_obj.display_type = "WIRE"
                    c_obj.show_wire = True
                    c_obj.hide_render = True
                    c_obj["_is_collider"] = True
                    c_obj["_om_asset_base"] = base_name
                    target_coll.objects.link(c_obj)
                    created_collider_objs.append(c_obj)
                    hull_index += 1
            finally:
                for bm_hull in hulls:
                    try:
                        bm_hull.free()
                    except Exception as exc:
                        logger.debug("bm_hull.free() skipped: %s", exc)
        else:
            # PER_OBJECT Area-Weighted Decomposition
            total_area = (
                sum(
                    sum(getattr(p, "area", 0.0) for p in getattr(obj.data, "polygons", []))
                    for obj in mesh_objs
                    if getattr(obj, "data", None)
                )
                or 1.0
            )

            for obj in mesh_objs:
                obj_data = getattr(obj, "data", None)
                if not obj_data:
                    continue
                obj_area = sum(getattr(p, "area", 0.0) for p in getattr(obj_data, "polygons", []))
                # Area-weighted hull budget
                obj_hull_budget = max(1, int(round(hull_count * (obj_area / total_area))))
                sub_base = obj.name.split("_LOD")[0]

                hulls = CollisionDecomposer.decompose_mesh_to_hulls(
                    obj,
                    k_target=obj_hull_budget,
                    max_verts_per_hull=max_verts_per_hull,
                    concavity_threshold=concavity_threshold,
                )

                try:
                    for bm_hull in hulls:
                        c_name = cls.map_collider_name_for_engine(sub_base, hull_index, resolved_engine)
                        c_mesh = bpy.data.meshes.new(f"{c_name}_Mesh")
                        bm_hull.to_mesh(c_mesh)

                        c_obj = bpy.data.objects.new(c_name, c_mesh)
                        # Inherit parent and transform hierarchy cleanly
                        if obj.parent:
                            c_obj.parent = obj.parent
                            c_obj.parent_type = obj.parent_type
                            if hasattr(obj, "parent_bone") and obj.parent_bone:
                                c_obj.parent_bone = obj.parent_bone
                            c_obj.matrix_parent_inverse = obj.matrix_parent_inverse.copy()
                        c_obj.matrix_world = obj.matrix_world.copy()

                        c_obj.display_type = "WIRE"
                        c_obj.show_wire = True
                        c_obj.hide_render = True
                        c_obj["_is_collider"] = True
                        c_obj["_om_asset_base"] = sub_base
                        target_coll.objects.link(c_obj)
                        created_collider_objs.append(c_obj)
                        hull_index += 1
                finally:
                    for bm_hull in hulls:
                        try:
                            bm_hull.free()
                        except Exception as exc:
                            logger.debug("bm_hull.free() skipped: %s", exc)

        logger.info("Generated %d collision hulls in collection '%s'", len(created_collider_objs), coll_name)
        return created_collider_objs

    @classmethod
    def remove_colliders_for_objects(cls, mesh_objs: List[Any], base_name: str) -> int:
        """
        Purges existing collider objects and meshes scoped strictly to `{base_name}`.
        Supports standard, UCX (UE5), and Godot engine naming prefixes.
        Does not affect colliders of other assets in the scene.
        """
        if not bpy:
            return 0

        coll_name = f"{base_name}_Colliders"
        removed_count = 0

        target_coll = bpy.data.collections.get(coll_name) if hasattr(bpy.data, "collections") else None
        to_remove = []

        # 1. Scope to target collection if it exists
        if target_coll and hasattr(target_coll, "objects"):
            for obj in list(target_coll.objects):
                to_remove.append(obj)

        # 2. Scope to scene objects matching this base_name or its mesh component names
        name_prefixes = [
            f"{base_name}_Collider_",
            f"UCX_{base_name}_",
        ]
        for obj in mesh_objs:
            if hasattr(obj, "name"):
                stem = obj.name.split("_LOD")[0]
                name_prefixes.append(f"{stem}_Collider_")
                name_prefixes.append(f"UCX_{stem}_")

        prefixes_tuple = tuple(name_prefixes)

        if hasattr(bpy.data, "objects"):
            for obj in bpy.data.objects:
                if obj in to_remove:
                    continue
                is_tagged = obj.get("_om_asset_base") == base_name and obj.get("_is_collider", False)
                name = getattr(obj, "name", "")
                is_named = name.startswith(prefixes_tuple)
                if is_tagged or is_named:
                    to_remove.append(obj)

        for obj in to_remove:
            mesh_data = obj.data if hasattr(obj, "data") else None
            if hasattr(bpy.data, "objects") and hasattr(bpy.data.objects, "remove"):
                try:
                    bpy.data.objects.remove(obj, do_unlink=True)
                except TypeError:
                    bpy.data.objects.remove(obj)
            if mesh_data and hasattr(mesh_data, "users") and mesh_data.users == 0:
                if hasattr(bpy.data, "meshes") and hasattr(bpy.data.meshes, "remove"):
                    try:
                        bpy.data.meshes.remove(mesh_data, do_unlink=True)
                    except TypeError:
                        bpy.data.meshes.remove(mesh_data)
            removed_count += 1

        return removed_count

    @staticmethod
    def map_collider_name_for_engine(base_name: str, index: int, target_engine: str = "") -> str:
        """
        Translates generic Blender collider name into the exact format required by target engine.
        - UE5: UCX_{base_name}_{index:02d}
        - Godot 4: {base_name}_Collider_{index:02d}-convcolonly
        - Unity 6 / MSFS 2024 / Generic: {base_name}_Collider_{index:02d}
        """
        if target_engine == "UE5":
            return f"UCX_{base_name}_{index:02d}"
        elif target_engine == "GODOT_4":
            return f"{base_name}_Collider_{index:02d}-convcolonly"
        elif target_engine in {"UNITY_6", "MSFS_2024"}:
            return f"{base_name}_Collider_{index:02d}"
        return f"{base_name}_Collider_{index:02d}"
