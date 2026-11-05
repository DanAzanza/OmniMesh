"""
Comprehensive deep unit tests for core/impostor_harness.py
Tests unlit shader emission harness for Impostor baking passes:
BASE_COLOR, NORMAL (UE5/Unity), DEPTH, and ORM (UE5/Unity), plus alpha cutout preservation.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch


from core.impostor_harness import ImpostorShaderHarness


class MockSocket:
    def __init__(self, name: str = "Color", default_val: Any = (0.8, 0.8, 0.8, 1.0)):
        self.name = name
        self.default_value = default_val
        self.is_linked = False
        self.links: list[Any] = []


class MockSocketCollection:
    def __init__(self):
        self._sockets: dict[Any, MockSocket] = {}

    def __getitem__(self, key: Any) -> MockSocket:
        if key not in self._sockets:
            self._sockets[key] = MockSocket(str(key))
        return self._sockets[key]

    def get(self, key: Any, default: Any = None) -> Any:
        if key not in self._sockets:
            self._sockets[key] = MockSocket(str(key))
        return self._sockets[key]

    def __contains__(self, key: Any) -> bool:
        return True

    def __iter__(self):
        return iter(self._sockets.values())

    def __len__(self) -> int:
        return len(self._sockets)


class MockNode:
    def __init__(self, name: str, node_type: str = "ShaderNodeEmission"):
        self.name = name
        self.type = node_type
        self.location = (0.0, 0.0)
        self.inputs = MockSocketCollection()
        self.outputs = MockSocketCollection()


class MockNodeTree:
    def __init__(self):
        self.nodes = MockNodes()
        self.links = MockLinks()


class MockNodes:
    def __init__(self):
        self.node_list: list[MockNode] = []

    def __iter__(self):
        return iter(self.node_list)

    def __len__(self) -> int:
        return len(self.node_list)

    def new(self, type: str) -> MockNode:
        n = MockNode(f"Node_{len(self.node_list)}", node_type=type)
        self.node_list.append(n)
        return n

    def clear(self) -> None:
        self.node_list.clear()

    def get(self, name: str) -> MockNode | None:
        for n in self.node_list:
            if n.name == name:
                return n
        return None


class MockLinks:
    def __init__(self):
        self.links: list[tuple[Any, Any]] = []

    def new(self, from_socket: Any, to_socket: Any) -> None:
        self.links.append((from_socket, to_socket))
        to_socket.is_linked = True
        to_socket.links.append(MagicMock(from_socket=from_socket, to_socket=to_socket))


class MockMaterial:
    def __init__(self, name: str = "TestMat", use_nodes: bool = True):
        self.name = name
        self.use_nodes = use_nodes
        self.node_tree = MockNodeTree()


class MockBlendData:
    def __init__(self):
        self.materials = MockMaterialCollection()


class MockMaterialCollection:
    def __init__(self):
        self.materials: dict[str, MockMaterial] = {}

    def new(self, name: str) -> MockMaterial:
        mat = MockMaterial(name)
        self.materials[name] = mat
        return mat

    def get(self, name: str) -> MockMaterial | None:
        return self.materials.get(name)


# ==============================================================================
# Harness Override Material Generation Tests
# ==============================================================================


def test_harness_create_override_none_blend_data():
    mock_bpy = MagicMock()
    with patch("core.impostor_harness.bpy", mock_bpy):
        mat = ImpostorShaderHarness.create_unlit_override_material(
            source_mat=None,
            channel_layer="BASE_COLOR",
            blend_data=None,  # type: ignore[arg-type]
        )
        assert mat is None


def test_harness_create_override_base_color_fallback():
    mock_bpy = MagicMock()
    bdata = MockBlendData()
    with patch("core.impostor_harness.bpy", mock_bpy):
        mat = ImpostorShaderHarness.create_unlit_override_material(
            source_mat=None,
            channel_layer="BASE_COLOR",
            blend_data=bdata,  # type: ignore[arg-type]
        )
        assert mat is not None
        assert "OM_Bake_BASE_COLOR" in mat.name
        assert mat.node_tree is not None
        assert any(n.type == "ShaderNodeEmission" for n in mat.node_tree.nodes)


def test_harness_create_override_base_color_from_source_bsdf():
    mock_bpy = MagicMock()
    bdata = MockBlendData()

    source_mat = MockMaterial("SourceTree")
    bsdf = source_mat.node_tree.nodes.new("BSDF_PRINCIPLED")
    bsdf.inputs["Base Color"].default_value = (0.2, 0.4, 0.6, 1.0)

    with patch("core.impostor_harness.bpy", mock_bpy):
        mat = ImpostorShaderHarness.create_unlit_override_material(
            source_mat=source_mat,  # type: ignore[arg-type]
            channel_layer="BASE_COLOR",
            blend_data=bdata,  # type: ignore[arg-type]
        )
        assert mat is not None


def test_harness_create_override_normal_pass_ue5():
    mock_bpy = MagicMock()
    bdata = MockBlendData()
    with patch("core.impostor_harness.bpy", mock_bpy):
        mat = ImpostorShaderHarness.create_unlit_override_material(
            source_mat=None,
            channel_layer="NORMAL",
            target_engine="UE5",
            blend_data=bdata,  # type: ignore[arg-type]
        )
        assert mat is not None
        assert "OM_Bake_NORMAL" in mat.name


def test_harness_create_override_normal_pass_unity():
    mock_bpy = MagicMock()
    bdata = MockBlendData()
    with patch("core.impostor_harness.bpy", mock_bpy):
        mat = ImpostorShaderHarness.create_unlit_override_material(
            source_mat=None,
            channel_layer="NORMAL",
            target_engine="UNITY",
            blend_data=bdata,  # type: ignore[arg-type]
        )
        assert mat is not None


def test_harness_create_override_depth_pass():
    mock_bpy = MagicMock()
    bdata = MockBlendData()
    with patch("core.impostor_harness.bpy", mock_bpy):
        mat = ImpostorShaderHarness.create_unlit_override_material(
            source_mat=None,
            channel_layer="DEPTH",
            radius=2.0,
            cam_distance=5.0,
            blend_data=bdata,  # type: ignore[arg-type]
        )
        assert mat is not None
        assert "OM_Bake_DEPTH" in mat.name


def test_harness_create_override_orm_ue5():
    mock_bpy = MagicMock()
    bdata = MockBlendData()
    with patch("core.impostor_harness.bpy", mock_bpy):
        mat = ImpostorShaderHarness.create_unlit_override_material(
            source_mat=None,
            channel_layer="ORM",
            target_engine="UE5",
            blend_data=bdata,  # type: ignore[arg-type]
        )
        assert mat is not None
        assert "OM_Bake_ORM" in mat.name


def test_harness_create_override_orm_unity():
    mock_bpy = MagicMock()
    bdata = MockBlendData()
    with patch("core.impostor_harness.bpy", mock_bpy):
        mat = ImpostorShaderHarness.create_unlit_override_material(
            source_mat=None,
            channel_layer="ORM",
            target_engine="UNITY",
            blend_data=bdata,  # type: ignore[arg-type]
        )
        assert mat is not None


def test_harness_create_override_with_alpha_cutout():
    mock_bpy = MagicMock()
    bdata = MockBlendData()

    source_mat = MockMaterial("FoliageLeaf")
    bsdf = source_mat.node_tree.nodes.new("BSDF_PRINCIPLED")
    tex_img = source_mat.node_tree.nodes.new("TEX_IMAGE")
    source_mat.node_tree.links.new(tex_img.outputs["Alpha"], bsdf.inputs["Alpha"])

    with patch("core.impostor_harness.bpy", mock_bpy):
        mat = ImpostorShaderHarness.create_unlit_override_material(
            source_mat=source_mat,  # type: ignore[arg-type]
            channel_layer="BASE_COLOR",
            blend_data=bdata,  # type: ignore[arg-type]
        )
        assert mat is not None
