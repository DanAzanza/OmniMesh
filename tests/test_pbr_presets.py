"""
Unit tests for OmniMesh PBR Importer Presets Subsystem (JSON storage, schema validation, atomic writes).
"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
from unittest.mock import MagicMock, patch

from core.pbr_presets import (
    DEFAULT_PRESET_ID,
    PBRImporterPresetManager,
)


def test_builtin_presets_discovery_and_schema():
    """Verify all shipped JSON presets in presets/pbr_importer/ are discovered and pass schema validation."""
    presets = PBRImporterPresetManager.load_presets(force_reload=True)
    expected_builtins = {
        "unreal_engine_5",
        "unity_hdrp_maskmap",
        "unity_urp_metallic",
        "godot_4_orm",
        "msfs_2024_comp",
        "standard_pbr_split",
    }
    for pid in expected_builtins:
        assert pid in presets, f"Expected built-in preset '{pid}' not found in presets."
        pdata = presets[pid]
        assert pdata.get("name"), f"Preset '{pid}' must have a valid non-empty name."
        assert pdata.get("version", 0) >= 2, f"Preset '{pid}' must have schema version >= 2."
        maps = pdata.get("maps", [])
        assert len(maps) > 0, f"Preset '{pid}' must define at least one map."
        for m in maps:
            assert m.get("id"), f"Map in '{pid}' missing id."
            assert len(m.get("suffixes", [])) > 0, f"Map '{m.get('id')}' in '{pid}' has no suffixes."
            assert len(m.get("channels", {})) > 0, f"Map '{m.get('id')}' in '{pid}' has no channels."


def test_validate_preset_schema_rejections():
    """Verify malformed presets are rejected."""
    assert PBRImporterPresetManager.validate_preset_schema(None) is None
    assert PBRImporterPresetManager.validate_preset_schema({}) is None
    assert PBRImporterPresetManager.validate_preset_schema({"name": ""}) is None
    assert PBRImporterPresetManager.validate_preset_schema({"name": "Valid", "maps": []}) is None

    # Maps with empty suffixes or empty channels
    bad_map_1 = {
        "name": "Test",
        "maps": [{"id": "base", "suffixes": [], "channels": {"rgb": {"target": "Base Color"}}}],
    }
    assert PBRImporterPresetManager.validate_preset_schema(bad_map_1) is None

    bad_map_2 = {"name": "Test", "maps": [{"id": "base", "suffixes": ["_BC"], "channels": {}}]}
    assert PBRImporterPresetManager.validate_preset_schema(bad_map_2) is None


def test_sanitize_id():
    """Verify ID sanitization strips path traversal and dangerous characters."""
    assert PBRImporterPresetManager.sanitize_id("My Preset! 123") == "my_preset_123"
    assert PBRImporterPresetManager.sanitize_id("../../../etc/passwd") == "etc_passwd"
    assert PBRImporterPresetManager.sanitize_id("C:\\Windows\\System32") == "c_windows_system32"
    assert PBRImporterPresetManager.sanitize_id("   ") == "custom_preset"


def test_save_and_delete_custom_preset():
    """Verify custom preset saving (atomic write) and deletion without touching built-in presets."""
    with tempfile.TemporaryDirectory() as tmp_user_dir:
        tmp_path = Path(tmp_user_dir)
        with patch.object(PBRImporterPresetManager, "get_user_dir", return_value=tmp_path):
            custom_data = {
                "name": "Custom Studio Pipeline",
                "version": 2,
                "description": "Studio custom export template",
                "maps": [
                    {
                        "id": "diffuse",
                        "name": "Diffuse",
                        "suffixes": ["_D", "_Diff"],
                        "color_space": "sRGB",
                        "channels": {"rgb": {"target": "Base Color", "invert": False}},
                    }
                ],
            }
            pid = PBRImporterPresetManager.save_custom_preset(custom_data, custom_id="studio_pipeline")
            assert pid == "studio_pipeline"
            assert (tmp_path / "studio_pipeline.json").exists()

            # Verify file content
            with open(tmp_path / "studio_pipeline.json", "r", encoding="utf-8") as f:
                saved = json.load(f)
            assert saved["name"] == "Custom Studio Pipeline"

            # Check retrieved preset
            retrieved = PBRImporterPresetManager.get_preset("studio_pipeline")
            assert retrieved["name"] == "Custom Studio Pipeline"

            # Refuse deleting built-in preset
            assert not PBRImporterPresetManager.delete_custom_preset(DEFAULT_PRESET_ID)

            # Successfully delete custom preset
            assert PBRImporterPresetManager.delete_custom_preset("studio_pipeline")
            assert not (tmp_path / "studio_pipeline.json").exists()


def test_factory_preset_immutability():
    """Verify that attempting to overwrite built-in factory presets raises PermissionError."""
    with tempfile.TemporaryDirectory() as tmp_user_dir:
        tmp_path = Path(tmp_user_dir)
        with patch.object(PBRImporterPresetManager, "get_user_dir", return_value=tmp_path):
            sample = {
                "name": "Unreal Engine 5",
                "version": 2,
                "maps": [{"id": "base", "suffixes": ["_BC"], "channels": {"rgb": {"target": "Base Color"}}}],
            }
            import pytest

            with pytest.raises(PermissionError, match="Cannot overwrite built-in factory preset"):
                PBRImporterPresetManager.save_custom_preset(sample, custom_id="unreal_engine_5")


def test_dos_device_name_protection():
    """Verify Windows DOS reserved device names (CON, NUL, COM1, etc.) are safely suffixed."""
    for dos_name in ("CON", "PRN", "AUX", "NUL", "COM1", "LPT1"):
        clean = PBRImporterPresetManager.sanitize_id(dos_name)
        assert clean.upper() not in PBRImporterPresetManager.DOS_DEVICE_NAMES
        assert clean.endswith("_preset")


def test_duplicate_preset_collision_numbering():
    """Verify duplicate_preset handles collision-safe incremental naming (_2, _3)."""
    with tempfile.TemporaryDirectory() as tmp_user_dir:
        tmp_path = Path(tmp_user_dir)
        with patch.object(PBRImporterPresetManager, "get_user_dir", return_value=tmp_path):
            # Duplicate factory preset
            dup1_id = PBRImporterPresetManager.duplicate_preset("unreal_engine_5", "My UE5")
            assert dup1_id == "my_ue5"
            assert (tmp_path / "my_ue5.json").exists()

            # Duplicate again with same name -> collision resolution
            dup2_id = PBRImporterPresetManager.duplicate_preset("unreal_engine_5", "My UE5")
            assert dup2_id == "my_ue5_2"
            assert (tmp_path / "my_ue5_2.json").exists()

            # Duplicate a third time
            dup3_id = PBRImporterPresetManager.duplicate_preset("unreal_engine_5", "My UE5")
            assert dup3_id == "my_ue5_3"
            assert (tmp_path / "my_ue5_3.json").exists()

            # Clean up
            assert PBRImporterPresetManager.delete_custom_preset(dup1_id)
            assert PBRImporterPresetManager.delete_custom_preset(dup2_id)
            assert PBRImporterPresetManager.delete_custom_preset(dup3_id)


def test_unified_preset_export_properties():
    """Verify factory presets expose valid target_engine, strategy, bit_depth, and naming_pattern."""
    presets = PBRImporterPresetManager.load_presets(force_reload=True)
    engine_presets = {
        "unreal_engine_5": ("UE5", "CONVERT_PNG", 8),
        "unity_hdrp_maskmap": ("UNITY_6", "CONVERT_PNG", 16),
        "unity_urp_metallic": ("UNITY_6", "CONVERT_PNG", 8),
        "godot_4_orm": ("GODOT_4", "PASSTHROUGH", 8),
        "msfs_2024_comp": ("MSFS_2024", "CONVERT_PNG", 8),
    }
    for pid, (expected_engine, expected_strat, expected_bits) in engine_presets.items():
        assert pid in presets
        p = presets[pid]
        assert p.get("target_engine") == expected_engine
        assert p.get("strategy") == expected_strat
        assert p.get("bit_depth") == expected_bits
        assert "{material}" in p.get("naming_pattern", "")
        assert PBRImporterPresetManager.is_builtin(pid) is True


def test_clean_preset_display_names():
    """Verify that preset dropdown display names are clean without [Factory] or [Custom] suffixes."""
    items = PBRImporterPresetManager.get_enum_items()
    assert len(items) > 0
    for pid, name, _desc in items:
        assert "[Factory]" not in name, f"Preset '{pid}' display name still contains '[Factory]': {name}"
        assert "[Custom]" not in name, f"Preset '{pid}' display name still contains '[Custom]': {name}"
        assert len(name) > 0


def test_cross_session_state_persistence():
    """Verify that user preset selections persist across sessions via user_state.json."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        state_file = Path(tmp_dir) / "user_state.json"
        with patch.object(PBRImporterPresetManager, "get_state_file", return_value=state_file):
            # Initially default
            assert PBRImporterPresetManager.get_last_active_preset("export") == DEFAULT_PRESET_ID
            assert PBRImporterPresetManager.get_last_active_preset("import") == DEFAULT_PRESET_ID

            # Save export and import preferences
            PBRImporterPresetManager.set_last_active_preset("export", "unity_hdrp_maskmap")
            PBRImporterPresetManager.set_last_active_preset("import", "godot_4_orm")

            assert state_file.exists()
            assert PBRImporterPresetManager.get_last_active_preset("export") == "unity_hdrp_maskmap"
            assert PBRImporterPresetManager.get_last_active_preset("import") == "godot_4_orm"

            # Invalid preset ID falls back to default
            PBRImporterPresetManager.set_last_active_preset("export", "non_existent_preset_xyz")
            assert PBRImporterPresetManager.get_last_active_preset("export") == DEFAULT_PRESET_ID


