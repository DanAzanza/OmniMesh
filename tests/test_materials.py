"""
Unit tests for OmniMesh Material Optimization, Cleanup & Slot Consolidation Module.
"""

from __future__ import annotations

from unittest.mock import MagicMock
import pytest

from core.materials import (
    DeepMaterialHasher,
    HeadlessSlotCompactor,
    MaterialOptimizer,
    SemanticTextureAuditor,
)


class DummyPolygon:
    def __init__(self, material_index: int, area: float):
        self.material_index = material_index
        self.area = area


class DummyMaterial:
    def __init__(self, name: str):
        self.name = name
        self.diffuse_color = (0.8, 0.8, 0.8, 1.0)
        self.node_tree = None


class DummyMaterialSlot:
    def __init__(self, material: DummyMaterial | None = None):
        self.material = material


class DummyMeshData:
    def __init__(self, polygons: list[DummyPolygon]):
        self.polygons = polygons
        self.materials = []


class DummyMeshObject:
    def __init__(self, material_slots: list[DummyMaterialSlot], polygons: list[DummyPolygon]):
        self.type = "MESH"
        self.material_slots = material_slots
        self.data = DummyMeshData(polygons)
        self.data.materials = [s.material for s in material_slots if s.material is not None]
        self.active_material_index = 0


def test_calculate_material_areas():
    slots = [DummyMaterialSlot(DummyMaterial("Mat0")), DummyMaterialSlot(DummyMaterial("Mat1"))]
    polys = [
        DummyPolygon(0, 10.0),
        DummyPolygon(0, 5.0),
        DummyPolygon(1, 2.5),
        DummyPolygon(1, 3.5),
    ]
    obj = DummyMeshObject(slots, polys)

    areas = MaterialOptimizer.calculate_material_areas(obj)
    assert areas[0] == pytest.approx(15.0)
    assert areas[1] == pytest.approx(6.0)


def test_calculate_material_areas_empty_or_null():
    assert MaterialOptimizer.calculate_material_areas(None) == {}

    obj_no_slots = DummyMeshObject([], [DummyPolygon(0, 5.0)])
    assert MaterialOptimizer.calculate_material_areas(obj_no_slots) == {}


def test_get_dominant_material_index():
    areas = {0: 12.5, 1: 45.2, 2: 3.1}
    assert MaterialOptimizer.get_dominant_material_index(areas) == 1
    assert MaterialOptimizer.get_dominant_material_index({}) == 0


def test_deep_material_hasher_non_nodes():
    mat1 = DummyMaterial("Wood")
    mat2 = DummyMaterial("Wood.001")
    mat3 = DummyMaterial("Metal")
    mat3.diffuse_color = (0.1, 0.2, 0.3, 1.0)

    h1 = DeepMaterialHasher.hash_material(mat1)
    h2 = DeepMaterialHasher.hash_material(mat2)
    h3 = DeepMaterialHasher.hash_material(mat3)

    assert h1 == h2
    assert h1 != h3
    assert DeepMaterialHasher.hash_material(None) is not None


def test_deep_material_hasher_with_mocked_nodes():
    mock_mat = MagicMock()
    mock_out_node = MagicMock()
    mock_out_node.type = "OUTPUT_MATERIAL"
    mock_out_node.name = "Material Output"
    mock_out_node.is_active_output = True

    mock_bsdf_node = MagicMock()
    mock_bsdf_node.type = "BSDF_PRINCIPLED"
    mock_bsdf_node.name = "Principled BSDF"

    mock_socket = MagicMock()
    mock_socket.name = "Surface"
    mock_socket.is_linked = True

    mock_link = MagicMock()
    mock_link.from_node = mock_bsdf_node
    mock_link.from_socket.name = "BSDF"
    mock_socket.links = [mock_link]
    mock_out_node.inputs = [mock_socket]
    mock_bsdf_node.inputs = []

    mock_mat.node_tree.nodes = [mock_out_node, mock_bsdf_node]
    mock_mat.node_tree.links = [mock_link]

    h = DeepMaterialHasher.hash_material(mock_mat)
    assert isinstance(h, str)
    assert len(h) == 64


