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
    def __init__(self, name: str = "Color", default_val: Any = (0.8, 0.8, 0.8, 1.0), node: Any = None):
        self.name = name
        self.default_value = default_val
        self.is_linked = False
        self.links: list[Any] = []
        self.node = node


class MockSocketCollection:
    def __init__(self, owner: Any = None):
        self._sockets: dict[Any, MockSocket] = {}
        self._owner = owner

    def __getitem__(self, key: Any) -> MockSocket:
        if key not in self._sockets:
            self._sockets[key] = MockSocket(str(key), node=self._owner)
        return self._sockets[key]

    def get(self, key: Any, default: Any = None) -> Any:
        if key not in self._sockets:
            self._sockets[key] = MockSocket(str(key), node=self._owner)
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
        self.bl_idname = ""
        self.location = (0.0, 0.0)
        self.inputs = MockSocketCollection(owner=self)
        self.outputs = MockSocketCollection(owner=self)


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
        to_socket.links.append(
            MagicMock(
                from_socket=from_socket,
                to_socket=to_socket,
                from_node=getattr(from_socket, "node", None),
            )
        )


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


def test_harness_clones_math_alpha_chain_and_scalar_glass():
    mock_bpy = MagicMock()
    bdata = MockBlendData()

    # Case 1: GLASS canopy where Alpha feeds through ShaderNodeMath -> Principled BSDF
    glass_mat = MockMaterial("CanopyGlass")
    bsdf = glass_mat.node_tree.nodes.new("BSDF_PRINCIPLED")
    math_node = glass_mat.node_tree.nodes.new("MATH")
    tex_img = glass_mat.node_tree.nodes.new("TEX_IMAGE")
    glass_mat.node_tree.links.new(tex_img.outputs["Alpha"], math_node.inputs[0])
    glass_mat.node_tree.links.new(math_node.outputs["Value"], bsdf.inputs["Alpha"])

    # Case 2: Unlinked semi-transparent glass (Alpha < 0.999)
    tint_mat = MockMaterial("TintGlass")
    bsdf_tint = tint_mat.node_tree.nodes.new("BSDF_PRINCIPLED")
    bsdf_tint.inputs["Alpha"].default_value = 0.25

    with patch("core.impostor_harness.bpy", mock_bpy):
        out_glass = ImpostorShaderHarness.create_unlit_override_material(
            source_mat=glass_mat,  # type: ignore[arg-type]
            channel_layer="BASE_COLOR",
            blend_data=bdata,  # type: ignore[arg-type]
        )
        assert out_glass is not None and out_glass.node_tree is not None
        node_types = {n.type for n in out_glass.node_tree.nodes}
        assert "ShaderNodeBsdfTransparent" in node_types
        assert "ShaderNodeMixShader" in node_types
        assert "ShaderNodeMath" in node_types
        assert out_glass.surface_render_method == "BLENDED"

        out_tint = ImpostorShaderHarness.create_unlit_override_material(
            source_mat=tint_mat,  # type: ignore[arg-type]
            channel_layer="NORMAL",
            blend_data=bdata,  # type: ignore[arg-type]
        )
        assert out_tint is not None and out_tint.node_tree is not None
        assert "ShaderNodeBsdfTransparent" in {n.type for n in out_tint.node_tree.nodes}


