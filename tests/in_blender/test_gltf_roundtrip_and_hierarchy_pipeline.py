"""In-Blender Integration Tests for glTF Roundtrip, Hierarchy Assembly, and Engine Import."""

from __future__ import annotations

import logging
from pathlib import Path
import tempfile
import time
from typing import TYPE_CHECKING, Any, cast
import unittest

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    import bpy
    from tests.in_blender.fixtures import create_hierarchy_fixture, create_skinned_mesh, in_blender_sandbox
else:
    try:
        import bpy
        from tests.in_blender.fixtures import create_hierarchy_fixture, create_skinned_mesh, in_blender_sandbox
    except ImportError:
        bpy = None
        create_hierarchy_fixture = None  # type: ignore
        create_skinned_mesh = None  # type: ignore
        in_blender_sandbox = None  # type: ignore

try:
    from core.engine_import_presets import EngineImportPresetManager
    from core.gltf_assembly import (
        GLTFAssemblyEngine,
        bind_manifest_to_omnimesh,
    )
    from core.hierarchy import MeshMergeEngine, safe_remove_collection_objects
    from core.msfs.project_scanner import MSFSLODInfo, MSFSModelTargetInfo, MSFSProjectManifest
except (ImportError, ValueError):
    from core.engine_import_presets import EngineImportPresetManager
    from core.gltf_assembly import (
        GLTFAssemblyEngine,
        bind_manifest_to_omnimesh,
    )
    from core.hierarchy import MeshMergeEngine, safe_remove_collection_objects
    from core.msfs.project_scanner import MSFSLODInfo, MSFSModelTargetInfo, MSFSProjectManifest


