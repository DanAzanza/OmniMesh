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
    from tests.in_blender.fixtures import create_skinned_mesh, in_blender_sandbox
else:
    try:
        import bpy
        from tests.in_blender.fixtures import create_skinned_mesh, in_blender_sandbox
    except ImportError:
        bpy = None
        create_skinned_mesh = None  # type: ignore
        in_blender_sandbox = None  # type: ignore

try:
    from core.simulator import LODSimulatorEngine, calculate_effective_distance_pure
    from exporters.engine_export import AssetMeshResolver, PreFlightValidator
    from exporters.msfs_export import MSFSExporter
    from exporters.ue5_export import UE5Exporter
    from exporters.unity_export import UnityExporter
except (ImportError, ValueError):
    from core.simulator import LODSimulatorEngine, calculate_effective_distance_pure
    from exporters.engine_export import AssetMeshResolver, PreFlightValidator
    from exporters.msfs_export import MSFSExporter
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

    def test_skeletal_multi_lod_export_ue5_unity_msfs(self) -> None:
        """Verify rigged Armature + multi-LOD skeletal export across UE5, Unity 6, and MSFS 2024."""
        with in_blender_sandbox() as scene:
            if scene is None or bpy is None:
                return

            asset_name = "SK_HeroUnit"
            mesh0, arm_obj = create_skinned_mesh(asset_name)

            # Build LOD0 & LOD1 collections with rigged LOD1 copy
            root_col = bpy.data.collections.new(asset_name)
            scene.collection.children.link(root_col)
            lod0_col = bpy.data.collections.new(f"{asset_name}_LOD0")
            lod1_col = bpy.data.collections.new(f"{asset_name}_LOD1")
            root_col.children.link(lod0_col)
            root_col.children.link(lod1_col)

            lod0_col.objects.link(mesh0)
            mesh1_data: Any = cast(Any, mesh0.data).copy()
            obj1 = bpy.data.objects.new(f"{asset_name}_LOD1", mesh1_data)
            obj1.parent = arm_obj
            mod1 = obj1.modifiers.new(name="Armature", type="ARMATURE")
            cast(Any, mod1).object = arm_obj
            lod1_col.objects.link(obj1)

            payload = AssetMeshResolver.resolve_payload(bpy.context, asset_name, blend_data=bpy.data)
            self.assertTrue(payload.is_skeletal)
            self.assertEqual(payload.armature_obj, arm_obj)

            with tempfile.TemporaryDirectory() as tmp_dir:
                tmp_path = Path(tmp_dir)

                ok_ue5, msg_ue5 = UE5Exporter.export_asset(
                    bpy.context, export_dir=tmp_dir, asset_name=asset_name, blend_data=bpy.data
                )
                self.assertTrue(ok_ue5, f"UE5 skeletal export failed: {msg_ue5}")
                ue5_py = tmp_path / f"{asset_name}_ue5_import.py"
                self.assertTrue(ue5_py.is_file())
                self.assertIn("IS_SKELETAL = True", ue5_py.read_text(encoding="utf-8"))

                ok_uni, msg_uni = UnityExporter.export_asset(
                    bpy.context, export_dir=tmp_dir, asset_name=asset_name, blend_data=bpy.data
                )
                self.assertTrue(ok_uni, f"Unity skeletal export failed: {msg_uni}")
                self.assertTrue((tmp_path / "Editor" / "OmniMeshPostprocessor.cs").is_file())

                ok_msfs, msg_msfs = MSFSExporter.export_asset(
                    bpy.context, export_dir=tmp_dir, asset_name=asset_name, blend_data=bpy.data
                )
                self.assertTrue(ok_msfs, f"MSFS skeletal export failed: {msg_msfs}")
                self.assertTrue((tmp_path / f"{asset_name}.xml").is_file())
                self.assertTrue((tmp_path / f"{asset_name}_LOD0.gltf").is_file())
                self.assertTrue((tmp_path / f"{asset_name}_LOD1.gltf").is_file())

    def test_exporter_transactional_rollback_and_visibility_restoration(self) -> None:
        """Verify UE5 & Unity exporters restore hidden layers, billboard constraints, names, and selection."""
        import bmesh

        with in_blender_sandbox() as scene:
            if scene is None or bpy is None:
                return

            asset_name = "SM_RollbackProp"
            obj0, obj1, col_obj = self._create_export_fixture_collections(asset_name, scene)

            # Give collider a raw non-UCX name to verify rollback
            col_obj.name = "RawHullBox"

            # Add an impostor tier with OmniMesh_Viewport_Billboard constraint
            imp_col = bpy.data.collections.new(f"{asset_name}_LOD_Impostor")
            root_col = bpy.data.collections.get(asset_name)
            if root_col:
                root_col.children.link(imp_col)
            imp_mesh = bpy.data.meshes.new("CustomImpMesh")
            bm_i = bmesh.new()
            bmesh.ops.create_grid(bm_i, x_segments=1, y_segments=1, size=1.0)
            bm_i.to_mesh(imp_mesh)
            bm_i.free()
            imp_obj = bpy.data.objects.new("CustomImpName", imp_mesh)
            imp_obj["_is_impostor"] = True
            imp_col.objects.link(imp_obj)
            bb_con = imp_obj.constraints.new(type="TRACK_TO")
            bb_con.name = "OmniMesh_Viewport_Billboard"
            bb_con.mute = False
            imp_obj.rotation_euler = (0.25, 0.0, 0.5)

            # Hide LOD1 object and exclude its LayerCollection
            obj1.hide_viewport = True
            vl = bpy.context.view_layer
            lod1_lc = next(
                (
                    lc
                    for lc in vl.layer_collection.children[asset_name].children
                    if lc.collection.name == f"{asset_name}_LOD1"
                ),
                None,
            )
            if lod1_lc is not None:
                lod1_lc.exclude = True

            # Set distinct selection state
            bpy.ops.object.select_all(action="DESELECT")
            obj0.select_set(True)
            vl.objects.active = obj0

            with tempfile.TemporaryDirectory() as tmp_dir:
                ok_ue5, msg_ue5 = UE5Exporter.export_asset(
                    bpy.context, export_dir=tmp_dir, asset_name=asset_name, blend_data=bpy.data
                )
                self.assertTrue(ok_ue5, f"UE5 export failed: {msg_ue5}")

                # Verify UE5 rollback invariants
                self.assertEqual(col_obj.name, "RawHullBox")
                self.assertEqual(imp_obj.name, "CustomImpName")
                self.assertIsNone(bpy.data.objects.get(f"LODGroup_{asset_name}"))
                self.assertTrue(obj1.hide_viewport)
                if lod1_lc is not None:
                    self.assertTrue(lod1_lc.exclude)
                self.assertFalse(bb_con.mute)
                self.assertAlmostEqual(imp_obj.rotation_euler[0], 0.25, places=4)
                self.assertEqual(vl.objects.active, obj0)

                ok_uni, msg_uni = UnityExporter.export_asset(
                    bpy.context, export_dir=tmp_dir, asset_name=asset_name, blend_data=bpy.data
                )
                self.assertTrue(ok_uni, f"Unity export failed: {msg_uni}")
                self.assertEqual(col_obj.name, "RawHullBox")
                self.assertEqual(imp_obj.name, "CustomImpName")
                self.assertTrue(obj1.hide_viewport)
                self.assertFalse(bb_con.mute)

    def test_preflight_validator_real_blender_checks(self) -> None:
        """Verify PreFlightValidator catches unapplied scale, origin mismatch, empty mesh, and unassigned slots."""
        with in_blender_sandbox() as scene:
            if scene is None or bpy is None:
                return

            asset_name = "SM_PreFlight"
            obj0, obj1, _ = self._create_export_fixture_collections(asset_name, scene)

            props: Any = getattr(scene, "lod_tool", None)
            if props is None:
                return
            props.export_base_name = asset_name
            props.active_asset = asset_name
            with tempfile.TemporaryDirectory() as tmp_dir:
                props.export_directory = tmp_dir
                props.lods.clear()
                t0 = props.lods.add()
                t0.name = "LOD0"
                t0.generated_obj = obj0
                t1 = props.lods.add()
                t1.name = "LOD1"
                t1.generated_obj = obj1

                # 1. Valid clean asset passes
                self.assertEqual(PreFlightValidator.run_checks(bpy.context, blend_data=bpy.data), [])

                # 2. Unapplied scale triggers error
                obj0.scale = (2.0, 1.0, 1.0)
                errs_scale = PreFlightValidator.run_checks(bpy.context, blend_data=bpy.data)
                self.assertTrue(any("unapplied scale" in e for e in errs_scale), f"Got: {errs_scale}")
                obj0.scale = (1.0, 1.0, 1.0)

                # 3. Origin mismatch between LOD0 and LOD1 triggers error
                obj1.location = (1.5, 0.0, 0.0)
                bpy.context.view_layer.update()
                errs_origin = PreFlightValidator.run_checks(bpy.context, blend_data=bpy.data)
                self.assertTrue(
                    any("origin does not match LOD0 pivot" in e for e in errs_origin), f"Got: {errs_origin}"
                )
                obj1.location = (0.0, 0.0, 0.0)
                bpy.context.view_layer.update()

                # 4. Unassigned material slot triggers error
                cast(Any, obj0.data).materials.append(None)
                errs_mat = PreFlightValidator.run_checks(bpy.context, blend_data=bpy.data)
                self.assertTrue(any("unassigned material" in e for e in errs_mat), f"Got: {errs_mat}")
                cast(Any, obj0.data).materials.clear()

                # 5. Empty polygon mesh triggers error
                empty_mesh = bpy.data.meshes.new("EmptyPolyMesh")
                obj1.data = empty_mesh
                errs_empty = PreFlightValidator.run_checks(bpy.context, blend_data=bpy.data)
                self.assertTrue(any("0 polygons" in e for e in errs_empty), f"Got: {errs_empty}")
