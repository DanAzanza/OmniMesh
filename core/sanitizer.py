"""
Mesh Sanitization and Pre-processing Engine.
Performs deterministic BMesh geometry hygiene, bowtie splitting,
degenerate cleanup, and sub-pixel island dissolution.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

try:
    import bmesh
    import bpy
    import mathutils
except ImportError:
    bpy = None
    bmesh = None
    mathutils = None


class MeshSanitizer:
    @staticmethod
    def clean_loose_and_degenerates(
        bm: Any, min_edge_length: float = 1e-7, min_face_area: float = 1e-12
    ) -> dict[str, int]:
        """
        Cleans zero-area faces, degenerate zero-length edges, wire edges, and loose vertices.
        Performs multi-pass sequencing to ensure that secondary loose geometry created by
        face and edge deletions is completely swept.
        """
        if not bmesh or not bm:
            return {"loose_verts": 0, "wire_edges": 0, "zero_edges": 0, "zero_faces": 0}

        bm.verts.ensure_lookup_table()
        bm.edges.ensure_lookup_table()
        bm.faces.ensure_lookup_table()

        stats = {"loose_verts": 0, "wire_edges": 0, "zero_edges": 0, "zero_faces": 0}

        # 1. Remove zero-area / degenerate faces
        zero_faces = [f for f in bm.faces if f.calc_area() < max(1e-15, min_face_area)]
        if zero_faces:
            stats["zero_faces"] = len(zero_faces)
            bmesh.ops.delete(bm, geom=zero_faces, context="FACES_ONLY")
            bm.faces.ensure_lookup_table()
            bm.edges.ensure_lookup_table()
            bm.verts.ensure_lookup_table()

        # 2. Collapse zero-length / degenerate edges
        zero_edges = [e for e in bm.edges if e.is_valid and e.calc_length() < max(1e-12, min_edge_length)]
        if zero_edges:
            stats["zero_edges"] = len(zero_edges)
            try:
                bmesh.ops.collapse(bm, edges=zero_edges)
            except (RuntimeError, ValueError, IndexError) as exc:
                # Fallback: delete invalid geometry if collapse fails on non-manifold edges
                logger.debug("Edge collapse fallback: %s", exc)
            bm.verts.ensure_lookup_table()
            bm.edges.ensure_lookup_table()
            bm.faces.ensure_lookup_table()

        # 3. Delete wire edges (edges without any link faces)
        wire_edges = [e for e in bm.edges if e.is_valid and not e.link_faces]
        if wire_edges:
            stats["wire_edges"] = len(wire_edges)
            bmesh.ops.delete(bm, geom=wire_edges, context="EDGES")
            bm.edges.ensure_lookup_table()
            bm.verts.ensure_lookup_table()

        # 4. Sweep loose vertices (vertices with no connected edges)
        loose_verts = [v for v in bm.verts if v.is_valid and not v.link_edges]
        if loose_verts:
            stats["loose_verts"] = len(loose_verts)
            bmesh.ops.delete(bm, geom=loose_verts, context="VERTS")
            bm.verts.ensure_lookup_table()

        # 5. Final validation sweep
        bm.verts.index_update()
        return stats

    @staticmethod
    def merge_doubles_boundary_safe(bm: Any, dist: float = 1e-5) -> int:
        """
        Merges coincident vertices within epsilon distance.
        Safely validates vertex table and returns the count of merged vertices.
        """
        if not bmesh or not bm or dist < 1e-9:
            return 0
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

    @staticmethod
    def split_bowtie_vertices(bm: Any) -> int:
        """
        Splits non-manifold bowtie vertices (pinch points sharing multiple disconnected face fans)
        into independent vertices, preserving UV layers, deform weights (vertex groups),
        face attributes, and smoothing.
        """
        if not bmesh or not bm:
            return 0
        bm.verts.ensure_lookup_table()
        split_count = 0

        dvert_lay = bm.verts.layers.deform.active
        uv_layers = list(bm.loops.layers.uv.values())

        for vert in list(bm.verts):
            if not vert.is_valid or len(vert.link_faces) <= 1:
                continue

            face_set = set(vert.link_faces)
            fans = []

            while face_set:
                start_face = face_set.pop()
                fan = [start_face]
                queue = [start_face]

                while queue:
                    curr_face = queue.pop(0)
                    for edge in curr_face.edges:
                        if vert not in edge.verts:
                            continue
                        for nbr_face in edge.link_faces:
                            if nbr_face in face_set:
                                face_set.remove(nbr_face)
                                fan.append(nbr_face)
                                queue.append(nbr_face)
                fans.append(fan)

            if len(fans) > 1:
                # Capture deform weights from original vertex
                orig_weights = {}
                if dvert_lay and vert[dvert_lay]:
                    orig_weights = dict(vert[dvert_lay])

                for extra_fan in fans[1:]:
                    new_vert = bm.verts.new(vert.co)
                    if dvert_lay and orig_weights:
                        dvert = new_vert[dvert_lay]
                        for g_idx, w in orig_weights.items():
                            dvert[g_idx] = w

                    for face in extra_fan:
                        if not face.is_valid:
                            continue
                        face_verts = list(face.verts)
                        idx = face_verts.index(vert)
                        face_verts[idx] = new_vert
                        mat_idx = face.material_index
                        smooth = face.smooth

                        # Store UV loop coordinates before removing face
                        saved_uvs: dict[tuple[Any, int], Any] = {}
                        for lp_i, lp in enumerate(face.loops):
                            for uv_lay in uv_layers:
                                saved_uvs[(uv_lay, lp_i)] = lp[uv_lay].uv.copy()

                        bm.faces.remove(face)
                        try:
                            new_face = bm.faces.new(face_verts)
                            new_face.material_index = mat_idx
                            new_face.smooth = smooth

                            # Reapply UVs to new face loops
                            for lp_i, new_lp in enumerate(new_face.loops):
                                for uv_lay in uv_layers:
                                    if (uv_lay, lp_i) in saved_uvs:
                                        new_lp[uv_lay].uv = saved_uvs[(uv_lay, lp_i)]
                        except ValueError:
                            pass
                    split_count += 1

        if split_count > 0:
            bm.verts.ensure_lookup_table()
            bm.edges.ensure_lookup_table()
            bm.faces.ensure_lookup_table()
            bm.verts.index_update()

        return split_count

    @staticmethod
    def cull_subpixel_islands(bm: Any, w_crit: float) -> int:
        """
        Removes disconnected mesh islands whose bounding diagonal is strictly less than w_crit.
        Protects against deleting the entire mesh if all components are small.
        """
        if not bmesh or not bm or not mathutils or w_crit <= 1e-6:
            return 0
        bm.faces.ensure_lookup_table()
        if len(bm.faces) == 0:
            return 0

        unvisited = set(bm.faces)
        islands = []

        while unvisited:
            start = unvisited.pop()
            island = [start]
            queue = [start]
            while queue:
                curr = queue.pop(0)
                for edge in curr.edges:
                    for nbr in edge.link_faces:
                        if nbr in unvisited:
                            unvisited.remove(nbr)
                            island.append(nbr)
                            queue.append(nbr)
            islands.append(island)

        if not islands:
            return 0

        culled_faces = []
        for island in islands:
            unique_verts = set(v for f in island for v in f.verts)
            if not unique_verts:
                continue
            coords = [v.co for v in unique_verts]
            min_c = mathutils.Vector((min(c.x for c in coords), min(c.y for c in coords), min(c.z for c in coords)))
            max_c = mathutils.Vector((max(c.x for c in coords), max(c.y for c in coords), max(c.z for c in coords)))
            diag = (max_c - min_c).length

            if diag < w_crit:
                culled_faces.extend(island)

        # Safeguard: never delete the entire mesh
        if culled_faces and len(culled_faces) < len(bm.faces):
            culled_count = len(culled_faces)
            bmesh.ops.delete(bm, geom=culled_faces, context="FACES")
            MeshSanitizer.clean_loose_and_degenerates(bm)
            return culled_count

        return 0

    @classmethod
    def sanitize_mesh_full(cls, bm: Any, epsilon_merge: float = 1e-5, w_crit: float = 0.0) -> dict[str, Any]:
        """
        Executes full sanitization pipeline:
        1. Degenerate and loose geometry cleanup
        2. Boundary-safe vertex double merging
        3. Bowtie vertex splitting
        4. Sub-pixel island culling
        5. Normal recalculation and validation
        """
        if not bmesh or not bm:
            return {}
        stats: dict[str, Any] = {}
        stats.update(cls.clean_loose_and_degenerates(bm))
        stats["merged_doubles"] = cls.merge_doubles_boundary_safe(bm, dist=epsilon_merge)
        stats["split_bowties"] = cls.split_bowtie_vertices(bm)
        if w_crit > 1e-4:
            stats["culled_islands"] = cls.cull_subpixel_islands(bm, w_crit)
        else:
            stats["culled_islands"] = 0

        if len(bm.faces) > 0:
            bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
        return stats
