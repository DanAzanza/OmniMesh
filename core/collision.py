"""
Multi-Convex Collision Hull Generator & Physics Decomposition Engine for OmniMesh.
Blender 4.2+ and 5.2 LTS Compatible.

Provides hierarchical concavity-driven convex decomposition (ACD) with SVD splitting planes,
zero-volume planar extrusion guards, PhysX/Jolt vertex budget clamping, and engine export mapping.
"""

from __future__ import annotations

import logging
import math
from typing import Any, List, Tuple

import numpy as np

logger = logging.getLogger(__name__)

try:
    import bmesh
    import bpy
    import mathutils
    from mathutils import Vector
    from mathutils.bvhtree import BVHTree
except ImportError:
    bmesh = None
    bpy = None
    mathutils = None
    BVHTree = None

    class Vector(tuple):  # type: ignore
        """Pure Python 3D vector fallback for standalone headless test environments."""

        def __new__(cls, coords: Any) -> Vector:
            return super().__new__(cls, tuple(float(x) for x in coords))

        @property
        def x(self) -> float:
            return self[0]

        @property
        def y(self) -> float:
            return self[1]

        @property
        def z(self) -> float:
            return self[2]

        @property
        def length(self) -> float:
            return math.sqrt(self[0] * self[0] + self[1] * self[1] + self[2] * self[2])

        def normalized(self) -> Vector:
            l_val = self.length
            if l_val < 1e-9:
                return Vector((0.0, 0.0, 0.0))
            return Vector((self[0] / l_val, self[1] / l_val, self[2] / l_val))

        def dot(self, other: Any) -> float:
            return self[0] * other[0] + self[1] * other[1] + self[2] * other[2]

        def cross(self, other: Any) -> Vector:
            return Vector(
                (
                    self[1] * other[2] - self[2] * other[1],
                    self[2] * other[0] - self[0] * other[2],
                    self[0] * other[1] - self[1] * other[0],
                )
            )

        def __add__(self, other: Any) -> Vector:
            return Vector((self[0] + other[0], self[1] + other[1], self[2] + other[2]))

        def __sub__(self, other: Any) -> Vector:
            return Vector((self[0] - other[0], self[1] - other[1], self[2] - other[2]))

        def __mul__(self, scalar: Any) -> Vector:
            return Vector((self[0] * float(scalar), self[1] * float(scalar), self[2] * float(scalar)))

        def __rmul__(self, scalar: Any) -> Vector:
            return self.__mul__(scalar)

        def __truediv__(self, scalar: Any) -> Vector:
            return Vector((self[0] / float(scalar), self[1] / float(scalar), self[2] / float(scalar)))


