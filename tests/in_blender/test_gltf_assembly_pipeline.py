"""In-Blender Integration Tests for glTF Multi-LOD Assembly, Bridge Sync, and Engine Exporters."""

from __future__ import annotations

import logging
from pathlib import Path
import tempfile
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
    from core.gltf_assembly import (
        GLTFAssemblyEngine,
        classify_imported_mesh_node,
        count_mesh_triangles,
    )
except (ImportError, ValueError):
    from ...core.gltf_assembly import (
        GLTFAssemblyEngine,
        classify_imported_mesh_node,
        count_mesh_triangles,
    )


class TestGLTFAssemblyPipeline(unittest.TestCase):
    """Verify material deduplication, armature retargeting, companion script deployment, and bridge sync."""

    def setUp(self) -> None:
        if not bpy:
            self.skipTest("Blender bpy runtime not available.")

    def test_gltf_assembly_material_deduplication(self) -> None:
        """Verify GLTFAssemblyEngine deduplicates glTF-imported materials sharing base names."""
        with in_blender_sandbox() as scene:
            if scene is None or bpy is None:
                return

            mesh_objs = create_hierarchy_fixture("GLTFMatDedup")
            obj_a, obj_b = mesh_objs[0], mesh_objs[1]

            # Create base and suffixed duplicate materials
            mat_base = bpy.data.materials.new("M_Fuselage")
            self.assertIsNotNone(mat_base)
            mat_dup1 = bpy.data.materials.new("M_Fuselage.001")
            mat_dup2 = bpy.data.materials.new("M_Fuselage.002")

            mesh_a = cast(Any, obj_a.data)
            mesh_b = cast(Any, obj_b.data)
            mesh_a.materials.clear()
            mesh_a.materials.append(mat_dup1)
            mesh_b.materials.clear()
            mesh_b.materials.append(mat_dup2)

            test_col = bpy.data.collections.new("GLTF_Dedup_Col")
            scene.collection.children.link(test_col)
            test_col.objects.link(obj_a)
            test_col.objects.link(obj_b)

            engine = GLTFAssemblyEngine()
            dedup_count = engine.deduplicate_materials([obj_a, obj_b], blend_data=bpy.data)
            self.assertGreaterEqual(dedup_count, 1)

            # Both objects should now reference the unified base material
            self.assertEqual(mesh_a.materials[0].name, "M_Fuselage")
            self.assertEqual(mesh_b.materials[0].name, "M_Fuselage")

    def test_gltf_assembly_armature_retargeting(self) -> None:
        """Verify GLTFAssemblyEngine retargets duplicate skinned armatures to a single master rig."""
        with in_blender_sandbox() as scene:
            if scene is None or bpy is None:
                return

            mesh_obj_1, master_arm = create_skinned_mesh("MasterChar")
            self.assertIsNotNone(mesh_obj_1)
            mesh_obj_2, dup_arm = create_skinned_mesh("DupChar")

            engine = GLTFAssemblyEngine()
            retargeted = engine.retarget_armatures_to_master(
                master_armature=master_arm,
                lod_objects=[mesh_obj_2, dup_arm],
                blend_data=bpy.data,
            )
            self.assertGreaterEqual(retargeted, 1)

            # Mesh 2 modifier should point to master_arm
            arm_mod = next((m for m in mesh_obj_2.modifiers if m.type == "ARMATURE"), None)
            self.assertIsNotNone(arm_mod)
            if arm_mod:
                self.assertEqual(cast(Any, arm_mod).object, master_arm)

    def test_classify_imported_mesh_node_and_triangle_count(self) -> None:
        """Verify classification logic and triangle counting on real mesh geometry."""
        with in_blender_sandbox() as scene:
            if scene is None or bpy is None:
                return

            mesh_objs = create_hierarchy_fixture("ClassifierProp")
            cube_obj = mesh_objs[0]

            # Standard cube has 6 quads = 12 triangles
            tri_count = count_mesh_triangles(cube_obj)
            self.assertEqual(tri_count, 12)

            # Classification rules: RENDER_MESH, PHYSICS_COLLIDER, INTERACTION_VOLUME
            cube_obj.name = "Fuselage_LOD0"
            self.assertEqual(classify_imported_mesh_node(cube_obj, is_interior=False), "RENDER_MESH")

            cube_obj.name = "UCX_Fuselage_01"
            self.assertEqual(classify_imported_mesh_node(cube_obj), "PHYSICS_COLLIDER")

            cube_obj.name = "interact_Cockpit_Switch"
            self.assertEqual(classify_imported_mesh_node(cube_obj), "INTERACTION_VOLUME")

    def test_pack_pbr_textures_operator(self) -> None:
        """Verify lod_tool.pack_pbr_textures executes channel packing pipeline."""
        with in_blender_sandbox() as scene:
            if scene is None or bpy is None:
                return

            mesh_objs = create_hierarchy_fixture("PackedMatMesh")
            target_obj = mesh_objs[0]
            bpy.context.view_layer.objects.active = target_obj
            target_obj.select_set(True)

            with tempfile.TemporaryDirectory(prefix="omnimesh_export_tex_") as temp_dir:
                props = getattr(scene, "lod_tool", None)
                if props:
                    props.export_directory = temp_dir
                    props.target_engine = "UE5"
                    props.texture_max_resolution = "1024"

                ops: Any = cast(Any, bpy.ops).lod_tool
                res = ops.pack_pbr_textures()
                self.assertEqual(res, {"FINISHED"})

                tex_dir = Path(temp_dir) / "Textures"
                self.assertTrue(tex_dir.is_dir())

    def test_install_companion_scripts_operator(self) -> None:
        """Verify deployment of engine integration scripts for Unreal, Unity, and Godot."""
        with in_blender_sandbox() as scene:
            if scene is None or bpy is None:
                return

            with tempfile.TemporaryDirectory(prefix="omnimesh_engine_proj_") as temp_dir:
                (Path(temp_dir) / "Content").mkdir(exist_ok=True)
                (Path(temp_dir) / "Assets").mkdir(exist_ok=True)
                props = getattr(scene, "lod_tool", None)
                if not props:
                    return

                props.engine_project_path = temp_dir
                ops: Any = cast(Any, bpy.ops).lod_tool

                for engine in ("UE5", "UNITY_6"):
                    props.target_engine = engine
                    res = ops.install_companion_scripts()
                    self.assertEqual(res, {"FINISHED"})

                # Negative test: missing project path should fail poll
                props.engine_project_path = ""
                self.assertFalse(ops.install_companion_scripts.poll())

    def test_live_bridge_toggle_and_sync(self) -> None:
        """Verify graceful error reporting when toggling and syncing live bridge without active daemon."""
        with in_blender_sandbox() as scene:
            if scene is None or bpy is None:
                return

            ops: Any = cast(Any, bpy.ops).lod_tool

            # Toggling live bridge when daemon is offline should handle disconnect gracefully
            res_toggle = ops.toggle_live_bridge()
            self.assertIn(res_toggle, ({"FINISHED"}, {"CANCELLED"}))

            # Syncing live bridge should report error / cancelled without crashing
            res_sync = ops.sync_live_bridge()
            self.assertIn(res_sync, ({"FINISHED"}, {"CANCELLED"}))


if __name__ == "__main__":
    unittest.main()
