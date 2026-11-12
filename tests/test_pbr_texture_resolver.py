from __future__ import annotations

import os
from pathlib import Path
import tempfile
from typing import Any
from unittest.mock import MagicMock, patch

from core.texture_resolver import (
    PBRTextureResolver,
    TextureResolutionSummary,
    UnresolvedTexture,
)


class MockSocket:
    def __init__(self, name: str, node: Any = None):
        self.name = name
        self.node = node
        self.links: list[Any] = []


class MockLink:
    def __init__(self, from_node: Any, from_socket: Any, to_node: Any, to_socket: Any):
        self.from_node = from_node
        self.from_socket = from_socket
        self.to_node = to_node
        self.to_socket = to_socket


class MockNode:
    def __init__(self, name: str, node_type: str = "TEX_IMAGE", label: str = ""):
        self.name = name
        self.type = node_type
        self.label = label
        self.image: Any = None
        self.outputs: list[MockSocket] = [MockSocket("Color", self), MockSocket("Alpha", self)]
        self.inputs: list[MockSocket] = []
        self.node_tree: Any = None


class MockNodeTree:
    def __init__(self, nodes: list[MockNode] | None = None):
        self.nodes = nodes or []


class MockMaterial:
    def __init__(self, name: str, node_tree: MockNodeTree | None = None, use_nodes: bool = True):
        self.name = name
        self.node_tree = node_tree or MockNodeTree()
        self.use_nodes = use_nodes


class MockImage:
    def __init__(self, name: str, filepath: str = "", source: str = "FILE"):
        self.name = name
        self.filepath = filepath
        self.source = source
        self.packed_file = None
        self.packed_files = []
        self.has_data = True
        self.reload_called = False

    def reload(self) -> None:
        self.reload_called = True


def test_sanitize_material_name():
    assert PBRTextureResolver.sanitize_material_name("M_Fuselage") == "Fuselage"
    assert PBRTextureResolver.sanitize_material_name("MAT_Cockpit.001") == "Cockpit"
    assert PBRTextureResolver.sanitize_material_name("MI_Wing_Top.002") == "Wing_Top"
    assert PBRTextureResolver.sanitize_material_name("FUSELAGE") == "FUSELAGE"


def test_deduce_texture_type():
    # 1. From node label / filename
    node1 = MockNode("Tex_Base", "TEX_IMAGE", label="Base Color")
    assert PBRTextureResolver.deduce_texture_type(node1, "") == "ALBEDO"  # type: ignore

    node2 = MockNode("Tex_Norm", "TEX_IMAGE", label="Normal")
    assert PBRTextureResolver.deduce_texture_type(node2, "D:/tex/fuselage_norm.png") == "NORMAL"  # type: ignore

    # 2. Downstream socket tracing
    node3 = MockNode("Unknown_Tex", "TEX_IMAGE", label="")
    bsdf = MockNode("Principled BSDF", "BSDF_PRINCIPLED")
    bsdf_color_sock = MockSocket("Base Color", bsdf)
    link = MockLink(node3, node3.outputs[0], bsdf, bsdf_color_sock)
    node3.outputs[0].links = [link]
    assert PBRTextureResolver.deduce_texture_type(node3, "") == "ALBEDO"  # type: ignore


def test_extract_all_texture_nodes_with_nested_groups():
    tex1 = MockNode("Tex1", "TEX_IMAGE")
    tex2 = MockNode("Tex2", "TEX_IMAGE")

    # Group node containing tex2
    group_tree = MockNodeTree([tex2])
    group_node = MockNode("Group", "GROUP")
    group_node.node_tree = group_tree

    # Cyclic reference to test infinite loop guard
    cyclic_group = MockNode("CyclicGroup", "GROUP")
    group_tree.nodes.append(cyclic_group)

    root_tree = MockNodeTree([tex1, group_node])
    cyclic_group.node_tree = root_tree

    nodes = PBRTextureResolver.extract_all_texture_nodes(root_tree)  # type: ignore
    assert len(nodes) == 2
    assert tex1 in nodes
    assert tex2 in nodes


