"""
Unit tests for OmniMesh Engine Import Presets Subsystem.
Verifies factory preset loading, schema validation, persistence, and duplication.
"""

from __future__ import annotations

from pathlib import Path
import pytest

from core.engine_import_presets import (
    DEFAULT_ENGINE_IMPORT_PRESET_ID,
    EngineImportPresetManager,
    delete_engine_import_preset,
    get_engine_import_preset,
    list_engine_import_presets,
    save_engine_import_preset,
)


def test_factory_preset_exists_and_loads():
    preset = get_engine_import_preset(DEFAULT_ENGINE_IMPORT_PRESET_ID)
    assert preset is not None
    assert preset.get("name") == "MSFS 2024 Aircraft"
    assert preset.get("engine") == "MSFS_2024"
    assert preset.get("import_geometry") is True
    assert preset.get("import_spatial") is True
    assert preset.get("import_lights") is True
    assert preset.get("import_cameras") is True
    assert preset.get("model_target") == "BOTH_SEPARATE"
    assert preset.get("use_lod0_suffix") is True
    assert preset.get("auto_assign_screen_pct") is True


def test_schema_validation_rules():
    # Missing name -> Invalid
    assert EngineImportPresetManager.validate_preset_schema({"engine": "MSFS_2024"}) is None

    # Invalid engine -> Falls back to MSFS_2024
    valid = EngineImportPresetManager.validate_preset_schema({"name": "Custom Test", "engine": "INVALID_ENG"})
    assert valid is not None
    assert valid["engine"] == "MSFS_2024"

    # Valid schema structure
    full = {
        "name": "Custom Setup",
        "engine": "MSFS_2020",
        "import_geometry": True,
        "import_spatial": False,
        "import_lights": False,
        "import_cameras": True,
        "model_target": "INTERIOR_ONLY",
        "use_lod0_suffix": False,
        "auto_assign_screen_pct": False,
        "deduplicate_materials": True,
        "reuse_master_rig": False,
    }
    validated = EngineImportPresetManager.validate_preset_schema(full)
    assert validated is not None
    assert validated["name"] == "Custom Setup"
    assert validated["engine"] == "MSFS_2020"
    assert validated["import_spatial"] is False
    assert validated["model_target"] == "INTERIOR_ONLY"


def test_list_presets():
    presets = list_engine_import_presets()
    assert len(presets) >= 1
    ids = [p.get("preset_id") for p in presets]
    assert DEFAULT_ENGINE_IMPORT_PRESET_ID in ids


