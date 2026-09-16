"""
Automated Pytest Suite for OmniMesh Material Presets.
Verifies Principled BSDF socket resolving across Blender versions,
EEVEE Next transparency guards, shader preset configuration, and object assignment.
"""

from __future__ import annotations

from unittest.mock import MagicMock


import core.material_presets as mp
from core.material_presets import (
    assign_material_to_objects,
    configure_material_transparency,
    create_or_update_material_preset,
    get_or_create_principled_node,
    set_principled_socket,
)


class MockSocket:
    def __init__(self, name: str, default_val: any = None):
        self.name = name
        self.default_value = default_val


class MockNode:
    def __init__(self, node_type: str = "BSDF_PRINCIPLED"):
        self.type = node_type
        self.inputs: dict[str, MockSocket] = {}
        self.outputs: dict[str, MockSocket] = {"BSDF": MockSocket("BSDF")}


class MockMaterial:
    def __init__(self, name: str):
        self.name = name
        self.use_nodes = True
        self.custom_props: dict[str, any] = {}
        self.node_tree = MagicMock()
        self.bsdf = MockNode("BSDF_PRINCIPLED")
        self.bsdf.inputs = {
            "Base Color": MockSocket("Base Color"),
            "Roughness": MockSocket("Roughness"),
            "Metallic": MockSocket("Metallic"),
            "Transmission Weight": MockSocket("Transmission Weight"),
            "Alpha": MockSocket("Alpha"),
            "IOR": MockSocket("IOR"),
            "Emission Color": MockSocket("Emission Color"),
            "Emission Strength": MockSocket("Emission Strength"),
        }
        self.node_tree.nodes = [self.bsdf]
        self.surface_render_method = "DITHERED"
        self.use_transparent_shadow = False

    def __setitem__(self, key: str, value: any):
        self.custom_props[key] = value

    def __getitem__(self, key: str):
        return self.custom_props[key]

    def get(self, key: str, default: any = None):
        return self.custom_props.get(key, default)


# =============================================================================
# SOCKET & TRANSPARENCY TESTS
# =============================================================================


def test_set_principled_socket_v2_fallback_to_v1():
    """Verify v2 socket name takes precedence, but falls back gracefully to v1."""
    node = MockNode()
    node.inputs["Transmission"] = MockSocket("Transmission", 0.0)

    # v2 is "Transmission Weight", but only "Transmission" (v1) exists on node
    success = set_principled_socket(node, "Transmission", "Transmission Weight", 0.85)
    assert success is True
    assert node.inputs["Transmission"].default_value == 0.85

    # Now add v2 and verify v2 is chosen
    node.inputs["Transmission Weight"] = MockSocket("Transmission Weight", 0.0)
    success = set_principled_socket(node, "Transmission", "Transmission Weight", 1.0)
    assert success is True
    assert node.inputs["Transmission Weight"].default_value == 1.0


def test_set_principled_socket_missing_socket():
    """Verify missing socket returns False without throwing exceptions."""
    node = MockNode()
    node.inputs = {}
    success = set_principled_socket(node, "NonExistentV1", "NonExistentV2", 1.0)
    assert success is False

    success_none = set_principled_socket(None, "Alpha", "Alpha", 1.0)
    assert success_none is False


def test_configure_material_transparency_eevee_next():
    """Verify EEVEE Next surface_render_method and use_transparent_shadow are assigned safely."""
    mat = MockMaterial("GlassMat")
    configure_material_transparency(mat, mode="BLEND", shadow="NONE")

    assert mat.surface_render_method == "BLENDED"
    assert mat.use_transparent_shadow is False

    configure_material_transparency(mat, mode="DITHERED", shadow="OPAQUE")
    assert mat.surface_render_method == "DITHERED"
    assert mat.use_transparent_shadow is True


def test_get_or_create_principled_node_existing():
    """Verify existing BSDF_PRINCIPLED is returned immediately."""
    mat = MockMaterial("TestMat")
    node = get_or_create_principled_node(mat)
    assert node is not None
    assert node.type == "BSDF_PRINCIPLED"


# =============================================================================
# PRESET GENERATION TESTS
# =============================================================================


