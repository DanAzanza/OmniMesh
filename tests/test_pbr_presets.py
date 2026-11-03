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
            PBRImporterPresetManager.set_last_active_preset("import", "standard_pbr_split")

            assert state_file.exists()
            assert PBRImporterPresetManager.get_last_active_preset("export") == "unity_hdrp_maskmap"
            assert PBRImporterPresetManager.get_last_active_preset("import") == "standard_pbr_split"

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


def test_format_texture_name_standard_and_variations():
    """Verify format_texture_name supports standard placeholders, UDIM, and custom casing."""
    from core.pbr_presets import format_texture_name

    # 1. Standard pattern with asset, material, suffix, and udim
    name = format_texture_name(
        pattern="{asset}_{material}{suffix}{udim}",
        asset="SimpleAircraft",
        material="FUSELAGE",
        suffix="_ALBEDO",
        udim="",
    )
    assert name == "SimpleAircraft_FUSELAGE_ALBEDO"

    # 2. With UDIM tile
    name_udim = format_texture_name(
        pattern="{asset}_{material}{suffix}{udim}",
        asset="SimpleAircraft",
        material="FUSELAGE",
        suffix="_ALBEDO",
        udim="1001",
    )
    assert name_udim == "SimpleAircraft_FUSELAGE_ALBEDO_1001"

    # 3. Without asset name (leading underscore must be cleanly stripped)
    name_no_asset = format_texture_name(
        pattern="{asset}_{material}{suffix}{udim}",
        asset="",
        material="Cockpit",
        suffix="_NORM",
        udim="",
    )
    assert name_no_asset == "Cockpit_NORM"

    # 4. German / custom casing placeholders {AssetName}_{MaterialName}_{TexturArt}_{UDIM}
    name_custom = format_texture_name(
        pattern="{AssetName}_{MaterialName}_{TexturArt}_{UDIM}",
        asset="A320",
        material="Wings",
        suffix="COMP",
        udim="1002",
    )
    assert name_custom == "A320_Wings_COMP_1002"

    # 5. Empty suffix and fallback material
    name_fallback = format_texture_name(
        pattern="{asset}_{material}{suffix}{udim}",
        asset="",
        material="",
        suffix="",
        udim="",
    )
    assert name_fallback == "Material"


def test_all_factory_presets_have_unified_naming_pattern():
    """Verify all built-in import and export presets use the unified AssetName_MaterialName_TexturArt_UDIM schema."""
    from core.pbr_presets import DEFAULT_NAMING_PATTERN, PBRExportPresetManager, PBRImportPresetManager

    importer_presets = PBRImportPresetManager.load_presets(force_reload=True)
    for pid, pdata in importer_presets.items():
        if pdata.get("_is_builtin"):
            pattern = pdata.get("naming_pattern", "")
            assert "{material}" in pattern, f"Importer preset {pid} missing {{material}}"
            assert pattern == DEFAULT_NAMING_PATTERN, f"Importer preset {pid} pattern is {pattern}"

    exporter_presets = PBRExportPresetManager.load_presets(force_reload=True)
    for pid, pdata in exporter_presets.items():
        if pdata.get("_is_builtin"):
            pattern = pdata.get("naming_pattern", "")
            assert "{material}" in pattern, f"Exporter preset {pid} missing {{material}}"
            assert pattern == DEFAULT_NAMING_PATTERN, f"Exporter preset {pid} pattern is {pattern}"


