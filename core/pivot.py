"""
OmniMesh Pivot & Socket Preservation Engine.
Architected for Blender 4.2+ LTS & Blender 5.2 LTS.
Features:
- Pivot empty detection (Pivot, Root, Origin, is_pivot tag).
- Sockets and accessory mount points identifier (SOCKET_*, SOCK_*, MOUNT_*, ATTACH_*).
- LocalPivotSpaceMerge: Vertex and Normal transformation into Pivot coordinate space.
- Non-destructive socket and accessory reparenting.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("OmniMesh.Pivot")

try:
    import bpy
    from mathutils import Matrix, Vector
except ImportError:
    bpy = None
    Matrix = None
    Vector = None


class PivotPreservationEngine:
    """
    Detects and preserves Pivot/Root empties and accessory attachment sockets across LOD tiers.
    """

    PIVOT_TAGS = {"PIVOT", "ROOT", "ORIGIN"}
    SOCKET_PREFIXES = ("SOCKET_", "SOCK_", "MOUNT_", "ATTACH_")

    @classmethod
    def identify_pivots_and_sockets(cls, collection: Any) -> tuple[Any | None, list[Any], list[Any], list[Any]]:
        """
        Scans collection for:
        Returns: (pivot_empty, sockets, meshes, armatures)
        """
        if not collection:
            return None, [], [], []

        pivot_obj = None
        sockets: list[Any] = []
        meshes: list[Any] = []
        armatures: list[Any] = []

        all_objs = getattr(collection, "all_objects", getattr(collection, "objects", []))

        for obj in all_objs:
            obj_type = getattr(obj, "type", "")
            name_upper = getattr(obj, "name", "").upper()

            if obj_type == "EMPTY":
                if any(tag in name_upper for tag in cls.PIVOT_TAGS) or getattr(obj, "get", lambda _: False)(
                    "is_pivot", False
                ):
                    if not pivot_obj:
                        pivot_obj = obj
                elif name_upper.startswith(cls.SOCKET_PREFIXES) or getattr(obj, "get", lambda _: False)(
                    "is_socket", False
                ):
                    sockets.append(obj)
                elif not pivot_obj and name_upper == "PIVOT":
                    pivot_obj = obj
            elif obj_type == "MESH":
                # Check if it's a collision mesh
                if not getattr(obj, "get", lambda _: False)("_is_collider", False) and not name_upper.startswith(
                    "UCX_"
                ):
                    meshes.append(obj)
            elif obj_type == "ARMATURE":
                armatures.append(obj)

        # Fallback: parent empty of top-level collection elements
        if not pivot_obj:
            for obj in getattr(collection, "objects", []):
                if getattr(obj, "parent", None) and getattr(obj.parent, "type", "") == "EMPTY":
                    pivot_obj = obj.parent
                    break

        return pivot_obj, sockets, meshes, armatures

    @classmethod
    def get_relative_matrix(cls, obj: Any, pivot_obj: Any | None) -> Any:
        """
        Computes the relative transformation matrix from object local space to pivot local space:
        M_relative = M_pivot^-1 * M_obj
        """
        fallback_identity = Matrix.Identity(4) if Matrix else [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]
        if not obj:
            return fallback_identity

        obj_world = getattr(obj, "matrix_world", None)
        if obj_world is None:
            return fallback_identity

        if not pivot_obj or not hasattr(pivot_obj, "matrix_world") or pivot_obj.matrix_world is None:
            return obj_world.copy() if hasattr(obj_world, "copy") else obj_world

        pivot_world = pivot_obj.matrix_world
        try:
            return pivot_world.inverted() @ obj_world
        except Exception as exc:
            logger.debug("Matrix inversion failed, using object world matrix: %s", exc)
            return obj_world.copy() if hasattr(obj_world, "copy") else obj_world

    @classmethod
    def transform_vertex_to_pivot_space(cls, co: Any, obj: Any, pivot_obj: Any | None) -> Any:
        """
        Transforms a vertex coordinate vector from mesh local space to pivot relative space:
        v_pivot = (M_pivot^-1 * M_obj) * v_local
        """
        rel_matrix = cls.get_relative_matrix(obj, pivot_obj)
        if rel_matrix is None:
            return co
        if hasattr(rel_matrix, "__matmul__"):
            return rel_matrix @ co
        return co

    @classmethod
    def transform_normal_to_pivot_space(cls, no: Any, obj: Any, pivot_obj: Any | None) -> Any:
        """
        Transforms a surface normal vector from mesh local space to pivot relative space
        using the inverse-transpose of the 3x3 rotational/scaling component:
        n_pivot = Normalize((M_pivot^-1 * M_obj)_3x3^-T * n_local)
        """
        rel_matrix = cls.get_relative_matrix(obj, pivot_obj)
        if rel_matrix is None:
            return no

        try:
            mat3 = rel_matrix.to_3x3()
            inv_trans_3x3 = mat3.inverted().transposed()
            transformed_no = inv_trans_3x3 @ no
            return transformed_no.normalized()
        except Exception:
            return no

    @classmethod
    def clone_pivot_empty(
        cls, pivot_obj: Any | None, target_collection: Any, tier_idx: int, base_name: str
    ) -> Any | None:
        """
        Duplicates or creates a matching Pivot Empty in the target LOD collection.
        """
        if not bpy or not target_collection:
            return None

        tier_name = f"{base_name}_LOD{tier_idx}" if tier_idx > 0 else base_name
        pivot_name = f"{tier_name}_Pivot"

        existing = bpy.data.objects.get(pivot_name)
        if existing:
            if existing.name not in target_collection.objects:
                target_collection.objects.link(existing)
            return existing

        if pivot_obj and hasattr(pivot_obj, "copy"):
            cloned_pivot = pivot_obj.copy()
            cloned_pivot.name = pivot_name
            cloned_pivot.matrix_world = pivot_obj.matrix_world.copy()
            cloned_pivot["is_pivot"] = True
            target_collection.objects.link(cloned_pivot)
            return cloned_pivot

        empty_obj = bpy.data.objects.new(pivot_name, None)
        empty_obj.empty_display_type = "ARROWS"
        empty_obj.empty_display_size = 0.5
        empty_obj["is_pivot"] = True
        target_collection.objects.link(empty_obj)
        return empty_obj

    @classmethod
    def reparent_sockets_to_pivot(
        cls, sockets: list[Any], target_pivot: Any | None, target_collection: Any
    ) -> list[Any]:
        """
        Clones sockets into target collection and parents them to the tier's Pivot Empty
        while strictly preserving their exact world-space locations.
        """
        cloned_sockets = []
        for sock in sockets:
            if not sock or not hasattr(sock, "copy"):
                continue
            sock_clone = sock.copy()
            sock_world = sock.matrix_world.copy()

            target_collection.objects.link(sock_clone)

            if getattr(sock, "parent_type", "") == "BONE" and getattr(sock, "parent", None):
                # Retain bone attachment on Master Armature
                sock_clone.parent = sock.parent
                sock_clone.parent_type = "BONE"
                if hasattr(sock, "parent_bone"):
                    sock_clone.parent_bone = sock.parent_bone
                if hasattr(sock, "matrix_parent_inverse"):
                    sock_clone.matrix_parent_inverse = sock.matrix_parent_inverse.copy()
                sock_clone.matrix_world = sock_world
            else:
                sock_clone.parent = target_pivot
                if hasattr(target_pivot, "matrix_world") and hasattr(target_pivot.matrix_world, "inverted"):
                    try:
                        sock_clone.matrix_parent_inverse = target_pivot.matrix_world.inverted()
                    except Exception as exc:
                        logger.debug("Matrix inversion failed: %s", exc)
                sock_clone.matrix_world = sock_world

            cloned_sockets.append(sock_clone)

        return cloned_sockets
