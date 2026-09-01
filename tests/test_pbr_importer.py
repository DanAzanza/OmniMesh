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
    assert PBRSemanticClassifier.classify("T_Brick_Normal.png") == "NORMAL_OPENGL"
    assert PBRSemanticClassifier.classify("T_Brick_nor_gl.png") == "NORMAL_OPENGL"
    assert PBRSemanticClassifier.classify("T_Brick_Normal_DX.png") == "NORMAL_DIRECTX"
    assert PBRSemanticClassifier.classify("T_Brick_nor_dx.png") == "NORMAL_DIRECTX"

    # Roughness & Glossiness
    assert PBRSemanticClassifier.classify("T_Metal_Roughness.png") == "ROUGHNESS"
    assert PBRSemanticClassifier.classify("T_Metal_rgh.png") == "ROUGHNESS"
    assert PBRSemanticClassifier.classify("T_Metal_Glossiness.png") == "GLOSSINESS"
    assert PBRSemanticClassifier.classify("T_Metal_smoothness.png") == "GLOSSINESS"

    # Metallic
    assert PBRSemanticClassifier.classify("T_Gold_Metallic.png") == "METALLIC"
    assert PBRSemanticClassifier.classify("T_Gold_metal.png") == "METALLIC"

    # AO & Emission
    assert PBRSemanticClassifier.classify("T_Car_AO.png") == "AMBIENT_OCCLUSION"
    assert PBRSemanticClassifier.classify("T_Car_ambient_occlusion.png") == "AMBIENT_OCCLUSION"
    assert PBRSemanticClassifier.classify("T_Light_Emission.png") == "EMISSION"
    assert PBRSemanticClassifier.classify("T_Light_emissive.png") == "EMISSION"

    # Opacity / Alpha & Displacement
    assert PBRSemanticClassifier.classify("T_Foliage_Opacity.png") == "OPACITY"
    assert PBRSemanticClassifier.classify("T_Foliage_alpha.png") == "OPACITY"
    assert PBRSemanticClassifier.classify("T_Terrain_Height.png") == "DISPLACEMENT"
    assert PBRSemanticClassifier.classify("T_Terrain_disp.png") == "DISPLACEMENT"

    # Packed maps
    assert PBRSemanticClassifier.classify("T_Vehicle_ORM.png") == "PACKED_ORM"
    assert PBRSemanticClassifier.classify("T_Vehicle_arm.png") == "PACKED_ORM"
    assert PBRSemanticClassifier.classify("T_Plane_COMP.png") == "PACKED_COMP"
    assert PBRSemanticClassifier.classify("T_Prop_MaskMap.png") == "PACKED_MASKMAP"


def test_udim_and_resolution_tag_stripping():
    # UDIM tiles
    assert PBRSemanticClassifier.classify("T_Character_BaseColor_1001.png") == "BASE_COLOR"
    assert PBRSemanticClassifier.classify("T_Character_Normal_1002.png") == "NORMAL_OPENGL"
    assert PBRSemanticClassifier.classify("T_Character_Roughness_u1_v1.png") == "ROUGHNESS"

    # Resolution & LOD suffixes
    assert PBRSemanticClassifier.classify("T_Rock_BaseColor_4k.png") == "BASE_COLOR"
    assert PBRSemanticClassifier.classify("T_Rock_Normal_2048.png") == "NORMAL_OPENGL"
    assert PBRSemanticClassifier.classify("T_Rock_Roughness_LOD0.png") == "ROUGHNESS"


def test_directx_precedence_over_generic_normal():
    # DirectX contains 'normal' as a substring, but must strictly classify as NORMAL_DIRECTX
    assert PBRSemanticClassifier.classify("T_Wall_normal_dx.png") == "NORMAL_DIRECTX"
    assert PBRSemanticClassifier.classify("T_Wall_Normal_DirectX.png") == "NORMAL_DIRECTX"
    assert PBRSemanticClassifier.classify("T_Wall_normal.png") == "NORMAL_OPENGL"


def test_batch_material_slot_matcher_longest_prefix():
    class DummySlot:
        def __init__(self, name: str):
            self.name = name

    class DummyObj:
        def __init__(self, slot_names: list[str]):
            self.material_slots = [DummySlot(n) for n in slot_names]

    with tempfile.TemporaryDirectory() as tmpdir:
        # Create test texture files
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
        assert "BASE_COLOR" in matches["Mat_Hull_Interior"]
        assert "Mat_Hull_Interior_BaseColor.png" in matches["Mat_Hull_Interior"]["BASE_COLOR"]

        # Mat_Hull should get its specific textures
        assert "BASE_COLOR" in matches["Mat_Hull"]
        assert "Mat_Hull_BaseColor.png" in matches["Mat_Hull"]["BASE_COLOR"]
        assert "ROUGHNESS" in matches["Mat_Hull"]


def test_batch_material_slot_matcher_single_slot_fallback():
    class DummySlot:
        def __init__(self, name: str):
            self.name = name

    class DummyObj:
        def __init__(self, slot_names: list[str]):
            self.material_slots = [DummySlot(n) for n in slot_names]

    with tempfile.TemporaryDirectory() as tmpdir:
        # Generic texture filenames
        with open(os.path.join(tmpdir, "Albedo.png"), "w") as f:
            f.write("dummy")
        with open(os.path.join(tmpdir, "Normal.png"), "w") as f:
            f.write("dummy")

        obj = DummyObj(["Material_Main"])
        matches = BatchMaterialSlotMatcher.match_directory_to_slots(obj, tmpdir)

        assert "BASE_COLOR" in matches["Material_Main"]
        assert "NORMAL_OPENGL" in matches["Material_Main"]


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


def test_shader_graph_builder_bsdf_socket_query():
    mock_bsdf = MagicMock()
    mock_sock = MagicMock()
    mock_bsdf.inputs = {"Base Color": mock_sock}

    # Query with alias fallback
    res = ShaderGraphBuilder.get_bsdf_socket(mock_bsdf, ["Albedo", "Base Color", "BaseColor"])
    assert res == mock_sock

    res_none = ShaderGraphBuilder.get_bsdf_socket(mock_bsdf, ["NonExistent"])
    assert res_none is None
