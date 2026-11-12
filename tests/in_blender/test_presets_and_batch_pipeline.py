"""In-Blender Integration Tests for Config Presets, Interaction Volumes, Animation Tagging, and Batch Engine."""

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
    from core.batch import BatchProcessorEngine
    from core.config_presets import ConfigPresetManager
except (ImportError, ValueError):
    from ...core.batch import BatchProcessorEngine
    from ...core.config_presets import ConfigPresetManager


class TestPresetsAndBatchPipeline(unittest.TestCase):
    """Verify configuration presets lifecycle, interaction trigger volumes, animation tagging, and batch engine."""

    def setUp(self) -> None:
        if not bpy:
            self.skipTest("Blender bpy runtime not available.")

    def test_config_preset_crud_operators(self) -> None:
        """Verify omnimesh create, rename, duplicate, and delete config presets."""
        with in_blender_sandbox() as scene:
            if scene is None or bpy is None:
                return

            props = getattr(scene, "lod_tool", None)
            self.assertIsNotNone(props)
            if not props:
                return

            ops: Any = cast(Any, bpy.ops).omnimesh

            import time

            unique_tag = f"Test_{int(time.time() * 1000)}"
            preset_init_name = f"Preset_{unique_tag}"
            preset_renamed = f"Renamed_{unique_tag}"

            curr_id = ""
            renamed_id = ""
            dup_id = ""
            try:
                # 1. Create a new custom config preset
                res_create = ops.create_config_preset(
                    preset_name=preset_init_name,
                    template_type="plane_commercial_airliner",
                )
                self.assertEqual(res_create, {"FINISHED"})
                cfg_props = getattr(props, "config_presets", None)
                self.assertIsNotNone(cfg_props)
                curr_id = getattr(cfg_props, "config_preset", "")
                preset = ConfigPresetManager.get_preset(curr_id)
                self.assertEqual(preset.get("name"), preset_init_name)

                # 2. Rename preset
                res_rename = ops.rename_config_preset(new_name=preset_renamed)
                self.assertEqual(res_rename, {"FINISHED"})
                renamed_id = getattr(cfg_props, "config_preset", "")
                renamed_preset = ConfigPresetManager.get_preset(renamed_id)
                self.assertEqual(renamed_preset.get("name"), preset_renamed)

                # 3. Duplicate preset
                res_dup = ops.duplicate_config_preset()
                self.assertEqual(res_dup, {"FINISHED"})
                dup_id = getattr(cfg_props, "config_preset", "")
                self.assertNotEqual(dup_id, renamed_id)

                # 4. Delete duplicated preset
                res_del = ops.delete_config_preset()
                self.assertEqual(res_del, {"FINISHED"})
            finally:
                # Clean up all created custom presets from disk
                if dup_id:
                    ConfigPresetManager.delete_custom_preset(dup_id)
                if renamed_id:
                    ConfigPresetManager.delete_custom_preset(renamed_id)
                if curr_id and curr_id not in (renamed_id, dup_id):
                    ConfigPresetManager.delete_custom_preset(curr_id)

    def test_interaction_volume_operator(self) -> None:
        """Verify omnimesh.add_interaction_volume creates Box, Sphere, and Cylinder triggers with engine tags."""
        with in_blender_sandbox() as scene:
            if scene is None or bpy is None:
                return

            mesh_objs = create_hierarchy_fixture("CockpitPanel")
            panel_obj = mesh_objs[0]
            bpy.context.view_layer.objects.active = panel_obj
            panel_obj.select_set(True)

            props = getattr(scene, "lod_tool", None)
            if not props:
                return

            inter_props = getattr(props, "interaction", None)
            if not inter_props:
                return

            ops: Any = cast(Any, bpy.ops).omnimesh

            # 1. Box Button
            inter_props.shape = "BOX"
            inter_props.role = "BUTTON"
            inter_props.volume_name = "AP_Master_Btn"
            res_box = ops.add_interaction_volume()
            self.assertEqual(res_box, {"FINISHED"})

            inter_col = next(
                (
                    c
                    for c in bpy.data.collections
                    if c.get("_omnimesh_role") == "INTERACTIONS" or "Interactions" in c.name
                ),
                None,
            )
            self.assertIsNotNone(inter_col)
            btn = bpy.data.objects.get("CockpitPanel_Body_BUTTON_AP_Master_Btn")
            self.assertIsNotNone(btn)
            if btn:
                self.assertEqual(btn.parent, panel_obj)

            # 2. Sphere Lever
            inter_props.shape = "SPHERE"
            inter_props.role = "LEVER"
            inter_props.volume_name = "Throttle_Lever"
            res_sphere = ops.add_interaction_volume()
            self.assertEqual(res_sphere, {"FINISHED"})

            # 3. Cylinder Door Handle
            inter_props.shape = "CYLINDER"
            inter_props.role = "DOOR_HANDLE"
            inter_props.volume_name = "Emergency_Handle"
            res_cyl = ops.add_interaction_volume()
            self.assertEqual(res_cyl, {"FINISHED"})

    def test_batch_processor_engine_and_import_project(self) -> None:
        """Verify BatchProcessorEngine asset discovery and engine project folder ingestion."""
        with in_blender_sandbox() as scene:
            if scene is None or bpy is None:
                return

            with tempfile.TemporaryDirectory(prefix="omnimesh_batch_") as temp_dir:
                # Create synthetic asset files
                (Path(temp_dir) / "PropA.obj").write_text("# OBJ file\nv 0 0 0\n", encoding="utf-8")
                (Path(temp_dir) / "PropB.gltf").write_text('{"asset": {"version": "2.0"}}', encoding="utf-8")
                sub_dir = Path(temp_dir) / "SubAssets"
                sub_dir.mkdir()
                (sub_dir / "PropC.blend").write_text("BLENDER", encoding="utf-8")

                # 1. Discover assets
                discovered = BatchProcessorEngine.discover_assets(temp_dir, recursive=True)
                self.assertGreaterEqual(len(discovered), 2)

                # 2. Discover blend files
                blend_files = BatchProcessorEngine.discover_blend_files(temp_dir, recursive=True)
                self.assertGreaterEqual(len(blend_files), 1)

                # 3. Compute mirrored output path
                out_dir, asset_name = BatchProcessorEngine.compute_mirrored_export_path(
                    blend_path=str(sub_dir / "PropC.blend"),
                    source_root=temp_dir,
                    export_root=os.path.join(temp_dir, "Export"),
                )
                self.assertEqual(asset_name, "PropC")
                self.assertIn("SubAssets", out_dir)

                # 4. Test GC
                BatchProcessorEngine.force_garbage_collection()

                # 5. Ingest project folder via operator
                ops: Any = cast(Any, bpy.ops).omnimesh
                res_import = ops.import_engine_project(directory=temp_dir)
                self.assertIn(res_import, ({"FINISHED"}, {"CANCELLED"}))

                # Negative test: invalid directory reports error (RuntimeError in headless test)
                with self.assertRaises(RuntimeError):
                    ops.import_engine_project(directory="/invalid/engine/path_xyz")


if __name__ == "__main__":
    unittest.main()
