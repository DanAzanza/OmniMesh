"""
In-Blender Integration Tests for Decimation, Boundary Tagging & Planar Dissolve.
Blender 4.2+ and 5.2 LTS Compatible.
"""

from __future__ import annotations

import math
import unittest

try:
    import bmesh
    import bpy
    from core.decimator import MeshDecimator
    from tests.in_blender.fixtures import in_blender_sandbox
except ImportError:
    bmesh = None  # type: ignore
    bpy = None
    MeshDecimator = None  # type: ignore
    in_blender_sandbox = None  # type: ignore


class TestDecimatorPipeline(unittest.TestCase):
    """Verify topological boundary preservation, curvature weighting, and QEM edge collapse."""

    def setUp(self) -> None:
        if not bpy or not bmesh:
            self.skipTest("Blender bpy/bmesh runtime not available.")

    def test_tag_boundaries_and_uv_seams(self) -> None:
        """Verify open boundaries and marked sharp edges are strictly pinned by MeshDecimator."""
        bm = bmesh.new()
        # Create 3x3 grid plane (9 faces, 16 verts, open boundary edges)
        bmesh.ops.create_grid(bm, x_segments=3, y_segments=3, size=1.0)
        bm.verts.ensure_lookup_table()
        bm.edges.ensure_lookup_table()

        # Mark an interior edge as sharp
        interior_edges = [e for e in bm.edges if len(e.link_faces) == 2]
        self.assertGreater(len(interior_edges), 0)
        interior_edge = interior_edges[0]
        interior_edge.smooth = False

        pinned = MeshDecimator.tag_boundaries_and_uv_seams(
            bm, pin_uv_seams=True, pin_material_borders=True, pin_sharp_edges=True
        )

        # Boundary vertices must be in pinned set
        boundary_verts = {v.index for v in bm.verts if v.is_boundary}
        self.assertTrue(boundary_verts.issubset(pinned), "All boundary vertices must be pinned.")

        # Marked interior edge vertices must also be pinned
        for v in interior_edge.verts:
            self.assertIn(v.index, pinned, "Sharp interior edge vertex must be pinned.")

        bm.free()

    def test_inject_curvature_weights_and_qem_decimate(self) -> None:
        """Verify curvature weight injection populates vertex group and guides QEM decimation."""
        with in_blender_sandbox() as scene:
            bm = bmesh.new()
            # Dense UV sphere (32 segments, 16 rings)
            bmesh.ops.create_uvsphere(bm, u_segments=32, v_segments=16, radius=1.0)
            bmesh.ops.triangulate(bm, faces=bm.faces[:])
            mesh_data = bpy.data.meshes.new("DenseSphere_Mesh")
            bm.to_mesh(mesh_data)

            obj = bpy.data.objects.new("SM_DenseSphere", mesh_data)
            scene.collection.objects.link(obj)
            scene.view_layers[0].objects.active = obj
            obj.select_set(True)

            initial_poly_count = len(mesh_data.polygons)
            self.assertGreater(initial_poly_count, 100)

            pinned = {0, 1, 2, 3}  # Pin pole vertices
            MeshDecimator.inject_curvature_weights(obj, bm, pinned, group_name="OmniMesh_Protection")
            bm.free()

            # Vertex group must exist
            self.assertIn("OmniMesh_Protection", obj.vertex_groups)

            # Decimate by 50%
            MeshDecimator.execute_decimate_qem(
                obj,
                target_ratio=0.5,
                use_curvature_weight=True,
                group_name="OmniMesh_Protection",
                cleanup_group=False,
            )

            final_poly_count = len(obj.data.polygons)
            self.assertLess(final_poly_count, initial_poly_count, "Polygon count must be reduced after decimation.")
            # Should be roughly half
            self.assertLessEqual(final_poly_count, int(initial_poly_count * 0.7))

    def test_apply_planar_limited_dissolve(self) -> None:
        """Verify coplanar faces collapse without collapsing sharp angle borders."""
        bm = bmesh.new()
        # Create subdivided 4x4 grid plane (16 coplanar faces)
        bmesh.ops.create_grid(bm, x_segments=4, y_segments=4, size=2.0)
        self.assertEqual(len(bm.faces), 16)

        MeshDecimator.apply_planar_limited_dissolve(bm, angle_limit_rad=math.radians(5.0))
        # Dissolve should collapse coplanar faces into a single face
        self.assertEqual(len(bm.faces), 1, "Coplanar flat grid should dissolve down to 1 face.")
        bm.free()