def test_duplicate_preset_with_overrides():
    """Verify that duplicate_preset applies atomic field overrides upon creation."""
    with tempfile.TemporaryDirectory() as tmp_user_dir:
        tmp_path = Path(tmp_user_dir)
        with patch.object(PBRImporterPresetManager, "get_user_dir", return_value=tmp_path):
            overrides = {
                "strategy": "BAKE",
                "bit_depth": 16,
                "naming_pattern": "{asset}_{material}_Custom",
            }
            dup_id = PBRImporterPresetManager.duplicate_preset("unreal_engine_5", "Overridden UE5", overrides=overrides)
            assert dup_id == "overridden_ue5"
            pdata = PBRImporterPresetManager.get_preset("overridden_ue5")
            assert pdata["strategy"] == "BAKE"
            assert pdata["bit_depth"] == 16
            assert pdata["naming_pattern"] == "{asset}_{material}_Custom"
            assert pdata["name"] == "Overridden UE5"

            assert PBRImporterPresetManager.delete_custom_preset(dup_id)


def test_preset_sync_guard():
    """Verify that PresetSyncGuard correctly nests depth and reports locked state."""
    from ui.properties import PresetSyncGuard

    assert not PresetSyncGuard.is_locked()
    with PresetSyncGuard():
        assert PresetSyncGuard.is_locked()
        with PresetSyncGuard():
            assert PresetSyncGuard.is_locked()
        assert PresetSyncGuard.is_locked()
    assert not PresetSyncGuard.is_locked()


