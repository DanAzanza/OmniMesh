"""
Unit tests for OmniMesh Automated PBR Texture Importer & Multi-Channel Shader Graph Builder.
"""

from __future__ import annotations

import os
import tempfile
from unittest.mock import MagicMock

from core.pbr_importer import (
    BatchMaterialSlotMatcher,
    OCIOColorSpaceResolver,
    PBRSemanticClassifier,
    ShaderGraphBuilder,
)
from core.pbr_presets import PBRImporterPresetManager


def test_pbr_semantic_classifier_tokens():
    # Base Color / Albedo
    assert PBRSemanticClassifier.classify("T_Wood_BaseColor.png") == "BASE_COLOR"
    assert PBRSemanticClassifier.classify("T_Wood_Albedo.png") == "BASE_COLOR"
    assert PBRSemanticClassifier.classify("T_Wood_diffuse.jpg") == "BASE_COLOR"
    assert PBRSemanticClassifier.classify("T_Wood_col.tga") == "BASE_COLOR"

    # Strict token isolation: Gun.png should NOT match normal or albedo by accident
    assert PBRSemanticClassifier.classify("Gun.png") is None
    assert PBRSemanticClassifier.classify("Head.png") is None
    assert PBRSemanticClassifier.classify("Door.png") is None

    # Normal maps
    assert PBRSemanticClassifier.classify("T_Brick_Normal.png") == "NORMAL_DIRECTX"  # default UE5 normal
    assert PBRSemanticClassifier.classify("T_Brick_Normal_DX.png") == "NORMAL_DIRECTX"

    # Roughness & Metallic
    assert PBRSemanticClassifier.classify("T_Metal_Roughness.png") == "ROUGHNESS_LOOSE"
    assert PBRSemanticClassifier.classify("T_Gold_Metallic.png") == "METALLIC_LOOSE"

    # Packed maps
    assert PBRSemanticClassifier.classify("T_Vehicle_ORM.png") == "PACKED_ORM"
    assert PBRSemanticClassifier.classify("T_Vehicle_arm.png") == "PACKED_ORM"


def test_udim_and_resolution_tag_stripping():
    # UDIM tiles
    assert PBRSemanticClassifier.classify("T_Character_BaseColor_1001.png") == "BASE_COLOR"
    assert PBRSemanticClassifier.classify("T_Character_Normal_1002.png") == "NORMAL_DIRECTX"
    assert PBRSemanticClassifier.classify("T_Character_Roughness_u1_v1.png") == "ROUGHNESS_LOOSE"

    # Resolution & LOD suffixes
    assert PBRSemanticClassifier.classify("T_Rock_BaseColor_4k.png") == "BASE_COLOR"
    assert PBRSemanticClassifier.classify("T_Rock_Normal_2048.png") == "NORMAL_DIRECTX"
    assert PBRSemanticClassifier.classify("T_Rock_Roughness_LOD0.png") == "ROUGHNESS_LOOSE"


def test_directx_precedence_over_generic_normal():
    ue5_preset = PBRImporterPresetManager.get_preset("unreal_engine_5")
    res_dx = PBRSemanticClassifier.classify_with_preset("T_Wall_normal_dx.png", ue5_preset)
    assert res_dx is not None
    assert res_dx[0] == "normal"
    assert res_dx[1]["normal_format"] == "DIRECTX"

    res_norm = PBRSemanticClassifier.classify_with_preset("T_Wall_normal.png", ue5_preset)
    assert res_norm is not None
    assert res_norm[0] == "normal"


def test_classify_with_unity_hdrp_preset():
    unity_preset = PBRImporterPresetManager.get_preset("unity_hdrp_maskmap")
    res_base = PBRSemanticClassifier.classify_with_preset("T_Hero_BaseMap.png", unity_preset)
    assert res_base is not None and res_base[0] == "base_map"

    res_mask = PBRSemanticClassifier.classify_with_preset("T_Hero_MaskMap.png", unity_preset)
    assert res_mask is not None and res_mask[0] == "mask_map"
    assert res_mask[1]["channels"]["a"]["invert"] is True  # Smoothness -> Roughness inversion

    res_norm = PBRSemanticClassifier.classify_with_preset("T_Hero_Normal_GL.png", unity_preset)
    assert res_norm is not None and res_norm[0] == "normal"
    assert res_norm[1]["normal_format"] == "OPENGL"


def test_classify_with_msfs_preset():
    msfs_preset = PBRImporterPresetManager.get_preset("msfs_2024_comp")
    res_comp = PBRSemanticClassifier.classify_with_preset("A320_Fuselage_COMP.png", msfs_preset)
    assert res_comp is not None and res_comp[0] == "comp"