def test_headless_slot_compactor_empty_and_deduplication():
    mat_gold = DummyMaterial("Gold")
    mat_chrome = DummyMaterial("Chrome")

    # Slots: [Gold, None, Chrome, Gold]
    # Polys reference: Slot 0 (Gold), Slot 2 (Chrome), Slot 3 (Gold)
    slots = [
        DummyMaterialSlot(mat_gold),
        DummyMaterialSlot(None),
        DummyMaterialSlot(mat_chrome),
        DummyMaterialSlot(mat_gold),
    ]
    polys = [
        DummyPolygon(0, 10.0),
        DummyPolygon(2, 5.0),
        DummyPolygon(3, 8.0),
    ]
    obj = DummyMeshObject(slots, polys)

    res = HeadlessSlotCompactor.compact_slots(obj, purge_empty=True, deduplicate_identical=True)
    assert res["slots_removed"] == 2
    # New materials list should be: [Gold, Chrome]
    assert len(obj.data.materials) == 2
    assert obj.data.materials[0] == mat_gold
    assert obj.data.materials[1] == mat_chrome

    # Polygon 0: old 0 -> new 0
    # Polygon 1: old 2 -> new 1
    # Polygon 2: old 3 -> new 0 (deduplicated to Gold)
    assert polys[0].material_index == 0
    assert polys[1].material_index == 1
    assert polys[2].material_index == 0


def test_semantic_texture_auditor_validation():
    assert SemanticTextureAuditor.is_image_valid(None) is False

    mock_packed = MagicMock()
    mock_packed.packed_file = b"data"
    assert SemanticTextureAuditor.is_image_valid(mock_packed) is True

    mock_has_data = MagicMock()
    mock_has_data.packed_file = None
    mock_has_data.has_data = True
    assert SemanticTextureAuditor.is_image_valid(mock_has_data) is True

    mock_gen = MagicMock()
    mock_gen.packed_file = None
    mock_gen.has_data = False
    mock_gen.source = "GENERATED"
    assert SemanticTextureAuditor.is_image_valid(mock_gen) is True


def test_semantic_texture_auditor_repair_missing():
    mock_mat = MagicMock()
    mock_tex_node = MagicMock()
    mock_tex_node.type = "TEX_IMAGE"
    mock_tex_node.image = None  # Broken image

    mock_out_sock = MagicMock()
    mock_link = MagicMock()
    mock_target_sock = MagicMock()
    mock_target_sock.name = "Roughness"
    mock_link.to_socket = mock_target_sock
    mock_link.to_node.type = "BSDF_PRINCIPLED"
    mock_out_sock.links = [mock_link]
    mock_tex_node.outputs = [mock_out_sock]

    mock_mat.node_tree.nodes = [mock_tex_node]
    mock_mat.node_tree.links = [mock_link]

    repaired = SemanticTextureAuditor.repair_missing_textures_in_material(mock_mat)
    assert repaired == 1
    assert mock_target_sock.default_value == 0.5


def test_semantic_texture_auditor_orphan_nodes():
    mock_mat = MagicMock()
    mock_dead_node = MagicMock()
    mock_dead_node.type = "TEX_IMAGE"
    mock_out_sock = MagicMock()
    mock_out_sock.links = []
    mock_dead_node.outputs = [mock_out_sock]

    mock_mat.node_tree.nodes = [mock_dead_node]

    removed = SemanticTextureAuditor.remove_orphan_texture_nodes(mock_mat)
    assert removed == 1


def test_material_protection_keywords():
    mat_body = DummyMaterial("Car_Body")
    mat_glass = DummyMaterial("Windshield_Glass")
    mat_light = DummyMaterial("Brake_Light_Emissive")
    mat_decal = DummyMaterial("Logo_Decal")

    assert MaterialOptimizer.is_material_protected(mat_body) is False
    assert MaterialOptimizer.is_material_protected(mat_glass) is True
    assert MaterialOptimizer.is_material_protected(mat_light) is True
    assert MaterialOptimizer.is_material_protected(mat_decal) is True


def test_clean_materials_full_null_and_summary():
    stats = MaterialOptimizer.clean_materials_full([])
    assert stats["slots_removed"] == 0
    assert stats["faces_remapped"] == 0
    assert stats["consolidated_slots"] == 0
    assert stats["repaired_textures"] == 0
    assert stats["orphan_nodes_removed"] == 0
    assert stats["merged_datablocks"] == 0
    assert stats["purged_orphans"] == 0