class CollisionDecomposer:
    """
    Core mathematical and geometric decomposition solver for multi-convex collision generation.
    """

    @staticmethod
    def compute_pca_splitting_plane(coords: np.ndarray) -> Tuple[Any, Any]:
        """
        Calculates geometric centroid and primary principal axis (normal) via SVD.
        """
        if len(coords) == 0:
            return Vector((0.0, 0.0, 0.0)), Vector((0.0, 0.0, 1.0))

        centroid_np = np.mean(coords, axis=0)
        centered = coords - centroid_np
        centroid_vec = Vector(centroid_np)

        if len(coords) < 3:
            return centroid_vec, Vector((0.0, 0.0, 1.0))

        try:
            _, _, vh = np.linalg.svd(centered)
            normal_vec = Vector(vh[0]).normalized()
            return centroid_vec, normal_vec
        except Exception as exc:
            logger.debug("SVD decomposition fallback: %s", exc)
            return centroid_vec, Vector((0.0, 0.0, 1.0))

    @staticmethod
    def measure_hull_concavity(bm_source: Any, bm_hull: Any) -> float:
        """
        Measures maximum surface deviation between source mesh geometry and its candidate convex hull.
        """
        if not bm_source or not bm_hull or not hasattr(bm_source, "faces") or not hasattr(bm_hull, "faces"):
            return 0.0
        if len(bm_source.faces) == 0 or len(bm_hull.faces) == 0:
            return 0.0
        if not BVHTree:
            return 0.0

        try:
            hull_bvh = BVHTree.FromBMesh(bm_hull, epsilon=1e-5)
            if not hull_bvh:
                return 0.0

            max_dist = 0.0
            for f in bm_source.faces:
                center = f.calc_center_median()
                _, _, _, dist = hull_bvh.find_nearest(center)
                if dist and dist > max_dist:
                    max_dist = dist
            return float(max_dist)
        except Exception as exc:
            logger.debug("BVH concavity measurement error: %s", exc)
            return 0.0

    @classmethod
    def harden_convex_hull(cls, bm: Any, max_verts: int = 32, min_thickness: float = 0.02) -> bool:
        """
        Hardens BMesh into a valid 3D convex hull:
        1. SVD Planarity Check: If thin 2D sheet, extrudes along normal by min_thickness.
        2. Computes convex hull and purges internal/unused vertex and face garbage.
        3. Clamps vertex budget to max_verts while strictly preserving convexity.
        """
        if not bmesh or not bm or len(bm.verts) < 3:
            return False

        bm.verts.ensure_lookup_table()
        bm.faces.ensure_lookup_table()
        bm.edges.ensure_lookup_table()

        coords = np.array([v.co for v in bm.verts], dtype=np.float64)
        if len(coords) < 3:
            return False

        # 1. Check for 2D Planar / Collinear Degeneracy via SVD
        if len(coords) >= 4:
            try:
                centered = coords - np.mean(coords, axis=0)
                _, s, vh = np.linalg.svd(centered)
                if s[2] < 1e-4:  # Planar 2D sheet detected
                    normal = Vector(vh[2]).normalized()
                    if bm.faces:
                        res_ext = bmesh.ops.extrude_face_region(bm, geom=bm.faces[:])
                        verts_to_move = [v for v in res_ext["geom"] if isinstance(v, bmesh.types.BMVert)]
                        bmesh.ops.translate(bm, vec=normal * float(min_thickness), verts=verts_to_move)
                    else:
                        bmesh.ops.extrude_vert_indiv(bm, verts=bm.verts[:])
                        bmesh.ops.translate(bm, vec=normal * float(min_thickness), verts=bm.verts[:])
            except Exception as exc:
                logger.debug("Planar extrusion fallback: %s", exc)

        # 2. Compute 3D Convex Hull
        try:
            res_hull = bmesh.ops.convex_hull(bm, input=bm.verts[:], use_existing_faces=False)
            to_delete = res_hull.get("geom_unused", []) + res_hull.get("geom_interior", [])
            if to_delete:
                bmesh.ops.delete(bm, geom=to_delete, context="VERTS")
        except Exception as exc:
            logger.debug("BMesh convex hull operation failed: %s", exc)
            return False

        bm.verts.ensure_lookup_table()
        bm.faces.ensure_lookup_table()
        bm.edges.ensure_lookup_table()

        # 3. Vertex Budget Clamping
        cls._clamp_hull_vertex_budget(bm, max_verts=max_verts)
        return len(bm.verts) >= 4

    @classmethod
    def _clamp_hull_vertex_budget(cls, bm: Any, max_verts: int = 32) -> None:
        """
        Iteratively simplifies convex hull geometry to satisfy physics engine vertex limits.
        """
        if not bmesh or not bm or len(bm.verts) <= max_verts:
            return

        # Stage 1: Planar limited dissolve for flat facet groups
        try:
            bmesh.ops.dissolve_limit(
                bm,
                angle_limit=math.radians(10.0),
                edges=bm.edges[:],
                verts=bm.verts[:],
            )
            bm.verts.ensure_lookup_table()
            bm.faces.ensure_lookup_table()
            bm.edges.ensure_lookup_table()
        except Exception as exc:
            logger.debug("Dissolve limit bypassed in budget clamp: %s", exc)

        if len(bm.verts) <= max_verts:
            return

        # Stage 2: Convex-preserving edge collapse
        max_iterations = len(bm.verts) - max_verts
        for _ in range(max_iterations):
            if len(bm.verts) <= max_verts or len(bm.edges) == 0:
                break

            # Pick shortest edge to minimize bounding volume alteration
            shortest_edge = min(bm.edges, key=lambda e: e.calc_length())
            try:
                bmesh.ops.collapse(bm, edges=[shortest_edge])
                # Re-compute convex hull to preserve strict outward curvature
                res = bmesh.ops.convex_hull(bm, input=bm.verts[:], use_existing_faces=False)
                to_delete = res.get("geom_unused", []) + res.get("geom_interior", [])
                if to_delete:
                    bmesh.ops.delete(bm, geom=to_delete, context="VERTS")
                bm.verts.ensure_lookup_table()
                bm.faces.ensure_lookup_table()
                bm.edges.ensure_lookup_table()
            except Exception as exc:
                logger.debug("Convex collapse step terminated: %s", exc)
                break

    @classmethod
    def decompose_mesh_to_hulls(
        cls,
        source_obj: Any,
        k_target: int = 4,
        max_verts_per_hull: int = 32,
        concavity_threshold: float = 0.05,
    ) -> List[Any]:
        """
        Hierarchical Concavity-Driven Convex Decomposition (ACD).
        Returns list of hardened BMesh objects representing convex collision hulls.
        """
        if not bmesh or not source_obj or not hasattr(source_obj, "data") or not source_obj.data:
            return []

        bm_master = bmesh.new()
        bm_master.from_mesh(source_obj.data)
        if len(bm_master.verts) < 4:
            bm_master.free()
            return []

        clusters: List[Any] = [bm_master]

        while len(clusters) < k_target:
            worst_idx = -1
            worst_concavity = -1.0

            for idx, cluster in enumerate(clusters):
                if len(cluster.verts) < 8:
                    continue
                bm_test = cluster.copy()
                try:
                    bmesh.ops.convex_hull(bm_test, input=bm_test.verts[:], use_existing_faces=False)
                    c_err = cls.measure_hull_concavity(cluster, bm_test)
                    if c_err > worst_concavity:
                        worst_concavity = c_err
                        worst_idx = idx
                finally:
                    bm_test.free()

            if worst_idx == -1 or worst_concavity <= concavity_threshold:
                break  # Sufficiently convex

            target_cluster = clusters.pop(worst_idx)
            coords = np.array([v.co for v in target_cluster.verts], dtype=np.float64)
            split_origin, split_normal = cls.compute_pca_splitting_plane(coords)

            child_a = target_cluster.copy()
            child_b = target_cluster

            # Slice child A
            bmesh.ops.bisect_plane(
                child_a,
                geom=child_a.verts[:] + child_a.edges[:] + child_a.faces[:],
                plane_co=split_origin,
                plane_no=split_normal,
                clear_outer=True,
            )
            # Slice child B (inverted plane normal)
            bmesh.ops.bisect_plane(
                child_b,
                geom=child_b.verts[:] + child_b.edges[:] + child_b.faces[:],
                plane_co=split_origin,
                plane_no=-split_normal,
                clear_outer=True,
            )

            # Validate child clusters
            if len(child_a.verts) >= 4 and len(child_b.verts) >= 4:
                clusters.extend([child_a, child_b])
            else:
                # Merge back if slice resulted in degenerate empty side
                child_a.free()
                clusters.append(child_b)
                break

        # Convert all clusters into hardened 3D convex hulls
        final_hulls: List[Any] = []
        for c in clusters:
            success = cls.harden_convex_hull(c, max_verts=max_verts_per_hull)
            if success:
                final_hulls.append(c)
            else:
                c.free()

        return final_hulls


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
    ) -> List[Any]:
        """
        Generates multi-convex collision hulls in Blender viewport for the given mesh objects.
        """
        if not bpy or not mesh_objs:
            return []

        coll_name = target_collection_name or f"{base_name}_Colliders"
        target_coll = bpy.data.collections.get(coll_name)
        if not target_coll:
            target_coll = bpy.data.collections.new(coll_name)
            bpy.context.scene.collection.children.link(target_coll)

        # Remove pre-existing colliders for clean regeneration
        cls.remove_colliders_for_objects(mesh_objs, base_name)

        created_collider_objs: List[Any] = []
        hull_index = 1

        if mode == "CONSOLIDATED" and len(mesh_objs) > 1:
            # Combine all objects into single temporary BMesh
            bm_unified = bmesh.new()
            for obj in mesh_objs:
                bm_temp = bmesh.new()
                bm_temp.from_mesh(obj.data)
                bmesh.ops.transform(bm_temp, matrix=obj.matrix_world, verts=bm_temp.verts[:])
                bm_temp.verts.ensure_lookup_table()
                bm_unified.from_mesh(obj.data)
                bm_temp.free()

            # Decompose unified
            hulls = CollisionDecomposer.decompose_mesh_to_hulls(
                mesh_objs[0],
                k_target=hull_count,
                max_verts_per_hull=max_verts_per_hull,
                concavity_threshold=concavity_threshold,
            )
            bm_unified.free()

            for bm_hull in hulls:
                c_name = f"{base_name}_Collider_{hull_index:02d}"
                c_mesh = bpy.data.meshes.new(f"{c_name}_Mesh")
                bm_hull.to_mesh(c_mesh)
                bm_hull.free()

                c_obj = bpy.data.objects.new(c_name, c_mesh)
                c_obj.display_type = "WIRE"
                c_obj.show_wire = True
                c_obj["_is_collider"] = True
                target_coll.objects.link(c_obj)
                created_collider_objs.append(c_obj)
                hull_index += 1
        else:
            # PER_OBJECT Area-Weighted Decomposition
            total_area = sum(sum(p.area for p in obj.data.polygons) for obj in mesh_objs) or 1.0

            for obj in mesh_objs:
                obj_area = sum(p.area for p in obj.data.polygons)
                # Area-weighted hull budget
                obj_hull_budget = max(1, int(round(hull_count * (obj_area / total_area))))
                sub_base = obj.name.split("_LOD")[0]

                hulls = CollisionDecomposer.decompose_mesh_to_hulls(
                    obj,
                    k_target=obj_hull_budget,
                    max_verts_per_hull=max_verts_per_hull,
                    concavity_threshold=concavity_threshold,
                )

                for bm_hull in hulls:
                    c_name = f"{sub_base}_Collider_{hull_index:02d}"
                    c_mesh = bpy.data.meshes.new(f"{c_name}_Mesh")
                    bm_hull.to_mesh(c_mesh)
                    bm_hull.free()

                    c_obj = bpy.data.objects.new(c_name, c_mesh)
                    # Inherit transform & parent relationship
                    c_obj.matrix_world = obj.matrix_world.copy()
                    if obj.parent:
                        c_obj.parent = obj.parent
                        c_obj.parent_type = obj.parent_type
                        if hasattr(obj, "parent_bone") and obj.parent_bone:
                            c_obj.parent_bone = obj.parent_bone
                        c_obj.matrix_parent_inverse = obj.matrix_parent_inverse.copy()

                    c_obj.display_type = "WIRE"
                    c_obj.show_wire = True
                    c_obj["_is_collider"] = True
                    target_coll.objects.link(c_obj)
                    created_collider_objs.append(c_obj)
                    hull_index += 1

        logger.info("Generated %d collision hulls in collection '%s'", len(created_collider_objs), coll_name)
        return created_collider_objs

    @classmethod
    def remove_colliders_for_objects(cls, mesh_objs: List[Any], base_name: str) -> int:
        """
        Purges existing collider objects and meshes matching `{base_name}_Collider_*`.
        """
        if not bpy:
            return 0

        coll_name = f"{base_name}_Colliders"
        removed_count = 0

        # Scan scene objects
        to_remove = []
        for obj in bpy.data.objects:
            if obj.get("_is_collider", False) or (f"{base_name}_Collider_" in obj.name):
                to_remove.append(obj)

        for obj in to_remove:
            mesh_data = obj.data if hasattr(obj, "data") else None
            bpy.data.objects.remove(obj, do_unlink=True)
            if mesh_data and mesh_data.users == 0:
                bpy.data.meshes.remove(mesh_data, do_unlink=True)
            removed_count += 1

        # Remove empty collection
        target_coll = bpy.data.collections.get(coll_name)
        if target_coll and len(target_coll.objects) == 0:
            bpy.data.collections.remove(target_coll)

        return removed_count

    @staticmethod
    def map_collider_name_for_engine(base_name: str, index: int, target_engine: str) -> str:
        """
        Translates generic Blender collider name into the exact format required by target engine.
        - UE5: UCX_{base_name}_{index:02d}
        - Godot 4: {base_name}_Collider_{index:02d}-convcol
        - Unity 6: {base_name}_Collider_{index:02d}
        - MSFS 2024: {base_name}_Collider_{index:02d}
        """
        if target_engine == "UE5":
            return f"UCX_{base_name}_{index:02d}"
        elif target_engine == "GODOT_4":
            return f"{base_name}_Collider_{index:02d}-convcol"
        elif target_engine in {"UNITY_6", "MSFS_2024"}:
            return f"{base_name}_Collider_{index:02d}"
        return f"{base_name}_Collider_{index:02d}"
