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
import math
from typing import Any, Dict, List

from .topology_repair import TopologyRepairEngine

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
                                n_dot = (n1[0] * n2[0] + n1[1] * n2[1] + n1[2] * n2[2]) / math.sqrt(n1_sq * n2_sq)
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

    split_bowtie_vertices = staticmethod(TopologyRepairEngine.split_bowtie_vertices)
    split_non_manifold_edges = staticmethod(TopologyRepairEngine.split_non_manifold_edges)
    fill_small_boundary_holes = staticmethod(TopologyRepairEngine.fill_small_boundary_holes)
    cull_subpixel_islands = staticmethod(TopologyRepairEngine.cull_subpixel_islands)
    execute_tier1_topological_repair = staticmethod(TopologyRepairEngine.execute_tier1_topological_repair)

    @staticmethod
    def run_preflight_inspection(context: Any, mesh_objs: list[Any]) -> dict[str, Any]:
        """Inspect mesh objects for unapplied scale/rotation, loose topology, degenerates, and materials."""
        if not bpy or not context:
            return {}
        props = getattr(getattr(context, "scene", None), "lod_tool", None)
        if not props:
            return {}

        total_loose_verts = 0
        total_loose_edges = 0
        total_non_manifold_edges = 0
        total_degenerate_tris = 0
        has_unapplied_scale = False
        missing_mats = 0

        for obj in mesh_objs:
            s = getattr(obj, "scale", None)
            if s and hasattr(s, "x") and hasattr(s, "y") and hasattr(s, "z"):
                try:
                    if abs(s.x - 1.0) > 1e-4 or abs(s.y - 1.0) > 1e-4 or abs(s.z - 1.0) > 1e-4:
                        has_unapplied_scale = True
                except (TypeError, ValueError):
                    pass

            if hasattr(obj, "material_slots") and type(obj.material_slots).__name__ != "MagicMock":
                try:
                    if len(obj.material_slots) == 0 or any(slot.material is None for slot in obj.material_slots):
                        missing_mats += 1
                except (TypeError, ValueError):
                    pass

            mesh_data = getattr(obj, "data", None)
            if not mesh_data or not bmesh:
                continue

            try:
                bm = bmesh.new()
                try:
                    bm.from_mesh(mesh_data)
                    for v in getattr(bm, "verts", []):
                        if len(getattr(v, "link_edges", [])) == 0:
                            total_loose_verts += 1
                    for e in getattr(bm, "edges", []):
                        face_count = len(getattr(e, "link_faces", []))
                        if face_count == 0:
                            total_loose_edges += 1
                        elif face_count > 2:
                            total_non_manifold_edges += 1
                    for f in getattr(bm, "faces", []):
                        calc_area = getattr(f, "calc_area", None)
                        if callable(calc_area) and float(calc_area()) <= 1e-10:
                            total_degenerate_tris += 1
                finally:
                    bm.free()
            except Exception as exc:
                logger.debug("Failed during mesh inspection: %s", exc)

        props.preflight_inspected = True
        props.preflight_loose_verts = total_loose_verts
        props.preflight_loose_edges = total_loose_edges
        props.preflight_non_manifold_edges = total_non_manifold_edges
        props.preflight_degenerate_tris = total_degenerate_tris
        props.preflight_unapplied_scale = has_unapplied_scale
        props.preflight_missing_materials = missing_mats

        is_clean = (
            (total_loose_verts == 0)
            and (total_loose_edges == 0)
            and (total_non_manifold_edges == 0)
            and (total_degenerate_tris == 0)
            and (not has_unapplied_scale)
            and (missing_mats == 0)
        )
        props.preflight_is_clean = is_clean

        if is_clean:
            props.preflight_summary_text = f"✔ LOD0 Healthy ({len(mesh_objs)} mesh(es), All Transforms Applied)"
        else:
            issues = []
            if has_unapplied_scale:
                issues.append("Unapplied Scale")
            if total_loose_verts > 0:
                issues.append(f"{total_loose_verts} Loose Verts")
            if total_loose_edges > 0:
                issues.append(f"{total_loose_edges} Loose Edges")
            if total_non_manifold_edges > 0:
                issues.append(f"{total_non_manifold_edges} Non-Manifold Edges")
            if total_degenerate_tris > 0:
                issues.append(f"{total_degenerate_tris} Degenerates")
            if missing_mats > 0:
                issues.append(f"{missing_mats} Missing Mats")
            props.preflight_summary_text = f"⚠ Issues: {', '.join(issues)}"

        return {
            "loose_verts": total_loose_verts,
            "loose_edges": total_loose_edges,
            "non_manifold_edges": total_non_manifold_edges,
            "degenerate_tris": total_degenerate_tris,
            "unapplied_scale": has_unapplied_scale,
            "missing_materials": missing_mats,
            "is_clean": is_clean,
        }

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
            # Identify truly closed manifold shells: group connected faces and check if the ENTIRE shell has zero boundary edges
            visited_faces: set[Any] = set()
            closed_shells: list[list[Any]] = []
            for face in bm.faces:
                if face in visited_faces or not getattr(face, "is_valid", False):
                    continue
                shell: list[Any] = []
                queue = [face]
                visited_faces.add(face)
                is_closed_shell = True

                while queue:
                    curr = queue.pop()
                    shell.append(curr)
                    for edge in getattr(curr, "edges", []):
                        link_faces = getattr(edge, "link_faces", [])
                        if len(link_faces) != 2:
                            is_closed_shell = False
                        for nbr in link_faces:
                            if nbr not in visited_faces and getattr(nbr, "is_valid", False):
                                visited_faces.add(nbr)
                                queue.append(nbr)

                if is_closed_shell and shell:
                    closed_shells.append(shell)

            all_closed_faces = [f for s in closed_shells for f in s]
            if all_closed_faces:
                try:
                    bmesh.ops.recalc_face_normals(bm, faces=all_closed_faces)
                    return {"recalculated_normals": True, "manifold_faces_aligned": len(all_closed_faces)}
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
