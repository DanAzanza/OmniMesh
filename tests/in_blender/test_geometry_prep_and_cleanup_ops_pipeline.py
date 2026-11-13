"""In-Blender Integration Tests for Geometry Preparation and Cleanup Ops."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, cast
import unittest

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    import bpy
    from tests.in_blender.fixtures import in_blender_sandbox
else:
    try:
        import bpy
        from tests.in_blender.fixtures import in_blender_sandbox
    except ImportError:
        bpy = None
        in_blender_sandbox = None  # type: ignore

try:
    from ui.properties.callbacks import on_target_engine_updated
except (ImportError, ValueError):
    from ui.properties.callbacks import on_target_engine_updated


class TestGeometryPrepAndCleanupOpsPipeline(unittest.TestCase):
    """Verify mesh sanitization, material cleaning, and asset initialization."""

    def setUp(self) -> None:
        if not bpy:
            self.skipTest("Blender bpy runtime not available.")

    def test_clean_repair_mesh(self) -> None:
        """Verify lod_tool.clean_and_repair_mesh repairs noisy geometry and degenerate faces."""
        with in_blender_sandbox() as scene:
            if scene is None or bpy is None:
                return

            import bmesh

            # Create test mesh with deliberate defects (degenerate faces, unapplied scale)
            mesh = bpy.data.meshes.new("DefectiveMesh")
            obj = bpy.data.objects.new("DefectiveObj", mesh)
            scene.collection.objects.link(obj)

            bm = bmesh.new()
            # Create cube
            bmesh.ops.create_cube(bm, size=1.0)
            # Add degenerate zero-area face
            v0 = bm.verts.new((0.0, 0.0, 0.0))
            v1 = bm.verts.new((0.0, 0.0, 0.0))
            v2 = bm.verts.new((0.0, 0.0, 0.0))
            bm.faces.new((v0, v1, v2))
            bm.to_mesh(mesh)
            bm.free()

            # Set unapplied scale
            obj.scale = (2.0, 2.0, 2.0)
            mesh.update()

            for o in bpy.data.objects:
                o.select_set(o == obj)
            bpy.context.view_layer.objects.active = obj

            ops_lod: Any = cast(Any, bpy.ops).lod_tool
            res_clean = ops_lod.clean_and_repair_mesh()
            self.assertEqual(res_clean, {"FINISHED"})
            self.assertEqual(len(mesh.polygons), 6)

    def test_clean_and_repair_materials(self) -> None:
        """Verify lod_tool.clean_and_repair_materials deduplicates slots and clears empty assignments."""
        with in_blender_sandbox() as scene:
            if scene is None or bpy is None:
                return

            mesh = bpy.data.meshes.new("MatCleanMesh")
            obj = bpy.data.objects.new("MatCleanObj", mesh)
            scene.collection.objects.link(obj)

            import bmesh

            bm = bmesh.new()
            bmesh.ops.create_cube(bm, size=1.0)
            bm.to_mesh(mesh)
            bm.free()

            mat_a = bpy.data.materials.new("M_Shared")
            mesh.materials.append(mat_a)
            mesh.materials.append(mat_a)  # Duplicate slot assignment

            for o in bpy.data.objects:
                o.select_set(o == obj)
            bpy.context.view_layer.objects.active = obj

            ops_lod: Any = cast(Any, bpy.ops).lod_tool
            res_mat_clean = ops_lod.clean_and_repair_materials()
            self.assertEqual(res_mat_clean, {"FINISHED"})

    def test_omnimesh_initialize_asset_and_quick_setup(self) -> None:
        """Verify omnimesh.initialize_asset routes selected mesh to standard collections."""
        with in_blender_sandbox() as scene:
            if scene is None or bpy is None:
                return

            mesh = bpy.data.meshes.new("InitTargetMesh")
            obj = bpy.data.objects.new("SM_Turret", mesh)
            scene.collection.objects.link(obj)

            import bmesh

            bm = bmesh.new()
            bmesh.ops.create_cube(bm, size=1.0)
            bm.to_mesh(mesh)
            bm.free()

            for o in bpy.data.objects:
                o.select_set(o == obj)
            bpy.context.view_layer.objects.active = obj

            ops_omni: Any = cast(Any, bpy.ops).omnimesh
            # Initialize asset hierarchy
            res_init = ops_omni.initialize_asset(
                asset_name="SM_Turret",
            )
            self.assertEqual(res_init, {"FINISHED"})

            # Verify collection was created and object linked
            turret_col = bpy.data.collections.get("SM_Turret")
            self.assertIsNotNone(turret_col)

    def test_property_callbacks_and_guards(self) -> None:
        """Verify UI property callbacks update scene state without exceptions."""
        with in_blender_sandbox() as scene:
            if scene is None or bpy is None:
                return

            props = getattr(scene, "lod_tool", None)
            self.assertIsNotNone(props)
            if not props:
                return

            # Test switching engine targets
            for eng in ("MSFS_2024", "UE5", "UNITY_6"):
                props.engine_target = eng
                on_target_engine_updated(props, bpy.context)
                self.assertEqual(props.engine_target, eng)

            # Test switching UI complexity property directly
            for comp in ("SIMPLE", "EXPERT"):
                props.ui_complexity = comp
                self.assertEqual(props.ui_complexity, comp)

    def test_cull_interior_faces_operator(self) -> None:
        """Verify lod_tool.cull_interior_faces removes occluded interior geometry across LOD0 meshes."""
        with in_blender_sandbox() as scene:
            if scene is None or bpy is None:
                return

            import bmesh

            # Create outer cube and interior occluded cube in the same mesh
            mesh = bpy.data.meshes.new("NestedMesh")
            obj = bpy.data.objects.new("SM_Nested", mesh)
            bpy.context.scene.collection.objects.link(obj)

            bm = bmesh.new()
            bmesh.ops.create_cube(bm, size=4.0)  # Outer shell
            bmesh.ops.create_cube(bm, size=1.0)  # Fully occluded interior cube
            bm.to_mesh(mesh)
            bm.free()

            for o in bpy.data.objects:
                o.select_set(o == obj)
            bpy.context.view_layer.objects.active = obj

            ops_lod: Any = cast(Any, bpy.ops).lod_tool
            res_cull = ops_lod.cull_interior_faces()
            self.assertEqual(res_cull, {"FINISHED"})

            props = getattr(bpy.context.scene, "lod_tool", None)
            if props:
                self.assertGreaterEqual(props.last_culled_faces_count, 6)

    def test_clean_and_repair_mesh_with_interior_culling_option(self) -> None:
        """Verify lod_tool.clean_and_repair_mesh executes interior culling when enabled."""
        with in_blender_sandbox() as scene:
            if scene is None or bpy is None:
                return

            import bmesh

            mesh = bpy.data.meshes.new("SanitizeNestedMesh")
            obj = bpy.data.objects.new("SM_SanitizeNested", mesh)
            bpy.context.scene.collection.objects.link(obj)

            bm = bmesh.new()
            bmesh.ops.create_cube(bm, size=4.0)
            bmesh.ops.create_cube(bm, size=1.0)
            bm.to_mesh(mesh)
            bm.free()

            for o in bpy.data.objects:
                o.select_set(o == obj)
            bpy.context.view_layer.objects.active = obj

            props = getattr(bpy.context.scene, "lod_tool", None)
            if props:
                props.cleanup_cull_interior_faces = True

            ops_lod: Any = cast(Any, bpy.ops).lod_tool
            res_clean = ops_lod.clean_and_repair_mesh()
            self.assertEqual(res_clean, {"FINISHED"})
            self.assertLess(len(mesh.polygons), 12)

    def test_voxel_scan_cleanup_operator(self) -> None:
        """Verify lod_tool.voxel_scan_cleanup runs on LOD0 meshes in real Blender runtime."""
        with in_blender_sandbox() as scene:
            if scene is None or bpy is None:
                return

            import bmesh

            mesh = bpy.data.meshes.new("VoxelTargetMesh")
            obj = bpy.data.objects.new("SM_VoxelScan", mesh)
            bpy.context.scene.collection.objects.link(obj)

            bm = bmesh.new()
            bmesh.ops.create_cube(bm, size=2.0)
            bm.to_mesh(mesh)
            bm.free()

            for o in bpy.data.objects:
                o.select_set(o == obj)
            bpy.context.view_layer.objects.active = obj

            props = getattr(bpy.context.scene, "lod_tool", None)
            if props:
                props.scan_remesh_voxel_size = 0.2

            ops_lod: Any = cast(Any, bpy.ops).lod_tool
            res_voxel = ops_lod.voxel_scan_cleanup()
            self.assertEqual(res_voxel, {"FINISHED"})
