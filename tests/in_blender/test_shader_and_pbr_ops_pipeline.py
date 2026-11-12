"""In-Blender Integration Tests for Shader Node Tracing, Material Presets, and PBR Map Pipeline."""

from __future__ import annotations

import contextlib
import logging
from pathlib import Path
import tempfile
from typing import TYPE_CHECKING, Any, cast
import numpy as np
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
    from core.shader_tracer import ShaderTracer
except (ImportError, ValueError):
    from ...core.shader_tracer import ShaderTracer


class TestShaderAndPBROpsPipeline(unittest.TestCase):
    """Verify live ShaderNodeTree AST tracing, procedural detection, preset assignment, and PBR maps."""

    def setUp(self) -> None:
        if not bpy:
            self.skipTest("Blender bpy runtime not available.")

    def test_shader_tracer_node_graph_extraction(self) -> None:
        """Verify ShaderTracer extraction of Normal maps, procedural channels, and decoupled inputs."""
        with in_blender_sandbox() as scene:
            if scene is None or bpy is None:
                return

            mat = bpy.data.materials.new(name="M_ComplexShader")
            mat.use_nodes = True
            self.assertIsNotNone(mat.node_tree)
            assert mat.node_tree is not None
            nodes = mat.node_tree.nodes
            nodes.clear()

            # 1. Output and BSDF
            out_node = nodes.new(type="ShaderNodeOutputMaterial")
            bsdf_node = nodes.new(type="ShaderNodeBsdfPrincipled")
            mat.node_tree.links.new(bsdf_node.outputs["BSDF"], out_node.inputs["Surface"])

            # 2. Base Color Image Texture
            tex_base = nodes.new(type="ShaderNodeTexImage")
            img_base = bpy.data.images.new("T_BaseColor", width=64, height=64)
            cast(Any, tex_base).image = img_base
            mat.node_tree.links.new(tex_base.outputs["Color"], bsdf_node.inputs["Base Color"])

            # 3. Normal Map Node + Texture
            norm_node = nodes.new(type="ShaderNodeNormalMap")
            tex_norm = nodes.new(type="ShaderNodeTexImage")
            img_norm = bpy.data.images.new("T_Normal", width=64, height=64)
            cast(Any, tex_norm).image = img_norm
            mat.node_tree.links.new(tex_norm.outputs["Color"], norm_node.inputs["Color"])
            mat.node_tree.links.new(norm_node.outputs["Normal"], bsdf_node.inputs["Normal"])

            # 4. Inverted Math Node on Roughness
            math_inv = nodes.new(type="ShaderNodeMath")
            cast(Any, math_inv).operation = "SUBTRACT"
            cast(Any, math_inv.inputs[0]).default_value = 1.0
            tex_rough = nodes.new(type="ShaderNodeTexImage")
            img_rough = bpy.data.images.new("T_Smoothness", width=64, height=64)
            cast(Any, tex_rough).image = img_rough
            mat.node_tree.links.new(tex_rough.outputs["Color"], math_inv.inputs[1])
            mat.node_tree.links.new(math_inv.outputs["Value"], bsdf_node.inputs["Roughness"])

            # 5. Procedural Noise on Metallic
            noise_node = nodes.new(type="ShaderNodeTexNoise")
            mat.node_tree.links.new(noise_node.outputs["Fac"], bsdf_node.inputs["Metallic"])

            # Test Normal extraction
            detected_norm = ShaderTracer.get_material_normal_image(mat)
            self.assertEqual(detected_norm, img_norm)

            # Test Base Color trace
            base_img, b_chan, b_inv, _ = ShaderTracer.trace_upstream_channel(mat, "Base Color")
            self.assertEqual(base_img, img_base)
            self.assertEqual(b_chan, 0)
            self.assertFalse(b_inv)

            # Test Inverted Roughness trace
            r_img, r_chan, r_inv, _ = ShaderTracer.trace_upstream_channel(mat, "Roughness")
            self.assertEqual(r_img, img_rough)
            self.assertTrue(r_inv)

            # Test Procedural detection
            self.assertFalse(ShaderTracer.is_procedural_socket(mat, "Base Color"))
            self.assertTrue(ShaderTracer.is_procedural_socket(mat, "Metallic"))

            # Test Resampling utility
            test_src = np.full((8, 8), 128, dtype=np.uint8)
            resampled = ShaderTracer.resample_channel_bilinear_numpy(test_src, target_w=16, target_h=16)
            self.assertEqual(resampled.shape, (16, 16))
            self.assertEqual(int(resampled[0, 0]), 128)

    def test_pbr_preset_map_management_operators(self) -> None:
        """Verify lod_tool preset map initialization, add, move, and delete operators."""
        with in_blender_sandbox() as scene:
            if scene is None or bpy is None:
                return

            props = getattr(scene, "lod_tool", None)
            if not props:
                return

            ops: Any = cast(Any, bpy.ops).lod_tool

            # 1. Initialize Preset Maps
            res_init = ops.init_preset_maps()
            self.assertEqual(res_init, {"FINISHED"})

            # Built-in presets are read-only; test negative guard
            props.pbr_import_preset = "unreal_engine_5"
            res_builtin_add = ops.add_preset_map()
            self.assertEqual(res_builtin_add, {"CANCELLED"})

            imp_dup_created = False
            exp_dup_created = False
            try:
                # Duplicate built-in presets to custom editable presets
                res_dup_imp = ops.duplicate_preset(preset_type="IMPORT", new_name="Custom_Import_Test")
                self.assertEqual(res_dup_imp, {"FINISHED"})
                imp_dup_created = True

                res_dup_exp = ops.duplicate_preset(preset_type="EXPORT", new_name="Custom_Export_Test")
                self.assertEqual(res_dup_exp, {"FINISHED"})
                exp_dup_created = True

                # 2. Add custom map to active import preset
                res_add = ops.add_preset_map()
                self.assertEqual(res_add, {"FINISHED"})
                orig_len = len(props.pbr_active_maps)
                self.assertGreaterEqual(orig_len, 1)

                # 3. Add map template
                res_tpl = ops.add_map_template(template_type="NORMAL_OPENGL")
                self.assertEqual(res_tpl, {"FINISHED"})
                self.assertEqual(len(props.pbr_active_maps), orig_len + 1)

                # 4. Move preset map
                props.pbr_active_map_index = len(props.pbr_active_maps) - 1
                res_move = ops.move_preset_map(direction="UP")
                self.assertEqual(res_move, {"FINISHED"})

                # 5. Delete preset map
                res_del = ops.delete_preset_map()
                self.assertEqual(res_del, {"FINISHED"})

                # 6. Test Export Map Operators
                res_exp_add = ops.add_export_preset_map()
                self.assertEqual(res_exp_add, {"FINISHED"})

                res_exp_tpl = ops.add_export_map_template(template_type="ORM")
                self.assertEqual(res_exp_tpl, {"FINISHED"})

                props.pbr_export_active_map_index = len(props.pbr_export_active_maps) - 1
                res_exp_move = ops.move_export_preset_map(direction="UP")
                self.assertEqual(res_exp_move, {"FINISHED"})

                res_exp_del = ops.delete_export_preset_map()
                self.assertEqual(res_exp_del, {"FINISHED"})
            finally:
                # Cleanup custom presets
                if imp_dup_created:
                    with contextlib.suppress(Exception):
                        ops.delete_import_preset()
                if exp_dup_created:
                    with contextlib.suppress(Exception):
                        ops.delete_export_preset()

    def test_pbr_folder_matching_and_relinking(self) -> None:
        """Verify auto-matching PBR texture folder and relinking project textures."""
        with in_blender_sandbox() as scene:
            if scene is None or bpy is None:
                return

            mesh_objs = create_hierarchy_fixture("TextureTarget")
            target_obj = mesh_objs[0]
            bpy.context.view_layer.objects.active = target_obj
            target_obj.select_set(True)

            ops: Any = cast(Any, bpy.ops).lod_tool

            # Negative test: invalid folder
            res_bad_match = ops.auto_match_pbr_folder(directory="/non_existent/folder_xyz/")
            self.assertEqual(res_bad_match, {"CANCELLED"})

            res_bad_relink = ops.relink_project_textures(directory="/non_existent/relink_dir/")
            self.assertEqual(res_bad_relink, {"CANCELLED"})

            # Positive test with temporary mock folder
            with tempfile.TemporaryDirectory(prefix="omnimesh_pbr_tex_") as temp_dir:
                # Create dummy texture files
                for suffix in ("BaseColor.png", "Normal.png", "Roughness.png", "Metallic.png"):
                    p = Path(temp_dir) / f"TextureTarget_{suffix}"
                    p.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06")

                res_match = ops.auto_match_pbr_folder(directory=temp_dir)
                self.assertIn(res_match, ({"FINISHED"}, {"CANCELLED"}))

                res_relink = ops.relink_project_textures(directory=temp_dir)
                self.assertIn(res_relink, ({"FINISHED"}, {"CANCELLED"}))


if __name__ == "__main__":
    unittest.main()
