"""
OmniMesh Advanced Topological Mesh Repair Engine.
Handles non-manifold bowtie vertex splitting, non-manifold edge splitting,
boundary hole sealing with beauty triangulation, and subpixel island culling.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

try:
    import bmesh
    import bpy
except ImportError:
    bpy = None
    bmesh = None


class TopologyRepairEngine:
    """Advanced topological manifold repair, bowtie splitting, and hole sealing."""

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

                        saved_uvs: dict[tuple[Any, int], Any] = {}
                        for lp_i, lp in enumerate(face.loops):
                            for uv_lay in uv_layers:
                                try:
                                    saved_uvs[(uv_lay, lp_i)] = lp[uv_lay].uv.copy()
                                except Exception as exc:
                                    logger.debug("Loop UV copy error: %s", exc)

                        orig_face_verts = list(face.verts)
                        bm.faces.remove(face)
                        try:
                            new_face = bm.faces.new(face_verts)
                            new_face.material_index = mat_idx
                            new_face.smooth = smooth

                            for lp_i, new_lp in enumerate(new_face.loops):
                                for uv_lay in uv_layers:
                                    if (uv_lay, lp_i) in saved_uvs:
                                        try:
                                            new_lp[uv_lay].uv = saved_uvs[(uv_lay, lp_i)]
                                        except Exception as exc:
                                            logger.debug("Reapply UV error: %s", exc)
                            split_count += 1
                        except ValueError as exc:
                            logger.debug("New face creation error: %s, restoring original face", exc)
                            try:
                                restored_f = bm.faces.new(orig_face_verts)
                                restored_f.material_index = mat_idx
                                restored_f.smooth = smooth
                            except Exception as rb_exc:
                                logger.debug("Restoring original face failed: %s", rb_exc)

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

        for edge in non_manifold_edges:
            if not getattr(edge, "is_valid", False) or len(getattr(edge, "link_faces", [])) <= 2:
                continue
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

                saved_uvs: dict[tuple[Any, int], Any] = {}
                for lp_i, lp in enumerate(face.loops):
                    for uv_lay in uv_layers:
                        try:
                            saved_uvs[(uv_lay, lp_i)] = lp[uv_lay].uv.copy()
                        except Exception as exc:
                            logger.debug("Loop UV copy error: %s", exc)

                orig_face_verts = list(face.verts)
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
                    logger.debug("Face creation failed: %s, restoring original face", exc)
                    try:
                        restored_f = bm.faces.new(orig_face_verts)
                        restored_f.material_index = mat_idx
                        restored_f.smooth = smooth
                    except Exception as rb_exc:
                        logger.debug("Restoring original face failed: %s", rb_exc)

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

        unvisited = set(f for f in bm.faces if getattr(f, "is_valid", False))
        islands = []

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

        culled_faces = []
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

        if culled_faces and len(culled_faces) < len(bm.faces):
            culled_count = len(culled_faces)
            try:
                bmesh.ops.delete(bm, geom=culled_faces, context="FACES")
                from .sanitizer import MeshSanitizer

                MeshSanitizer.execute_tier0_pure_hygiene(bm)
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
    ) -> dict[str, int]:
        """
        Tier 1: Topological Repair (Opt-in with explicit user toggles).
        Ordering: Weld -> Split Bowties & Non-Manifold -> Fill Holes (+Triangulate) -> N-Gon Triangulate -> Cull Islands.
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
            from .sanitizer import MeshSanitizer

            stats["welded_verts"] = MeshSanitizer.merge_doubles_boundary_safe(bm, dist=weld_dist)

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
                    bm.faces.ensure_lookup_table()
                    bm.edges.ensure_lookup_table()
                    bm.verts.ensure_lookup_table()
                    stats["triangulated_ngons"] = len(ngons)
            except Exception as exc:
                logger.debug("N-gon triangulation error: %s", exc)

        # 5. Cull Subpixel / Micro Islands
        if enable_cull_micro_islands and island_size_threshold > 1e-6:
            stats["culled_islands"] = cls.cull_subpixel_islands(
                bm, w_crit=island_size_threshold, world_matrix=world_matrix
            )

        return stats
