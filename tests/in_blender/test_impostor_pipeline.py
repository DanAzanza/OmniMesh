"""
In-Blender Integration Tests for Billboard Impostor Generation & Shader Wiring.
Blender 5.0+ and 5.2 LTS Compatible.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import shutil
import tempfile
import unittest

import numpy as np

if TYPE_CHECKING:
    import bpy
    from core.impostor import ImpostorMath
    from tests.in_blender.fixtures import create_hierarchy_fixture, in_blender_sandbox
else:
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
        self._temp_dirs: list[str] = []

    def tearDown(self) -> None:
        for p in self._temp_dirs:
            shutil.rmtree(p, ignore_errors=True)
        self._temp_dirs.clear()

    def _get_isolated_export_dir(self) -> str:
        d = tempfile.mkdtemp(prefix="om_test_impostor_")
        self._temp_dirs.append(d)
        return d

    def test_generate_impostor_ortho_3_axes(self) -> None:
        """Verify ORTHO_3_AXES billboard geometry (3 orthogonal planes, 24 verts, 6 faces) and material setup."""
        with in_blender_sandbox() as scene:
            if scene is None or bpy is None:
                return
            mesh_objs = create_hierarchy_fixture("SM_OrthoTree")
            for obj in mesh_objs:
                obj.select_set(True)
            scene.view_layers[0].objects.active = mesh_objs[0]

            props: Any = getattr(scene, "lod_tool", None)
            if props is None:
                return
            props.export_base_name = "SM_OrthoTree"
            props.impostor_mode = "ORTHO_3_AXES"
            props.target_engine = "UE5"
            props.export_directory = self._get_isolated_export_dir()
            props.auto_impostor_resolution = False
            props.impostor_resolution = "512"

            ops: Any = cast(Any, bpy.ops).lod_tool
            res = ops.generate_impostor()
            self.assertEqual(res, {"FINISHED"})

            coll_name = "SM_OrthoTree_LOD_Impostor"
            target_coll = bpy.data.collections.get(coll_name)
            self.assertIsNotNone(target_coll, f"Collection '{coll_name}' must exist in scene.")
            if target_coll is None:
                return

            impostor_objs = list(target_coll.objects)
            self.assertEqual(len(impostor_objs), 1, "Exactly one impostor billboard object must be created.")

            imp_obj = impostor_objs[0]
            self.assertEqual(imp_obj.name, "SM_OrthoTree_LOD_Impostor")
            self.assertTrue(imp_obj.get("_is_impostor", False), "Impostor tag _is_impostor must be True.")
            self.assertEqual(imp_obj.get("_impostor_mode", ""), "ORTHO_3_AXES")

            # Verify geometry contract: 3 Orthogonal Planes (XY, YZ, XZ) x 2 sides = 24 verts, 6 polygon faces
            imp_data: Any = imp_obj.data
            self.assertEqual(len(imp_data.vertices), 24, "Ortho 3-Axes must have exactly 24 vertices.")
            self.assertEqual(len(imp_data.polygons), 6, "Ortho 3-Axes must have exactly 6 polygon faces.")

            # Verify PBR Impostor Material
            self.assertEqual(len(imp_data.materials), 1, "Impostor must have 1 material assigned.")
            mat = imp_data.materials[0]
            self.assertIsNotNone(mat)
            if mat is None or mat.node_tree is None:
                return
            self.assertEqual(mat.name, "M_SM_OrthoTree_Impostor")
            self.assertTrue(mat.use_nodes)

            node_names = {node.name for node in mat.node_tree.nodes}
            self.assertIn("Tex_BaseColor", node_names)
            self.assertIn("Tex_Normal", node_names)
            self.assertIn("Tex_ORM", node_names)

    def test_generate_impostor_octahedral(self) -> None:
        """Verify OCTAHEDRAL_HEMI billboard geometry (single camera-facing cutout octagon, 8 verts, 1 face)."""
        with in_blender_sandbox() as scene:
            if scene is None or bpy is None:
                return
            mesh_objs = create_hierarchy_fixture("SM_OctaTree")
            for obj in mesh_objs:
                obj.select_set(True)
            scene.view_layers[0].objects.active = mesh_objs[0]

            props: Any = getattr(scene, "lod_tool", None)
            if props is None:
                return
            props.export_base_name = "SM_OctaTree"
            props.impostor_mode = "OCTAHEDRAL_HEMI"
            props.target_engine = "UE5"
            props.export_directory = self._get_isolated_export_dir()
            props.auto_impostor_resolution = False
            props.impostor_resolution = "512"

            ops: Any = cast(Any, bpy.ops).lod_tool
            res = ops.generate_impostor()
            self.assertEqual(res, {"FINISHED"})

            target_coll = bpy.data.collections.get("SM_OctaTree_LOD_Impostor")
            self.assertIsNotNone(target_coll)
            if target_coll is None:
                return

            imp_obj = target_coll.objects.get("SM_OctaTree_LOD_Impostor")
            self.assertIsNotNone(imp_obj)
            if imp_obj is None:
                return
            imp_data: Any = imp_obj.data
            self.assertEqual(imp_obj.get("_impostor_mode", ""), "OCTAHEDRAL_HEMI")
            self.assertEqual(len(imp_data.vertices), 8, "Cutout octagon card must have exactly 8 vertices.")
            self.assertEqual(len(imp_data.polygons), 1, "Cutout octagon card must have exactly 1 polygon face.")

    def test_impostor_material_engine_routing(self) -> None:
        """Verify direct engine shader routing (Unity 6 MaskMap invert) and canonical operator repacking."""
        import os
        from core.impostor import ImpostorManager

        with in_blender_sandbox() as scene:
            if scene is None or bpy is None:
                return
            direct_mat = ImpostorManager.create_impostor_material(
                "DirectUnityMat", target_engine="UNITY_6", blend_data=bpy.data
            )
            self.assertIsNotNone(direct_mat)
            if direct_mat and direct_mat.node_tree:
                invert_nodes = [node for node in direct_mat.node_tree.nodes if getattr(node, "type", "") == "INVERT"]
                self.assertGreater(
                    len(invert_nodes), 0, "Direct UNITY_6 Impostor material must include Invert node for roughness."
                )

            mesh_objs = create_hierarchy_fixture("SM_ShaderAsset")
            for obj in mesh_objs:
                obj.select_set(True)
            scene.view_layers[0].objects.active = mesh_objs[0]

            export_dir = self._get_isolated_export_dir()
            props: Any = getattr(scene, "lod_tool", None)
            if props is None:
                return
            props.export_base_name = "SM_ShaderAsset"
            props.impostor_mode = "ORTHO_3_AXES"
            props.target_engine = "UNITY_6"
            props.pbr_export_preset = "unity_hdrp_maskmap"
            props.export_directory = export_dir
            props.auto_impostor_resolution = False
            props.impostor_resolution = "512"

            ops: Any = cast(Any, bpy.ops).lod_tool
            res = ops.generate_impostor()
            self.assertEqual(res, {"FINISHED"})

            imp_obj = bpy.data.objects.get("SM_ShaderAsset_LOD_Impostor")
            self.assertIsNotNone(imp_obj)
            if imp_obj is not None:
                self.assertTrue(bool(imp_obj.get("_impostor_canonical", False)))

            tex_dir = os.path.join(export_dir, "Textures")
            # Baking creates ONLY canonical engine-independent master textures (no MaskMap until export/pack)
            self.assertTrue(os.path.isfile(os.path.join(tex_dir, "T_SM_ShaderAsset_Impostor_BaseColor.png")))
            self.assertTrue(os.path.isfile(os.path.join(tex_dir, "T_SM_ShaderAsset_Impostor_Normal.png")))
            self.assertTrue(os.path.isfile(os.path.join(tex_dir, "T_SM_ShaderAsset_Impostor_ORM.png")))
            self.assertFalse(os.path.isfile(os.path.join(tex_dir, "T_SM_ShaderAsset_Impostor_MaskMap.png")))

            # Pack for Unity HDRP -> MaskMap is created from canonical masters
            pack_unity = ops.pack_pbr_textures()
            self.assertEqual(pack_unity, {"FINISHED"})
            self.assertTrue(os.path.isfile(os.path.join(tex_dir, "T_SM_ShaderAsset_Impostor_MaskMap.png")))

            # Switch target preset to UE5 without re-baking Cycles and repack in headless Blender (no PIL)
            props.target_engine = "UE5"
            props.pbr_export_preset = "unreal_engine_5"
            pack_res = ops.pack_pbr_textures()
            self.assertEqual(pack_res, {"FINISHED"})
            self.assertTrue(os.path.isfile(os.path.join(tex_dir, "T_SM_ShaderAsset_Impostor_Normal_DirectX.png")))

    def test_impostor_shader_harness_unlit_override_passes(self) -> None:
        """Verify ImpostorShaderHarness builds emission shaders for BASE_COLOR, NORMAL, DEPTH, and ORM passes."""
        from core.impostor_harness import ImpostorShaderHarness

        with in_blender_sandbox():
            src_mat = bpy.data.materials.new("M_SourceTest")
            src_mat.use_nodes = True

            for pass_name in ("BASE_COLOR", "NORMAL", "DEPTH", "ORM"):
                unlit_mat = ImpostorShaderHarness.create_unlit_override_material(
                    source_mat=src_mat,
                    channel_layer=pass_name,
                    target_engine="UE5",
                    blend_data=bpy.context.blend_data,
                )
                self.assertIsNotNone(unlit_mat, f"Unlit material for pass {pass_name} must not be None.")
                if unlit_mat is None or unlit_mat.node_tree is None:
                    continue
                self.assertTrue(unlit_mat.use_nodes)
                node_types = {n.type for n in unlit_mat.node_tree.nodes}
                self.assertIn("EMISSION", node_types)
                self.assertIn("OUTPUT_MATERIAL", node_types)

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

    def test_octahedral_sphere_bake_shaders_and_repack_masters(self) -> None:
        """Verify OCTAHEDRAL_SPHERE baking, companion HLSL shaders, and master backup preservation on repack."""
        import os

        from core.impostor_repacker import CanonicalImpostorSources, ImpostorTextureRepacker
        from core.png_writer import write_png_direct

        with in_blender_sandbox() as scene:
            if scene is None or bpy is None:
                return
            mesh_objs = create_hierarchy_fixture("SM_SphereAsset")
            for obj in mesh_objs:
                obj.select_set(True)
            scene.view_layers[0].objects.active = mesh_objs[0]

            export_dir = self._get_isolated_export_dir()
            props: Any = getattr(scene, "lod_tool", None)
            if props is None:
                return
            props.export_base_name = "SM_SphereAsset"
            props.impostor_mode = "OCTAHEDRAL_HEMI"
            props.impostor_render_underside = True
            props.impostor_grid_size = 4
            props.auto_impostor_resolution = False
            props.impostor_resolution = "512"
            props.target_engine = "UE5"
            props.pbr_export_preset = "unreal_engine_5"
            props.export_directory = export_dir

            ops: Any = cast(Any, bpy.ops).lod_tool
            res = ops.generate_impostor()
            self.assertEqual(res, {"FINISHED"})

            imp_obj = bpy.data.objects.get("SM_SphereAsset_LOD_Impostor")
            self.assertIsNotNone(imp_obj)
            if imp_obj is None:
                return
            self.assertEqual(imp_obj.get("_impostor_mode", ""), "OCTAHEDRAL_SPHERE")
            self.assertEqual(imp_obj.get("_impostor_grid_size", 0), 4)
            self.assertTrue(bool(imp_obj.get("_impostor_canonical", False)))

            tex_dir = os.path.join(export_dir, "Textures")
            bc_path = os.path.join(tex_dir, "T_SM_SphereAsset_Impostor_BaseColor.png")
            norm_path = os.path.join(tex_dir, "T_SM_SphereAsset_Impostor_Normal.png")
            orm_path = os.path.join(tex_dir, "T_SM_SphereAsset_Impostor_ORM.png")
            self.assertTrue(os.path.isfile(bc_path))
            self.assertTrue(os.path.isfile(norm_path))
            self.assertTrue(os.path.isfile(orm_path))

            # Companion HLSL shaders emitted alongside octahedral bake (UE5 setup guide is written on repack/export)
            shader_dir = os.path.join(tex_dir, "shaders")
            self.assertTrue(os.path.isfile(os.path.join(shader_dir, "SM_SphereAsset_Octahedral.hlsl")))
            self.assertTrue(os.path.isfile(os.path.join(shader_dir, "SM_SphereAsset_Octahedral_UE5.hlsl")))
            self.assertFalse(os.path.isfile(os.path.join(tex_dir, "README_SM_SphereAsset_UE5_SETUP.txt")))

            # Verify bound octahedral preview material graph
            imp_mesh: Any = imp_obj.data
            imp_mat = imp_mesh.materials[0] if imp_mesh and imp_mesh.materials else None
            self.assertIsNotNone(imp_mat)
            if imp_mat and imp_mat.node_tree:
                tex_base = imp_mat.node_tree.nodes.get("Tex_BaseColor")
                self.assertIsNotNone(tex_base)
                self.assertIsNotNone(getattr(tex_base, "image", None))

            # Repack in-place and confirm *_Master.png backups & UE5 setup guide are emitted
            pack_res = ops.pack_pbr_textures()
            self.assertEqual(pack_res, {"FINISHED"})
            self.assertTrue(os.path.isfile(os.path.join(tex_dir, "T_SM_SphereAsset_Impostor_BaseColor_Master.png")))
            self.assertTrue(os.path.isfile(os.path.join(tex_dir, "T_SM_SphereAsset_Impostor_Normal_DirectX.png")))
            self.assertTrue(os.path.isfile(os.path.join(tex_dir, "README_SM_SphereAsset_UE5_SETUP.txt")))

            # Negative boundary: mismatched Normal dimensions must raise ValueError
            bad_norm = os.path.join(tex_dir, "bad_norm.png")
            write_png_direct(bad_norm, np.zeros((16, 16, 4), dtype=np.uint8))
            bad_src = CanonicalImpostorSources(
                base_name="SM_SphereAsset",
                base_color_path=bc_path,
                normal_path=bad_norm,
                orm_path=orm_path,
            )
            with self.assertRaises(ValueError):
                ImpostorTextureRepacker.repack_impostor_textures(bad_src, tex_dir, target_engine="UE5")

    def test_impostor_selected_to_active_bake_and_restore_state(self) -> None:
        """Verify Cycles selected-to-active impostor bake writes PBR maps and restores scene render state."""
        import os

        import bmesh
        from core.impostor_baker import ImpostorAtlasBaker

        with in_blender_sandbox() as scene:
            if scene is None or bpy is None:
                return

            mesh_objs = create_hierarchy_fixture("SM_S2A")
            cast(Any, scene.render).engine = "BLENDER_WORKBENCH"
            scene.render.film_transparent = False

            # Build UV-mapped quad target overlapping source fixture
            quad_mesh = bpy.data.meshes.new("SM_S2A_Quad_Mesh")
            bm = bmesh.new()
            uv_layer = bm.loops.layers.uv.new("UVMap")
            v0 = bm.verts.new((-1.5, 0.0, -1.5))
            v1 = bm.verts.new((1.5, 0.0, -1.5))
            v2 = bm.verts.new((1.5, 0.0, 2.5))
            v3 = bm.verts.new((-1.5, 0.0, 2.5))
            face = bm.faces.new((v0, v1, v2, v3))
            uvs = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
            for loop, uv in zip(face.loops, uvs, strict=True):
                loop[uv_layer].uv = uv
            bm.to_mesh(quad_mesh)
            bm.free()

            imp_obj = bpy.data.objects.new("SM_S2A_LOD_Impostor", quad_mesh)
            scene.collection.objects.link(imp_obj)

            out_dir = self._get_isolated_export_dir()
            baked = ImpostorAtlasBaker.bake_impostor_textures(
                mesh_objs=mesh_objs,
                base_name="SM_S2A",
                output_dir=out_dir,
                mode="14_PLANES",
                atlas_resolution=64,
                target_engine="UE5",
                impostor_obj=imp_obj,
                context=bpy.context,
                blend_data=bpy.data,
            )

            self.assertIn("BaseColor", baked)
            self.assertIn("Normal", baked)
            self.assertIn("ORM", baked)
            for p in baked.values():
                self.assertTrue(os.path.isfile(p), f"Expected baked file at {p}")

            # Verify render engine and transparency state restored
            self.assertEqual(scene.render.engine, "BLENDER_WORKBENCH")
            self.assertFalse(scene.render.film_transparent)

            # Empty mesh list negative boundary returns {}
            self.assertEqual(
                ImpostorAtlasBaker.bake_impostor_textures(
                    mesh_objs=[],
                    base_name="SM_Empty",
                    output_dir=out_dir,
                    context=bpy.context,
                    blend_data=bpy.data,
                ),
                {},
            )

    def test_impostor_preview_rig_turntable_and_teardown(self) -> None:
        """Verify setup_impostor_preview_rig creates isolated tracking/turntable and teardown cleans up."""
        import os

        from core.impostor_baker import ImpostorAtlasBaker
        from core.impostor_preview import setup_impostor_preview_rig, teardown_impostor_preview_rig

        with in_blender_sandbox() as scene:
            if scene is None or bpy is None:
                return

            mesh_objs = create_hierarchy_fixture("SM_PrevRig")
            orig_loc = mesh_objs[0].location.copy()
            out_dir = self._get_isolated_export_dir()

            baked = ImpostorAtlasBaker.bake_octahedral_animation_atlas(
                mesh_objs=mesh_objs,
                base_name="SM_PrevRig",
                output_dir=out_dir,
                mode="OCTAHEDRAL_HEMI",
                atlas_resolution=128,
                target_engine="UE5",
                grid_size=4,
                context=bpy.context,
                blend_data=bpy.data,
            )
            self.assertIn("BaseColor", baked)
            tex_dir = os.path.dirname(baked["BaseColor"])

            rig_info = setup_impostor_preview_rig(
                context=bpy.context,
                mesh_objs=mesh_objs,
                base_name="SM_PrevRig",
                texture_dir=tex_dir,
                mode="SIDE_BY_SIDE",
                num_frames=8,
                target_engine="UE5",
                create_turntable=True,
                grid_size=4,
                impostor_mode="OCTAHEDRAL_HEMI",
                blend_data=bpy.data,
            )
            self.assertEqual(rig_info.get("collection"), "SM_PrevRig_Preview_Rig")
            self.assertIsNotNone(bpy.data.collections.get("SM_PrevRig_Preview_Rig"))

            proxy_obj = bpy.data.objects.get("SM_PrevRig_Preview_Impostor")
            cam_obj = bpy.data.objects.get("SM_PrevRig_Preview_Camera")
            self.assertIsNotNone(proxy_obj)
            self.assertIsNotNone(cam_obj)
            if proxy_obj is not None:
                track_con = proxy_obj.constraints.get("OmniMesh_Preview_Track")
                self.assertIsNotNone(track_con)
            if cam_obj is not None:
                self.assertIsNotNone(cam_obj.animation_data)
                self.assertEqual(scene.frame_end, 8)
            self.assertEqual(scene.camera, cam_obj)

            # Production mesh transforms and animation remain untouched
            self.assertIsNone(mesh_objs[0].animation_data)
            cur_loc = mesh_objs[0].location
            self.assertEqual(
                (float(cur_loc.x), float(cur_loc.y), float(cur_loc.z)),
                (float(orig_loc.x), float(orig_loc.y), float(orig_loc.z)),
            )

            # Teardown removes collection, material, and restores active camera
            self.assertTrue(teardown_impostor_preview_rig(bpy.context, "SM_PrevRig", blend_data=bpy.data))
            self.assertIsNone(bpy.data.collections.get("SM_PrevRig_Preview_Rig"))
            self.assertIsNone(bpy.data.materials.get("M_SM_PrevRig_Octahedral_Preview"))
            self.assertFalse(teardown_impostor_preview_rig(bpy.context, "MissingRig", blend_data=bpy.data))
