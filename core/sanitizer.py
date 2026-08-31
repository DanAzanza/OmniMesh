"""
Mesh Sanitization and Pre-processing Engine.
Performs deterministic BMesh geometry hygiene, bowtie splitting,
degenerate cleanup, and sub-pixel island dissolution.
"""

from __future__ import annotations

from typing import Any

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
        if not bmesh or not bm:
            return {"loose_verts": 0, "wire_edges": 0, "zero_edges": 0, "zero_faces": 0}

        bm.verts.ensure_lookup_table()
        bm.edges.ensure_lookup_table()
        bm.faces.ensure_lookup_table()

        stats = {"loose_verts": 0, "wire_edges": 0, "zero_edges": 0, "zero_faces": 0}

        zero_faces = [f for f in bm.faces if f.calc_area() < min_face_area]
        if zero_faces:
            stats["zero_faces"] = len(zero_faces)
            bmesh.ops.delete(bm, geom=zero_faces, context="FACES_ONLY")
            bm.faces.ensure_lookup_table()

        zero_edges = [e for e in bm.edges if e.calc_length() < min_edge_length]
        if zero_edges:
            stats["zero_edges"] = len(zero_edges)
            bmesh.ops.collapse(bm, edges=zero_edges)
            bm.verts.ensure_lookup_table()
            bm.edges.ensure_lookup_table()
            bm.faces.ensure_lookup_table()

        loose_verts = [v for v in bm.verts if not v.link_edges]
        if loose_verts:
            stats["loose_verts"] = len(loose_verts)
            bmesh.ops.delete(bm, geom=loose_verts, context="VERTS")
            bm.verts.ensure_lookup_table()

        wire_edges = [e for e in bm.edges if not e.link_faces]
        if wire_edges:
            stats["wire_edges"] = len(wire_edges)
            bmesh.ops.delete(bm, geom=wire_edges, context="EDGES")
            bm.edges.ensure_lookup_table()
            bm.verts.ensure_lookup_table()

        return stats

    @staticmethod
    def merge_doubles_boundary_safe(bm: Any, dist: float = 1e-5) -> int:
        if not bmesh or not bm:
            return 0
        bm.verts.ensure_lookup_table()
        initial_verts = len(bm.verts)
        bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=dist)
        bm.verts.ensure_lookup_table()
        bm.edges.ensure_lookup_table()
        bm.faces.ensure_lookup_table()
        return initial_verts - len(bm.verts)

    @staticmethod
    def split_bowtie_vertices(bm: Any) -> int:
        if not bmesh or not bm:
            return 0
        bm.verts.ensure_lookup_table()
        split_count = 0

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
                for extra_fan in fans[1:]:
                    new_vert = bm.verts.new(vert.co)
                    for face in extra_fan:
                        face_verts = list(face.verts)
                        idx = face_verts.index(vert)
                        face_verts[idx] = new_vert
                        mat_idx = face.material_index
                        smooth = face.smooth
                        bm.faces.remove(face)
                        try:
                            new_face = bm.faces.new(face_verts)
                            new_face.material_index = mat_idx
                            new_face.smooth = smooth
                        except ValueError:
                            pass
                    split_count += 1

        if split_count > 0:
            bm.verts.ensure_lookup_table()
            bm.edges.ensure_lookup_table()
            bm.faces.ensure_lookup_table()

        return split_count

    @staticmethod
    def cull_subpixel_islands(bm: Any, w_crit: float) -> int:
        if not bmesh or not bm or not mathutils:
            return 0
        bm.faces.ensure_lookup_table()
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
            coords = [v.co for f in island for v in f.verts]
            if not coords:
                continue
            min_c = mathutils.Vector((min(c.x for c in coords), min(c.y for c in coords), min(c.z for c in coords)))
            max_c = mathutils.Vector((max(c.x for c in coords), max(c.y for c in coords), max(c.z for c in coords)))
            diag = (max_c - min_c).length

            if diag < w_crit:
                culled_faces.extend(island)

        if culled_faces and len(culled_faces) < len(bm.faces):
            culled_count = len(culled_faces)
            bmesh.ops.delete(bm, geom=culled_faces, context="FACES")
            MeshSanitizer.clean_loose_and_degenerates(bm)
            return culled_count

        return 0

    @classmethod
    def sanitize_mesh_full(cls, bm: Any, epsilon_merge: float, w_crit: float) -> dict[str, Any]:
        if not bmesh or not bm:
            return {}
        stats = {}
        stats.update(cls.clean_loose_and_degenerates(bm))
        stats["merged_doubles"] = cls.merge_doubles_boundary_safe(bm, dist=epsilon_merge)
        stats["split_bowties"] = cls.split_bowtie_vertices(bm)
        if w_crit > 1e-4:
            stats["culled_islands"] = cls.cull_subpixel_islands(bm, w_crit)
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        return stats
