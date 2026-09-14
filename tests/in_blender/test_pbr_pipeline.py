"""
In-Blender Integration Tests for PBR Importer & Shader Graph Construction.
Blender 4.2+ and 5.2 LTS Compatible.
"""

from __future__ import annotations

import contextlib
import os
import tempfile
import unittest

try:
    import bpy
    from core.pbr_importer import BatchMaterialSlotMatcher, ShaderGraphBuilder
    from core.pbr_presets import PBRImportPresetManager
    from tests.in_blender.fixtures import create_hierarchy_fixture, in_blender_sandbox
except ImportError:
    bpy = None
    BatchMaterialSlotMatcher = None  # type: ignore
    ShaderGraphBuilder = None  # type: ignore
    PBRImportPresetManager = None  # type: ignore
    create_hierarchy_fixture = None  # type: ignore
    in_blender_sandbox = None  # type: ignore


class TestPBRPipeline(unittest.TestCase):
    """Verify live shader graph construction, socket routing, and material slot matching in Blender."""

    def setUp(self) -> None:
        if not bpy:
            self.skipTest("Blender bpy runtime not available.")
        self.temp_dir = tempfile.TemporaryDirectory()
        self.tmpdir = self.temp_dir.name
        self._generate_synthetic_pbr_textures()

    def tearDown(self) -> None:
        with contextlib.suppress(Exception):
            self.temp_dir.cleanup()

    def _generate_synthetic_pbr_textures(self) -> None:
        """Generate small 4x4 synthetic image files directly using Blender image datablocks."""
        textures = {
            "T_Asset_BaseColor.png": (0.8, 0.2, 0.2, 1.0),
            "T_Asset_Normal.png": (0.5, 0.5, 1.0, 1.0),
            "T_Asset_ORM.png": (1.0, 0.5, 0.0, 1.0),
        }
        for name, color in textures.items():
            path = os.path.join(self.tmpdir, name)
            img = bpy.data.images.new(name, width=4, height=4, alpha=True)
            try:
                # Fill pixel buffer (RGBA float)
                img.pixels = list(color) * (4 * 4)
                img.filepath_raw = path
                img.file_format = "PNG"
                img.save()
            finally:
                bpy.data.images.remove(img)

    def test_shader_graph_builder_real_nodes_ue5(self) -> None:
        """Verify ShaderGraphBuilder creates Principled BSDF, NormalMap, and SeparateColor nodes in Blender."""
        with in_blender_sandbox():
            mat = bpy.data.materials.new(name="M_LivePBR_UE5")
            texture_map = {
                "base_color": os.path.join(self.tmpdir, "T_Asset_BaseColor.png"),
                "normal": os.path.join(self.tmpdir, "T_Asset_Normal.png"),
                "orm": os.path.join(self.tmpdir, "T_Asset_ORM.png"),
            }

            preset = PBRImportPresetManager.get_preset("unreal_engine_5")
            self.assertIsNotNone(preset)

            success = ShaderGraphBuilder.build_pbr_graph(mat, texture_map, preset=preset)
            self.assertTrue(success, "ShaderGraphBuilder must report successful graph generation.")

            self.assertTrue(mat.use_nodes)
            nodes = mat.node_tree.nodes

            # Output and Principled BSDF nodes
            output_node = next((n for n in nodes if n.type == "OUTPUT_MATERIAL"), None)
            bsdf_node = next((n for n in nodes if n.type == "BSDF_PRINCIPLED"), None)
            self.assertIsNotNone(output_node)
            self.assertIsNotNone(bsdf_node)

            # Texture nodes
            tex_nodes = [n for n in nodes if n.type == "TEX_IMAGE"]
            self.assertGreaterEqual(len(tex_nodes), 3, "At least 3 texture nodes must be created (BC, Normal, ORM).")

            # Normal map node
            norm_node = next((n for n in nodes if n.type == "NORMAL_MAP"), None)
            self.assertIsNotNone(norm_node, "NormalMap node must be present in shader tree.")

            # Separate color node for ORM unpacking
            sep_node = next((n for n in nodes if n.type == "SEPARATE_COLOR"), None)
            self.assertIsNotNone(sep_node, "SeparateColor node must be present for ORM unpacking.")

    def test_shader_graph_builder_real_nodes_unity_maskmap(self) -> None:
        """Verify ShaderGraphBuilder creates Math SUBTRACT node for Unity MaskMap smoothness inversion."""
        with in_blender_sandbox():
            mat = bpy.data.materials.new(name="M_LivePBR_Unity")
            texture_map = {
                "base_map": os.path.join(self.tmpdir, "T_Asset_BaseColor.png"),
                "normal": os.path.join(self.tmpdir, "T_Asset_Normal.png"),
                "mask_map": os.path.join(self.tmpdir, "T_Asset_ORM.png"),
            }

            preset = PBRImportPresetManager.get_preset("unity_hdrp_maskmap")
            self.assertIsNotNone(preset)

            success = ShaderGraphBuilder.build_pbr_graph(mat, texture_map, preset=preset)
            self.assertTrue(success)

            sub_math_nodes = [
                n for n in mat.node_tree.nodes if n.type == "MATH" and getattr(n, "operation", "") == "SUBTRACT"
            ]
            self.assertGreaterEqual(
                len(sub_math_nodes), 1, "Math SUBTRACT node must exist for Unity MaskMap smoothness inversion."
            )

    def test_batch_material_slot_matcher_live_mesh(self) -> None:
        """Verify BatchMaterialSlotMatcher pairs texture sets to live Blender mesh material slots."""
        with in_blender_sandbox() as scene:
            mesh_objs = create_hierarchy_fixture("SM_SlotTest")
            active_obj = mesh_objs[0]
            scene.view_layers[0].objects.active = active_obj

            # Create multiple material slots on object
            mat1 = bpy.data.materials.new(name="Asset_Body")
            mat2 = bpy.data.materials.new(name="Asset_Glass")
            active_obj.data.materials.append(mat1)
            active_obj.data.materials.append(mat2)

            # Generate slot-specific textures in tempdir
            for prefix in ("Asset_Body", "Asset_Glass"):
                path = os.path.join(self.tmpdir, f"T_{prefix}_BaseColor.png")
                with open(path, "wb") as f:
                    f.write(b"\x89PNG\r\n\x1a\n")

            matches = BatchMaterialSlotMatcher.match_directory_to_slots(active_obj, self.tmpdir)
            self.assertIn("Asset_Body", matches)
            self.assertIn("Asset_Glass", matches)
            self.assertIn("base_color", matches["Asset_Body"])
            self.assertIn("base_color", matches["Asset_Glass"])