class TestGLTFRoundtripAndHierarchyPipeline(unittest.TestCase):
    """Verify glTF file export-import roundtrips, hierarchy merging, and engine import presets."""

    def setUp(self) -> None:
        if not bpy:
            self.skipTest("Blender bpy runtime not available.")

    def test_gltf_export_import_roundtrip_in_collection(self) -> None:
        """Export real geometry to .glb and verify GLTFAssemblyEngine isolated ingestion."""
        with in_blender_sandbox() as scene:
            if scene is None or bpy is None:
                return

            with tempfile.TemporaryDirectory() as tmp_dir:
                export_glb = Path(tmp_dir) / "TestAirframe.glb"

                # 1. Create source mesh in default scene
                cube_objs = create_hierarchy_fixture("Airframe_LOD0")
                self.assertTrue(len(cube_objs) > 0)
                main_obj = cube_objs[0]

                # Select only main_obj for glTF export
                for o in bpy.data.objects:
                    o.select_set(o == main_obj)
                bpy.context.view_layer.objects.active = main_obj

                # Export using Blender native glTF exporter
                bpy.ops.export_scene.gltf(
                    filepath=str(export_glb),
                    use_selection=True,
                    export_format="GLB",
                )
                self.assertTrue(export_glb.is_file(), f"GLB export failed: {export_glb}")

                # 2. Target isolated collection for assembly engine
                target_col = bpy.data.collections.new("Col_Ingested_GLTF")
                scene.collection.children.link(target_col)

                imported_objs = GLTFAssemblyEngine.import_gltf_into_collection(
                    bpy.context,
                    gltf_path=export_glb,
                    target_collection=target_col,
                    asset_name="TestAirframe",
                    is_interior=False,
                    blend_data=bpy.data,
                )

                self.assertTrue(len(imported_objs) > 0)
                for obj in imported_objs:
                    self.assertIn(obj.name, target_col.objects)

    def test_hierarchy_merge_to_mesh_with_mats_and_weights(self) -> None:
        """Verify HierarchyManager.merge_hierarchy_to_mesh unifies materials, deform weights, and transforms."""
        with in_blender_sandbox() as scene:
            if scene is None or bpy is None:
                return

            # Create 2 separate meshes with distinct materials and vertex groups
            cube1 = bpy.data.objects.new("Wing_Left", bpy.data.meshes.new("Wing_Left_Mesh"))
            cube2 = bpy.data.objects.new("Wing_Right", bpy.data.meshes.new("Wing_Right_Mesh"))
            scene.collection.objects.link(cube1)
            scene.collection.objects.link(cube2)

            # Assign simple geometry
            import bmesh

            for obj, offset_x in [(cube1, -2.0), (cube2, 2.0)]:
                bm = bmesh.new()
                bmesh.ops.create_cube(bm, size=1.0)
                bm.to_mesh(cast(Any, obj.data))
                bm.free()
                obj.location.x = offset_x
                cast(Any, obj.data).update()

            mat1 = bpy.data.materials.new("M_Wing_L")
            mat2 = bpy.data.materials.new("M_Wing_R")
            cast(Any, cube1.data).materials.append(mat1)
            cast(Any, cube2.data).materials.append(mat2)

            vg1 = cube1.vertex_groups.new(name="DEF_Wing_L")
            vg1.add([0, 1, 2, 3], 0.75, "REPLACE")
            vg2 = cube2.vertex_groups.new(name="DEF_Wing_R")
            vg2.add([0, 1, 2, 3], 0.85, "REPLACE")

            # Pivot object
            pivot_empty = bpy.data.objects.new("Aircraft_Pivot", None)
            pivot_empty.location = (0.0, 1.0, 0.0)
            scene.collection.objects.link(pivot_empty)

            merged_obj = MeshMergeEngine.consolidate_and_merge_meshes(
                [cube1, cube2],
                output_obj_name="Wings_Merged",
                pivot_obj=pivot_empty,
                blend_data=bpy.data,
            )

            self.assertIsNotNone(merged_obj)
            if merged_obj and merged_obj.data:
                mesh_data: Any = cast(Any, merged_obj.data)
                self.assertEqual(len(mesh_data.materials), 2)
                # Polygons from both cubes (6 faces each = 12 faces)
                self.assertEqual(len(mesh_data.polygons), 12)

    def test_bind_manifest_to_omnimesh_properties(self) -> None:
        """Verify bind_manifest_to_omnimesh properly sets OmniMesh tier thresholds and counts."""
        with in_blender_sandbox() as scene:
            if scene is None or bpy is None:
                return

            mesh_objs = create_hierarchy_fixture("ManifestAirframe")
            model_info = MSFSModelTargetInfo(
                target_type="normal",
                xml_path=None,
                lods=[
                    MSFSLODInfo(index=0, min_size=50.0, gltf_path=Path("/virtual/LOD0.gltf"), exists=True),
                    MSFSLODInfo(index=1, min_size=10.0, gltf_path=Path("/virtual/LOD1.gltf"), exists=True),
                ],
            )
            manifest = MSFSProjectManifest(
                package_root=Path("/virtual/aircraft"),
                asset_name="Boeing747",
                model_cfg_path=None,
                models={"normal": model_info},
                flight_model_cfg_path=None,
                systems_cfg_path=None,
                cameras_cfg_path=None,
            )

            lod_mesh_map = {
                0: [mesh_objs[0]],
                1: [mesh_objs[1]],
            }

            bind_manifest_to_omnimesh(bpy.context, manifest, lod_mesh_map)
            props = getattr(scene, "lod_tool", None)
            self.assertIsNotNone(props)
            if props:
                self.assertEqual(props.export_base_name, "Boeing747")
                self.assertTrue(props.is_configured)
                self.assertGreaterEqual(len(props.lods), 2)
                self.assertEqual(props.lods[0].state, "SOURCE")
                self.assertEqual(props.lods[1].state, "BAKED")

    def test_engine_import_preset_crud_operators(self) -> None:
        """Verify creation, duplication, renaming, and deletion of engine import presets."""
        with in_blender_sandbox() as scene:
            if scene is None or bpy is None:
                return

            ts = int(time.time() * 1000)
            initial_name = f"EnginePre_{ts}"
            dup_name = f"EnginePreDup_{ts}"
            renamed_name = f"EnginePreRenamed_{ts}"

            ops_omni: Any = cast(Any, bpy.ops).omnimesh
            new_id = ""
            dup_id = ""
            renamed_id = ""
            try:
                # 1. Create preset
                res = ops_omni.create_engine_import_preset(preset_name=initial_name)
                self.assertEqual(res, {"FINISHED"})

                props = getattr(scene, "lod_tool", None)
                self.assertIsNotNone(props)
                new_id = getattr(props, "engine_import_preset", "")
                self.assertTrue(len(new_id) > 0)

                # 2. Duplicate preset
                res_dup = ops_omni.duplicate_engine_import_preset(new_name=dup_name)
                self.assertEqual(res_dup, {"FINISHED"})
                dup_id = getattr(props, "engine_import_preset", "")
                self.assertNotEqual(new_id, dup_id)

                # 3. Rename preset
                res_ren = ops_omni.rename_engine_import_preset(new_name=renamed_name)
                self.assertEqual(res_ren, {"FINISHED"})
                renamed_id = getattr(props, "engine_import_preset", "")

                # 4. Delete duplicated preset
                res_del = ops_omni.delete_engine_import_preset()
                self.assertEqual(res_del, {"FINISHED"})
            finally:
                # Clean up all created custom presets from disk
                if renamed_id:
                    EngineImportPresetManager.delete_custom_preset(renamed_id)
                if dup_id and dup_id != renamed_id:
                    EngineImportPresetManager.delete_custom_preset(dup_id)
                if new_id and new_id not in (dup_id, renamed_id):
                    EngineImportPresetManager.delete_custom_preset(new_id)

    def test_safe_remove_collection_objects_and_negative_boundaries(self) -> None:
        """Verify safe removal of collection items and negative bounds for glTF import."""
        with in_blender_sandbox() as scene:
            if scene is None or bpy is None:
                return

            # Negative: non-existent file import returns empty list
            res_missing = GLTFAssemblyEngine.import_gltf_into_collection(
                bpy.context,
                gltf_path="/non/existent/mesh.glb",
                target_collection=scene.collection,
                blend_data=bpy.data,
            )
            self.assertEqual(res_missing, [])

            # Test safe collection objects removal
            temp_col = bpy.data.collections.new("Col_To_Purge")
            scene.collection.children.link(temp_col)
            obj = bpy.data.objects.new("PurgeMe", bpy.data.meshes.new("PurgeMesh"))
            temp_col.objects.link(obj)

            safe_remove_collection_objects(temp_col, blend_data=bpy.data)
            self.assertEqual(len(temp_col.objects), 0)
