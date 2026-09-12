"""
Pure geometric decomposition solver for multi-convex collision generation in OmniMesh.
"""

from __future__ import annotations

import logging
import math
from typing import Any, List, Tuple

import numpy as np

try:
    import bmesh
    from mathutils import Vector
    from mathutils.bvhtree import BVHTree
except ImportError:
    bmesh = None  # type: ignore
    BVHTree = None  # type: ignore

    class Vector(list):  # type: ignore
        def __init__(self, iterable: Any):
            super().__init__([float(x) for x in iterable])

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
            return float(math.sqrt(self[0] ** 2 + self[1] ** 2 + self[2] ** 2))

        def normalized(self) -> Vector:
            v_len = self.length
            if v_len < 1e-8:
                return Vector((0.0, 0.0, 1.0))
            return Vector((self[0] / v_len, self[1] / v_len, self[2] / v_len))

        def __mul__(self, scalar: Any) -> Vector:
            return Vector((self[0] * float(scalar), self[1] * float(scalar), self[2] * float(scalar)))

        def __rmul__(self, scalar: Any) -> Vector:
            return self.__mul__(scalar)

        def __truediv__(self, scalar: Any) -> Vector:
            return Vector((self[0] / float(scalar), self[1] / float(scalar), self[2] / float(scalar)))

        def __neg__(self) -> Vector:
            return Vector((-self[0], -self[1], -self[2]))