def test_find_texture_by_preset_pattern():
    cand_other = Path("C:/Project/Textures/OtherAsset_FUSELAGE_albd.png")
    cand_exact = Path("C:/Project/Textures/SimpleAircraft_FUSELAGE_albd_000.png")
    # Both match material and albedo, but cand_exact matches asset_name
    index = {
        "otherasset_fuselage_albd.png": [cand_other],
        "simpleaircraft_fuselage_albd_000.png": [cand_exact],
    }

    match = PBRTextureResolver.find_texture_by_preset_pattern(
        asset_name="SimpleAircraft",
        material_name="FUSELAGE",
        texture_type="ALBEDO",
        texture_index=index,
    )
    assert match == cand_exact

    # Fallback to cand_other when asset_name does not match any key
    match_fallback = PBRTextureResolver.find_texture_by_preset_pattern(
        asset_name="NonExistentAsset",
        material_name="FUSELAGE",
        texture_type="ALBEDO",
        texture_index=index,
    )
    assert match_fallback == cand_other

    # Custom preset suffix matching
    cand_custom = Path("C:/Project/Textures/SimpleAircraft_FUSELAGE_CustomColor.png")
    index_custom = {"simpleaircraft_fuselage_customcolor.png": [cand_custom]}
    custom_preset = {
        "name": "Custom Test",
        "maps": [
            {"id": "albedo", "suffixes": ["_CustomColor"]},
        ],
    }
    match_custom = PBRTextureResolver.find_texture_by_preset_pattern(
        asset_name="SimpleAircraft",
        material_name="FUSELAGE",
        texture_type="ALBEDO",
        texture_index=index_custom,
        preset=custom_preset,
    )
    assert match_custom == cand_custom

    # Negative isolation: NORMAL custom suffix must not match ALBEDO channel
    cand_norm = Path("C:/Project/Textures/SimpleAircraft_FUSELAGE_CustomNorm.png")
    index_norm = {"simpleaircraft_fuselage_customnorm.png": [cand_norm]}
    preset_norm = {
        "name": "Norm Custom Test",
        "maps": [
            {"id": "normal", "suffixes": ["_CustomNorm"]},
        ],
    }
    match_wrong_channel = PBRTextureResolver.find_texture_by_preset_pattern(
        asset_name="SimpleAircraft",
        material_name="FUSELAGE",
        texture_type="ALBEDO",
        texture_index=index_norm,
        preset=preset_norm,
    )
    assert match_wrong_channel is None

    # Boundary & Malformed Inputs: suffixes=None, non-dict map items, non-string tokens
    malformed_preset = {
        "name": "Malformed Preset",
        "maps": [
            None,
            123,
            {"id": "albedo", "suffixes": None},
            {"id": "albedo", "suffixes": [123, None, "", "_ValidCustom"]},
        ],
    }
    cand_valid = Path("C:/Project/Textures/SimpleAircraft_FUSELAGE_ValidCustom.png")
    index_malformed = {"simpleaircraft_fuselage_validcustom.png": [cand_valid]}
    match_malformed = PBRTextureResolver.find_texture_by_preset_pattern(
        asset_name="SimpleAircraft",
        material_name="FUSELAGE",
        texture_type="ALBEDO",
        texture_index=index_malformed,
        preset=malformed_preset,
    )
    assert match_malformed == cand_valid


def test_resolve_material_textures_relinks_and_reports_unresolved():
    temp_dir = str(Path(tempfile.mkdtemp()).resolve())
    try:
        tex_dir = os.path.join(temp_dir, "Textures")
        os.makedirs(tex_dir, exist_ok=True)

        albd_file = os.path.join(tex_dir, "SimpleAircraft_FUSELAGE_albd_000.png")
        with open(albd_file, "wb") as f:
            f.write(b"ALBD")

        # Create material with 2 texture nodes: 1 resolvable, 1 truly missing
        node_albd = MockNode("Albedo_Tex", "TEX_IMAGE")
        img_albd = MockImage("Broken_Albedo", "D:/Asobo/Dev/SimpleAircraft_FUSELAGE_albd_000.png")
        node_albd.image = img_albd

        node_norm = MockNode("Normal_Tex", "TEX_IMAGE", label="Normal")
        img_norm = MockImage("Missing_Normal", "D:/Asobo/Dev/SimpleAircraft_FUSELAGE_norm.png")
        node_norm.image = img_norm

        mat = MockMaterial("FUSELAGE", MockNodeTree([node_albd, node_norm]))

        from tests.conftest import MockBlendData

        summary = PBRTextureResolver.resolve_material_textures(
            materials=[mat],  # type: ignore
            search_roots=[temp_dir],
            asset_name="SimpleAircraft",
            blend_data=MockBlendData(),
        )

        assert isinstance(summary, TextureResolutionSummary)
        assert summary.total_nodes_checked == 2
        assert summary.relinked == 1
        assert summary.has_errors is True
        assert len(summary.unresolved) == 1
        assert summary.unresolved[0].material_name == "FUSELAGE"
        assert summary.unresolved[0].expected_type == "NORMAL"

        assert img_albd.reload_called is True
        assert Path(img_albd.filepath).resolve() == Path(albd_file).resolve()
    finally:
        import shutil

        shutil.rmtree(temp_dir, ignore_errors=True)


