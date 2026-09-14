"""
In-Blender Integration Tests for Billboard Impostor Generation & Shader Wiring.
Blender 4.2+ and 5.2 LTS Compatible.
"""

from __future__ import annotations

import unittest

import numpy as np

try:
    import bpy
    from core.impostor import ImpostorMath
    from tests.in_blender.fixtures import create_hierarchy_fixture, in_blender_sandbox
except ImportError:
    bpy = None
    ImpostorMath = None  # type: ignore
    create_hierarchy_fixture = None  # type: ignore
    in_blender_sandbox = None  # type: ignore


class TestImpostorPipeline(unittest.TestCase):
    """Verify billboard impostor creation, mesh geometry, material graph routing, and removal."""

    def setUp(self) -> None:
        if not bpy:
            self.skipTest("Blender bpy runtime not available.")

    def test_generate_impostor_cross_quads(self) -> None:
        """Verify CROSS_QUADS billboard geometry (2 intersecting quads, 8 verts, 2 faces) and material setup."""
        with in_blender_sandbox() as scene:
            mesh_objs = create_hierarchy_fixture("SM_CrossTree")
            for obj in mesh_objs:
                obj.select_set(True)
            scene.view_layers[0].objects.active = mesh_objs[0]

            props = scene.lod_tool
            props.export_base_name = "SM_CrossTree"
            props.impostor_mode = "CROSS_QUADS"
            props.target_engine = "UE5"

            res = bpy.ops.lod_tool.generate_impostor()
            self.assertEqual(res, {"FINISHED"})

            coll_name = "SM_CrossTree_LOD_Impostor"
            target_coll = bpy.data.collections.get(coll_name)
            self.assertIsNotNone(target_coll, f"Collection '{coll_name}' must exist in scene.")

            impostor_objs = list(target_coll.objects)
            self.assertEqual(len(impostor_objs), 1, "Exactly one impostor billboard object must be created.")

            imp_obj = impostor_objs[0]
            self.assertEqual(imp_obj.name, "SM_CrossTree_LOD_Impostor")
            self.assertTrue(imp_obj.get("_is_impostor", False), "Impostor tag _is_impostor must be True.")
            self.assertEqual(imp_obj.get("_impostor_mode", ""), "CROSS_QUADS")

            # Verify geometry contract: Cross quads = 8 verts, 2 polygon faces (4 tris)
            self.assertEqual(len(imp_obj.data.vertices), 8, "Cross quads must have exactly 8 vertices.")
            self.assertEqual(len(imp_obj.data.polygons), 2, "Cross quads must have exactly 2 polygon faces.")

            # Verify PBR Impostor Material
            self.assertEqual(len(imp_obj.data.materials), 1, "Impostor must have 1 material assigned.")
            mat = imp_obj.data.materials[0]
            self.assertIsNotNone(mat)
            self.assertEqual(mat.name, "M_SM_CrossTree_Impostor")
            self.assertTrue(mat.use_nodes)

            node_names = {node.name for node in mat.node_tree.nodes}
            self.assertIn("Tex_BaseColor", node_names)
            self.assertIn("Tex_Normal", node_names)
            self.assertIn("Tex_ORM", node_names)

    def test_generate_impostor_star_quads(self) -> None:
        """Verify STAR_QUADS billboard geometry (3 quads at 60 deg, 12 verts, 3 faces)."""
        with in_blender_sandbox() as scene:
            mesh_objs = create_hierarchy_fixture("SM_StarTree")
            for obj in mesh_objs:
                obj.select_set(True)
            scene.view_layers[0].objects.active = mesh_objs[0]

            props = scene.lod_tool
            props.export_base_name = "SM_StarTree"
            props.impostor_mode = "STAR_QUADS"
            props.target_engine = "UE5"

            res = bpy.ops.lod_tool.generate_impostor()
            self.assertEqual(res, {"FINISHED"})

            target_coll = bpy.data.collections.get("SM_StarTree_LOD_Impostor")
            self.assertIsNotNone(target_coll)

            imp_obj = target_coll.objects.get("SM_StarTree_LOD_Impostor")
            self.assertIsNotNone(imp_obj)
            self.assertEqual(imp_obj.get("_impostor_mode", ""), "STAR_QUADS")
            self.assertEqual(len(imp_obj.data.vertices), 12, "Star quads must have exactly 12 vertices.")
            self.assertEqual(len(imp_obj.data.polygons), 3, "Star quads must have exactly 3 polygon faces.")

    def test_generate_impostor_octahedral(self) -> None:
        """Verify OCTAHEDRAL_HEMI billboard geometry (single camera-facing quad, 4 verts, 1 face)."""
        with in_blender_sandbox() as scene:
            mesh_objs = create_hierarchy_fixture("SM_OctaTree")
            for obj in mesh_objs:
                obj.select_set(True)
            scene.view_layers[0].objects.active = mesh_objs[0]

            props = scene.lod_tool
            props.export_base_name = "SM_OctaTree"
            props.impostor_mode = "OCTAHEDRAL_HEMI"
            props.target_engine = "UE5"

            res = bpy.ops.lod_tool.generate_impostor()
            self.assertEqual(res, {"FINISHED"})

            target_coll = bpy.data.collections.get("SM_OctaTree_LOD_Impostor")
            self.assertIsNotNone(target_coll)

            imp_obj = target_coll.objects.get("SM_OctaTree_LOD_Impostor")
            self.assertIsNotNone(imp_obj)
            self.assertEqual(imp_obj.get("_impostor_mode", ""), "OCTAHEDRAL_HEMI")
            self.assertEqual(len(imp_obj.data.vertices), 4, "Single quad card must have exactly 4 vertices.")
            self.assertEqual(len(imp_obj.data.polygons), 1, "Single quad card must have exactly 1 polygon face.")

    def test_impostor_material_engine_routing(self) -> None:
        """Verify engine-specific shader tree wiring (UE5 vs Unity 6 MaskMap inversion)."""
        with in_blender_sandbox() as scene:
            mesh_objs = create_hierarchy_fixture("SM_ShaderAsset")
            for obj in mesh_objs:
                obj.select_set(True)
            scene.view_layers[0].objects.active = mesh_objs[0]

            props = scene.lod_tool
            props.export_base_name = "SM_ShaderAsset"
            props.impostor_mode = "CROSS_QUADS"
            props.target_engine = "UNITY_6"

            res = bpy.ops.lod_tool.generate_impostor()
            self.assertEqual(res, {"FINISHED"})

            mat = bpy.data.materials.get("M_SM_ShaderAsset_Impostor")
            self.assertIsNotNone(mat)

            # In Unity 6, an Invert node must exist to convert Smoothness to Roughness
            invert_nodes = [node for node in mat.node_tree.nodes if node.type == "INVERT"]
            self.assertGreater(
                len(invert_nodes), 0, "Unity 6 Impostor material must include Invert node for roughness."
            )

    def test_remove_impostor(self) -> None:
        """Verify remove_impostor operator completely cleans up objects and sibling collection."""
        with in_blender_sandbox() as scene:
            mesh_objs = create_hierarchy_fixture("SM_PurgeTree")
            for obj in mesh_objs:
                obj.select_set(True)
            scene.view_layers[0].objects.active = mesh_objs[0]

            props = scene.lod_tool
            props.export_base_name = "SM_PurgeTree"

            bpy.ops.lod_tool.generate_impostor()
            target_coll = bpy.data.collections.get("SM_PurgeTree_LOD_Impostor")
            self.assertIsNotNone(target_coll)
            self.assertGreater(len(target_coll.objects), 0)

            # Purge
            res = bpy.ops.lod_tool.remove_impostor()
            self.assertEqual(res, {"FINISHED"})

            self.assertIsNone(
                bpy.data.collections.get("SM_PurgeTree_LOD_Impostor"),
                "Impostor collection must be deleted from scene.",
            )
            self.assertIsNone(
                bpy.data.objects.get("SM_PurgeTree_LOD_Impostor"),
                "Impostor object must be removed from scene data.",
            )

    def test_impostor_morphological_dilation_bleed(self) -> None:
        """Verify vectorized morphological dilation bleeds RGB border colors without alpha disruption."""
        # Create a 4x4 RGBA image with an opaque center pixel and transparent borders
        img = np.zeros((4, 4, 4), dtype=np.float32)
        img[1:3, 1:3, 0] = 1.0  # Red channel
        img[1:3, 1:3, 3] = 1.0  # Fully opaque alpha in 2x2 center

        dilated = ImpostorMath.morphological_dilate_rgb(img, iterations=1)
        self.assertEqual(dilated.shape, (4, 4, 4))
        # Center pixels must remain red and opaque
        self.assertEqual(dilated[1, 1, 0], 1.0)
        self.assertEqual(dilated[1, 1, 3], 1.0)
        # Adjacent border pixel at (0, 1) was transparent, but must now contain dilated red color
        self.assertEqual(dilated[0, 1, 0], 1.0)
        # However, its alpha must remain 0.0 so geometry silhouette is uncorrupted
        self.assertEqual(dilated[0, 1, 3], 0.0)