def test_map_sync_guard():
    """Verify that MapSyncGuard correctly tracks nested active state."""
    from ui.properties import MapSyncGuard

    assert not MapSyncGuard.is_active()
    with MapSyncGuard():
        assert MapSyncGuard.is_active()
        with MapSyncGuard():
            assert MapSyncGuard.is_active()
        assert MapSyncGuard.is_active()
    assert not MapSyncGuard.is_active()


def test_sync_maps_from_preset_and_to_preset():
    """Verify conversion between JSON preset maps dictionary and RNA-like items."""
    from unittest.mock import MagicMock
    from ui.properties import sync_maps_from_preset

    # Mock props object with active maps collection
    class MockMapItem:
        def __init__(self):
            self.map_id = "test_map"
            self.name = "Test Map"
            self.priority = 10
            self.suffixes_str = "_Test, _T"
            self.color_space = "Non-Color"
            self.is_normal_map = False
            self.normal_format = "OPENGL"
            self.is_packed = False
            self.target_rgb = "Base Color"
            self.target_a = "NONE"
            self.invert_a = False
            self.target_r = "NONE"
            self.invert_r = False
            self.target_g = "NONE"
            self.invert_g = False
            self.target_b = "NONE"
            self.invert_b = False

    class MockCollection(list):
        def add(self):
            item = MockMapItem()
            self.append(item)
            return item

        def clear(self):
            del self[:]

        def remove(self, idx):
            del self[idx]

    mock_props = MagicMock()
    mock_props.pbr_active_maps = MockCollection()
    mock_props.pbr_active_map_index = 0
    mock_props.pbr_import_preset = "unreal_engine_5"

    sample_preset = {
        "id": "unreal_engine_5",
        "name": "Unreal Engine 5",
        "maps": [
            {
                "id": "base_color",
                "name": "Base Color",
                "priority": 1,
                "suffixes": ["_BaseColor", "_BC"],
                "color_space": "sRGB",
                "channels": {"rgb": {"target": "Base Color", "invert": False}},
            },
            {
                "id": "orm",
                "name": "ORM",
                "priority": 2,
                "suffixes": ["_ORM"],
                "color_space": "Non-Color",
                "channels": {
                    "r": {"target": "Ambient Occlusion", "invert": False},
                    "g": {"target": "Roughness", "invert": False},
                    "b": {"target": "Metallic", "invert": False},
                },
            },
        ],
    }

    # Test populate
    sync_maps_from_preset(mock_props, sample_preset)
    assert len(mock_props.pbr_active_maps) == 2
    assert mock_props.pbr_active_maps[0].map_id == "base_color"
    assert mock_props.pbr_active_maps[0].name == "Base Color"
    assert not mock_props.pbr_active_maps[0].is_packed
    assert mock_props.pbr_active_maps[0].target_rgb == "Base Color"

    assert mock_props.pbr_active_maps[1].map_id == "orm"
    assert mock_props.pbr_active_maps[1].is_packed
    assert mock_props.pbr_active_maps[1].target_r == "Ambient Occlusion"
    assert mock_props.pbr_active_maps[1].target_g == "Roughness"
    assert mock_props.pbr_active_maps[1].target_b == "Metallic"