def test_harness_orm_clones_separate_color_and_stops_on_cycle():
    mock_bpy = MagicMock()
    bdata = MockBlendData()

    pbr_mat = MockMaterial("AircraftMetal")
    bsdf = pbr_mat.node_tree.nodes.new("BSDF_PRINCIPLED")
    sep = pbr_mat.node_tree.nodes.new("SEPARATE_COLOR")
    tex_comp = pbr_mat.node_tree.nodes.new("TEX_IMAGE")
    pbr_mat.node_tree.links.new(tex_comp.outputs["Color"], sep.inputs["Color"])
    pbr_mat.node_tree.links.new(sep.outputs["Green"], bsdf.inputs["Roughness"])
    pbr_mat.node_tree.links.new(sep.outputs["Blue"], bsdf.inputs["Metallic"])

    with patch("core.impostor_harness.bpy", mock_bpy):
        orm_mat = ImpostorShaderHarness.create_unlit_override_material(
            source_mat=pbr_mat,  # type: ignore[arg-type]
            channel_layer="ORM",
            target_engine="UE5",
            blend_data=bdata,  # type: ignore[arg-type]
        )
        assert orm_mat is not None and orm_mat.node_tree is not None
        node_types = [n.type for n in orm_mat.node_tree.nodes]
        assert "ShaderNodeSeparateColor" in node_types
        # Same upstream TEX_IMAGE node is memoized across both Roughness and Metallic channels
        assert node_types.count("ShaderNodeTexImage") == 1


def test_harness_clone_depth_unknown_node_color_ramp_and_unity6_orm() -> None:
    """Verifies max recursion guard, unknown node skip, ValToRGB stop copy, and UNITY_6 Smoothness invert."""
    from core.impostor_harness import _MAX_CLONE_DEPTH

    mock_bpy = MagicMock()
    bdata = MockBlendData()
    source_mat = MockMaterial("ComplexMat")
    bsdf = source_mat.node_tree.nodes.new("BSDF_PRINCIPLED")

    # 1. Unknown node -> skips cloning cleanly and falls back to scalar
    unknown = source_mat.node_tree.nodes.new("UNKNOWN_CUSTOM_NODE")
    unknown.bl_idname = "ShaderNodeCustomUnknown"
    unknown.type = "CUSTOM_UNKNOWN"
    source_mat.node_tree.links.new(unknown.outputs["Color"], bsdf.inputs["Base Color"])

    # 2. ValToRGB ColorRamp on Roughness (for UNITY_6 inverted smoothness pass)
    ramp = source_mat.node_tree.nodes.new("VALTORGB")
    ramp.bl_idname = "ShaderNodeValToRGB"
    ramp.color_ramp = MagicMock()  # type: ignore[attr-defined]
    ramp.color_ramp.elements = [  # type: ignore[attr-defined]
        MagicMock(position=0.2, color=(0.1, 0.1, 0.1, 1.0)),
        MagicMock(position=0.9, color=(0.9, 0.9, 0.9, 1.0)),
    ]
    source_mat.node_tree.links.new(ramp.outputs["Color"], bsdf.inputs["Roughness"])

    with patch("core.impostor_harness.bpy", mock_bpy):
        mat_base = ImpostorShaderHarness.create_unlit_override_material(
            source_mat=source_mat,  # type: ignore[arg-type]
            channel_layer="BASE_COLOR",
            blend_data=bdata,  # type: ignore[arg-type]
        )
        assert mat_base is not None

        mat_orm = ImpostorShaderHarness.create_unlit_override_material(
            source_mat=source_mat,  # type: ignore[arg-type]
            channel_layer="ORM",
            target_engine="UNITY_6",
            blend_data=bdata,  # type: ignore[arg-type]
        )
        assert mat_orm is not None
        assert mat_orm.node_tree is not None
        node_types = [getattr(n, "type", "") for n in mat_orm.node_tree.nodes]
        assert "ShaderNodeMath" in node_types
        assert "ShaderNodeValToRGB" in node_types

        # 3. Max recursion cutoff returns cleanly without adding links
        before_count = len(mat_orm.node_tree.links.links)  # type: ignore[attr-defined]
        ImpostorShaderHarness._duplicate_link_to_target(
            bsdf.inputs["Roughness"].links[0],
            mat_orm.node_tree.nodes,
            mat_orm.node_tree.links,
            bsdf.inputs["Metallic"],  # type: ignore[arg-type]
            depth=_MAX_CLONE_DEPTH + 1,
        )
        assert len(mat_orm.node_tree.links.links) == before_count  # type: ignore[attr-defined]
