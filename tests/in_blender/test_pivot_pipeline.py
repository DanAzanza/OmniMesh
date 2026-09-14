"""
In-Blender Integration Tests for Pivot Preservation & Socket Reparenting Engine.
Blender 4.2+ and 5.2 LTS Compatible.
"""

from __future__ import annotations

import unittest

try:
    import bpy
    from core.pivot import PivotPreservationEngine
    from mathutils import Matrix, Vector
    from tests.in_blender.fixtures import in_blender_sandbox
except ImportError:
    bpy = None
    PivotPreservationEngine = None  # type: ignore
    Matrix = None  # type: ignore
    Vector = None  # type: ignore
    in_blender_sandbox = None  # type: ignore


class TestPivotPipeline(unittest.TestCase):
    """Verify identification, cloning, and transformation math for root pivots and engine sockets."""

    def setUp(self) -> None:
        if not bpy:
            self.skipTest("Blender bpy runtime not available.")

    def test_identify_pivots_and_sockets(self) -> None:
        """Verify identify_pivots_and_sockets accurately detects empties, meshes, and colliders."""
        with in_blender_sandbox():
            coll = bpy.data.collections.new("Test_Asset_Coll")
            bpy.context.scene.collection.children.link(coll)

            # 1. Pivot empty
            pivot = bpy.data.objects.new("ROOT_Pivot", None)
            coll.objects.link(pivot)

            # 2. Sockets
            sock1 = bpy.data.objects.new("SOCKET_Weapon", None)
            sock2 = bpy.data.objects.new("ATTACH_Muzzle", None)
            coll.objects.link(sock1)
            coll.objects.link(sock2)

            # 3. Visible Mesh
            mesh_data = bpy.data.meshes.new("Body_Mesh")
            mesh_obj = bpy.data.objects.new("SM_Body", mesh_data)
            coll.objects.link(mesh_obj)

            # 4. Collision Hull (should be ignored from meshes)
            coll_data = bpy.data.meshes.new("Collider_Mesh")
            coll_obj = bpy.data.objects.new("UCX_Body_01", coll_data)
            coll_obj["_is_collider"] = True
            coll.objects.link(coll_obj)

            p_obj, sockets, meshes, armatures = PivotPreservationEngine.identify_pivots_and_sockets(coll)

            self.assertEqual(p_obj, pivot, "Root pivot empty must be detected.")
            self.assertEqual(len(sockets), 2, "Both socket empties must be identified.")
            self.assertIn(sock1, sockets)
            self.assertIn(sock2, sockets)
            self.assertEqual(len(meshes), 1, "Only non-collider mesh must be listed.")
            self.assertEqual(meshes[0], mesh_obj)

    def test_clone_pivot_and_reparent_sockets(self) -> None:
        """Verify sockets reparent to cloned pivot in target LOD collection while preserving world matrix."""
        with in_blender_sandbox():
            src_coll = bpy.data.collections.new("SM_Hero")
            tgt_coll = bpy.data.collections.new("SM_Hero_LOD1")
            bpy.context.scene.collection.children.link(src_coll)
            bpy.context.scene.collection.children.link(tgt_coll)

            # Pivot located at (0, 0, 1)
            pivot = bpy.data.objects.new("SM_Hero_Pivot", None)
            pivot.location = Vector((0.0, 0.0, 1.0))
            src_coll.objects.link(pivot)

            # Socket located at (0.5, 1.0, 2.5)
            socket = bpy.data.objects.new("SOCKET_Hand_R", None)
            socket.location = Vector((0.5, 1.0, 2.5))
            src_coll.objects.link(socket)
            bpy.context.view_layer.update()

            # Clone pivot for LOD1
            cloned_pivot = PivotPreservationEngine.clone_pivot_empty(pivot, tgt_coll, tier_idx=1, base_name="SM_Hero")
            self.assertIsNotNone(cloned_pivot)
            self.assertIn(cloned_pivot.name, tgt_coll.objects)
            self.assertTrue(cloned_pivot.get("is_pivot", False))

            # Reparent socket into target collection
            cloned_sockets = PivotPreservationEngine.reparent_sockets_to_pivot([socket], cloned_pivot, tgt_coll)
            self.assertEqual(len(cloned_sockets), 1)
            cs = cloned_sockets[0]

            self.assertIn(cs.name, tgt_coll.objects)
            self.assertEqual(cs.parent, cloned_pivot)

            # Evaluate depsgraph so parent-child hierarchy matrices are updated
            bpy.context.view_layer.update()

            # World location must be preserved identically
            orig_world = socket.matrix_world.translation
            cloned_world = cs.matrix_world.translation
            for i in range(3):
                self.assertAlmostEqual(
                    orig_world[i],
                    cloned_world[i],
                    places=4,
                    msg=f"Socket world translation axis {i} drifted after reparenting.",
                )

    def test_transform_vertex_and_normal_to_pivot_space(self) -> None:
        """Verify mathematical coordinate transformation from mesh local space to offset pivot space."""
        mesh_obj = bpy.data.objects.new("DummyMesh", None)
        mesh_obj.matrix_world = Matrix.Translation(Vector((2.0, 0.0, 0.0)))

        pivot_obj = bpy.data.objects.new("DummyPivot", None)
        pivot_obj.matrix_world = Matrix.Translation(Vector((1.0, 0.0, 0.0)))

        local_vert = Vector((0.0, 1.0, 0.0))
        # local_vert world pos = (2, 1, 0). Pivot world pos = (1, 0, 0).
        # In pivot space, pos should be (1, 1, 0).
        pivot_vert = PivotPreservationEngine.transform_vertex_to_pivot_space(local_vert, mesh_obj, pivot_obj)
        self.assertAlmostEqual(pivot_vert.x, 1.0, places=4)
        self.assertAlmostEqual(pivot_vert.y, 1.0, places=4)
        self.assertAlmostEqual(pivot_vert.z, 0.0, places=4)

        # Normals are purely rotational and should remain unchanged under pure translation
        normal = Vector((0.0, 0.0, 1.0))
        pivot_norm = PivotPreservationEngine.transform_normal_to_pivot_space(normal, mesh_obj, pivot_obj)
        self.assertAlmostEqual(pivot_norm.z, 1.0, places=4)
