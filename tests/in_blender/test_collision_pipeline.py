"""
In-Blender Integration Tests for Convex Hull Collision Decomposition & Management.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import unittest

if TYPE_CHECKING:
    import bpy
    from tests.in_blender.fixtures import create_hierarchy_fixture, in_blender_sandbox
else:
    try:
        import bpy
        from tests.in_blender.fixtures import create_hierarchy_fixture, in_blender_sandbox
    except ImportError:
        bpy = None
        create_hierarchy_fixture = None  # type: ignore
        in_blender_sandbox = None  # type: ignore


class TestCollisionPipeline(unittest.TestCase):
    """Verify multi-convex collision hull generation, engine naming, and removal."""

    def setUp(self) -> None:
        if not bpy:
            self.skipTest("Blender bpy runtime not available.")

    def test_generate_collision_hulls_per_object(self) -> None:
        """Verify PER_OBJECT collision decomposition produces valid wireframe convex hulls."""
        with in_blender_sandbox() as scene:
            if scene is None or bpy is None:
                return
            mesh_objs = create_hierarchy_fixture("SM_CollAsset")
            for obj in mesh_objs:
                obj.select_set(True)
            scene.view_layers[0].objects.active = mesh_objs[0]

            props: Any = getattr(scene, "lod_tool", None)
            if props is None:
                return
            props.export_base_name = "SM_CollAsset"
            props.target_engine = "UE5"
            props.collision_decomposition_mode = "PER_OBJECT"
            props.collision_hull_count = 2

            ops: Any = cast(Any, bpy.ops).lod_tool
            res = ops.generate_collision_hulls()
            self.assertEqual(res, {"FINISHED"})

            # Verify collision collection was created
            coll_name = "SM_CollAsset_Colliders"
            target_coll = bpy.data.collections.get(coll_name)
            self.assertIsNotNone(target_coll, f"Collection '{coll_name}' must exist.")
            if target_coll is None:
                return

            # Verify generated collider objects
            collider_objs = list(target_coll.objects)
            self.assertGreater(len(collider_objs), 0, "At least one collider must be generated.")

            for c_obj in collider_objs:
                self.assertTrue(
                    c_obj.name.startswith("UCX_"), f"UE5 collider name should start with UCX_: {c_obj.name}"
                )
                self.assertTrue(c_obj.get("_is_collider", False), "Collider must have _is_collider tag.")
                self.assertEqual(c_obj.display_type, "WIRE", "Collider display_type must be WIRE.")
                self.assertTrue(c_obj.show_wire, "Collider show_wire must be True.")
                self.assertTrue(c_obj.hide_render, "Collider hide_render must be True.")
                c_data: Any = c_obj.data
                self.assertGreater(len(c_data.vertices), 3, "Convex hull must have at least 4 vertices.")
                self.assertGreater(len(c_data.polygons), 3, "Convex hull must have at least 4 faces.")

    def test_generate_collision_hulls_consolidated(self) -> None:
        """Verify CONSOLIDATED collision decomposition creates unified assembly hulls."""
        with in_blender_sandbox() as scene:
            if scene is None or bpy is None:
                return
            mesh_objs = create_hierarchy_fixture("SM_ConsolAsset")
            for obj in mesh_objs:
                obj.select_set(True)
            scene.view_layers[0].objects.active = mesh_objs[0]

            props: Any = getattr(scene, "lod_tool", None)
            if props is None:
                return
            props.export_base_name = "SM_ConsolAsset"
            props.collision_decomposition_mode = "CONSOLIDATED"
            props.collision_hull_count = 2

            ops: Any = cast(Any, bpy.ops).lod_tool
            res = ops.generate_collision_hulls()
            self.assertEqual(res, {"FINISHED"})

            coll_name = "SM_ConsolAsset_Colliders"
            target_coll = bpy.data.collections.get(coll_name)
            self.assertIsNotNone(target_coll, f"Collection '{coll_name}' must exist.")
            if target_coll is None:
                return

            collider_objs = list(target_coll.objects)
            self.assertGreater(len(collider_objs), 0, "Consolidated colliders must be generated.")
            for c_obj in collider_objs:
                self.assertTrue(c_obj.get("_is_collider", False))
                c_data: Any = c_obj.data
                self.assertGreater(len(c_data.vertices), 3)

    def test_remove_collision_hulls(self) -> None:
        """Verify remove_collision_hulls cleanly purges all collider objects and meshes."""
        with in_blender_sandbox() as scene:
            if scene is None or bpy is None:
                return
            mesh_objs = create_hierarchy_fixture("SM_PurgeAsset")
            for obj in mesh_objs:
                obj.select_set(True)
            scene.view_layers[0].objects.active = mesh_objs[0]

            props: Any = getattr(scene, "lod_tool", None)
            if props is None:
                return
            props.export_base_name = "SM_PurgeAsset"

            ops: Any = cast(Any, bpy.ops).lod_tool
            ops.generate_collision_hulls()
            target_coll = bpy.data.collections.get("SM_PurgeAsset_Colliders")
            self.assertIsNotNone(target_coll)
            if target_coll is None:
                return
            self.assertGreater(len(target_coll.objects), 0)

            # Purge
            res = ops.remove_collision_hulls()
            self.assertEqual(res, {"FINISHED"})
            self.assertEqual(len(target_coll.objects), 0, "All collider objects must be unlinked.")
            self.assertEqual(props.last_generated_collider_count, 0)
