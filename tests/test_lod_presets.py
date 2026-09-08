"""
Unit tests for OmniMesh LOD Presets Subsystem (JSON storage, schema validation, atomic writes).
"""

from __future__ import annotations

from pathlib import Path
import tempfile
from unittest.mock import patch


from core.lod_presets import (
    DEFAULT_LOD_PRESET_ID,
    LODPresetManager,
)


def test_builtin_lod_presets_discovery_and_schema():
    """Verify all shipped JSON presets in presets/lod_presets/ are discovered and pass schema validation."""
    presets = LODPresetManager.load_presets(force_reload=True)
    expected_builtins = {
        "unreal_engine_5",
        "unity_hdrp",
        "godot_4",
        "msfs_2024",
        "msfs_aircraft_huge_ext",
        "msfs_aircraft_big_ext",
        "msfs_aircraft_medium_ext",
        "msfs_aircraft_small_ext",
        "msfs_aircraft_interior",
        "mobile_vr",
    }
    for pid in expected_builtins:
        assert pid in presets, f"Expected built-in LOD preset '{pid}' not found in presets."
        pdata = presets[pid]
        assert pdata.get("name"), f"Preset '{pid}' must have a valid non-empty name."
        assert pdata.get("version", 0) >= 1, f"Preset '{pid}' must have schema version >= 1."
        assert pdata.get("_is_builtin") is True, f"Preset '{pid}' must be marked as built-in."
        assert pdata.get("budget_mode") in {"PERCENTAGE", "ABSOLUTE"}, f"Invalid budget_mode in '{pid}'."
        tiers = pdata.get("tiers", [])
        assert len(tiers) >= 2, f"Preset '{pid}' must define at least two LOD tiers."
        for idx, t in enumerate(tiers):
            assert t.get("name"), f"Tier {idx} in '{pid}' missing name."
            assert 0.01 <= t.get("screen_size_pct", 0) <= 100.0, f"Invalid screen_size_pct in tier {idx} of '{pid}'."
            if pdata.get("budget_mode") == "ABSOLUTE":
                assert t.get("target_tris", 0) >= 1, (
                    f"Missing or invalid target_tris in absolute tier {idx} of '{pid}'."
                )
            else:
                assert 0.01 <= t.get("target_tris_pct", 0) <= 100.0, (
                    f"Invalid target_tris_pct in tier {idx} of '{pid}'."
                )


def test_validate_lod_preset_schema_rejections():
    """Verify malformed LOD presets are rejected by schema validation."""
    assert LODPresetManager.validate_preset_schema(None) is None
    assert LODPresetManager.validate_preset_schema({}) is None
    assert LODPresetManager.validate_preset_schema({"name": ""}) is None
    assert LODPresetManager.validate_preset_schema({"name": "Valid", "tiers": []}) is None
    assert LODPresetManager.validate_preset_schema({"name": "Valid", "tiers": "not-a-list"}) is None

    # Tiers with non-dict or unparseable values
    bad_tiers = {"name": "Test", "tiers": [{"screen_size_pct": "invalid"}]}
    assert LODPresetManager.validate_preset_schema(bad_tiers) is None


def test_sanitize_id():
    """Verify ID sanitization strips invalid characters and guards DOS device names."""
    assert LODPresetManager.sanitize_id("My Custom LOD! 123") == "my_custom_lod_123"
    assert LODPresetManager.sanitize_id("../../../etc/passwd") == "etc_passwd"
    assert LODPresetManager.sanitize_id("CON") == "con_preset"
    assert LODPresetManager.sanitize_id("   ") == "custom_preset"


def test_save_and_delete_custom_lod_preset():
    """Verify custom LOD preset saving and deletion without mutating built-in presets."""
    with tempfile.TemporaryDirectory() as tmp_user_dir:
        tmp_path = Path(tmp_user_dir)
        with patch.object(LODPresetManager, "get_user_dir", return_value=tmp_path):
            custom_data = {
                "name": "Custom Mobile Flight",
                "version": 1,
                "description": "Custom aggressive curve for flight simulator mobile port",
                "target_engine": "MSFS_2024",
                "tiers": [
                    {"name": "LOD0", "screen_size_pct": 100.0, "target_tris_pct": 100.0},
                    {"name": "LOD1", "screen_size_pct": 45.0, "target_tris_pct": 40.0},
                    {"name": "LOD2", "screen_size_pct": 15.0, "target_tris_pct": 10.0},
                ],
            }

            custom_id = LODPresetManager.save_custom_preset(custom_data)
            assert custom_id == "custom_mobile_flight"

            # Verify saved file exists on disk
            json_file = tmp_path / f"{custom_id}.json"
            assert json_file.is_file()

            # Verify loaded through manager
            presets = LODPresetManager.load_presets(force_reload=True)
            assert custom_id in presets
            loaded = presets[custom_id]
            assert loaded["name"] == "Custom Mobile Flight"
            assert loaded["_is_builtin"] is False
            assert len(loaded["tiers"]) == 3

            # Test unrestricted saving over built-in template as user override
            override_id = LODPresetManager.save_custom_preset(custom_data, custom_id=DEFAULT_LOD_PRESET_ID)
            assert override_id == DEFAULT_LOD_PRESET_ID
            override_file = tmp_path / f"{DEFAULT_LOD_PRESET_ID}.json"
            assert override_file.is_file()
            assert LODPresetManager.is_user_preset(DEFAULT_LOD_PRESET_ID) is True

            # Deleting override restores factory template
            assert LODPresetManager.delete_custom_preset(DEFAULT_LOD_PRESET_ID) is True
            assert not override_file.exists()
            assert LODPresetManager.is_user_preset(DEFAULT_LOD_PRESET_ID) is False
            reloaded = LODPresetManager.load_presets(force_reload=True)
            assert reloaded[DEFAULT_LOD_PRESET_ID]["_is_builtin"] is True

            # Deleting again returns False since no user file exists
            assert LODPresetManager.delete_custom_preset(DEFAULT_LOD_PRESET_ID) is False

            # Delete custom preset
            assert LODPresetManager.delete_custom_preset(custom_id) is True
            assert not json_file.exists()
            assert custom_id not in LODPresetManager.load_presets(force_reload=True)


