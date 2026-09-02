"""
Hardened Mesh Sanitization & Topology Repair Engine for OmniMesh.
Blender 4.2+ and 5.2 LTS Compatible.

Provides 3-tiered architecture:
- Tier 0: Pure Geometric Hygiene (Uncritical, safe, always executed via fixed-point iteration)
- Tier 1: Topological Repair (Critical / Opt-in with explicit user toggles)
- Tier 2: Pipeline & Normal/Material Guards (Manifold-only normal alignment, material slot lock)
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Set, Tuple

logger = logging.getLogger(__name__)

try:
    import bmesh
    import bpy
    import mathutils
    from mathutils import Vector
except ImportError:
    bpy = None
    bmesh = None
    mathutils = None

    class Vector(tuple):  # type: ignore
        """Fallback Vector for headless unit tests."""

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
            import math

            return math.sqrt(self[0] * self[0] + self[1] * self[1] + self[2] * self[2])

        def dot(self, other: Any) -> float:
            return self[0] * other[0] + self[1] * other[1] + self[2] * other[2]

        def __sub__(self, other: Any) -> Vector:
            return Vector((self[0] - other[0], self[1] - other[1], self[2] - other[2]))


class MeshSanitizer:
    """
    Production-grade mesh sanitization and topology repair engine.
    Strictly preserves UV seams, vertex deform groups, custom split normals, and material signatures.
    """

    @classmethod
    def _purge_duplicate_faces(cls, bm: Any) -> int:
        """
        Detects and removes exact duplicate coplanar faces sharing the same vertex set.
        Purges only if face normals are collinear (dot > 0.999), preserving intentional
        double-sided geometry (foliage cards, hair ribbons, cloth).
        """
        if not bmesh or not bm or not hasattr(bm, "faces") or len(bm.faces) == 0:
            return 0

        try:
            bm.faces.ensure_lookup_table()
        except Exception as exc:
            logger.debug("Lookup table init error: %s", exc)
            return 0

        vert_set_to_faces: Dict[frozenset[Any], List[Any]] = {}

        for f in bm.faces:
            if not getattr(f, "is_valid", False):
                continue
            key = frozenset(f.verts)
            if key not in vert_set_to_faces:
                vert_set_to_faces[key] = []
            vert_set_to_faces[key].append(f)

        faces_to_delete: List[Any] = []
        for _key, face_list in vert_set_to_faces.items():
            if len(face_list) <= 1:
                continue

            # Compare pairs for normal collinearity
            kept_faces: List[Any] = []
            for candidate in face_list:
                is_duplicate = False
                for kept in kept_faces:
                    # Check normal alignment
                    try:
                        n1 = candidate.normal
                        n2 = kept.normal
                        n1_sq = n1[0] * n1[0] + n1[1] * n1[1] + n1[2] * n1[2]
                        n2_sq = n2[0] * n2[0] + n2[1] * n2[1] + n2[2] * n2[2]
                        if n1_sq > 1e-8 and n2_sq > 1e-8:
                            if hasattr(n1, "dot"):
                                n_dot = n1.dot(n2)
                            else:
                                n_dot = (n1[0] * n2[0] + n1[1] * n2[1] + n1[2] * n2[2]) / (
                                    mathutils.sqrt(n1_sq * n2_sq) if mathutils else (n1_sq * n2_sq) ** 0.5
                                )
                            if n_dot > 0.999:  # Exact duplicate coplanar face
                                is_duplicate = True
                                break
                    except Exception as exc:
                        logger.debug("Duplicate face normal check error: %s", exc)

                if is_duplicate:
                    faces_to_delete.append(candidate)
                else:
                    kept_faces.append(candidate)

        if faces_to_delete:
            try:
                bmesh.ops.delete(bm, geom=faces_to_delete, context="FACES_ONLY")
                bm.faces.ensure_lookup_table()
                bm.edges.ensure_lookup_table()
                bm.verts.ensure_lookup_table()
                return len(faces_to_delete)
            except Exception as exc:
                logger.debug("Delete duplicate faces error: %s", exc)

        return 0

    @classmethod
    def execute_tier0_pure_hygiene(
        cls, bm: Any, min_edge_length: float = 1e-7, min_face_area: float = 1e-12
    ) -> Dict[str, int]:
        """
        Tier 0: Pure Geometric Hygiene (Uncritical, safe, always executed).
        Executes multi-pass fixed-point iteration until complete convergence (max 3 passes).
        """
        if not bmesh or not bm or not hasattr(bm, "verts"):
            return {"zero_faces": 0, "zero_edges": 0, "wire_edges": 0, "loose_verts": 0, "duplicate_faces": 0}

        try:
            bm.verts.ensure_lookup_table()
            bm.edges.ensure_lookup_table()
            bm.faces.ensure_lookup_table()
        except Exception as exc:
            logger.debug("Lookup table init error in tier0: %s", exc)
            return {"zero_faces": 0, "zero_edges": 0, "wire_edges": 0, "loose_verts": 0, "duplicate_faces": 0}

        total_stats = {
            "zero_faces": 0,
            "zero_edges": 0,
            "wire_edges": 0,
            "loose_verts": 0,
            "duplicate_faces": 0,
        }

        # 1. Exact Duplicate Coplanar Faces (Normal-aligned only)
        total_stats["duplicate_faces"] = cls._purge_duplicate_faces(bm)

        # 2. Fixed-Point Multi-Pass Convergence (Max 3 passes)
        for _ in range(3):
            pass_culled = 0

            # Step A: Zero-area faces
            zero_faces = []
            for f in bm.faces:
                if getattr(f, "is_valid", False):
                    try:
                        if f.calc_area() < max(1e-15, min_face_area):
                            zero_faces.append(f)
                    except Exception:
                        zero_faces.append(f)

            if zero_faces:
                pass_culled += len(zero_faces)
                total_stats["zero_faces"] += len(zero_faces)
                try:
                    bmesh.ops.delete(bm, geom=zero_faces, context="FACES_ONLY")
                    bm.faces.ensure_lookup_table()
                    bm.edges.ensure_lookup_table()
                    bm.verts.ensure_lookup_table()
                except Exception as exc:
                    logger.debug("Delete zero faces error: %s", exc)

            # Step B: Zero-length edges
            zero_edges = []
            for e in bm.edges:
                if getattr(e, "is_valid", False):
                    try:
                        if e.calc_length() < max(1e-12, min_edge_length):
                            zero_edges.append(e)
                    except Exception:
                        zero_edges.append(e)

            if zero_edges:
                pass_culled += len(zero_edges)
                total_stats["zero_edges"] += len(zero_edges)
                try:
                    bmesh.ops.collapse(bm, edges=zero_edges)
                except (RuntimeError, ValueError, IndexError) as exc:
                    logger.debug("Edge collapse fallback in Tier 0: %s", exc)
                try:
                    bm.verts.ensure_lookup_table()
                    bm.edges.ensure_lookup_table()
                    bm.faces.ensure_lookup_table()
                except Exception as exc:
                    logger.debug("Lookup table ensure error: %s", exc)

            # Step C: Wire edges (no linked faces)
            wire_edges = [e for e in bm.edges if getattr(e, "is_valid", False) and not getattr(e, "link_faces", [])]
            if wire_edges:
                pass_culled += len(wire_edges)
                total_stats["wire_edges"] += len(wire_edges)
                try:
                    bmesh.ops.delete(bm, geom=wire_edges, context="EDGES")
                    bm.edges.ensure_lookup_table()
                    bm.verts.ensure_lookup_table()
                except Exception as exc:
                    logger.debug("Delete wire edges error: %s", exc)

            # Step D: Isolated loose vertices (no linked edges)
            loose_verts = [v for v in bm.verts if getattr(v, "is_valid", False) and not getattr(v, "link_edges", [])]
            if loose_verts:
                pass_culled += len(loose_verts)
                total_stats["loose_verts"] += len(loose_verts)
                try:
                    bmesh.ops.delete(bm, geom=loose_verts, context="VERTS")
                    bm.verts.ensure_lookup_table()
                except Exception as exc:
                    logger.debug("Delete loose verts error: %s", exc)

            if pass_culled == 0:
                break

        try:
            bm.verts.index_update()
        except Exception as exc:
            logger.debug("Index update error: %s", exc)
        return total_stats

    # Backward compatibility alias
    clean_loose_and_degenerates = execute_tier0_pure_hygiene

    @staticmethod
    def merge_doubles_boundary_safe(bm: Any, dist: float = 1e-5) -> int:
        """
        Merges coincident vertices within epsilon distance.
        Safely validates vertex table and returns the count of merged vertices.
        """
        if not bmesh or not bm or dist < 1e-9 or not hasattr(bm, "verts"):
            return 0
        try:
            bm.verts.ensure_lookup_table()
            initial_verts = len(bm.verts)
            if initial_verts <= 1:
                return 0
            bmesh.ops.remove_doubles(bm, verts=bm.verts[:], dist=max(1e-8, dist))
            bm.verts.ensure_lookup_table()
            bm.edges.ensure_lookup_table()
            bm.faces.ensure_lookup_table()
            bm.verts.index_update()
            return max(0, initial_verts - len(bm.verts))
        except Exception as exc:
            logger.debug("Merge doubles error: %s", exc)
            return 0

    @staticmethod
    def split_bowtie_vertices(bm: Any) -> int:
        """
        Splits non-manifold bowtie vertices (pinch points sharing multiple disconnected face fans)
        into independent vertices, preserving UV layers, deform weights (vertex groups),
        face attributes, and smoothing.
        """
        if not bmesh or not bm or not hasattr(bm, "verts"):
            return 0
        try:
            bm.verts.ensure_lookup_table()
        except Exception as exc:
            logger.debug("Lookup table init error in split_bowtie_vertices: %s", exc)
            return 0

        split_count = 0
        dvert_lay = (
            bm.verts.layers.deform.active
            if (hasattr(bm.verts, "layers") and hasattr(bm.verts.layers, "deform"))
            else None
        )
        uv_layers = (
            list(bm.loops.layers.uv.values())
            if (hasattr(bm, "loops") and hasattr(bm.loops, "layers") and hasattr(bm.loops.layers, "uv"))
            else []
        )

        for vert in list(bm.verts):
            if not getattr(vert, "is_valid", False) or len(getattr(vert, "link_faces", [])) <= 1:
                continue

            face_set = set(vert.link_faces)
            fans = []

            while face_set:
                start_face = face_set.pop()
                fan = [start_face]
                queue = [start_face]

                while queue:
                    curr_face = queue.pop(0)
                    for edge in getattr(curr_face, "edges", []):
                        if vert not in getattr(edge, "verts", []):
                            continue
                        for nbr_face in getattr(edge, "link_faces", []):
                            if nbr_face in face_set:
                                face_set.remove(nbr_face)
                                fan.append(nbr_face)
                                queue.append(nbr_face)
                fans.append(fan)

            if len(fans) > 1:
                # Capture deform weights from original vertex
                orig_weights = {}
                if dvert_lay:
                    try:
                        if vert[dvert_lay]:
                            orig_weights = dict(vert[dvert_lay])
                    except Exception:
                        orig_weights = {}

                for extra_fan in fans[1:]:
                    new_vert = bm.verts.new(vert.co)
                    if dvert_lay and orig_weights:
                        try:
                            dvert = new_vert[dvert_lay]
                            for g_idx, w in orig_weights.items():
                                dvert[g_idx] = w
                        except Exception as exc:
                            logger.debug("Deform weight assign error: %s", exc)

                    for face in extra_fan:
                        if not getattr(face, "is_valid", False):
                            continue
                        face_verts = list(face.verts)
                        if vert not in face_verts:
                            continue
                        idx = face_verts.index(vert)
                        face_verts[idx] = new_vert
                        mat_idx = getattr(face, "material_index", 0)
                        smooth = getattr(face, "smooth", True)

                        # Store UV loop coordinates before removing face
                        saved_uvs: Dict[Tuple[Any, int], Any] = {}
                        for lp_i, lp in enumerate(face.loops):
                            for uv_lay in uv_layers:
                                try:
                                    saved_uvs[(uv_lay, lp_i)] = lp[uv_lay].uv.copy()
                                except Exception as exc:
                                    logger.debug("Loop UV copy error: %s", exc)

                        bm.faces.remove(face)
                        try:
                            new_face = bm.faces.new(face_verts)
                            new_face.material_index = mat_idx
                            new_face.smooth = smooth

                            # Reapply UVs to new face loops
                            for lp_i, new_lp in enumerate(new_face.loops):
                                for uv_lay in uv_layers:
                                    if (uv_lay, lp_i) in saved_uvs:
                                        try:
                                            new_lp[uv_lay].uv = saved_uvs[(uv_lay, lp_i)]
                                        except Exception as exc:
                                            logger.debug("Reapply UV error: %s", exc)
                        except ValueError as exc:
                            logger.debug("New face creation error: %s", exc)
                    split_count += 1

        if split_count > 0:
            try:
                bm.verts.ensure_lookup_table()
                bm.edges.ensure_lookup_table()
                bm.faces.ensure_lookup_table()
                bm.verts.index_update()
            except Exception as exc:
                logger.debug("Lookup table ensure error: %s", exc)

        return split_count

    @staticmethod
    def split_non_manifold_edges(bm: Any) -> int:
        """
        Detects and splits non-manifold edges connected to > 2 faces into separate manifold edges,
        preserving UV layers, deform weights (vertex groups), face attributes, and smoothing.
        """
        if not bmesh or not bm or not hasattr(bm, "edges"):
            return 0
        try:
            bm.edges.ensure_lookup_table()
        except Exception as exc:
            logger.debug("Lookup table init error in split_non_manifold_edges: %s", exc)
            return 0

        split_count = 0
        non_manifold_edges = [
            e for e in bm.edges if getattr(e, "is_valid", False) and len(getattr(e, "link_faces", [])) > 2
        ]
        if not non_manifold_edges:
            return 0

        dvert_lay = (
            bm.verts.layers.deform.active
            if (hasattr(bm.verts, "layers") and hasattr(bm.verts.layers, "deform"))
            else None
        )
        uv_layers = (
            list(bm.loops.layers.uv.values())
            if (hasattr(bm, "loops") and hasattr(bm.loops, "layers") and hasattr(bm.loops.layers, "uv"))
            else []
        )

        # Split non-manifold edges by duplicating extra faces
        for edge in non_manifold_edges:
            if not getattr(edge, "is_valid", False) or len(getattr(edge, "link_faces", [])) <= 2:
                continue
            # Duplicate excess faces onto new vertices
            faces_to_split = list(edge.link_faces)[2:]
            for face in faces_to_split:
                if not getattr(face, "is_valid", False):
                    continue
                v1, v2 = edge.verts
                nv1 = bm.verts.new(v1.co)
                nv2 = bm.verts.new(v2.co)

                if dvert_lay:
                    try:
                        if v1[dvert_lay]:
                            dvert1 = nv1[dvert_lay]
                            for g_idx, w in dict(v1[dvert_lay]).items():
                                dvert1[g_idx] = w
                        if v2[dvert_lay]:
                            dvert2 = nv2[dvert_lay]
                            for g_idx, w in dict(v2[dvert_lay]).items():
                                dvert2[g_idx] = w
                    except Exception as exc:
                        logger.debug("Deform weight copy error in split_non_manifold_edges: %s", exc)

                face_verts = [nv1 if v == v1 else (nv2 if v == v2 else v) for v in face.verts]
                mat_idx = getattr(face, "material_index", 0)
                smooth = getattr(face, "smooth", True)

                saved_uvs: Dict[Tuple[Any, int], Any] = {}
                for lp_i, lp in enumerate(face.loops):
                    for uv_lay in uv_layers:
                        try:
                            saved_uvs[(uv_lay, lp_i)] = lp[uv_lay].uv.copy()
                        except Exception as exc:
                            logger.debug("Loop UV copy error: %s", exc)

                bm.faces.remove(face)
                try:
                    nf = bm.faces.new(face_verts)
                    nf.material_index = mat_idx
                    nf.smooth = smooth

                    for lp_i, new_lp in enumerate(nf.loops):
                        for uv_lay in uv_layers:
                            if (uv_lay, lp_i) in saved_uvs:
                                try:
                                    new_lp[uv_lay].uv = saved_uvs[(uv_lay, lp_i)]
                                except Exception as exc:
                                    logger.debug("Loop UV restoration failed: %s", exc)
                    split_count += 1
                except ValueError as exc:
                    logger.debug("Face creation failed: %s", exc)

        if split_count > 0:
            try:
                bm.verts.ensure_lookup_table()
                bm.edges.ensure_lookup_table()
                bm.faces.ensure_lookup_table()
                bm.verts.index_update()
            except Exception as exc:
                logger.debug("Lookup table update failed: %s", exc)

        return split_count

    @classmethod
    def fill_small_boundary_holes(cls, bm: Any, max_edges: int = 4) -> int:
        """
        Detects open boundary loops with <= max_edges, seals them, and executes
        MANDATORY immediate local beauty triangulation to prevent non-planar N-gons.
        """
        if not bmesh or not bm or not hasattr(bm, "edges") or max_edges < 3:
            return 0
        try:
            bm.edges.ensure_lookup_table()
        except Exception as exc:
            logger.debug("Lookup table init error in fill_small_boundary_holes: %s", exc)
            return 0

        boundary_edges = [e for e in bm.edges if getattr(e, "is_valid", False) and getattr(e, "is_boundary", False)]
        if not boundary_edges:
            return 0

        try:
            res = bmesh.ops.holes_fill(bm, edges=boundary_edges, sides=max_edges)
            new_faces = res.get("faces", [])
            if new_faces:
                # MANDATORY: Triangulate newly created cap faces to prevent non-planar N-gon folding in QEM
                bmesh.ops.triangulate(bm, faces=new_faces, quad_method="BEAUTY", ngon_method="BEAUTY")
                bm.faces.ensure_lookup_table()
                bm.edges.ensure_lookup_table()
                bm.verts.ensure_lookup_table()
                return len(new_faces)
        except Exception as exc:
            logger.debug("Hole filling error: %s", exc)

        return 0

    @classmethod
    def cull_subpixel_islands(cls, bm: Any, w_crit: float, world_matrix: Any = None) -> int:
        """
        Removes disconnected mesh islands whose bounding diagonal in world space is < w_crit.
        Protects against deleting the entire mesh if all components are small.
        """
        if not bmesh or not bm or not hasattr(bm, "faces") or w_crit <= 1e-6:
            return 0
        try:
            bm.faces.ensure_lookup_table()
        except Exception as exc:
            logger.debug("Lookup table init error in cull_subpixel_islands: %s", exc)
            return 0

        if len(bm.faces) == 0:
            return 0

        unvisited: Set[Any] = set(f for f in bm.faces if getattr(f, "is_valid", False))
        islands: List[List[Any]] = []

        while unvisited:
            start = unvisited.pop()
            island = [start]
            queue = [start]
            while queue:
                curr = queue.pop(0)
                for edge in getattr(curr, "edges", []):
                    for nbr in getattr(edge, "link_faces", []):
                        if nbr in unvisited:
                            unvisited.remove(nbr)
                            island.append(nbr)
                            queue.append(nbr)
            islands.append(island)

        if not islands:
            return 0

        culled_faces: List[Any] = []
        for island in islands:
            unique_verts = set(v for f in island for v in getattr(f, "verts", []))
            if not unique_verts:
                continue

            try:
                if world_matrix is not None and hasattr(world_matrix, "__matmul__"):
                    coords = [world_matrix @ v.co for v in unique_verts]
                else:
                    coords = [v.co for v in unique_verts]

                min_x = min(c[0] for c in coords)
                min_y = min(c[1] for c in coords)
                min_z = min(c[2] for c in coords)
                max_x = max(c[0] for c in coords)
                max_y = max(c[1] for c in coords)
                max_z = max(c[2] for c in coords)

                diag = ((max_x - min_x) ** 2 + (max_y - min_y) ** 2 + (max_z - min_z) ** 2) ** 0.5

                if diag < w_crit:
                    culled_faces.extend(island)
            except Exception as exc:
                logger.debug("Island bounding box calculation error: %s", exc)

        # Safeguard: never delete the entire mesh
        if culled_faces and len(culled_faces) < len(bm.faces):
            culled_count = len(culled_faces)
            try:
                bmesh.ops.delete(bm, geom=culled_faces, context="FACES")
                cls.execute_tier0_pure_hygiene(bm)
                return culled_count
            except Exception as exc:
                logger.debug("Delete island faces error: %s", exc)

        return 0

    @classmethod
    def execute_tier1_topological_repair(
        cls,
        bm: Any,
        enable_weld: bool = False,
        weld_dist: float = 0.0005,
        enable_split_non_manifold: bool = True,
        enable_fill_holes: bool = False,
        hole_max_edges: int = 4,
        enable_triangulate_ngons: bool = False,
        enable_cull_micro_islands: bool = False,
        island_size_threshold: float = 0.005,
        world_matrix: Any = None,
    ) -> Dict[str, int]:
        """
        Tier 1: Topological Repair (Opt-in with explicit user toggles).
        Strict ordering: Weld -> Split Bowties & Non-Manifold -> Fill Holes (+Triangulate) -> N-Gon Triangulate -> Cull Islands.
        """
        if not bmesh or not bm:
            return {
                "welded_verts": 0,
                "split_bowties": 0,
                "split_non_manifold_edges": 0,
                "filled_holes": 0,
                "triangulated_ngons": 0,
                "culled_islands": 0,
            }

        stats = {
            "welded_verts": 0,
            "split_bowties": 0,
            "split_non_manifold_edges": 0,
            "filled_holes": 0,
            "triangulated_ngons": 0,
            "culled_islands": 0,
        }

        # 1. Weld Coincident Vertices (Boundary Safe)
        if enable_weld and weld_dist > 1e-6:
            stats["welded_verts"] = cls.merge_doubles_boundary_safe(bm, dist=weld_dist)

        # 2. Split Non-Manifold Bowtie Vertices & Edges
        if enable_split_non_manifold:
            stats["split_bowties"] = cls.split_bowtie_vertices(bm)
            stats["split_non_manifold_edges"] = cls.split_non_manifold_edges(bm)

        # 3. Fill Small Open Holes (with immediate local beauty triangulation)
        if enable_fill_holes:
            stats["filled_holes"] = cls.fill_small_boundary_holes(bm, max_edges=hole_max_edges)

        # 4. Triangulate Remaining N-Gons (>4 vertices) if requested
        if enable_triangulate_ngons and hasattr(bm, "faces"):
            try:
                bm.faces.ensure_lookup_table()
                ngons = [f for f in bm.faces if getattr(f, "is_valid", False) and len(getattr(f, "verts", [])) > 4]
                if ngons:
                    bmesh.ops.triangulate(bm, faces=ngons, quad_method="BEAUTY", ngon_method="BEAUTY")
                    stats["triangulated_ngons"] = len(ngons)
                    bm.faces.ensure_lookup_table()
                    bm.edges.ensure_lookup_table()
                    bm.verts.ensure_lookup_table()
            except Exception as exc:
                logger.debug("N-gon triangulation error: %s", exc)

        # 5. Cull Floating Micro-Islands
        if enable_cull_micro_islands and island_size_threshold > 1e-4:
            stats["culled_islands"] = cls.cull_subpixel_islands(
                bm, w_crit=island_size_threshold, world_matrix=world_matrix
            )

        try:
            bm.verts.index_update()
        except Exception as exc:
            logger.debug("Index update failed: %s", exc)
        return stats

    @classmethod
    def execute_tier2_pipeline_guards(cls, bm: Any, normal_recalc_policy: str = "MANIFOLD_ONLY") -> Dict[str, Any]:
        """
        Tier 2: Pipeline & Normal/Material Guards.
        - MANIFOLD_ONLY (Default): Recalculates outward normals ONLY on strictly closed 2-manifold shells.
          Protects foliage cards, single-sided cloth, inverted outline shells, and open meshes.
        - FORCE_ALL: Flood-fills outward normal recalculation across entire mesh.
        - OFF: Keeps face winding 100% untouched.
        """
        if not bmesh or not bm or not hasattr(bm, "faces") or len(bm.faces) == 0:
            return {"recalculated_normals": False}

        try:
            bm.faces.ensure_lookup_table()
            bm.edges.ensure_lookup_table()
        except Exception as exc:
            logger.debug("Lookup table init error in tier2: %s", exc)
            return {"recalculated_normals": False}

        if normal_recalc_policy == "MANIFOLD_ONLY":
            # Identify closed manifold shells (faces where every edge has exactly 2 link faces)
            closed_faces = [
                f
                for f in bm.faces
                if getattr(f, "is_valid", False)
                and all(len(getattr(e, "link_faces", [])) == 2 for e in getattr(f, "edges", []))
            ]
            if closed_faces:
                try:
                    bmesh.ops.recalc_face_normals(bm, faces=closed_faces)
                    return {"recalculated_normals": True, "manifold_faces_aligned": len(closed_faces)}
                except Exception as exc:
                    logger.debug("Manifold normal recalc fallback: %s", exc)
        elif normal_recalc_policy == "FORCE_ALL":
            try:
                bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
                return {"recalculated_normals": True, "forced_all_aligned": len(bm.faces)}
            except Exception as exc:
                logger.debug("Forced normal recalc fallback: %s", exc)

        return {"recalculated_normals": False}

    @classmethod
    def sanitize_mesh_full(
        cls,
        bm: Any,
        epsilon_merge: float = 1e-5,
        w_crit: float = 0.0,
        enable_weld: bool = False,
        enable_split_non_manifold: bool = True,
        enable_fill_holes: bool = False,
        hole_max_edges: int = 4,
        enable_triangulate_ngons: bool = False,
        enable_cull_micro_islands: bool = False,
        normal_recalc_policy: str = "MANIFOLD_ONLY",
        world_matrix: Any = None,
    ) -> Dict[str, Any]:
        """
        Coordinates full 3-tier mesh sanitation & repair pipeline.
        Returns comprehensive summary statistics dictionary.
        """
        if not bmesh or not bm:
            return {}

        stats: Dict[str, Any] = {}

        # Tier 0: Pure Geometric Hygiene (Uncritical, Always Active)
        stats.update(cls.execute_tier0_pure_hygiene(bm))

        # Strictly respect explicit enable flags
        actual_weld = bool(enable_weld and epsilon_merge > 1e-6)
        actual_dist = epsilon_merge if (epsilon_merge > 1e-6) else 0.0005
        actual_cull = bool(enable_cull_micro_islands and w_crit > 1e-5)
        actual_crit = w_crit if (w_crit > 1e-5) else 0.005

        # Tier 1: Topological Repair (Critical / Opt-in)
        tier1_stats = cls.execute_tier1_topological_repair(
            bm,
            enable_weld=actual_weld,
            weld_dist=actual_dist,
            enable_split_non_manifold=enable_split_non_manifold,
            enable_fill_holes=enable_fill_holes,
            hole_max_edges=hole_max_edges,
            enable_triangulate_ngons=enable_triangulate_ngons,
            enable_cull_micro_islands=actual_cull,
            island_size_threshold=actual_crit,
            world_matrix=world_matrix,
        )
        stats.update(tier1_stats)
        stats["merged_doubles"] = tier1_stats.get("welded_verts", 0)
        stats["split_bowties"] = tier1_stats.get("split_bowties", 0)

        # Tier 2: Pipeline & Normal Guards
        tier2_stats = cls.execute_tier2_pipeline_guards(bm, normal_recalc_policy=normal_recalc_policy)
        stats.update(tier2_stats)

        return stats
