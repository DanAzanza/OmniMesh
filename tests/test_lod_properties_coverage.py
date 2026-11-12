"""
Comprehensive unit tests for ui.properties.lod_properties.
Validates RNA callbacks, hydration, serialization, chunking/impostor/culling sync,
and dirty state management.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch


from ui.properties.guards import PresetSyncGuard, StateRestorationGuard
from ui.properties.lod_properties import (
    on_lod_preset_property_modified,
    on_preset_tier_item_updated,
    on_tier_target_pct_updated,
    on_tier_target_tris_updated,
    sync_preset_tiers_from_preset,
    sync_preset_tiers_to_preset,
)


def test_on_tier_target_pct_updated():
    # Context None or missing scene
    item = {"target_tris": 0, "triangle_target": 0}
    on_tier_target_pct_updated(item, None)
    assert item["target_tris"] == 0

    mock_context = MagicMock()
    mock_props = MagicMock()
    mock_props.base_triangles = 0
    mock_context.scene.lod_tool = mock_props

    mock_item = MagicMock()
    mock_item.target_tris_pct = 50.0
    mock_item.target_tris = 100
    store: dict[str, Any] = {}
    mock_item.__setitem__.side_effect = store.__setitem__

    on_tier_target_pct_updated(mock_item, mock_context)
    assert "target_tris" not in store

    # Positive case
    mock_props.base_triangles = 10000
    mock_item.target_tris = 0
    on_tier_target_pct_updated(mock_item, mock_context)
    assert store.get("target_tris") == 5000
    assert store.get("triangle_target") == 5000


def test_on_tier_target_tris_updated():
    # Context None or missing scene
    mock_item = MagicMock()
    on_tier_target_tris_updated(mock_item, None)

    mock_context = MagicMock()
    mock_props = MagicMock()
    mock_props.base_triangles = 10000
    mock_context.scene.lod_tool = mock_props

    mock_item.target_tris = 2500
    mock_item.target_tris_pct = 0.0
    store: dict[str, Any] = {}
    mock_item.__setitem__.side_effect = store.__setitem__

    on_tier_target_tris_updated(mock_item, mock_context)
    assert store.get("target_tris_pct") == 25.0


def test_preset_modification_callbacks():
    mock_context = MagicMock()
    mock_props = MagicMock()
    mock_props.lod_preset = "built_in_default"
    mock_props.lod_preset_is_dirty = False
    mock_context.scene.lod_tool = mock_props

    # Guard locked: no-op
    with PresetSyncGuard():
        on_preset_tier_item_updated(None, mock_context)
        assert mock_props.lod_preset_is_dirty is False

    with StateRestorationGuard():
        on_lod_preset_property_modified(None, mock_context)
        assert mock_props.lod_preset_is_dirty is False

    # Unlocked: flags dirty
    with patch("core.lod_presets.LODPresetManager.is_builtin", return_value=True):
        on_preset_tier_item_updated(None, mock_context)
        assert mock_props.lod_preset_is_dirty is True

        mock_props.lod_preset_is_dirty = False
        on_lod_preset_property_modified(None, mock_context)
        assert mock_props.lod_preset_is_dirty is True


def test_sync_preset_tiers_from_preset_complete():
    class MockTier:
        def __init__(self):
            self.name = ""
            self.screen_size_pct = 0.0
            self.target_tris_pct = 0.0
            self.target_tris = 0

    class MockProps:
        def __init__(self):
            self.tiers: list[MockTier] = []
            self.lod_preset_active_id = ""
            self.lod_preset_budget_mode = ""
            self.lod_preset_active_tier_index = 0
            self.lod_preset_is_dirty = True
            self.base_triangles = 80000

            # Sub-features
            self.enable_spatial_chunking = False
            self.chunk_cell_size = 0.0
            self.chunk_split_z = False
            self.chunk_cell_size_z = 0.0
            self.chunk_partitioning_mode = ""
            self.adaptive_cluster_target_polys = 0
            self.enable_hlod = False
            self.hlod_start_tier = 0

            self.enable_impostor_lod = False
            self.impostor_mode = ""
            self.impostor_resolution = ""
            self.impostor_replace_last_lod = False

            self.enable_occlusion_culling = False
            self.occlusion_lod_start = 0
            self.occlusion_ray_density = 0
            self.occlusion_evaluate_alpha = False
            self.enable_slender_culling = False

            self.pin_uv_seams = False
            self.pin_material_borders = False

            self.tau_sse = 0.0
            self.cull_screen_size_pct = 0.0
            self.consolidate_hierarchy = False

        @property
        def lod_preset_active_tiers(self):
            props_self = self

            class TierCollection:
                def clear(self):
                    props_self.tiers.clear()

                def add(self):
                    t = MockTier()
                    props_self.tiers.append(t)
                    return t

                def __iter__(self):
                    return iter(props_self.tiers)

                def __len__(self):
                    return len(props_self.tiers)

            return TierCollection()

    props = MockProps()
    preset = {
        "id": "custom_hero_preset",
        "budget_mode": "PERCENTAGE",
        "tiers": [
            {"name": "LOD0", "screen_size_pct": 100.0, "target_tris_pct": 100.0, "target_tris": 80000},
            {"name": "LOD1", "screen_size_pct": 50.0, "target_tris_pct": 50.0},
        ],
        "chunking": {
            "enabled": True,
            "cell_size": 64.0,
            "split_z": True,
            "cell_size_z": 16.0,
            "partitioning_mode": "ADAPTIVE_OCTREE",
            "adaptive_target_polys": 25000,
            "enable_hlod": True,
            "hlod_start_tier": 1,
        },
        "impostor": {
            "enabled": True,
            "mode": "OCTAHEDRAL_HEMI",
            "resolution": "1024",
            "replace_last_lod": True,
        },
        "culling": {
            "occlusion_enabled": True,
            "occlusion_lod_start": 2,
            "occlusion_ray_density": 32,
            "occlusion_evaluate_alpha": False,
            "slender_enabled": True,
        },
        "pinning": {
            "pin_uv_seams": True,
            "pin_material_borders": False,
        },
        "tau_sse": 0.05,
        "cull_screen_size_pct": 1.5,
        "consolidate_hierarchy": True,
    }

    sync_preset_tiers_from_preset(props, preset)

    assert props.lod_preset_active_id == "custom_hero_preset"
    assert props.lod_preset_budget_mode == "PERCENTAGE"
    assert len(props.tiers) == 2
    assert props.tiers[0].target_tris == 80000
    assert props.tiers[1].target_tris == 40000  # 50% of 80000 base
    assert props.enable_spatial_chunking is True
    assert props.chunk_cell_size == 64.0
    assert props.chunk_split_z is True
    assert props.chunk_partitioning_mode == "ADAPTIVE_OCTREE"
    assert props.impostor_mode == "OCTAHEDRAL_HEMI"
    assert props.occlusion_lod_start == 2
    assert props.pin_uv_seams is True
    assert props.pin_material_borders is False
    assert props.tau_sse == 0.05
    assert props.cull_screen_size_pct == 1.5
    assert props.consolidate_hierarchy is True
    assert props.lod_preset_is_dirty is False


def test_sync_preset_tiers_to_preset():
    class MockTier:
        def __init__(self, name: str, screen: float, tris_pct: float, tris: int):
            self.name = name
            self.screen_size_pct = screen
            self.target_tris_pct = tris_pct
            self.target_tris = tris
            self.is_pinned = False
            self.is_impostor = False

    class MockProps:
        def __init__(self):
            self.lod_preset = "my_preset"
            self.lod_preset_budget_mode = "ABSOLUTE"
            self.tau_sse = 0.04
            self.cull_screen_size_pct = 2.0
            self.consolidate_hierarchy = True
            self.lod_preset_active_tiers = [
                MockTier("LOD0", 100.0, 100.0, 50000),
                MockTier("LOD1", 50.0, 50.0, 25000),
            ]
            self.enable_spatial_chunking = False
            self.chunk_cell_size = 32.0
            self.chunk_split_z = False
            self.chunk_cell_size_z = 32.0
            self.chunk_partitioning_mode = "UNIFORM_GRID"
            self.adaptive_cluster_target_polys = 50000
            self.enable_hlod = True
            self.hlod_start_tier = 2

            self.enable_impostor_lod = False
            self.impostor_mode = "ORTHO_3_AXES"
            self.impostor_resolution = "2048"
            self.impostor_replace_last_lod = True

            self.enable_occlusion_culling = True
            self.occlusion_lod_start = 1
            self.occlusion_ray_density = 16
            self.occlusion_evaluate_alpha = True
            self.enable_slender_culling = True

            self.pin_uv_seams = True
            self.pin_material_borders = True
            self.lod_preset_active_id = ""
            self.lod_preset_is_dirty = True

    props = MockProps()
    saved_data = {}

    def mock_save(data, custom_id=None):
        saved_data["id"] = custom_id
        saved_data["data"] = data

    with (
        patch("core.lod_presets.LODPresetManager.get_preset", return_value={"name": "Template"}),
        patch("core.lod_presets.LODPresetManager.save_custom_preset", side_effect=mock_save),
    ):
        result_id = sync_preset_tiers_to_preset(props)

    assert result_id == "my_preset"
    assert props.lod_preset_active_id == "my_preset"
    assert props.lod_preset_is_dirty is False
    assert saved_data["data"]["budget_mode"] == "ABSOLUTE"
    assert len(saved_data["data"]["tiers"]) == 2
    assert saved_data["data"]["tiers"][0]["target_tris"] == 50000
    assert saved_data["data"]["chunking"]["cell_size"] == 32.0
    assert saved_data["data"]["impostor"]["mode"] == "ORTHO_3_AXES"