def test_resolve_material_textures_ignores_unassigned_optional_slots():
    """Confirms empty template nodes (image=None) with no matching preset files do not trigger false-positive errors."""
    temp_dir = tempfile.mkdtemp()
    try:
        # Create material with template slots that have no image assigned (standard in MSFS glTF)
        node_detail = MockNode("Detail Color(RGBA)", "TEX_IMAGE", label="Detail Color(RGBA)")
        node_detail.image = None

        node_mask = MockNode("Blend Mask", "TEX_IMAGE", label="Blend Mask")
        node_mask.image = None

        mat = MockMaterial("FUSELAGE", MockNodeTree([node_detail, node_mask]))

        from tests.conftest import MockBlendData

        summary = PBRTextureResolver.resolve_material_textures(
            materials=[mat],  # type: ignore
            search_roots=[temp_dir],
            asset_name="SimpleAircraft",
            blend_data=MockBlendData(),
        )

        assert isinstance(summary, TextureResolutionSummary)
        assert summary.total_nodes_checked == 0
        assert summary.relinked == 0
        assert summary.has_errors is False
        assert len(summary.unresolved) == 0
    finally:
        import shutil

        shutil.rmtree(temp_dir, ignore_errors=True)


def test_operator_import_pbr_set_error_toast_on_unresolved():
    from ui.pbr_ops import LOD_OT_import_pbr_set

    op = LOD_OT_import_pbr_set()
    op.report = MagicMock()

    mock_bpy = MagicMock()
    mock_bpy.data.filepath = "C:/Project/scene.blend"

    # Material with missing texture
    node_missing = MockNode("Missing_Tex", "TEX_IMAGE", label="Roughness")
    node_missing.image = MockImage("Missing", "D:/missing_comp.png")
    mat = MockMaterial("M_Wing", MockNodeTree([node_missing]))

    obj = MagicMock()
    obj.type = "MESH"
    slot = MagicMock()
    slot.material = mat
    obj.material_slots = [slot]

    context = MagicMock()
    context.scene.lod_tool.pbr_import_directory = "C:/EmptyDir"

    with (
        patch("ui.pbr_ops.bpy", mock_bpy),
        patch("ui.pbr_ops.get_lod0_mesh_objects", return_value=[obj]),
        patch("os.path.isdir", return_value=True),
        patch.object(
            PBRTextureResolver,
            "resolve_material_textures",
            return_value=TextureResolutionSummary(
                total_nodes_checked=1,
                already_valid=0,
                relinked=0,
                unresolved=(UnresolvedTexture("M_Wing", "Missing_Tex", "COMP", "D:/missing_comp.png"),),
            ),
        ),
    ):
        res = op.execute(context)
        assert res == {"FINISHED"}

        # Verify error toast was fired
        op.report.assert_called_once()
        args, _ = op.report.call_args
        assert args[0] == {"ERROR"}
        assert "M_Wing" in args[1]


def test_operator_import_pbr_set_invoke_opens_fileselect():
    """Verify LOD_OT_import_pbr_set.invoke opens the file/directory browser modal dialog."""
    from ui.pbr_ops import LOD_OT_import_pbr_set

    op = LOD_OT_import_pbr_set()
    mock_ctx = MagicMock()
    mock_props = MagicMock()
    mock_props.pbr_import_directory = "C:/Textures"
    mock_ctx.scene.lod_tool = mock_props

    mock_bpy = MagicMock()
    mock_bpy.path.abspath.return_value = "C:/Textures"

    with (
        patch("ui.pbr_ops.bpy", mock_bpy),
        patch("os.path.isdir", return_value=True),
    ):
        res = op.invoke(mock_ctx, MagicMock())
        assert res == {"RUNNING_MODAL"}
        assert op.directory == "C:/Textures"
        mock_ctx.window_manager.fileselect_add.assert_called_once_with(op)