def test_omnimesh_ul_preset_maps_draw_item():
    """Verify OMNIMESH_UL_preset_maps draws valid icons and responsive columns without gaps."""
    from ui.lists import OMNIMESH_UL_preset_maps

    ul = OMNIMESH_UL_preset_maps()
    ul.layout_type = "DEFAULT"

    mock_layout = MagicMock()
    mock_row = MagicMock()
    mock_col = MagicMock()
    mock_layout.row.return_value = mock_row
    mock_row.split.return_value = mock_col

    # 1. Normal map test
    normal_item = MagicMock()
    normal_item.is_normal_map = True
    normal_item.name = "Normal Map"
    normal_item.suffixes_str = "_Normal, _Norm, _N, _NRM"
    ul.draw_item(None, mock_layout, None, normal_item, None, None, None)
    mock_col.label.assert_any_call(text="Normal Map", icon="SNAP_NORMAL")
    mock_col.label.assert_any_call(text="(_Normal, _Norm (+2))")

    # 2. Packed map test
    mock_col.reset_mock()
    packed_item = MagicMock()
    packed_item.is_normal_map = False
    packed_item.is_packed = True
    packed_item.name = "ORM"
    packed_item.suffixes_str = "_ORM, _ARM"
    ul.draw_item(None, mock_layout, None, packed_item, None, None, None)
    mock_col.label.assert_any_call(text="ORM", icon="IMAGE_RGB_ALPHA")
    mock_col.label.assert_any_call(text="(_ORM, _ARM)")

    # 3. None item handling (must not raise)
    ul.draw_item(None, mock_layout, None, None, None, None, None)