def test_batch_material_slot_matcher_longest_prefix():
    class DummySlot:
        def __init__(self, name: str):
            self.name = name

    class DummyObj:
        def __init__(self, slot_names: list[str]):
            self.material_slots = [DummySlot(n) for n in slot_names]

    with tempfile.TemporaryDirectory() as tmpdir:
        fnames = [
            "Mat_Hull_Interior_BaseColor.png",
            "Mat_Hull_Interior_Normal.png",
            "Mat_Hull_BaseColor.png",
            "Mat_Hull_Normal.png",
            "Mat_Hull_Roughness.png",
        ]
        for fn in fnames:
            with open(os.path.join(tmpdir, fn), "w") as f:
                f.write("dummy")

        obj = DummyObj(["Mat_Hull", "Mat_Hull_Interior"])
        matches = BatchMaterialSlotMatcher.match_directory_to_slots(obj, tmpdir)

        # Mat_Hull_Interior should get its specific textures
        assert "base_color" in matches["Mat_Hull_Interior"]
        assert "Mat_Hull_Interior_BaseColor.png" in matches["Mat_Hull_Interior"]["base_color"]

        # Mat_Hull should get its specific textures
        assert "base_color" in matches["Mat_Hull"]
        assert "Mat_Hull_BaseColor.png" in matches["Mat_Hull"]["base_color"]
        assert "roughness_loose" in matches["Mat_Hull"]


def test_batch_material_slot_matcher_single_slot_fallback():
    class DummySlot:
        def __init__(self, name: str):
            self.name = name

    class DummyObj:
        def __init__(self, slot_names: list[str]):
            self.material_slots = [DummySlot(n) for n in slot_names]

    with tempfile.TemporaryDirectory() as tmpdir:
        with open(os.path.join(tmpdir, "Albedo.png"), "w") as f:
            f.write("dummy")
        with open(os.path.join(tmpdir, "Normal.png"), "w") as f:
            f.write("dummy")

        obj = DummyObj(["Material_Main"])
        matches = BatchMaterialSlotMatcher.match_directory_to_slots(obj, tmpdir)

        assert "base_color" in matches["Material_Main"]
        assert "normal" in matches["Material_Main"]


def test_ocio_colorspace_resolver_safe_mock():
    mock_img = MagicMock()
    mock_prop = MagicMock()
    mock_item1 = MagicMock()
    mock_item1.identifier = "Non-Color"
    mock_prop.enum_items = [mock_item1]
    mock_img.colorspace_settings.bl_rna.properties = {"name": mock_prop}

    OCIOColorSpaceResolver.apply_colorspace(mock_img, is_data=True)
    assert mock_img.colorspace_settings.name == "Non-Color"

    # Non-data texture
    mock_item2 = MagicMock()
    mock_item2.identifier = "sRGB"
    mock_prop.enum_items = [mock_item2]
    OCIOColorSpaceResolver.apply_colorspace(mock_img, is_data=False)
    assert mock_img.colorspace_settings.name == "sRGB"


def test_get_mix_rgba_socket_duplicate_names_guard():
    """Verify get_mix_rgba_socket avoids returning Float sockets with identical names 'A' / 'B'."""

    class DummySocket:
        def __init__(self, name: str, sock_type: str):
            self.name = name
            self.type = sock_type

    class DummyMixNode:
        def __init__(self):
            self.inputs = [
                DummySocket("Factor", "VALUE"),
                DummySocket("A", "VALUE"),  # Float socket A
                DummySocket("B", "VALUE"),  # Float socket B
                DummySocket("A", "VECTOR"),  # Vector socket A
                DummySocket("B", "VECTOR"),  # Vector socket B
                DummySocket("A", "RGBA"),  # Color RGBA socket A
                DummySocket("B", "RGBA"),  # Color RGBA socket B
            ]
            self.outputs = [
                DummySocket("Result", "VALUE"),
                DummySocket("Result", "VECTOR"),
                DummySocket("Result", "RGBA"),
            ]

    mix_node = DummyMixNode()
    sock_a = ShaderGraphBuilder.get_mix_rgba_socket(mix_node, "A", is_output=False)
    assert sock_a is not None
    assert sock_a.type == "RGBA"
    assert sock_a == mix_node.inputs[5]

    sock_b = ShaderGraphBuilder.get_mix_rgba_socket(mix_node, "B", is_output=False)
    assert sock_b is not None
    assert sock_b.type == "RGBA"
    assert sock_b == mix_node.inputs[6]

    res_out = ShaderGraphBuilder.get_mix_rgba_socket(mix_node, "Result", is_output=True)
    assert res_out is not None
    assert res_out.type == "RGBA"
    assert res_out == mix_node.outputs[2]


def test_shader_graph_builder_bsdf_socket_query():
    mock_bsdf = MagicMock()
    mock_sock = MagicMock()
    mock_bsdf.inputs = {"Base Color": mock_sock}

    # Query with alias fallback
    res = ShaderGraphBuilder.get_bsdf_socket(mock_bsdf, ["Albedo", "Base Color", "BaseColor"])
    assert res == mock_sock

    res_none = ShaderGraphBuilder.get_bsdf_socket(mock_bsdf, ["NonExistent"])
    assert res_none is None