def test_create_pbr_standard_preset(monkeypatch):
    """Verify PBR_STANDARD preset sets opaque properties and standard tags."""
    mock_mat = MockMaterial("Mat_PBR_Standard")
    mock_bpy = MagicMock()
    mock_bpy.data.materials.get.return_value = None
    mock_bpy.data.materials.new.return_value = mock_mat
    monkeypatch.setattr(mp, "bpy", mock_bpy)

    mat = create_or_update_material_preset(
        material_name="Aircraft_Fuselage",
        preset_type="PBR_STANDARD",
        base_color=(0.5, 0.5, 0.5, 1.0),
        roughness=0.3,
        metallic=0.8,
    )
    assert mat is not None
    assert mat["_omnimesh_shader_preset"] == "PBR_STANDARD"
    assert mat["msfs_material_type"] == 1
    assert mat.bsdf.inputs["Metallic"].default_value == 0.8
    assert mat.bsdf.inputs["Roughness"].default_value == 0.3


def test_create_glass_preset(monkeypatch):
    """Verify GLASS_TRANSPARENT preset sets high transmission, low roughness, and windshield tags."""
    mock_mat = MockMaterial("Mat_Glass")
    mock_bpy = MagicMock()
    mock_bpy.data.materials.get.return_value = None
    mock_bpy.data.materials.new.return_value = mock_mat
    monkeypatch.setattr(mp, "bpy", mock_bpy)

    mat = create_or_update_material_preset(
        material_name="Cockpit_Canopy",
        preset_type="GLASS_TRANSPARENT",
        roughness=0.05,
    )
    assert mat is not None
    assert mat["_omnimesh_shader_preset"] == "GLASS_TRANSPARENT"
    assert mat["_omnimesh_translucent"] is True
    assert mat["msfs_material_type"] == 4
    assert mat.bsdf.inputs["Transmission Weight"].default_value == 1.0
    assert mat.surface_render_method == "BLENDED"


def test_create_decal_and_invisible_presets(monkeypatch):
    """Verify FLOATING_DECAL and INVISIBLE_COLLIDER presets."""
    mock_mat_decal = MockMaterial("Mat_Decal")
    mock_mat_invis = MockMaterial("Mat_Invis")

    mock_bpy = MagicMock()
    mock_bpy.data.materials.get.return_value = None
    mock_bpy.data.materials.new.side_effect = lambda name: mock_mat_decal if "Decal" in name else mock_mat_invis
    monkeypatch.setattr(mp, "bpy", mock_bpy)

    decal = create_or_update_material_preset("Decal", "FLOATING_DECAL")
    assert decal["_omnimesh_decal"] is True
    assert decal["msfs_material_type"] == 2

    invis = create_or_update_material_preset("Invis", "INVISIBLE_COLLIDER")
    assert invis["_omnimesh_invisible"] is True
    assert invis["msfs_material_type"] == 12
    assert invis.bsdf.inputs["Alpha"].default_value == 0.0


def test_create_emissive_preset(monkeypatch):
    """Verify EMISSIVE_LIGHT preset sets emission color and strength."""
    mock_mat = MockMaterial("Mat_Light")
    mock_bpy = MagicMock()
    mock_bpy.data.materials.get.return_value = None
    mock_bpy.data.materials.new.return_value = mock_mat
    monkeypatch.setattr(mp, "bpy", mock_bpy)

    mat = create_or_update_material_preset(
        material_name="Warning_Annunciator",
        preset_type="EMISSIVE_LIGHT",
        base_color=(1.0, 0.2, 0.0, 1.0),
        emission_strength=12.0,
    )
    assert mat["_omnimesh_emissive"] is True
    assert mat.bsdf.inputs["Emission Strength"].default_value == 12.0


# =============================================================================
# OBJECT ASSIGNMENT TESTS
# =============================================================================


def test_assign_material_to_objects():
    """Verify assign_material_to_objects handles new and existing material slots."""
    mat = MockMaterial("AssignedMat")

    mesh_obj1 = MagicMock()
    mesh_obj1.type = "MESH"
    mesh_obj1.data.materials = []

    mesh_obj2 = MagicMock()
    mesh_obj2.type = "MESH"
    mesh_obj2.data.materials = [MockMaterial("OldMat")]

    empty_obj = MagicMock()
    empty_obj.type = "EMPTY"

    count = assign_material_to_objects(mat, [mesh_obj1, mesh_obj2, empty_obj])
    assert count == 2
    assert mesh_obj1.data.materials[0] == mat
    assert mesh_obj2.data.materials[0] == mat
