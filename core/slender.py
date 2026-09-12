"""
OmniMesh Unified Sub-Pixel & Slender Feature Culler.
Architected for Blender 4.2+ LTS & Blender 5.2 LTS.
Features:
- Pure Screen-Space Error (SSE) Bound Coupling: 100% physically and geometrically grounded.
- Unified Sub-Pixel Geometry Culling:
  * Case A (Compact Micro-Parts): Culls islands with bounding extent d_max <= delta_world.
  * Case B (Slender Thin Features): Culls cables, railings, wires with hydraulic thickness t <= delta_world and AR >= 4.0.
- Hydraulic Caliper: Volume-to-surface invariant thickness (t = 4V / A) for curved cables, railings, and spiral wires without PCA axis distortions.
- Robust Silhouette Protection: Protects major load-bearing structural bodies while ensuring sub-pixel wires and micro-islands are cleanly eliminated.
"""

from __future__ import annotations

import logging
import math
from typing import Any

logger = logging.getLogger(__name__)

try:
    import bmesh
    import bpy
except ImportError:
    bpy = None
    bmesh = None


class SlenderFeatureCuller:
    """
    Detects and culls sub-pixel small parts and slender geometry
    strictly using the LOD tier's Screen-Space Error (SSE) tolerance bound.
    """

    MIN_ASPECT_RATIO = 4.0  # Length-to-thickness ratio for slender rods/wires

    @staticmethod
    def compute_hydraulic_thickness(volume: float, surface_area: float) -> float:
        """
        Computes the hydraulic cross-sectional thickness:
        t = 4 * V / A
        For a cylinder of radius r: V = pi*r^2*L, A = 2*pi*r*L => 4*V/A = 2*r = Diameter.
        Invariant on curved, sagging (catenary), or spiral trajectories.
        """
        if surface_area <= 1e-9:
            return 0.0
        return (4.0 * abs(volume)) / surface_area

    @staticmethod
    def compute_slenderness_aspect_ratio(surface_area: float, volume: float, max_dim: float = 0.0) -> float:
        """
        Computes the topological slenderness aspect ratio (Length / Diameter).
        If max_dim is provided: AR = max_dim / t_hydro.
        Dimensionless hydraulic cylinder formula: AR = A^3 / (16 * pi * V^2).
        """
        abs_vol = abs(volume)
        if abs_vol <= 1e-9 or surface_area <= 1e-9:
            return 0.0
        if max_dim > 0.0:
            t_hydro = (4.0 * abs_vol) / surface_area
            return max_dim / max(1e-6, t_hydro)
        return (surface_area**3) / (16.0 * math.pi * (abs_vol**2))

    @staticmethod
    def compute_screen_projected_thickness(
        thickness_m: float, screen_size_pct: float, resolution_y: int, root_radius_m: float
    ) -> float:
        """
        Computes the projected thickness in screen pixels:
        w_proj (px) = t * ((S_i / 100) * R_y / (2 * R_root))
        """
        if root_radius_m <= 1e-7:
            return 999.0
        s_frac = max(0.0001, screen_size_pct / 100.0)
        return thickness_m * (s_frac * resolution_y) / (2.0 * root_radius_m)

    @staticmethod
    def compute_world_tolerance(
        tau_sse: float, screen_size_pct: float, resolution_y: int = 1080, root_radius_m: float = 1.0
    ) -> float:
        """
        Computes maximum allowable world-space thickness below which an element is sub-pixel:
        delta_world = (2 * tau_frac * R_root) / S_frac

        If tau_sse >= 0.4, it is treated as legacy pixel tolerance:
        delta_world = (tau_sse * 2 * R_root) / (S_frac * resolution_y)
        """
        s_frac = max(0.0001, screen_size_pct / 100.0)
        if s_frac <= 0 or root_radius_m <= 0:
            return 0.0

        if tau_sse >= 0.4 and resolution_y > 0:
            tau_frac = tau_sse / float(resolution_y)
        else:
            tau_frac = max(0.0001, tau_sse / 100.0)

        return (tau_frac * 2.0 * root_radius_m) / s_frac

    @classmethod
    def analyze_island_geometry(cls, face_group: list[Any]) -> dict[str, float]:
        """
        Analyzes a connected face island's volume, area, bounding extents, and slenderness.
        """
        if not face_group:
            return {"thickness": 0.0, "aspect_ratio": 0.0, "volume": 0.0, "area": 0.0, "max_dim": 0.0}

        total_area = 0.0
        signed_volume = 0.0

        min_co = [float("inf"), float("inf"), float("inf")]
        max_co = [float("-inf"), float("-inf"), float("-inf")]

        for f in face_group:
            area = getattr(f, "calc_area", lambda: 0.0)()
            total_area += area

            # Signed volume contribution from face tetrahedra
            verts = getattr(f, "verts", [])
            if len(verts) >= 3:
                v0 = verts[0].co
                for i in range(1, len(verts) - 1):
                    v1 = verts[i].co
                    v2 = verts[i + 1].co
                    # 1/6 * v0 . (v1 x v2)
                    c_x = v1[1] * v2[2] - v1[2] * v2[1]
                    c_y = v1[2] * v2[0] - v1[0] * v2[2]
                    c_z = v1[0] * v2[1] - v1[1] * v2[0]
                    vol = (1.0 / 6.0) * (v0[0] * c_x + v0[1] * c_y + v0[2] * c_z)
                    signed_volume += vol

            for v in verts:
                co = v.co
                for axis in range(3):
                    if co[axis] < min_co[axis]:
                        min_co[axis] = co[axis]
                    if co[axis] > max_co[axis]:
                        max_co[axis] = co[axis]

        dx = max(0.0, max_co[0] - min_co[0])
        dy = max(0.0, max_co[1] - min_co[1])
        dz = max(0.0, max_co[2] - min_co[2])
        dims = sorted([dx, dy, dz])
        max_dim = dims[2]
        min_dim = dims[0]
        mid_dim = dims[1]

        abs_vol = abs(signed_volume)

        # Closed volume (tube/cylinder): use hydraulic caliper
        if abs_vol > 1e-8 and total_area > 1e-8:
            t_hydro = cls.compute_hydraulic_thickness(abs_vol, total_area)
            ar_hydro = cls.compute_slenderness_aspect_ratio(total_area, abs_vol, max_dim=max_dim)
            if t_hydro > 0 and ar_hydro > 0:
                return {
                    "thickness": t_hydro,
                    "aspect_ratio": ar_hydro,
                    "volume": abs_vol,
                    "area": total_area,
                    "max_dim": max_dim,
                }

        # Open ribbon / flat sheet fallback: use bounding extents
        t_obb = min(mid_dim, max(1e-6, min_dim))
        ar_obb = max_dim / max(1e-6, t_obb)
        return {
            "thickness": t_obb,
            "aspect_ratio": ar_obb,
            "volume": abs_vol,
            "area": total_area,
            "max_dim": max_dim,
        }

    @classmethod
    def cull_slender_features(
        cls,
        bm: Any,
        screen_size_pct: float,
        resolution_y: int = 1080,
        root_radius_m: float = 1.0,
        tau_sse: float = 0.08,
        protect_silhouettes: bool = False,
    ) -> dict[str, int]:
        """
        Identifies and removes all sub-pixel small parts and slender face islands from BMesh.
        - Case A (Compact Micro-Parts): max_dim <= delta_world
        - Case B (Slender Thin Features): thickness <= delta_world AND aspect_ratio >= MIN_ASPECT_RATIO
        Returns: {"culled_islands": int, "culled_faces": int}
        """
        if not bm or not hasattr(bm, "faces") or len(bm.faces) == 0:
            return {"culled_islands": 0, "culled_faces": 0}

        delta_world = cls.compute_world_tolerance(
            tau_sse=tau_sse,
            screen_size_pct=screen_size_pct,
            resolution_y=resolution_y,
            root_radius_m=root_radius_m,
        )

        # 1. Extract connected face islands
        visited_faces: set[Any] = set()
        islands: list[list[Any]] = []

        for f in bm.faces:
            if f in visited_faces:
                continue

            island: list[Any] = []
            queue = [f]
            visited_faces.add(f)

            while queue:
                curr = queue.pop()
                island.append(curr)

                for edge in curr.edges:
                    for neighbor in edge.link_faces:
                        if neighbor not in visited_faces:
                            visited_faces.add(neighbor)
                            queue.append(neighbor)

            islands.append(island)

        # 2. Evaluate and cull sub-pixel small parts and slender islands
        culled_faces: list[Any] = []
        culled_islands_count = 0

        for island in islands:
            analysis = cls.analyze_island_geometry(island)
            thickness = analysis["thickness"]
            aspect_ratio = analysis["aspect_ratio"]
            max_dim = analysis["max_dim"]

            # Culling conditions:
            # 1. Small compact sub-pixel part (bolts, screws, micro-debris): max_dim <= delta_world
            is_small_part = max_dim <= delta_world and max_dim > 0

            # 2. Slender thin feature (cables, wires, railings): thickness <= delta_world AND aspect_ratio >= MIN_ASPECT_RATIO
            is_slender_wire = thickness <= delta_world and aspect_ratio >= cls.MIN_ASPECT_RATIO and thickness > 0

            if is_slender_wire and protect_silhouettes:
                has_silhouette_boundary = any(
                    getattr(e, "is_boundary", False) for f in island for e in getattr(f, "edges", [])
                )
                if has_silhouette_boundary:
                    is_slender_wire = False

            if is_small_part or is_slender_wire:
                culled_faces.extend(island)
                culled_islands_count += 1

        # 3. Clean face deletion with total extinction protection
        if culled_faces and bmesh:
            if len(culled_faces) == len(bm.faces) and islands:
                # Protect against wiping out the entire mesh (which causes 0 polygons and fails export checks)
                largest_island = max(
                    islands,
                    key=lambda isl: sum(getattr(f, "calc_area", lambda: 0.0)() for f in isl),
                )
                safe_to_cull = [f for f in culled_faces if f not in set(largest_island)]
                culled_islands_count = max(0, culled_islands_count - 1)
                culled_faces = safe_to_cull

            if culled_faces:
                bmesh.ops.delete(bm, geom=culled_faces, context="FACES")
                try:
                    from .sanitizer import MeshSanitizer

                    MeshSanitizer.clean_loose_and_degenerates(bm)
                except Exception as exc:
                    logger.debug("Clean loose after slender culling skipped: %s", exc)

        return {"culled_islands": culled_islands_count, "culled_faces": len(culled_faces)}