def test_custom_preset_save_and_delete(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(EngineImportPresetManager, "get_user_dir", classmethod(lambda cls: tmp_path))

    custom_data = {
        "name": "User Custom Preset",
        "engine": "MSFS_2024",
        "import_geometry": True,
        "import_spatial": True,
        "import_lights": True,
        "import_cameras": True,
    }
    custom_id = save_engine_import_preset(custom_data)
    assert custom_id == "user_custom_preset"

    loaded = EngineImportPresetManager.get_preset(custom_id)
    assert loaded["name"] == "User Custom Preset"

    # Delete
    deleted = delete_engine_import_preset(custom_id)
    assert deleted is True
    # Verify fallback to default
    after_del = EngineImportPresetManager.get_preset(custom_id)
    assert after_del["preset_id"] == DEFAULT_ENGINE_IMPORT_PRESET_ID


def test_engine_import_collection_hierarchy(monkeypatch: pytest.MonkeyPatch):
    """Verify that get_or_create_engine_import_collection nests Spatial, Lights,

    and Cameras directly under LOD0, while LOD1..N remain siblings under root.
    """
    from unittest.mock import MagicMock
    import ui.utils as ui_utils

    class MockCollection:
        def __init__(self, name: str):
            self.name = name
            self.children = MagicMock()
            self.children.__contains__ = lambda s, x: x in self._child_list
            self._child_list = []
            self.children.link = lambda c: self._child_list.append(c.name if hasattr(c, "name") else c)
            self.children.unlink = lambda c: self._child_list.remove(c.name if hasattr(c, "name") else c)
            self.data = {}

        def __setitem__(self, key, val):
            self.data[key] = val

        def __getitem__(self, key):
            return self.data[key]

    created_collections: dict[str, MockCollection] = {}

    def mock_get(name):
        return created_collections.get(name)

    def mock_new(name):
        c = MockCollection(name)
        created_collections[name] = c
        return c

    mock_bpy = MagicMock()
    mock_bpy.data.collections.get = mock_get
    mock_bpy.data.collections.new = mock_new

    mock_scene_col = MockCollection("Scene Collection")
    mock_context = MagicMock()
    mock_context.scene.collection = mock_scene_col

    monkeypatch.setattr(ui_utils, "bpy", mock_bpy)

    # 1. Create root and LOD0
    root = ui_utils.get_or_create_engine_import_collection(mock_context, "Aircraft", "PACKAGE_ROOT")
    assert root.name == "Aircraft"
    assert "Aircraft" in mock_scene_col._child_list

    lod0 = ui_utils.get_or_create_engine_import_collection(mock_context, "Aircraft", "LOD0")
    assert lod0.name == "Aircraft_LOD0"
    assert "Aircraft_LOD0" in root._child_list

    # 2. Config collections must be child of Aircraft_Config (sibling of LOD0)
    spatial = ui_utils.get_or_create_engine_import_collection(mock_context, "Aircraft", "SPATIAL")
    assert spatial.name == "Aircraft_Spatial"
    assert "Aircraft_Config" in root._child_list
    assert "Aircraft_Spatial" in created_collections["Aircraft_Config"]._child_list
    assert "Aircraft_Spatial" not in lod0._child_list
    assert "Aircraft_Spatial" not in root._child_list

    lights = ui_utils.get_or_create_engine_import_collection(mock_context, "Aircraft", "LIGHTS")
    assert lights.name == "Aircraft_Lights"
    assert "Aircraft_Lights" in created_collections["Aircraft_Config"]._child_list
    assert "Aircraft_Lights" not in lod0._child_list

    cams = ui_utils.get_or_create_engine_import_collection(mock_context, "Aircraft", "CAMERAS")
    assert cams.name == "Aircraft_Cameras"
    assert "Aircraft_Cameras" in created_collections["Aircraft_Config"]._child_list
    assert "Aircraft_Cameras" not in lod0._child_list

    # 3. LOD1 must be child of root
    lod1 = ui_utils.get_or_create_engine_import_collection(mock_context, "Aircraft", "LOD1")
    assert lod1.name == "Aircraft_LOD1"
    assert "Aircraft_LOD1" in root._child_list
    assert "Aircraft_LOD1" not in lod0._child_list


def test_variante_a_multi_model_and_variant_collections(monkeypatch: pytest.MonkeyPatch):
    """Verify that Variante A creates sibling top-level collections directly under Scene Collection

    for Exterior, Interior, and Variants, with config collections properly nested under _Config.
    """
    from unittest.mock import MagicMock
    import ui.utils as ui_utils

    class MockCollection:
        def __init__(self, name: str):
            self.name = name
            self.children = MagicMock()
            self._child_objs = []
            self.children.__contains__ = lambda s, x: x in [c.name for c in self._child_objs]
            self.children.link = lambda c: self._child_objs.append(c)
            self.children.unlink = lambda c: self._child_objs.remove(c) if c in self._child_objs else None
            self.children.__iter__ = lambda s: iter(self._child_objs)
            self.data = {}

        def __setitem__(self, key, val):
            self.data[key] = val

        def __getitem__(self, key):
            return self.data[key]

        def get(self, key, default=None):
            return self.data.get(key, default)

    created_collections: dict[str, MockCollection] = {}

    def mock_get(name):
        return created_collections.get(name)

    def mock_new(name):
        c = MockCollection(name)
        created_collections[name] = c
        return c

    mock_bpy = MagicMock()
    mock_bpy.data.collections.get = mock_get
    mock_bpy.data.collections.new = mock_new

    mock_scene_col = MockCollection("Scene Collection")
    mock_context = MagicMock()
    mock_context.scene.collection = mock_scene_col

    monkeypatch.setattr(ui_utils, "bpy", mock_bpy)

    # 1. Base / Exterior Model
    ext_root = ui_utils.get_or_create_engine_import_collection(mock_context, "Wasm_Aircraft", "ROOT")
    assert ext_root.name == "Wasm_Aircraft"
    assert "Wasm_Aircraft" in mock_scene_col.children
    assert ext_root.get("_omnimesh_role") == "MODEL_ROOT"

    ext_lod0 = ui_utils.get_or_create_engine_import_collection(mock_context, "Wasm_Aircraft", "LOD0")
    assert ext_lod0.name == "Wasm_Aircraft_LOD0"
    assert "Wasm_Aircraft_LOD0" in ext_root.children

    # 2. Interior / Cockpit Model
    inte_root = ui_utils.get_or_create_engine_import_collection(mock_context, "Wasm_Aircraft_Interior", "ROOT")
    assert inte_root.name == "Wasm_Aircraft_Interior"
    assert "Wasm_Aircraft_Interior" in mock_scene_col.children
    assert inte_root.get("_omnimesh_role") == "INTERIOR"
    assert inte_root.get("_omnimesh_parent") == "Wasm_Aircraft"

    inte_lod0 = ui_utils.get_or_create_engine_import_collection(mock_context, "Wasm_Aircraft_Interior", "LOD0")
    assert inte_lod0.name == "Wasm_Aircraft_Interior_LOD0"
    assert "Wasm_Aircraft_Interior_LOD0" in inte_root.children

    inte_cams = ui_utils.get_or_create_engine_import_collection(mock_context, "Wasm_Aircraft_Interior", "CAMERAS")
    assert inte_cams.name == "Wasm_Aircraft_Interior_Cameras"
    assert "Wasm_Aircraft_Interior_Config" in inte_root.children
    assert "Wasm_Aircraft_Interior_Cameras" in created_collections["Wasm_Aircraft_Interior_Config"].children

    # 3. Geometry Variant (e.g. Floats)
    var_root = ui_utils.get_or_create_engine_import_collection(mock_context, "Wasm_Aircraft_Floats", "ROOT")
    assert var_root.name == "Wasm_Aircraft_Floats"
    assert "Wasm_Aircraft_Floats" in mock_scene_col.children
    assert var_root.get("_omnimesh_role") == "VARIANT"

    var_lod0 = ui_utils.get_or_create_engine_import_collection(mock_context, "Wasm_Aircraft_Floats", "LOD0")
    assert var_lod0.name == "Wasm_Aircraft_Floats_LOD0"
    assert "Wasm_Aircraft_Floats_LOD0" in var_root.children


def test_asset_enum_items_formatting(monkeypatch: pytest.MonkeyPatch):
    """Verify that get_asset_enum_items decorates options with clear, friendly badges."""
    from unittest.mock import MagicMock
    import ui.utils as ui_utils

    discovered = ["Wasm_Aircraft", "Wasm_Aircraft_Floats", "Wasm_Aircraft_Interior"]
    monkeypatch.setattr(ui_utils, "get_available_asset_names", lambda ctx: discovered)

    items = ui_utils.get_asset_enum_items(None, MagicMock())
    item_map = {id_val: (label, desc) for id_val, label, desc in items}

    assert "AUTO" in item_map
    assert item_map["Wasm_Aircraft"][0] == "Wasm_Aircraft [Base / Exterior]"
    assert item_map["Wasm_Aircraft_Interior"][0] == "Wasm_Aircraft_Interior [Cockpit / Interior]"
    assert item_map["Wasm_Aircraft_Floats"][0] == "Wasm_Aircraft_Floats [Variant: Floats]"