def test_sync_export_maps_from_and_to_preset():
    """Verify bidirectional synchronization for export preset maps and Copy-on-Write."""
    from ui.properties import sync_export_maps_from_preset

    class MockExportItem:
        def __init__(self):
            self.map_id = "test_map"
            self.name = "Test Map"
            self.export = True
            self.export_suffix = "_Test"
            self.color_space = "Non-Color"
            self.is_normal_map = False
            self.normal_format = "OPENGL"
            self.is_packed = False
            self.target_rgb = "Base Color"
            self.target_a = "NONE"
            self.invert_a = False
            self.target_r = "Ambient Occlusion"
            self.invert_r = False
            self.target_g = "Roughness"
            self.invert_g = False
            self.target_b = "Metallic"
            self.invert_b = False

    class MockExportCollection:
        def __init__(self):
            self.items: list[MockExportItem] = []

        def clear(self):
            self.items.clear()

        def add(self):
            it = MockExportItem()
            self.items.append(it)
            return it

        def __iter__(self):
            return iter(self.items)

        def __len__(self):
            return len(self.items)

        def __getitem__(self, idx):
            return self.items[idx]

    mock_props = MagicMock()
    mock_props.pbr_export_active_maps = MockExportCollection()
    mock_props.pbr_export_active_map_index = 0
    mock_props.pbr_export_preset = "custom_test_export"

    sample_preset = {
        "id": "custom_test_export",
        "name": "Custom Export Preset",
        "version": 2,
        "target_engine": "UE5",
        "strategy": "SMART_AUTO",
        "maps": [
            {
                "id": "base_color",
                "name": "Base Color",
                "export": True,
                "export_suffix": "_BaseColor",
                "color_space": "sRGB",
                "channels": {"rgb": {"target": "Base Color", "invert": False}},
            },
            {
                "id": "orm",
                "name": "ORM",
                "export": True,
                "export_suffix": "_ORM",
                "color_space": "Non-Color",
                "channels": {
                    "r": {"target": "Ambient Occlusion", "invert": False},
                    "g": {"target": "Roughness", "invert": False},
                    "b": {"target": "Metallic", "invert": False},
                },
            },
        ],
    }

    # Test populate from preset
    sync_export_maps_from_preset(mock_props, sample_preset)
    assert len(mock_props.pbr_export_active_maps) == 2
    assert mock_props.pbr_export_active_maps[0].map_id == "base_color"
    assert mock_props.pbr_export_active_maps[0].export is True
    assert mock_props.pbr_export_active_maps[0].export_suffix == "_BaseColor"
    assert not mock_props.pbr_export_active_maps[0].is_packed

    assert mock_props.pbr_export_active_maps[1].map_id == "orm"
    assert mock_props.pbr_export_active_maps[1].is_packed
    assert mock_props.pbr_export_active_maps[1].target_r == "Ambient Occlusion"
    assert mock_props.pbr_export_active_maps[1].target_g == "Roughness"
    assert mock_props.pbr_export_active_maps[1].target_b == "Metallic"


def test_omnimesh_ul_export_preset_maps_draw_item():
    """Verify OMNIMESH_UL_export_preset_maps renders export checkbox, icons, and suffix badge."""
    from ui.lists import OMNIMESH_UL_export_preset_maps

    ul = OMNIMESH_UL_export_preset_maps()
    ul.layout_type = "DEFAULT"

    mock_layout = MagicMock()
    mock_row = MagicMock()
    mock_col = MagicMock()
    mock_col_name = MagicMock()
    mock_layout.row.return_value = mock_row
    mock_row.split.side_effect = [mock_col, mock_col_name]

    # Export map item
    export_item = MagicMock()
    export_item.export = True
    export_item.is_normal_map = True
    export_item.name = "Normal Map"
    export_item.export_suffix = "_Normal"

    ul.draw_item(None, mock_layout, None, export_item, None, None, None)
    mock_col.prop.assert_any_call(export_item, "export", text="")
    mock_col_name.label.assert_any_call(text="Normal Map", icon="SNAP_NORMAL")
    mock_row.label.assert_any_call(text="(_Normal)")