def test_duplicate_lod_preset():
    """Verify cloning an existing preset produces a unique user custom preset."""
    with tempfile.TemporaryDirectory() as tmp_user_dir:
        tmp_path = Path(tmp_user_dir)
        with patch.object(LODPresetManager, "get_user_dir", return_value=tmp_path):
            LODPresetManager.load_presets(force_reload=True)
            new_id = LODPresetManager.duplicate_preset("unreal_engine_5")
            assert new_id == "unreal_engine_5_standard_copy"

            presets = LODPresetManager.load_presets(force_reload=True)
            assert new_id in presets
            assert presets[new_id]["_is_builtin"] is False
            assert len(presets[new_id]["tiers"]) == 4


def test_get_enum_items():
    """Verify get_enum_items returns 3-tuples suitable for Blender EnumProperty."""
    items = LODPresetManager.get_enum_items()
    assert len(items) >= 5
    for item in items:
        assert len(item) == 3
        pid, name, desc = item
        assert pid and name


def test_chunking_preset_schema_validation():
    """Verify chunking dictionary validation with defaults and boundary clamping."""
    data = {
        "name": "Terrain Preset",
        "tiers": [{"name": "LOD0", "screen_size_pct": 100.0, "target_tris_pct": 100.0}],
        "chunking": {
            "enabled": True,
            "cell_size": 64.0,
            "split_z": True,
            "cell_size_z": 16.0,
            "partitioning_mode": "ADAPTIVE_CLUSTERING",
            "adaptive_target_polys": 25000,
            "enable_hlod": True,
            "hlod_start_tier": 3,
        },
    }
    validated = LODPresetManager.validate_preset_schema(data)
    assert validated is not None
    chunk = validated.get("chunking")
    assert chunk is not None
    assert chunk["enabled"] is True
    assert chunk["cell_size"] == 64.0
    assert chunk["split_z"] is True
    assert chunk["cell_size_z"] == 16.0
    assert chunk["partitioning_mode"] == "ADAPTIVE_CLUSTERING"
    assert chunk["adaptive_target_polys"] == 25000
    assert chunk["enable_hlod"] is True
    assert chunk["hlod_start_tier"] == 3


def test_impostor_culling_pinning_preset_schema():
    """Verify impostor, culling, and pinning validation, default fallbacks, and resolution 512."""
    data = {
        "name": "Full Feature Preset",
        "tiers": [{"name": "LOD0", "screen_size_pct": 100.0, "target_tris_pct": 100.0}],
        "impostor": {
            "enabled": True,
            "mode": "OCTAHEDRAL_HEMI",
            "resolution": "512",
            "replace_last_lod": True,
            "screen_size_pct": 2.0,
        },
        "culling": {
            "occlusion_enabled": True,
            "occlusion_lod_start": 2,
            "occlusion_ray_density": 32,
            "occlusion_evaluate_alpha": False,
            "slender_enabled": True,
        },
        "pinning": {
            "pin_uv_seams": False,
            "pin_material_borders": True,
        },
    }
    val = LODPresetManager.validate_preset_schema(data)
    assert val is not None

    imp = val["impostor"]
    assert imp["enabled"] is True
    assert imp["mode"] == "OCTAHEDRAL_HEMI"
    assert imp["resolution"] == "512"
    assert imp["replace_last_lod"] is True
    assert imp["screen_size_pct"] == 2.0

    cull = val["culling"]
    assert cull["occlusion_enabled"] is True
    assert cull["occlusion_lod_start"] == 2
    assert cull["occlusion_ray_density"] == 32
    assert cull["occlusion_evaluate_alpha"] is False
    assert cull["slender_enabled"] is True

    pin = val["pinning"]
    assert pin["pin_uv_seams"] is False
    assert pin["pin_material_borders"] is True

    # Test fallback defaults for legacy preset lacking these blocks
    legacy_data = {
        "name": "Legacy Preset",
        "tiers": [{"name": "LOD0", "screen_size_pct": 100.0, "target_tris_pct": 100.0}],
    }
    val_legacy = LODPresetManager.validate_preset_schema(legacy_data)
    assert val_legacy is not None
    assert val_legacy["impostor"]["enabled"] is False
    assert val_legacy["impostor"]["resolution"] == "2048"
    assert val_legacy["culling"]["occlusion_enabled"] is True
    assert val_legacy["culling"]["occlusion_lod_start"] == 1
    assert val_legacy["pinning"]["pin_uv_seams"] is True
