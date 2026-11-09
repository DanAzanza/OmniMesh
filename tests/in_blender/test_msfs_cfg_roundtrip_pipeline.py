"""In-Blender Integration Tests for MSFS 2024 CFG Roundtrip (Spatial, Lights, Cameras, Attachments)."""

from __future__ import annotations

import logging
import os
from pathlib import Path
import tempfile
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
    from ui.msfs_camera_ops import find_cameras_collection
    from ui.msfs_lighting_ops import find_lights_collection
    from ui.msfs_spatial_ops import find_spatial_collection
except (ImportError, ValueError):
    from ...ui.msfs_camera_ops import find_cameras_collection
    from ...ui.msfs_lighting_ops import find_lights_collection
    from ...ui.msfs_spatial_ops import find_spatial_collection


class TestMSFSCFGRoundtripPipeline(unittest.TestCase):
    """Verify lossless import, modification, synchronization and mirroring of MSFS CFG configurations."""

    def setUp(self) -> None:
        if not bpy:
            self.skipTest("Blender bpy runtime not available.")

    def test_spatial_cfg_import_export_roundtrip(self) -> None:
        """Verify import of flight_model.cfg contact points/tanks, Blender transformation, and export sync."""
        with in_blender_sandbox() as scene:
            if scene is None or bpy is None:
                return

            sample_cfg = (
                "[WEIGHT_AND_BALANCE]\n"
                "reference_datum_position = 0.0, 0.0, 0.0\n"
                "empty_weight_CG_position = -1.5, 0.0, 0.5\n"
                "\n"
                "[CONTACT_POINTS]\n"
                "point.0 = 1,  5.0,  0.0, -1.2, 1500, 0, 0.5, 60, 0.3, 2.5, 0.7, 0, 0, 0\n"
                "point.1 = 1, -2.0, -3.5, -1.4, 2500, 1, 0.6,  0, 0.4, 2.5, 0.8, 0, 0, 2\n"
                "point.2 = 1, -2.0,  3.5, -1.4, 2500, 2, 0.6,  0, 0.4, 2.5, 0.8, 0, 0, 3\n"
                "\n"
                "[FUEL]\n"
                "LeftMain = -1.0, -3.0, 0.5, 25, 1\n"
                "RightMain = -1.0, 3.0, 0.5, 25, 1\n"
            )

            with tempfile.TemporaryDirectory(prefix="omnimesh_msfs_spatial_") as temp_dir:
                cfg_path = os.path.join(temp_dir, "flight_model.cfg")
                with open(cfg_path, "w", encoding="utf-8") as f:
                    f.write(sample_cfg)

                # Set scene property
                props = getattr(scene, "lod_tool", None)
                self.assertIsNotNone(props)
                if props:
                    props.msfs_spatial_cfg_path = cfg_path

                ops: Any = cast(Any, bpy.ops).omnimesh

                # 1. Import spatial config
                res_import = ops.import_msfs_spatial(filepath=cfg_path)
                self.assertEqual(res_import, {"FINISHED"})

                # Verify spatial collection and empties exist
                spatial_col = find_spatial_collection(bpy.context)
                self.assertIsNotNone(spatial_col)
                if spatial_col:
                    empties = list(spatial_col.objects)
                    self.assertGreaterEqual(len(empties), 5)

                    # Check that reference datum exists
                    datum = next((o for o in empties if "reference_datum_position" in o.get("msfs_id", "")), None)
                    self.assertIsNotNone(datum)

                    # Move a contact point empty slightly
                    pt0 = next((o for o in empties if "point.0" in o.get("msfs_id", "")), None)
                    self.assertIsNotNone(pt0)
                    if pt0:
                        pt0.location.x += 0.5

                    # 2. Export/Sync spatial config back to disk
                    res_export = ops.export_msfs_spatial()
                    self.assertEqual(res_export, {"FINISHED"})

                    # Verify file content updated and backup file was created
                    backup_files = list(Path(temp_dir).glob("flight_model.cfg.bak_*"))
                    self.assertGreaterEqual(len(backup_files), 1)

                    with open(cfg_path, "r", encoding="utf-8") as f:
                        updated_content = f.read()
                    self.assertIn("point.0", updated_content)

    def test_spatial_marker_snap_to_nearest_vertex(self) -> None:
        """Verify snapping an MSFS marker empty to the nearest vertex of target geometry."""
        with in_blender_sandbox() as scene:
            if scene is None or bpy is None:
                return

            mesh_objs = create_hierarchy_fixture("GearFixture")
            target_mesh = mesh_objs[0]
            target_mesh.location = (0.0, 0.0, 0.0)

            # Create an MSFS marker empty nearby
            marker = bpy.data.objects.new("MSFS_Contact_Gear", None)
            marker["msfs_id"] = "CONTACT_POINTS:point.0"
            marker.location = (0.8, 0.8, 0.8)
            scene.collection.objects.link(marker)

            # Select both marker and target mesh; active must be marker
            for o in scene.objects:
                o.select_set(False)
            target_mesh.select_set(True)
            marker.select_set(True)
            bpy.context.view_layer.objects.active = marker

            ops: Any = cast(Any, bpy.ops).omnimesh
            res_snap = ops.snap_msfs_point_to_vertex()
            self.assertEqual(res_snap, {"FINISHED"})

            # Marker location should have snapped to one of the cube vertices (0.75, 0.75, 0.75 for size 1.5)
            self.assertAlmostEqual(marker.location.x, 0.75, places=2)
            self.assertAlmostEqual(marker.location.y, 0.75, places=2)
            self.assertAlmostEqual(marker.location.z, 0.75, places=2)

    def test_spatial_marker_mirror_and_centerline_guard(self) -> None:
        """Verify sagittal reflection (X=0) and centerline rejection guard."""
        with in_blender_sandbox() as scene:
            if scene is None or bpy is None:
                return

            ops: Any = cast(Any, bpy.ops).omnimesh

            # 1. Test centerline guard: marker at X ~ 0 should be rejected safely
            center_marker = bpy.data.objects.new("MSFS_Center_Nose", None)
            center_marker["msfs_id"] = "CONTACT_POINTS:point.0"
            center_marker.location = (0.01, 5.0, -1.0)
            scene.collection.objects.link(center_marker)
            bpy.context.view_layer.objects.active = center_marker
            center_marker.select_set(True)

            res_center = ops.mirror_msfs_marker()
            self.assertEqual(res_center, {"CANCELLED"})

            # 2. Test valid bilateral pair: Left and Right markers
            left_marker = bpy.data.objects.new("MSFS_Contact_Left", None)
            left_marker["msfs_id"] = "CONTACT_POINTS:point.1"
            left_marker["msfs_type"] = "CONTACT_POINT"
            left_marker.location = (-2.5, -1.0, -1.2)
            scene.collection.objects.link(left_marker)

            right_marker = bpy.data.objects.new("MSFS_Contact_Right", None)
            right_marker["msfs_id"] = "CONTACT_POINTS:point.2"
            right_marker["msfs_type"] = "CONTACT_POINT"
            right_marker.location = (2.48, -1.0, -1.2)
            scene.collection.objects.link(right_marker)

            # Active is left marker; mirror should synchronize counterpart on X
            bpy.context.view_layer.objects.active = left_marker
            left_marker.select_set(True)

            res_mirror = ops.mirror_msfs_marker()
            self.assertEqual(res_mirror, {"FINISHED"})
            self.assertAlmostEqual(right_marker.location.x, 2.5, places=3)

    def test_lighting_cfg_import_export_roundtrip(self) -> None:
        """Verify import of [LIGHTS] from systems.cfg, Blender Light creation, and sync back to cfg."""
        with in_blender_sandbox() as scene:
            if scene is None or bpy is None:
                return

            sample_systems_cfg = (
                "[LIGHTS]\n"
                "lightdef.0 = Type:1#Index:1#LocalPosition:-1.2,-4.5,0.8#LocalRotation:0,0,45#EffectFile:LIGHT_ASOBO_NavigationRed#Node:#PotentiometerIndex:1#Emissive:0\n"
                "lightdef.1 = Type:2#Index:2#LocalPosition:-1.2,4.5,0.8#LocalRotation:0,0,-45#EffectFile:LIGHT_ASOBO_NavigationGreen#Node:#PotentiometerIndex:1#Emissive:0\n"
                "lightdef.2 = Type:5#Index:3#LocalPosition:2.5,0.0,-0.5#LocalRotation:10,0,0#EffectFile:LIGHT_ASOBO_Landing#Node:#PotentiometerIndex:2#Emissive:0\n"
            )

            with tempfile.TemporaryDirectory(prefix="omnimesh_msfs_lights_") as temp_dir:
                cfg_path = os.path.join(temp_dir, "systems.cfg")
                with open(cfg_path, "w", encoding="utf-8") as f:
                    f.write(sample_systems_cfg)

                props = getattr(scene, "lod_tool", None)
                if props:
                    props.msfs_systems_cfg_path = cfg_path

                ops: Any = cast(Any, bpy.ops).omnimesh

                # 1. Import lights
                res_import = ops.import_msfs_lights(filepath=cfg_path)
                self.assertEqual(res_import, {"FINISHED"})

                lights_col = find_lights_collection(bpy.context)
                self.assertIsNotNone(lights_col)
                if lights_col:
                    light_objs = list(lights_col.objects)
                    self.assertEqual(len(light_objs), 3)

                    # Verify light datablocks created
                    spot_or_point = [o for o in light_objs if o.type == "LIGHT"]
                    self.assertGreaterEqual(len(spot_or_point), 1)

                    # Move a light and sync back
                    light_objs[0].location.y += 0.2
                    res_export = ops.export_msfs_lights()
                    self.assertEqual(res_export, {"FINISHED"})

                    with open(cfg_path, "r", encoding="utf-8") as f:
                        updated_cfg = f.read()
                    self.assertIn("lightdef.0", updated_cfg)

    def test_camera_cfg_import_export_roundtrip(self) -> None:
        """Verify import of cameras.cfg, Camera datablock spawning, and export back to cfg."""
        with in_blender_sandbox() as scene:
            if scene is None or bpy is None:
                return

            sample_cameras_cfg = (
                "[VIEWS]\n"
                "eyepoint = -1.2, -0.8, 1.4\n"
                "\n"
                "[CameraDefinition.0]\n"
                'Title = "Pilot View"\n'
                'Guid = "{195E1944-93B4-40E7-9913-B8D81EE32D93}"\n'
                "Translation = -1.2, -0.8, 1.4\n"
                "Rotation = 0, 0, 0\n"
                "InitialZoom = 0.35\n"
                'Category = "Cockpit"\n'
                "\n"
                "[CameraDefinition.1]\n"
                'Title = "Tail View"\n'
                'Guid = "{295E1944-93B4-40E7-9913-B8D81EE32D94}"\n'
                "Translation = -8.0, 0.0, 3.5\n"
                "Rotation = 15, 0, 0\n"
                "InitialZoom = 0.5\n"
                'Category = "Aircraft"\n'
            )

            with tempfile.TemporaryDirectory(prefix="omnimesh_msfs_cams_") as temp_dir:
                cfg_path = os.path.join(temp_dir, "cameras.cfg")
                with open(cfg_path, "w", encoding="utf-8") as f:
                    f.write(sample_cameras_cfg)

                props = getattr(scene, "lod_tool", None)
                if props:
                    props.msfs_cameras_cfg_path = cfg_path

                ops: Any = cast(Any, bpy.ops).omnimesh

                # 1. Import cameras
                res_import = ops.import_msfs_cameras(filepath=cfg_path)
                self.assertEqual(res_import, {"FINISHED"})

                cam_col = find_cameras_collection(bpy.context)
                self.assertIsNotNone(cam_col)
                if cam_col:
                    cam_objects = list(cast(Any, cam_col).objects)
                    cams = [o for o in cam_objects if o.type == "CAMERA"]
                    self.assertGreaterEqual(len(cams), 1)

                    # Check eyepoint empty was created
                    eyepoint = next((o for o in cam_objects if o.get("msfs_id") == "VIEWS:eyepoint"), None)
                    self.assertIsNotNone(eyepoint)

                    # Export cameras back to cfg
                    res_export = ops.export_msfs_cameras()
                    self.assertEqual(res_export, {"FINISHED"})

                    with open(cfg_path, "r", encoding="utf-8") as f:
                        updated_cameras = f.read()
                    self.assertIn("CAMERADEFINITION.0", updated_cameras.upper())

    def test_attachment_cfg_import_export_roundtrip(self) -> None:
        """Verify import, adding new attachment hotspots, and export of attached_objects.cfg."""
        with in_blender_sandbox() as scene:
            if scene is None or bpy is None:
                return

            sample_attached_cfg = (
                "[ATTACHMENT.0]\n"
                'attach_to_model = "Exterior"\n'
                'socket_name = "ATTACH_POINT_WingLeft"\n'
                'attachment_path = "Submodels/FuelTank.xml"\n'
                "translation = 0.0, -2.5, -0.3\n"
                "rotation = 0.0, 0.0, 0.0\n"
                "scale = 1.0, 1.0, 1.0\n"
                'alias = "FuelPod_L"\n'
            )

            with tempfile.TemporaryDirectory(prefix="omnimesh_msfs_attach_") as temp_dir:
                cfg_path = os.path.join(temp_dir, "attached_objects.cfg")
                with open(cfg_path, "w", encoding="utf-8") as f:
                    f.write(sample_attached_cfg)

                props = getattr(scene, "lod_tool", None)
                if props:
                    msfs_cfg = getattr(props, "msfs_configs", None)
                    if msfs_cfg:
                        msfs_cfg.attached_objects_cfg_path = cfg_path

                ops: Any = cast(Any, bpy.ops).omnimesh

                # 1. Import attachments
                res_import = ops.import_msfs_attachments(filepath=cfg_path)
                self.assertEqual(res_import, {"FINISHED"})

                # 2. Add an attachment hotspot
                res_add = ops.add_msfs_attachment(
                    alias="Garmin_G1000",
                    attachment_path="Submodels/Screen.xml",
                    attach_to_model="Interior",
                )
                self.assertEqual(res_add, {"FINISHED"})

                # 3. Export attachments back to cfg
                res_export = ops.export_msfs_attachments(filepath=cfg_path)
                self.assertEqual(res_export, {"FINISHED"})

                with open(cfg_path, "r", encoding="utf-8") as f:
                    updated_attach = f.read()
                self.assertIn("ATTACHMENT", updated_attach)


if __name__ == "__main__":
    unittest.main()
