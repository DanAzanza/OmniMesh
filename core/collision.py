"""
Multi-Convex Collision Hull Generator & Physics Hierarchy Manager for OmniMesh.

Provides Blender scene integration, collection linking, transform hierarchy synchronization,
and engine-specific collider naming (UE5, Unity, MSFS).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, List, cast

from .collision_decomposer import CollisionDecomposer

if TYPE_CHECKING:
    import bmesh
    import bpy
    from bpy.types import BlendData
else:
    try:
        import bmesh
        import bpy
    except ImportError:
        bpy = None  # type: ignore
        bmesh = None  # type: ignore

    BlendData = object  # runtime fallback for type annotations

logger = logging.getLogger(__name__)


def _cleanup_temp_meshes(blend_data: BlendData, temp_meshes: list[bpy.types.Mesh]) -> int:
    """Removes temporary collision decomposition meshes from ``blend_data``."""
    removed = 0
    for temp_m in temp_meshes:
        try:
            blend_data.meshes.remove(temp_m)
            removed += 1
        except (RuntimeError, ReferenceError, KeyError) as exc:
            logger.warning("Failed removing temporary collision mesh: %s", exc)
    temp_meshes.clear()
    return removed


from .exceptions import DependencyInjectionError

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
        mesh_objs: List[bpy.types.Object],
        base_name: str,
        hull_count: int = 4,
        max_verts_per_hull: int = 32,
        concavity_threshold: float = 0.05,
        mode: str = "PER_OBJECT",
        target_collection_name: str = "",
        target_engine: str = "",
        scene: bpy.types.Scene | None = None,
        *,
        blend_data: BlendData,
    ) -> List[bpy.types.Object]:
        if blend_data is None:
            raise DependencyInjectionError("Explicit 'blend_data' dependency is required for collider generation.")

        if not bpy or not mesh_objs:
            return []

        sc = scene or (blend_data.scenes[0] if len(blend_data.scenes) > 0 else None)

        # Remove pre-existing colliders for clean regeneration first
        cls.remove_colliders_for_objects(mesh_objs, base_name, blend_data=blend_data)

        coll_name = target_collection_name or f"{base_name}_Colliders"
        target_coll = blend_data.collections.get(coll_name)
        if not target_coll:
            target_coll = blend_data.collections.new(coll_name)

        if not target_coll:
            return []

        root_coll = blend_data.collections.get(base_name)
        if root_coll:
            c_children = root_coll.children
            already_in = False
            try:
                already_in = (
                    target_coll.name in c_children if not isinstance(c_children, list) else target_coll in c_children
                )
            except (AttributeError, TypeError, ReferenceError) as e:
                logger.debug("Failed checking target collection membership: %s", e)
            if not already_in:
                if isinstance(c_children, list):
                    c_children.append(target_coll)
                else:
                    c_children.link(target_coll)
            # Unlink from scene root if nested under root_coll
            if sc and sc.collection:
                try:
                    if target_coll.name in sc.collection.children:
                        sc.collection.children.unlink(target_coll)
                except (RuntimeError, ReferenceError, AttributeError) as e:
                    logger.debug("Failed unlinking target collection from scene root: %s", e)
        elif sc and sc.collection and target_coll.name not in sc.collection.children:
            sc.collection.children.link(target_coll)

        # Resolve target engine for naming if not explicitly passed
        resolved_engine = target_engine
        if not resolved_engine and sc:
            props = getattr(sc, "lod_tool", None)
            if props:
                resolved_engine = getattr(props, "target_engine", "")

        created_collider_objs: List[bpy.types.Object] = []
        hull_index = 1

        if mode == "CONSOLIDATED" and len(mesh_objs) > 1:
            # Combine all objects into single temporary BMesh in world coordinates
            bm_unified = bmesh.new()
            temp_meshes_to_clean: list[bpy.types.Mesh] = []
            try:
                for idx, obj in enumerate(mesh_objs):
                    bm_temp = bmesh.new()
                    try:
                        obj_mesh = cast("bpy.types.Mesh", obj.data)
                        bm_temp.from_mesh(obj_mesh)
                        bmesh.ops.transform(bm_temp, matrix=obj.matrix_world, verts=bm_temp.verts[:])
                        temp_m = blend_data.meshes.new(f"_om_temp_sub_{idx}")
                        bm_temp.to_mesh(temp_m)
                        temp_meshes_to_clean.append(temp_m)
                        bm_unified.from_mesh(temp_m)
                    finally:
                        bm_temp.free()

                _cleanup_temp_meshes(blend_data, temp_meshes_to_clean)

                # Decompose unified geometry
                hulls = CollisionDecomposer.decompose_mesh_to_hulls(
                    k_target=hull_count,
                    max_verts_per_hull=max_verts_per_hull,
                    concavity_threshold=concavity_threshold,
                    bm_source=bm_unified,
                )
            finally:
                bm_unified.free()
                _cleanup_temp_meshes(blend_data, temp_meshes_to_clean)

            try:
                for bm_hull in hulls:
                    c_name = cls.map_collider_name_for_engine(base_name, hull_index, resolved_engine)
                    c_mesh = blend_data.meshes.new(f"{c_name}_Mesh")
                    bm_hull.to_mesh(c_mesh)

                    c_obj = blend_data.objects.new(c_name, c_mesh)
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
                    except (RuntimeError, ReferenceError, AttributeError) as exc:
                        logger.debug("bm_hull.free() skipped: %s", exc)
        else:
            # PER_OBJECT Area-Weighted Decomposition
            total_area = (
                sum(sum(p.area for p in cast("bpy.types.Mesh", obj.data).polygons) for obj in mesh_objs if obj.data)
                or 1.0
            )

            for obj in mesh_objs:
                obj_data = cast("bpy.types.Mesh | None", obj.data)
                if not obj_data:
                    continue
                obj_area = sum(p.area for p in obj_data.polygons)
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
                        c_mesh = blend_data.meshes.new(f"{c_name}_Mesh")
                        bm_hull.to_mesh(c_mesh)

                        c_obj = blend_data.objects.new(c_name, c_mesh)
                        # Inherit parent and transform hierarchy cleanly
                        if obj.parent:
                            c_obj.parent = obj.parent
                            c_obj.parent_type = obj.parent_type
                            if obj.parent_bone:
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
                        except (RuntimeError, ReferenceError, AttributeError) as exc:
                            logger.debug("bm_hull.free() skipped: %s", exc)

        logger.info("Generated %d collision hulls in collection '%s'", len(created_collider_objs), coll_name)
        return created_collider_objs

    @classmethod
    def remove_colliders_for_objects(
        cls,
        mesh_objs: List[bpy.types.Object],
        base_name: str,
        *,
        blend_data: BlendData,
    ) -> int:
        """
        Purges existing collider objects and meshes scoped strictly to `{base_name}`.
        Supports standard and UCX (UE5) engine naming prefixes.
        Does not affect colliders of other assets in the scene.
        """
        if blend_data is None:
            raise DependencyInjectionError("Explicit 'blend_data' dependency is required for collider removal.")

        if not bpy:
            return 0

        coll_name = f"{base_name}_Colliders"
        removed_count = 0

        target_coll = blend_data.collections.get(coll_name)
        to_remove = []

        # 1. Scope to target collection if it exists
        if target_coll:
            for obj in list(target_coll.objects):
                to_remove.append(obj)

        # 2. Scope to scene objects matching this base_name or its mesh component names
        name_prefixes = [
            f"{base_name}_Collider_",
            f"UCX_{base_name}_",
        ]
        for obj in mesh_objs:
            stem = obj.name.split("_LOD")[0]
            name_prefixes.append(f"{stem}_Collider_")
            name_prefixes.append(f"UCX_{stem}_")

        prefixes_tuple = tuple(name_prefixes)

        for obj in blend_data.objects:
            if obj in to_remove:
                continue
            is_tagged = obj.get("_om_asset_base") == base_name and obj.get("_is_collider", False)
            name = obj.name
            is_named = name.startswith(prefixes_tuple)
            if is_tagged or is_named:
                to_remove.append(obj)

        for obj in to_remove:
            mesh_data = obj.data
            try:
                blend_data.objects.remove(obj, do_unlink=True)
            except TypeError:
                blend_data.objects.remove(obj)
            if mesh_data and mesh_data.users == 0:
                try:
                    blend_data.meshes.remove(mesh_data, do_unlink=True)
                except TypeError:
                    blend_data.meshes.remove(mesh_data)
            removed_count += 1

        return removed_count

    @staticmethod
    def map_collider_name_for_engine(base_name: str, index: int, target_engine: str = "") -> str:
        """
        Translates generic Blender collider name into the exact format required by target engine.
        - UE5: UCX_{base_name}_{index:02d}
        - Unity 6 / MSFS 2024 / Generic: {base_name}_Collider_{index:02d}
        """
        if target_engine == "UE5":
            return f"UCX_{base_name}_{index:02d}"
        elif target_engine in {"UNITY_6", "MSFS_2024"}:
            return f"{base_name}_Collider_{index:02d}"
        return f"{base_name}_Collider_{index:02d}"