logger = logging.getLogger(__name__)


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
    def harden_convex_hull(
        cls,
        bm: Any,
        max_verts: int = 32,
        min_thickness: float = 0.02,
        scale_factor: float = 1.0,
    ) -> bool:
        """
        Hardens BMesh into a valid 3D convex hull:
        1. SVD Relative Eccentricity Check: If thin 2D sheet or 1D needle, extrudes along normal axes.
        2. Computes convex hull and purges internal/unused face and vertex geometry via two-pass deletion.
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

        # 1. Check for 2D Planar / 1D Collinear Degeneracy via SVD with relative eccentricity
        if len(coords) >= 4:
            try:
                centered = coords - np.mean(coords, axis=0)
                _, s, vh = np.linalg.svd(centered)
                s_max = max(1e-12, float(s[0]))
                rel_s1 = float(s[1]) / s_max
                rel_s2 = float(s[2]) / s_max

                effective_thickness = max(1e-4, float(min_thickness) / max(1e-4, scale_factor))

                if rel_s2 < 1e-3:
                    # Planar 2D sheet detected: extrude along tertiary normal axis vh[2]
                    normal = Vector(vh[2]).normalized()
                    if bm.faces:
                        res_ext = bmesh.ops.extrude_face_region(bm, geom=bm.faces[:])
                        verts_to_move = [v for v in res_ext["geom"] if isinstance(v, bmesh.types.BMVert)]
                        bmesh.ops.translate(bm, vec=normal * effective_thickness, verts=verts_to_move)
                    else:
                        bmesh.ops.extrude_vert_indiv(bm, verts=bm.verts[:])
                        bmesh.ops.translate(bm, vec=normal * effective_thickness, verts=bm.verts[:])

                    # If also 1D collinear needle: extrude along secondary axis vh[1]
                    if rel_s1 < 1e-3:
                        normal_sec = Vector(vh[1]).normalized()
                        if bm.faces:
                            res_ext2 = bmesh.ops.extrude_face_region(bm, geom=bm.faces[:])
                            verts_to_move2 = [v for v in res_ext2["geom"] if isinstance(v, bmesh.types.BMVert)]
                            bmesh.ops.translate(bm, vec=normal_sec * effective_thickness, verts=verts_to_move2)
                        else:
                            bmesh.ops.extrude_vert_indiv(bm, verts=bm.verts[:])
                            bmesh.ops.translate(bm, vec=normal_sec * effective_thickness, verts=bm.verts[:])
            except Exception as exc:
                logger.debug("Planar extrusion fallback: %s", exc)

        # 2. Compute 3D Convex Hull with two-pass internal geometry purge
        try:
            res_hull = bmesh.ops.convex_hull(bm, input=bm.verts[:], use_existing_faces=False)
            to_delete = res_hull.get("geom_unused", []) + res_hull.get("geom_interior", [])
            if to_delete:
                cls._purge_hull_interior_geom(bm, to_delete)
        except Exception as exc:
            logger.debug("BMesh convex hull operation failed: %s", exc)
            return False

        bm.verts.ensure_lookup_table()
        bm.faces.ensure_lookup_table()
        bm.edges.ensure_lookup_table()

        # 3. Vertex Budget Clamping
        cls._clamp_hull_vertex_budget(bm, max_verts=max_verts)
        return len(bm.verts) >= 4

    @staticmethod
    def _purge_hull_interior_geom(bm: Any, to_delete: list[Any]) -> None:
        """Two-pass deletion of interior faces and unused vertices to ensure clean BVH indexing."""
        faces_to_del = [f for f in to_delete if bmesh and isinstance(f, bmesh.types.BMFace) and f.is_valid]
        if faces_to_del:
            try:
                bmesh.ops.delete(bm, geom=faces_to_del, context="FACES_ONLY")
            except Exception as exc:
                logger.debug("Interior face purge bypassed: %s", exc)

        verts_to_del = [v for v in to_delete if bmesh and isinstance(v, bmesh.types.BMVert) and v.is_valid]
        if verts_to_del:
            try:
                bmesh.ops.delete(bm, geom=verts_to_del, context="VERTS")
            except Exception as exc:
                logger.debug("Interior vert purge bypassed: %s", exc)

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
                    cls._purge_hull_interior_geom(bm, to_delete)
                bm.verts.ensure_lookup_table()
                bm.faces.ensure_lookup_table()
                bm.edges.ensure_lookup_table()
            except Exception as exc:
                logger.debug("Convex collapse step terminated: %s", exc)
                break

    @classmethod
    def decompose_mesh_to_hulls(
        cls,
        source_obj: Any = None,
        k_target: int = 4,
        max_verts_per_hull: int = 32,
        concavity_threshold: float = 0.05,
        bm_source: Any = None,
    ) -> List[Any]:
        """
        Hierarchical Concavity-Driven Convex Decomposition (ACD).
        Returns list of hardened BMesh objects representing convex collision hulls.
        Accepts either source_obj (with .data) or a pre-assembled bm_source BMesh.
        """
        if not bmesh:
            return []

        scale_factor = 1.0
        if source_obj and hasattr(source_obj, "scale"):
            s = source_obj.scale
            scale_factor = max(1e-4, (abs(s[0]) + abs(s[1]) + abs(s[2])) / 3.0)

        eval_obj = None
        if bm_source is not None:
            bm_master = bm_source.copy()
        elif source_obj and hasattr(source_obj, "data") and source_obj.data:
            eval_mesh = None
            try:
                from .modifiers import ModifierManager

                eval_mesh, eval_obj = ModifierManager.get_evaluated_mesh(source_obj, preserve_armature=True)
            except Exception as exc:
                logger.debug("Failed evaluating modifier mesh for collision: %s", exc)
            bm_master = bmesh.new()
            try:
                try:
                    if eval_mesh:
                        bm_master.from_mesh(eval_mesh)
                    else:
                        bm_master.from_mesh(source_obj.data)
                except Exception:
                    bm_master.free()
                    raise
            finally:
                if eval_obj and hasattr(eval_obj, "to_mesh_clear"):
                    eval_obj.to_mesh_clear()
        else:
            return []

        if len(bm_master.verts) < 4:
            bm_master.free()
            return []

        clusters: List[Any] = [bm_master]
        completed_clusters: List[Any] = []
        target_cluster = None
        child_a = None
        child_b = None

        try:
            while (len(clusters) + len(completed_clusters)) < k_target:
                worst_idx = -1
                worst_concavity = -1.0

                for idx, cluster in enumerate(clusters):
                    if len(cluster.verts) < 8:
                        continue
                    bm_test = cluster.copy()
                    try:
                        res_hull = bmesh.ops.convex_hull(bm_test, input=bm_test.verts[:], use_existing_faces=False)
                        to_del = res_hull.get("geom_unused", []) + res_hull.get("geom_interior", [])
                        if to_del:
                            cls._purge_hull_interior_geom(bm_test, to_del)
                        bm_test.faces.ensure_lookup_table()
                        c_err = cls.measure_hull_concavity(cluster, bm_test)
                        if c_err > worst_concavity:
                            worst_concavity = c_err
                            worst_idx = idx
                    finally:
                        bm_test.free()

                if worst_idx == -1 or worst_concavity <= concavity_threshold:
                    break  # Sufficiently convex or no more splittable clusters

                target_cluster = clusters.pop(worst_idx)
                coords = np.array([v.co for v in target_cluster.verts], dtype=np.float64)
                split_origin, split_normal = cls.compute_pca_splitting_plane(coords)

                child_a = target_cluster.copy()
                child_b = target_cluster.copy()

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
                    target_cluster.free()
                    target_cluster = None
                    clusters.extend([child_a, child_b])
                    child_a = None
                    child_b = None
                else:
                    # Slice resulted in degenerate empty side; rollback and preserve intact target_cluster
                    child_a.free()
                    child_b.free()
                    child_a = None
                    child_b = None
                    completed_clusters.append(target_cluster)
                    target_cluster = None
                    continue

            # Merge all clusters for final hull conversion
            clusters.extend(completed_clusters)
            completed_clusters = []

            # Convert all clusters into hardened 3D convex hulls
            final_hulls: List[Any] = []
            for c in clusters:
                success = cls.harden_convex_hull(c, max_verts=max_verts_per_hull, scale_factor=scale_factor)
                if success:
                    final_hulls.append(c)
                else:
                    c.free()

            # Transfer ownership of successfully created final_hulls
            clusters = []
            return final_hulls

        except Exception:
            if child_a is not None:
                try:
                    child_a.free()
                except Exception as exc:
                    logger.debug("Failed freeing child_a BMesh: %s", exc)
            if child_b is not None:
                try:
                    child_b.free()
                except Exception as exc:
                    logger.debug("Failed freeing child_b BMesh: %s", exc)
            if target_cluster is not None:
                try:
                    target_cluster.free()
                except Exception as exc:
                    logger.debug("Failed freeing target_cluster BMesh: %s", exc)
            for c in clusters + completed_clusters:
                try:
                    c.free()
                except Exception as exc:
                    logger.debug("Failed freeing cluster BMesh: %s", exc)
            raise
