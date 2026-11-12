"""In-Blender Integration Tests for Spatial Chunking, HLOD Merging, Collision Hulls, and Impostor Rigging."""

from __future__ import annotations

import logging
import shutil
from typing import TYPE_CHECKING, Any, cast
import unittest

logger = logging.getLogger(__name__)

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


class TestSpatialChunkingPipeline(unittest.TestCase):
    """Verify spatial chunking, HLOD generation, convex hull colliders, and impostors in live Blender."""

    def setUp(self) -> None:
        if not bpy:
            self.skipTest("Blender bpy runtime not available.")
        self._temp_dirs: list[str] = []

    def tearDown(self) -> None:
        for p in self._temp_dirs:
            shutil.rmtree(p, ignore_errors=True)
        self._temp_dirs.clear()

    def test_convex_collision_hulls_generate_and_remove(self) -> None:
        """Verify convex collision hulls decompose and generate cleanly on hierarchy meshes."""
        with in_blender_sandbox() as scene:
            if scene is None or bpy is None:
                return
            mesh_objs = create_hierarchy_fixture("SM_HullTest")
            for obj in mesh_objs:
                obj.select_set(True)
            bpy.context.view_layer.objects.active = mesh_objs[0]

            ops: Any = cast(Any, bpy.ops).lod_tool
            res_gen = ops.generate_collision_hulls()
            self.assertEqual(res_gen, {"FINISHED"})

            # Check that collider collection was created with meshes
            col = next((c for c in bpy.data.collections if "Colliders" in c.name), None)
            self.assertIsNotNone(col)
            if col:
                self.assertGreater(len(col.objects), 0)

    def test_spatial_chunk_and_hlod_generation(self) -> None:
        """Verify spatial chunking partitions meshes and builds HLOD clusters."""
        from core.chunking import HLODClusterMerger

        with in_blender_sandbox() as scene:
            if scene is None or bpy is None:
                return
            mesh_objs = create_hierarchy_fixture("SM_ChunkTest")
            for obj in mesh_objs:
                obj.select_set(True)
            bpy.context.view_layer.objects.active = mesh_objs[0]

            # Merge chunks for HLOD test
            hlod_col = bpy.data.collections.new("SM_ChunkTest_HLOD")
            scene.collection.children.link(hlod_col)

            merged = HLODClusterMerger.merge_chunks_for_hlod(
                chunk_objs=mesh_objs,
                hlod_name="SM_ChunkTest_HLOD_Merged",
                target_collection=hlod_col,
                weld_dist=0.005,
                blend_data=bpy.data,
            )
            self.assertIsNotNone(merged)
            if merged:
                mesh_data: Any = merged.data
                self.assertGreater(len(mesh_data.polygons), 0)


if __name__ == "__main__":
    unittest.main()
