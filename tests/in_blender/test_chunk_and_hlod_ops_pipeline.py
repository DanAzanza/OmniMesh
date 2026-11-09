"""In-Blender Integration Tests for Spatial Chunking, Octree Slicing, and Recursive HLOD Pipelines."""

from __future__ import annotations

import logging
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

try:
    from core.chunking import MeshChunkSlicer, SpatialGridSpec
    from core.recursive_hlod import RecursiveHLODManager
except (ImportError, ValueError):
    from ...core.chunking import MeshChunkSlicer, SpatialGridSpec
    from ...core.recursive_hlod import RecursiveHLODManager


class TestChunkAndHLODOpsPipeline(unittest.TestCase):
    """Verify spatial chunk slicing, cell clustering, recursive HLOD tree creation, and voxel remeshing."""

    def setUp(self) -> None:
        if not bpy:
            self.skipTest("Blender bpy runtime not available.")

    def test_spatial_chunk_and_generate_operator(self) -> None:
        """Verify lod_tool.spatial_chunk_and_generate creates partitioned chunks and decimation tiers."""
        with in_blender_sandbox() as scene:
            if scene is None or bpy is None:
                return

            mesh_objs = create_hierarchy_fixture("CityBlock")
            for obj in mesh_objs:
                obj.select_set(True)
            bpy.context.view_layer.objects.active = mesh_objs[0]

            props = getattr(scene, "lod_tool", None)
            self.assertIsNotNone(props)
            if props:
                props.is_configured = True
                props.chunk_cell_size = 0.5
                props.chunk_partitioning_mode = "UNIFORM_GRID"
                props.adaptive_cluster_target_polys = 1000

                # Ensure at least 2 LOD tiers exist
                if len(props.lods) < 2:
                    t0 = props.lods.add()
                    t0.tier_index = 0
                    t0.target_tris_pct = 100.0
                    t1 = props.lods.add()
                    t1.tier_index = 1
                    t1.target_tris_pct = 50.0

            ops: Any = cast(Any, bpy.ops).lod_tool
            res = ops.spatial_chunk_and_generate()
            self.assertEqual(res, {"FINISHED"})

            # Verify chunk collections created
            chunk_collections = [c for c in bpy.data.collections if "Chunks" in c.name]
            self.assertGreater(len(chunk_collections), 0)

    def test_mesh_chunk_slicer_and_grid_spec_direct(self) -> None:
        """Verify direct MeshChunkSlicer bounding extraction, cell index computation, and cluster grouping."""
        with in_blender_sandbox() as scene:
            if scene is None or bpy is None:
                return

            mesh_objs = create_hierarchy_fixture("TerrainSegment")
            source_obj = mesh_objs[0]

            grid_spec = SpatialGridSpec.from_object(source_obj, cell_size_meters=0.5)
            self.assertGreater(grid_spec.num_cells_x, 0)
            self.assertGreater(grid_spec.num_cells_y, 0)
            self.assertGreater(grid_spec.num_cells_z, 0)

            # Test cell coordinate lookup
            cell_idx = grid_spec.get_cell_index((0.0, 0.0, 0.0))
            self.assertIsInstance(cell_idx, tuple)
            self.assertEqual(len(cell_idx), 3)

            parent_idx = grid_spec.get_parent_cluster_index(cell_idx[0], cell_idx[1], cell_idx[2], stride=2)
            self.assertEqual(len(parent_idx), 3)

            # Partition mesh directly
            target_col = bpy.data.collections.new("Test_Direct_Chunks")
            scene.collection.children.link(target_col)

            chunks = MeshChunkSlicer.slice_and_partition(
                source_obj=source_obj,
                grid_spec=grid_spec,
                base_name="TerrainChunk",
                target_collection=target_col,
                partitioning_mode="UNIFORM_GRID",
                target_cluster_polys=500,
                blend_data=bpy.data,
            )
            self.assertIsInstance(chunks, list)
            self.assertGreaterEqual(len(chunks), 1)

    def test_recursive_hlod_tier_assembly_and_proxy_shell(self) -> None:
        """Verify RecursiveHLODManager quadtree grouping, tier decimation, and voxel proxy shell."""
        with in_blender_sandbox() as scene:
            if scene is None or bpy is None:
                return

            mesh_objs = create_hierarchy_fixture("HLODSource")
            source_obj = mesh_objs[0]

            grid_spec = SpatialGridSpec.from_object(source_obj, cell_size_meters=0.8)
            target_col = bpy.data.collections.new("HLOD_LOD0")
            scene.collection.children.link(target_col)

            chunks = MeshChunkSlicer.slice_and_partition(
                source_obj=source_obj,
                grid_spec=grid_spec,
                base_name="HLODBlock",
                target_collection=target_col,
                partitioning_mode="UNIFORM_GRID",
                target_cluster_polys=500,
                blend_data=bpy.data,
            )
            self.assertGreaterEqual(len(chunks), 1)

            # Group chunks into quadtree / octree clusters
            clusters = RecursiveHLODManager.group_chunks_quadtree(chunks, stride=2)
            self.assertIsInstance(clusters, dict)

            # Build recursive hierarchical tier (e.g. LOD2 / HLOD)
            hlod_col = bpy.data.collections.new("HLOD_LOD2")
            scene.collection.children.link(hlod_col)

            hlod_nodes = RecursiveHLODManager.build_hierarchical_tier(
                parent_clusters=clusters,
                base_name="HLODBlock",
                tier_index=2,
                target_collection=hlod_col,
                target_ratio=0.2,
                context=bpy.context,
                blend_data=bpy.data,
            )
            self.assertIsInstance(hlod_nodes, list)
            self.assertGreaterEqual(len(hlod_nodes), 1)

            # Test applying voxel proxy shell on the first cluster mesh
            if hlod_nodes:
                shell_applied = RecursiveHLODManager.apply_voxel_proxy_shell(
                    obj=hlod_nodes[0],
                    voxel_size_m=0.1,
                    context=bpy.context,
                    blend_data=bpy.data,
                )
                self.assertTrue(shell_applied)

    def test_voxel_scan_cleanup_operator(self) -> None:
        """Verify lod_tool.voxel_scan_cleanup reconstructs noisy/complex surface geometry."""
        with in_blender_sandbox() as scene:
            if scene is None or bpy is None:
                return

            mesh_objs = create_hierarchy_fixture("NoisyScan")
            scan_obj = mesh_objs[0]
            for o in scene.objects:
                o.select_set(False)
            scan_obj.select_set(True)
            bpy.context.view_layer.objects.active = scan_obj

            props = getattr(scene, "lod_tool", None)
            if props:
                props.scan_remesh_voxel_size = 0.08

            ops: Any = cast(Any, bpy.ops).lod_tool
            res = ops.voxel_scan_cleanup()
            self.assertEqual(res, {"FINISHED"})

    def test_chunking_and_cleanup_negative_boundaries(self) -> None:
        """Verify graceful error reporting when running operators without valid mesh selection."""
        with in_blender_sandbox() as scene:
            if scene is None or bpy is None:
                return

            # Slicing empty list directly
            grid_spec = SpatialGridSpec(
                min_corner=(0.0, 0.0, 0.0),
                max_corner=(1.0, 1.0, 1.0),
                cell_size_x=1.0,
                cell_size_y=1.0,
                cell_size_z=1.0,
                num_cells_x=1,
                num_cells_y=1,
                num_cells_z=1,
            )
            empty_col = bpy.data.collections.new("Empty_Col")
            scene.collection.children.link(empty_col)

            empty_chunks = MeshChunkSlicer.slice_and_partition(
                source_obj=None,
                grid_spec=grid_spec,
                base_name="Empty",
                target_collection=empty_col,
                blend_data=bpy.data,
            )
            self.assertEqual(empty_chunks, [])

            # 2. Quadtree grouping on empty objects
            clusters = RecursiveHLODManager.group_chunks_quadtree([])
            self.assertEqual(clusters, {})


if __name__ == "__main__":
    unittest.main()