def test_create_new_preset_lifecycle():
    """Verify create_new_preset generates valid files from templates and minimal starters."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        with patch.object(PBRImporterPresetManager, "get_user_dir", return_value=tmp_path):
            # 1. Create from template
            pid_tpl = PBRImporterPresetManager.create_new_preset(
                name="Studio UE5",
                description="Custom studio profile",
                template_id="unreal_engine_5",
            )
            assert pid_tpl == "studio_ue5"
            assert (tmp_path / "studio_ue5.json").exists()
            data_tpl = PBRImporterPresetManager.get_preset("studio_ue5")
            assert data_tpl["name"] == "Studio UE5"
            assert "description" not in data_tpl
            assert len(data_tpl["maps"]) >= 3

            # 2. Create minimal starter
            pid_min = PBRImporterPresetManager.create_new_preset(
                name="Minimal Pipeline",
                template_id="minimal",
            )
            assert pid_min == "minimal_pipeline"
            assert (tmp_path / "minimal_pipeline.json").exists()
            data_min = PBRImporterPresetManager.get_preset("minimal_pipeline")
            assert data_min["name"] == "Minimal Pipeline"
            assert len(data_min["maps"]) == 1
            assert data_min["maps"][0]["id"] == "base_color"


def test_rename_custom_preset_lifecycle_and_boundaries():
    """Verify renaming custom presets updates files on disk, and enforces security boundaries."""
    import pytest

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        with patch.object(PBRImporterPresetManager, "get_user_dir", return_value=tmp_path):
            # Create a test custom preset
            assert PBRImporterPresetManager.create_new_preset("Old Pipeline") == "old_pipeline"
            assert (tmp_path / "old_pipeline.json").exists()

            # Successful rename
            new_id = PBRImporterPresetManager.rename_custom_preset("old_pipeline", "New Cool Pipeline")
            assert new_id == "new_cool_pipeline"
            assert not (tmp_path / "old_pipeline.json").exists()
            assert (tmp_path / "new_cool_pipeline.json").exists()
            renamed = PBRImporterPresetManager.get_preset("new_cool_pipeline")
            assert renamed["name"] == "New Cool Pipeline"

            # Boundaries:
            # 1. Cannot rename built-in preset
            with pytest.raises(PermissionError, match="built-in"):
                PBRImporterPresetManager.rename_custom_preset("unreal_engine_5", "Hacked UE5")

            # 2. Cannot rename with empty name
            with pytest.raises(ValueError, match="empty"):
                PBRImporterPresetManager.rename_custom_preset("new_cool_pipeline", "   ")

            # 3. Cannot rename non-existent preset
            with pytest.raises(FileNotFoundError):
                PBRImporterPresetManager.rename_custom_preset("ghost_preset", "Ghost")

            # 4. Cannot rename to built-in ID
            with pytest.raises(PermissionError, match="built-in factory preset ID"):
                PBRImporterPresetManager.rename_custom_preset("new_cool_pipeline", "unreal_engine_5")


def test_is_user_preset_distinction():
    """Verify is_user_preset accurately distinguishes factory templates from custom files."""
    assert PBRImporterPresetManager.is_user_preset("unreal_engine_5") is False
    assert PBRImporterPresetManager.is_user_preset("msfs_2024_comp") is False
    assert PBRImporterPresetManager.is_user_preset("") is False

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        with patch.object(PBRImporterPresetManager, "get_user_dir", return_value=tmp_path):
            pid = PBRImporterPresetManager.create_new_preset("User Spec")
            assert PBRImporterPresetManager.is_user_preset(pid) is True


def test_map_template_definitions_and_reordering():
    """Verify map template definitions contain valid suffixes and reordering synchronizes priority."""
    from ui.pbr_map_ops import (
        MAP_TEMPLATE_DEFINITIONS,
        TEMPLATE_ITEMS,
        LOD_OT_move_preset_map,
    )

    # 1. Verify template items contract
    for t_id, _name, _desc in TEMPLATE_ITEMS:
        assert t_id in MAP_TEMPLATE_DEFINITIONS
        t_data = MAP_TEMPLATE_DEFINITIONS[t_id]
        assert t_data["map_id"]
        assert len(t_data["suffixes"].split(",")) >= 1
        assert t_data["color_space"] in {"sRGB", "Non-Color"}

    # 2. Verify reordering priorities
    mock_item1 = MagicMock(priority=10)
    mock_item2 = MagicMock(priority=20)
    mock_item3 = MagicMock(priority=30)
    items = [mock_item1, mock_item2, mock_item3]

    mock_maps = MagicMock()
    mock_maps.__len__.side_effect = lambda: len(items)
    mock_maps.__iter__.side_effect = lambda: iter(items)
    mock_maps.__getitem__.side_effect = lambda i: items[i]
    mock_maps.move.side_effect = lambda src, dst: items.insert(dst, items.pop(src))

    mock_props = MagicMock()
    mock_props.pbr_active_maps = mock_maps
    mock_props.pbr_active_map_index = 0
    mock_props.pbr_import_preset = "custom_test"

    mock_context = MagicMock()
    mock_context.scene.lod_tool = mock_props

    with (
        patch.object(PBRImporterPresetManager, "is_builtin", return_value=False),
        patch("ui.pbr_map_ops.sync_maps_to_preset"),
    ):
        op_down = LOD_OT_move_preset_map()
        op_down.direction = "DOWN"
        res = op_down.execute(mock_context)
        assert res == {"FINISHED"}
        assert mock_props.pbr_active_map_index == 1
        # Priority should be deterministically re-indexed
        for idx, m in enumerate(items):
            assert m.priority == (idx + 1) * 10
