"""
In-Blender Integration Tests for Multi-Engine Export Packages (UE5, Unity 6, MSFS 2024).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import logging
import os
from pathlib import Path
import tempfile
import unittest

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    import addon_utils
    import bpy
    from tests.in_blender.fixtures import create_hierarchy_fixture, in_blender_sandbox
else:
    try:
        import addon_utils
        import bpy
        from tests.in_blender.fixtures import create_hierarchy_fixture, in_blender_sandbox
    except ImportError:
        bpy = None
        addon_utils = None
        create_hierarchy_fixture = None  # type: ignore
        in_blender_sandbox = None  # type: ignore


class TestExportPipeline(unittest.TestCase):
    """Verify 1-click multi-engine export package generation and XML/FBX/glTF integrity."""

    @classmethod
    def setUpClass(cls) -> None:
        if not bpy or not addon_utils:
            return
        # Ensure native exporter addons are enabled
        for addon in ("io_scene_fbx", "io_scene_gltf2"):
            try:
                addon_utils.enable(addon, default_set=False)
            except Exception as exc:
                logger.debug("Native exporter addon enable skipped for %s: %s", addon, exc)

    def setUp(self) -> None:
        if not bpy:
            self.skipTest("Blender bpy runtime not available.")

    def test_multi_engine_exports_generate_valid_files(self) -> None:
        """Verify exports create valid disk artifacts for MSFS 2024, UE5, and Unity 6."""
        with in_blender_sandbox() as scene:
            if scene is None or bpy is None:
                return
            mesh_objs = create_hierarchy_fixture("SM_ExpAsset")
            for obj in mesh_objs:
                obj.select_set(True)
            bpy.context.view_layer.objects.active = mesh_objs[0]

            props: Any = getattr(scene, "lod_tool", None)
            if props is None:
                return
            props.export_base_name = "SM_ExpAsset"
            props.export_packed_textures = False

            ops: Any = cast(Any, bpy.ops).lod_tool
            ops.analyze_and_configure()
            ops.generate_all()

            with tempfile.TemporaryDirectory() as tmpdir:
                props.export_directory = tmpdir

                # 1. Test MSFS 2024 (glTF + XML)
                props.target_engine = "MSFS_2024"
                res_msfs = ops.export_engine_package()
                self.assertEqual(res_msfs, {"FINISHED"})
                tmp_path = Path(tmpdir)
                xml_path = (
                    tmp_path / "model" / "SM_ExpAsset.xml"
                    if (tmp_path / "model").exists()
                    else tmp_path / "SM_ExpAsset.xml"
                )
                self.assertTrue(xml_path.is_file(), f"MSFS XML file must exist at: {xml_path}")
                xml_content = xml_path.read_text(encoding="utf-8")
                self.assertIn("<LODS>", xml_content)
                self.assertIn("minSize=", xml_content)

                # 2. Test Unreal Engine 5 (Single Multi-LOD FBX)
                props.target_engine = "UE5"
                res_ue5 = ops.export_engine_package()
                self.assertEqual(res_ue5, {"FINISHED"})
                ue5_fbx = os.path.join(tmpdir, "SM_ExpAsset.fbx")
                self.assertTrue(os.path.exists(ue5_fbx), "UE5 FBX file must exist.")
                self.assertGreater(os.path.getsize(ue5_fbx), 0)

                # 3. Test Unity 6 (Multi-LOD FBX)
                props.target_engine = "UNITY_6"
                res_unity = ops.export_engine_package()
                self.assertEqual(res_unity, {"FINISHED"})
                unity_fbx = os.path.join(tmpdir, "SM_ExpAsset.fbx")
                self.assertTrue(os.path.exists(unity_fbx), "Unity FBX file must exist.")
                self.assertGreater(os.path.getsize(unity_fbx), 0)

    def test_msfs_project_package_exterior_interior_variant_and_attachments(self) -> None:
        """Verify full MSFS 2024 package layout with Exterior, Interior, Variant, model.cfg, and ATTACH_POINT."""
        import bmesh
        from exporters.manager import ExporterManager

        def _make_box_obj(name: str, coll: Any, size: float = 1.0) -> Any:
            mesh = bpy.data.meshes.new(f"{name}_Mesh")
            bm = bmesh.new()
            bmesh.ops.create_cube(bm, size=size)
            bm.to_mesh(mesh)
            bm.free()
            obj = bpy.data.objects.new(name, mesh)
            coll.objects.link(obj)
            return obj

        with in_blender_sandbox() as scene:
            if scene is None or bpy is None:
                return

            props: Any = getattr(scene, "lod_tool", None)
            if props is None:
                return
            props.asset_category = "HERO_CHARACTER"
            props.msfs_target_version = "2024"
            props.msfs_with_exterior_show_interior = True
            props.msfs_with_interior_show_exterior = True

            # Exterior root + LOD0 (with ATTACH_POINT_Pilot) + LOD1
            ext_root = bpy.data.collections.new("C172_Pkg")
            scene.collection.children.link(ext_root)
            ext_lod0 = bpy.data.collections.new("C172_Pkg_LOD0")
            ext_lod1 = bpy.data.collections.new("C172_Pkg_LOD1")
            ext_helpers = bpy.data.collections.new("C172_Pkg_Helpers")
            ext_root.children.link(ext_lod0)
            ext_root.children.link(ext_lod1)
            ext_root.children.link(ext_helpers)

            _make_box_obj("C172_Pkg_Body_LOD0", ext_lod0, size=2.0)
            _make_box_obj("C172_Pkg_Body_LOD1", ext_lod1, size=2.0)

            att_empty = bpy.data.objects.new("ATTACH_POINT_Pilot", None)
            att_empty.location = (0.0, 0.5, 1.0)
            ext_helpers.objects.link(att_empty)

            # Interior
            int_root = bpy.data.collections.new("C172_Pkg_Interior")
            scene.collection.children.link(int_root)
            int_lod0 = bpy.data.collections.new("C172_Pkg_Interior_LOD0")
            int_root.children.link(int_lod0)
            _make_box_obj("C172_Pkg_Interior_Cockpit", int_lod0, size=1.0)

            # Variant
            var_root = bpy.data.collections.new("C172_Pkg_Float")
            scene.collection.children.link(var_root)
            var_lod0 = bpy.data.collections.new("C172_Pkg_Float_LOD0")
            var_root.children.link(var_lod0)
            _make_box_obj("C172_Pkg_Float_Hull", var_lod0, size=1.5)

            with tempfile.TemporaryDirectory() as tmpdir:
                ok, msg = ExporterManager.export_asset(
                    bpy.context,
                    "MSFS_2024",
                    tmpdir,
                    "C172_Pkg",
                    full_package=True,
                    blend_data=bpy.data,
                )
                self.assertTrue(ok, f"MSFS project package export failed: {msg}")

                tmp_path = Path(tmpdir)
                model_dir = tmp_path / "model"
                var_dir = tmp_path / "model.float"

                self.assertTrue((model_dir / "C172_Pkg.xml").is_file())
                self.assertTrue((model_dir / "C172_Pkg_LOD0.gltf").is_file())
                self.assertTrue((model_dir / "C172_Pkg_LOD1.gltf").is_file())
                self.assertTrue((model_dir / "C172_Pkg_Interior.xml").is_file())
                self.assertTrue((model_dir / "C172_Pkg_Interior_LOD0.gltf").is_file())

                # Verify LOD0 glTF includes ATTACH_POINT_Pilot node
                lod0_gltf = (model_dir / "C172_Pkg_LOD0.gltf").read_text(encoding="utf-8")
                self.assertIn("ATTACH_POINT_Pilot", lod0_gltf)

                # Verify aircraft model.cfg contains [model.options] and interior link
                model_cfg = (model_dir / "model.cfg").read_text(encoding="utf-8")
                self.assertIn("[model.options]", model_cfg)
                self.assertIn("withExterior_showInterior=true", model_cfg)
                self.assertIn("normal=C172_Pkg.xml", model_cfg)
                self.assertIn("interior=C172_Pkg_Interior.xml", model_cfg)

                # Verify variant folder and POSIX forward-slash interior reference
                self.assertTrue((var_dir / "C172_Pkg_Float.xml").is_file())
                var_cfg = (var_dir / "model.cfg").read_text(encoding="utf-8")
                self.assertIn("normal=C172_Pkg_Float.xml", var_cfg)
                self.assertIn("interior=../model/C172_Pkg_Interior.xml", var_cfg)

    def test_msfs_xml_merge_preserves_behaviors_and_scenery_suppresses_options(self) -> None:
        """Verify ModelXMLMerger preserves custom XML behaviors and scenery suppresses [model.options]."""
        import bmesh
        from exporters.msfs_export import MSFSExporter

        with in_blender_sandbox() as scene:
            if scene is None or bpy is None:
                return

            props: Any = getattr(scene, "lod_tool", None)
            if props is None:
                return
            props.asset_category = "PROP"
            props.msfs_target_version = "2024"

            scenery_col = bpy.data.collections.new("Scenery_Beacon")
            scene.collection.children.link(scenery_col)
            lod0_col = bpy.data.collections.new("Scenery_Beacon_LOD0")
            scenery_col.children.link(lod0_col)

            mesh = bpy.data.meshes.new("Scenery_Beacon_Mesh")
            bm = bmesh.new()
            bmesh.ops.create_cube(bm, size=1.0)
            bm.to_mesh(mesh)
            bm.free()
            obj = bpy.data.objects.new("Scenery_Beacon_Body", mesh)
            lod0_col.objects.link(obj)

            with tempfile.TemporaryDirectory() as tmpdir:
                model_dir = Path(tmpdir) / "model"
                model_dir.mkdir(parents=True)
                existing_xml = model_dir / "Scenery_Beacon.xml"
                existing_xml.write_text(
                    '<?xml version="1.0" encoding="utf-8" ?>\n'
                    '<ModelInfo version="1.1" guid="{11111111-2222-3333-4444-555555555555}">\n'
                    "    <LODS>\n"
                    '        <LOD minSize="5" ModelFile="Old.gltf"/>\n'
                    "    </LODS>\n"
                    "    <Behaviors>\n"
                    '        <Component ID="BeaconFlash"/>\n'
                    "    </Behaviors>\n"
                    "</ModelInfo>\n",
                    encoding="utf-8",
                )

                ok, msg = MSFSExporter.export_project_package(
                    bpy.context,
                    tmpdir,
                    "Scenery_Beacon",
                    blend_data=bpy.data,
                )
                self.assertTrue(ok, f"Scenery MSFS export failed: {msg}")

                merged_xml = existing_xml.read_text(encoding="utf-8")
                self.assertIn("BeaconFlash", merged_xml)
                self.assertIn("Scenery_Beacon_LOD0.gltf", merged_xml)
                self.assertNotIn("Old.gltf", merged_xml)

                scenery_cfg = (model_dir / "model.cfg").read_text(encoding="utf-8")
                self.assertNotIn("[model.options]", scenery_cfg)
                self.assertIn("normal=Scenery_Beacon.xml", scenery_cfg)

    def test_export_operator_with_octahedral_impostor_and_pbr_repack(self) -> None:
        """Verify 1-click export operator with packed PBR textures and an octahedral impostor tier."""
        with in_blender_sandbox() as scene:
            if scene is None or bpy is None:
                return

            mesh_objs = create_hierarchy_fixture("SM_ImpExp")
            for obj in mesh_objs:
                obj.select_set(True)
            bpy.context.view_layer.objects.active = mesh_objs[0]

            props: Any = getattr(scene, "lod_tool", None)
            if props is None:
                return
            props.export_base_name = "SM_ImpExp"
            props.impostor_mode = "OCTAHEDRAL_HEMI"
            props.impostor_grid_size = 4
            props.auto_impostor_resolution = False
            props.impostor_resolution = "512"
            props.export_packed_textures = True

            ops: Any = cast(Any, bpy.ops).lod_tool
            ops.analyze_and_configure()
            ops.generate_all()

            with tempfile.TemporaryDirectory() as tmpdir:
                props.export_directory = tmpdir
                self.assertEqual(ops.generate_impostor(), {"FINISHED"})

                props.target_engine = "UE5"
                props.pbr_export_preset = "unreal_engine_5"
                self.assertEqual(ops.export_engine_package(), {"FINISHED"})

                tmp_path = Path(tmpdir)
                self.assertTrue((tmp_path / "SM_ImpExp.fbx").is_file())
                self.assertTrue((tmp_path / "SM_ImpExp_ue5_import.py").is_file())
                self.assertTrue((tmp_path / "Textures" / "shaders" / "SM_ImpExp_Octahedral_UE5.hlsl").is_file())
                self.assertTrue((tmp_path / "Textures" / "README_SM_ImpExp_UE5_SETUP.txt").is_file())


if __name__ == "__main__":
    unittest.main()
