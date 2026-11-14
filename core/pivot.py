"""
OmniMesh Pivot & Socket Preservation Engine.
Architected for Blender 5.0+ & Blender 5.2 LTS.
Features:
- Pivot empty detection (Pivot, Root, Origin, is_pivot tag).
- Sockets and accessory mount points identifier (SOCKET_*, SOCK_*, MOUNT_*, ATTACH_*).
- LocalPivotSpaceMerge: Vertex and Normal transformation into Pivot coordinate space.
- Non-destructive socket and accessory reparenting.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, cast

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    import bpy
    from bpy.types import BlendData
    from mathutils import Matrix, Vector
else:
    try:
        import bpy
        from mathutils import Matrix, Vector
    except ImportError:
        bpy = None
        Matrix = None
        Vector = None
    BlendData = object


class PivotPreservationEngine:
    """
    Detects and preserves Pivot/Root empties and accessory attachment sockets across LOD tiers.
    """

    PIVOT_TAGS = {"PIVOT", "ROOT", "ORIGIN"}
    SOCKET_PREFIXES = ("SOCKET_", "SOCK_", "MOUNT_", "ATTACH_")

    @classmethod
    def identify_pivots_and_sockets(
        cls, collection: bpy.types.Collection | None
    ) -> tuple[
        bpy.types.Object | None,
        list[bpy.types.Object],
        list[bpy.types.Object],
        list[bpy.types.Object],
    ]:
        """
        Scans collection for:
        Returns: (pivot_empty, sockets, meshes, armatures)
        """
        if not collection:
            return None, [], [], []

        pivot_obj = None
        sockets: list[bpy.types.Object] = []
        meshes: list[bpy.types.Object] = []
        armatures: list[bpy.types.Object] = []

        all_objs = collection.all_objects

        for obj in all_objs:
            if not obj:
                continue
            obj_type = obj.type
            name_upper = obj.name.upper()

            if obj_type == "EMPTY":
                has_pivot_prop = bool(obj.get("is_pivot", False))
                if any(tag in name_upper for tag in cls.PIVOT_TAGS) or has_pivot_prop:
                    if not pivot_obj:
                        pivot_obj = obj
                else:
                    has_socket_prop = bool(obj.get("is_socket", False))
                    if name_upper.startswith(cls.SOCKET_PREFIXES) or has_socket_prop:
                        sockets.append(obj)
            elif obj_type == "MESH":
                is_collider = bool(obj.get("_is_collider", False))
                if not is_collider and not name_upper.startswith("UCX_"):
                    meshes.append(obj)
            elif obj_type == "ARMATURE":
                armatures.append(obj)

        # Fallback: parent empty of top-level collection elements
        if not pivot_obj and collection.objects is not None:
            for obj in collection.objects:
                if obj.parent and obj.parent.type == "EMPTY":
                    pivot_obj = obj.parent
                    break

        return pivot_obj, sockets, meshes, armatures

    @classmethod
    def get_relative_matrix(
        cls, obj: bpy.types.Object | None, pivot_obj: bpy.types.Object | None
    ) -> Matrix | list[list[int]]:
        """
        Computes the relative transformation matrix from object local space to pivot local space:
        M_relative = M_pivot^-1 * M_obj
        """
        fallback_identity = Matrix.Identity(4) if Matrix else [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]
        if not obj:
            return fallback_identity

        obj_world = obj.matrix_world
        if obj_world is None:
            return fallback_identity

        if not pivot_obj or pivot_obj.matrix_world is None:
            return obj_world.copy()

        pivot_world = pivot_obj.matrix_world
        try:
            return pivot_world.inverted() @ obj_world
        except (ValueError, AttributeError, RuntimeError) as exc:
            logger.debug("Matrix inversion failed, using object world matrix: %s", exc)
            return obj_world.copy()

    @classmethod
    def transform_vertex_to_pivot_space(
        cls, co: Vector, obj: bpy.types.Object | None, pivot_obj: bpy.types.Object | None
    ) -> Vector:
        """
        Transforms a vertex coordinate vector from mesh local space to pivot relative space:
        v_pivot = (M_pivot^-1 * M_obj) * v_local
        """
        rel_matrix = cls.get_relative_matrix(obj, pivot_obj)
        if rel_matrix is None:
            return co
        return cast("Vector", cast("Matrix", rel_matrix) @ cast("Vector", co))

    @classmethod
    def transform_normal_to_pivot_space(
        cls, no: Vector, obj: bpy.types.Object | None, pivot_obj: bpy.types.Object | None
    ) -> Vector:
        """
        Transforms a surface normal vector from mesh local space to pivot relative space
        using the inverse-transpose of the 3x3 rotational/scaling component:
        n_pivot = Normalize((M_pivot^-1 * M_obj)_3x3^-T * n_local)
        """
        rel_matrix = cls.get_relative_matrix(obj, pivot_obj)
        if rel_matrix is None:
            return no

        try:
            mat3 = cast("Matrix", rel_matrix).to_3x3()
            inv_trans_3x3 = mat3.inverted().transposed()
            transformed_no = inv_trans_3x3 @ no
            return transformed_no.normalized()
        except (ValueError, AttributeError, ReferenceError) as exc:
            logger.debug("Normal transform to pivot space fell back to source normal: %s", exc)
            return no

    @classmethod
    def clone_pivot_empty(
        cls,
        pivot_obj: bpy.types.Object | None,
        target_collection: bpy.types.Collection | None,
        tier_idx: int,
        base_name: str,
        *,
        blend_data: BlendData,
    ) -> bpy.types.Object | None:
        """
        Duplicates or creates a matching Pivot Empty in the target LOD collection.
        """
        if not bpy or not target_collection:
            return None

        tier_name = f"{base_name}_LOD{tier_idx}" if tier_idx > 0 else base_name
        pivot_name = f"{tier_name}_Pivot"

        bdata = blend_data
        bdata_objs = bdata.objects if bdata else None

        existing = bdata_objs.get(pivot_name) if bdata_objs else None
        if existing:
            if existing.name not in target_collection.objects:
                target_collection.objects.link(existing)
            return existing

        if pivot_obj:
            cloned_pivot = pivot_obj.copy()
            if cloned_pivot is not None:
                cloned_pivot.name = pivot_name
                cloned_pivot.matrix_world = pivot_obj.matrix_world.copy()
                cloned_pivot["is_pivot"] = True
                target_collection.objects.link(cloned_pivot)
                return cloned_pivot

        if bdata_objs is None:
            return None
        empty_obj = bdata_objs.new(pivot_name, None)
        empty_obj.empty_display_type = "ARROWS"
        empty_obj.empty_display_size = 0.5
        empty_obj["is_pivot"] = True
        target_collection.objects.link(empty_obj)
        return empty_obj

    @classmethod
    def reparent_sockets_to_pivot(
        cls,
        sockets: list[bpy.types.Object],
        target_pivot: bpy.types.Object | None,
        target_collection: bpy.types.Collection | None,
        context: bpy.types.Context | None = None,
    ) -> list[bpy.types.Object]:
        """
        Clones sockets into target collection and parents them to the tier's Pivot Empty
        while strictly preserving their exact world-space locations.
        """
        ctx = context
        vl = ctx.view_layer if ctx else None
        if vl:
            try:
                vl.update()
            except (RuntimeError, AttributeError) as exc:
                logger.debug("View layer update skipped: %s", exc)

        cloned_sockets = []
        for sock in sockets:
            if not sock:
                continue
            sock_clone = sock.copy()
            if sock_clone is None:
                continue
            sock_world = sock.matrix_world.copy()

            if target_collection is not None:
                target_collection.objects.link(sock_clone)

            sock_parent = sock.parent
            sock_parent_type = sock.parent_type
            if sock_parent_type == "BONE" and sock_parent is not None:
                # Retain bone attachment on Master Armature
                sock_clone.parent = sock_parent
                sock_clone.parent_type = "BONE"
                sock_clone.parent_bone = sock.parent_bone
                sock_clone.matrix_parent_inverse = sock.matrix_parent_inverse.copy()
                sock_clone.matrix_world = sock_world
            else:
                sock_clone.parent = target_pivot
                if target_pivot is not None and target_pivot.matrix_world is not None:
                    try:
                        sock_clone.matrix_parent_inverse = target_pivot.matrix_world.inverted()
                    except (ValueError, AttributeError, RuntimeError) as exc:
                        logger.debug("Matrix inversion failed: %s", exc)
                sock_clone.matrix_world = sock_world

            cloned_sockets.append(sock_clone)

        return cloned_sockets
