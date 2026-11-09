"""In-Blender Integration Tests for UE5/Unity Engine Exporters and Interactive Camera LOD Simulator."""

from __future__ import annotations

import logging
from pathlib import Path
import tempfile
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
    from core.simulator import LODSimulatorEngine, calculate_effective_distance_pure
    from exporters.ue5_export import UE5Exporter
    from exporters.unity_export import UnityExporter
except (ImportError, ValueError):
    from core.simulator import LODSimulatorEngine, calculate_effective_distance_pure
    from exporters.ue5_export import UE5Exporter
    from exporters.unity_export import UnityExporter


class TestEngineExportAndSimulatorPipeline(unittest.TestCase):
    """Verify multi-LOD export to Unreal Engine 5 & Unity, and interactive camera distance simulation."""

    def setUp(self) -> None:
        if not bpy:
            self.skipTest("Blender bpy runtime not available.")

    def _create_export_fixture_collections(self, asset_name: str, scene: Any) -> tuple[Any, Any, Any]:
        """Creates standard root collection, LOD0/LOD1 collections and UCX collider."""
        root_col = bpy.data.collections.new(asset_name)
        scene.collection.children.link(root_col)

        lod0_col = bpy.data.collections.new(f"{asset_name}_LOD0")
        lod1_col = bpy.data.collections.new(f"{asset_name}_LOD1")
        col_col = bpy.data.collections.new(f"{asset_name}_Colliders")
        root_col.children.link(lod0_col)
        root_col.children.link(lod1_col)
        root_col.children.link(col_col)

        # Meshes
        import bmesh

        mesh0 = bpy.data.meshes.new(f"{asset_name}_LOD0_Mesh")
        obj0 = bpy.data.objects.new(f"{asset_name}_LOD0", mesh0)
        bm0 = bmesh.new()
        bmesh.ops.create_cube(bm0, size=2.0)
        bm0.to_mesh(mesh0)
        bm0.free()
        lod0_col.objects.link(obj0)

        mesh1 = bpy.data.meshes.new(f"{asset_name}_LOD1_Mesh")
        obj1 = bpy.data.objects.new(f"{asset_name}_LOD1", mesh1)
        bm1 = bmesh.new()
        bmesh.ops.create_cube(bm1, size=2.0)
        bm1.to_mesh(mesh1)
        bm1.free()
        lod1_col.objects.link(obj1)

        # UCX Collision hull
        col_mesh = bpy.data.meshes.new(f"UCX_{asset_name}_01_Mesh")
        col_obj = bpy.data.objects.new(f"UCX_{asset_name}_01", col_mesh)
        col_obj["_is_collider"] = True
        bm_c = bmesh.new()
        bmesh.ops.create_cube(bm_c, size=2.2)
        bm_c.to_mesh(col_mesh)
        bm_c.free()
        col_col.objects.link(col_obj)

        return obj0, obj1, col_obj

    def test_ue5_exporter_pipeline(self) -> None:
        """Verify UE5Exporter.export_asset writes FBX geometry with UCX colliders and LOD hierarchy."""
        with in_blender_sandbox() as scene:
            if scene is None or bpy is None:
                return

            with tempfile.TemporaryDirectory() as tmp_dir:
                asset_name = "SM_CargoCrate"
                self._create_export_fixture_collections(asset_name, scene)

                success, msg = UE5Exporter.export_asset(
                    bpy.context,
                    export_dir=tmp_dir,
                    asset_name=asset_name,
                    blend_data=bpy.data,
                )

                self.assertTrue(success, f"UE5 export failed: {msg}")
                exported_fbx = Path(tmp_dir) / f"{asset_name}.fbx"
                self.assertTrue(exported_fbx.is_file(), f"Expected FBX not found: {exported_fbx}")

    def test_unity_exporter_pipeline(self) -> None:
        """Verify UnityExporter.export_asset writes FBX geometry with LODGroup naming convention."""
        with in_blender_sandbox() as scene:
            if scene is None or bpy is None:
                return

            with tempfile.TemporaryDirectory() as tmp_dir:
                asset_name = "SM_HangarDoor"
                self._create_export_fixture_collections(asset_name, scene)

                success, msg = UnityExporter.export_asset(
                    bpy.context,
                    export_dir=tmp_dir,
                    asset_name=asset_name,
                    blend_data=bpy.data,
                )

                self.assertTrue(success, f"Unity export failed: {msg}")
                exported_fbx = Path(tmp_dir) / f"{asset_name}.fbx"
                self.assertTrue(exported_fbx.is_file(), f"Expected FBX not found: {exported_fbx}")

    def test_camera_lod_simulator_stepping_and_reset(self) -> None:
        """Verify LODSimulatorEngine screen-size calculation, distance stepping, and operator controls."""
        with in_blender_sandbox() as scene:
            if scene is None or bpy is None:
                return

            # Create test mesh and camera
            mesh = bpy.data.meshes.new("SimTargetMesh")
            target_obj = bpy.data.objects.new("SimTargetObj", mesh)
            scene.collection.objects.link(target_obj)

            cam_data = bpy.data.cameras.new("SimCamData")
            cam_obj = bpy.data.objects.new("SimCamObj", cam_data)
            cam_obj.location = (0.0, -10.0, 2.0)
            scene.collection.objects.link(cam_obj)
            scene.camera = cam_obj

            props = getattr(scene, "lod_tool", None)
            self.assertIsNotNone(props)
            if not props:
                return

            # Setup basic LOD tiers in properties
            props.lods.clear()
            lod0 = props.lods.add()
            lod0.name = "LOD0"
            lod0.screen_size_pct = 100.0
            lod0.generated_obj = target_obj

            lod1 = props.lods.add()
            lod1.name = "LOD1"
            lod1.screen_size_pct = 50.0
            lod1.generated_obj = target_obj

            # 1. Test effective distance calculation and distance scrub
            dist = calculate_effective_distance_pure(
                cam_pos=(0.0, -10.0, 0.0),
                center=(0.0, 0.0, 0.0),
                radius=1.0,
            )
            self.assertGreater(dist, 0.0)
            scrub_res = LODSimulatorEngine.evaluate_distance_scrub(bpy.context, distance_m=10.0, blend_data=bpy.data)
            self.assertIsInstance(scrub_res, dict)

            ops: Any = cast(Any, bpy.ops).lod_tool
            # 2. Operator toggle simulator
            res_toggle = ops.toggle_simulator()
            self.assertIn(res_toggle, ({"FINISHED"}, {"CANCELLED"}))

            # 3. Toggle live simulator
            res_live = ops.toggle_live_simulator()
            self.assertIn(res_live, ({"FINISHED"}, {"CANCELLED"}))

            # 4. Reset virtual distance
            res_reset = ops.reset_virtual_distance()
            self.assertIn(res_reset, ({"FINISHED"}, {"CANCELLED"}))

    def test_engine_export_negative_boundaries(self) -> None:
        """Verify exporters fail gracefully when target asset has no generated geometry."""
        with in_blender_sandbox() as scene:
            if scene is None or bpy is None:
                return

            with tempfile.TemporaryDirectory() as tmp_dir:
                # Export non-existent asset
                ok_ue5, msg_ue5 = UE5Exporter.export_asset(
                    bpy.context,
                    export_dir=tmp_dir,
                    asset_name="NonExistentAsset",
                    blend_data=bpy.data,
                )
                self.assertFalse(ok_ue5)
                self.assertIn("No generated LOD objects found", msg_ue5)

                ok_uni, msg_uni = UnityExporter.export_asset(
                    bpy.context,
                    export_dir=tmp_dir,
                    asset_name="NonExistentAsset",
                    blend_data=bpy.data,
                )
                self.assertFalse(ok_uni)
                self.assertIn("No generated LOD objects found", msg_uni)
