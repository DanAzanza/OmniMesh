"""
OmniMesh LOD Polygon & Metric Statistics.
Provides O(1) triangle counting and baseline LOD0 statistics.
"""

from __future__ import annotations

from collections.abc import Iterable, Sized
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    import bmesh
    import bpy
else:
    try:
        import bmesh
        import bpy
    except ImportError:
        bmesh = None
        bpy = None

from .compat import count_mesh_triangles
from .modifiers import ModifierManager


@runtime_checkable
class _PolyWithVertices(Protocol):
    vertices: Sized


@runtime_checkable
class _FaceWithVerts(Protocol):
    verts: Sized


@runtime_checkable
class _MeshWithPolygons(Protocol):
    polygons: object


@runtime_checkable
class _MeshWithLoops(Protocol):
    loops: object


@runtime_checkable
class _BMeshWithFaces(Protocol):
    faces: object


def _count_triangles(mesh_data: object) -> int:
    """Computes true triangle count in O(1) via loop-poly invariant with safe fallback."""
    if not mesh_data:
        return 0
    if bpy is not None and isinstance(mesh_data, bpy.types.Mesh):
        return count_mesh_triangles(mesh_data)
    if bmesh is not None and isinstance(mesh_data, bmesh.types.BMesh):
        return sum(max(0, len(f.verts) - 2) for f in mesh_data.faces)
    if isinstance(mesh_data, _MeshWithPolygons):
        polys = mesh_data.polygons
        loops = mesh_data.loops if isinstance(mesh_data, _MeshWithLoops) else None
        if isinstance(loops, Sized) and isinstance(polys, Sized):
            n_loops = len(loops)
            n_polys = len(polys)
            return max(0, n_loops - 2 * n_polys) if n_polys > 0 else 0
        if isinstance(polys, Iterable):
            return sum(max(0, len(p.vertices) - 2) for p in polys if isinstance(p, _PolyWithVertices))
    if isinstance(mesh_data, _BMeshWithFaces):
        faces = mesh_data.faces
        if isinstance(faces, Iterable):
            return sum(max(0, len(f.verts) - 2) if isinstance(f, _FaceWithVerts) else 1 for f in faces)
        if isinstance(faces, Sized):
            return len(faces)
    return 0


def _compute_lod0_stats(mesh_objs: list[bpy.types.Object]) -> tuple[int, int]:
    """Calculates initial triangle count and material slot count for LOD0."""
    tier_tris = 0
    tier_mats = sum(len(obj.material_slots) for obj in mesh_objs)
    for obj in mesh_objs:
        if ModifierManager.has_unapplied_modifiers(obj):
            eval_mesh, eval_obj = ModifierManager.get_evaluated_mesh(obj, preserve_armature=True)
            if eval_mesh:
                try:
                    tier_tris += _count_triangles(eval_mesh)
                finally:
                    if eval_obj:
                        eval_obj.to_mesh_clear()
            else:
                tier_tris += _count_triangles(obj.data)
        else:
            tier_tris += _count_triangles(obj.data)
    return tier_tris, tier_mats


__all__ = [
    "_count_triangles",
    "_compute_lod0_stats",
]
