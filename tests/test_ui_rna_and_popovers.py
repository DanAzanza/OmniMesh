"""Unit and boundary tests for UI RNA helpers, options-only popover invariants, guards, and panel CTAs."""

from __future__ import annotations

from pathlib import Path
import threading
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

import ui.popover_presets as pop_mod
import ui.popovers as workflow_pop_mod
from ui.popover_presets import (
    OMNIMESH_PT_popover_export_preset,
    OMNIMESH_PT_popover_import_preset,
)
from ui.properties.guards import MapSyncGuard, PresetSyncGuard, StateRestorationGuard
from ui.vehicle_attachment_ops import import_msfs_attachments_file


def test_popovers_options_only_no_operators_or_timers() -> None:
    """Verify all preset and workflow popovers stay read-only and options-only during draw()."""
    op_calls: list[str] = []

    class _SpyLayout:
        def __init__(self) -> None:
            self.enabled = True
            self.use_property_split = False
            self.use_property_decorate = False

        def row(self, *args: Any, **kwargs: Any) -> "_SpyLayout":
            return _SpyLayout()

        def column(self, *args: Any, **kwargs: Any) -> "_SpyLayout":
            return _SpyLayout()

        def box(self, *args: Any, **kwargs: Any) -> "_SpyLayout":
            return _SpyLayout()

        def split(self, *args: Any, **kwargs: Any) -> "_SpyLayout":
            return _SpyLayout()

        def operator(self, bl_idname: str, *args: Any, **kwargs: Any) -> MagicMock:
            op_calls.append(bl_idname)
            return MagicMock()

        def prop(self, *args: Any, **kwargs: Any) -> None:
            return None

        def label(self, *args: Any, **kwargs: Any) -> None:
            return None

        def separator(self, *args: Any, **kwargs: Any) -> None:
            return None

        def template_list(self, *args: Any, **kwargs: Any) -> None:
            return None

    fake_bpy = MagicMock()
    map_item = SimpleNamespace(
        name="Albedo",
        suffixes_str="_albedo",
        target_socket="Base Color",
        invert=False,
        export=True,
        export_suffix="_D",
        color_space="sRGB",
        is_normal_map=False,
        normal_format="OPENGL",
        is_packed=True,
        target_r="NONE",
        invert_r=False,
        target_g="NONE",
        invert_g=False,
        target_b="NONE",
        invert_b=False,
        target_a="NONE",
        invert_a=False,
    )
    tier_item = SimpleNamespace(name="LOD1", screen_size_pct=40.0, target_tris_pct=50.0, target_tris=5000)
    props = SimpleNamespace(
        engine_import_preset="msfs_aircraft",
        engine_import_geometry=True,
        engine_import_spatial=True,
        engine_import_lights=True,
        engine_import_cameras=True,
        engine_import_model_target="BOTH",
        engine_import_use_lod0_suffix=True,
        engine_import_auto_assign_screen_pct=True,
        engine_import_deduplicate_materials=True,
        engine_import_reuse_master_rig=True,
        pbr_import_preset="custom_imp",
        pbr_import_ao_mode="MULTIPLY",
        pbr_active_maps=[],
        pbr_active_map_index=0,
        config_preset="custom_cfg",
        include_spatial=True,
        include_lights=True,
        include_cameras=True,
        include_exits=True,
        include_engines=True,
        include_interactions=True,
        lod_preset="custom_lod",
        tau_sse=1.0,
        lod_preset_active_tiers=[tier_item],
        lod_preset_active_tier_index=0,
        cull_screen_size_pct=1.0,
        consolidate_hierarchy=False,
        enable_occlusion_culling=True,
        occlusion_lod_start=1,
        enable_slender_culling=True,
        enable_spatial_chunking=True,
        chunk_partitioning_mode="ADAPTIVE_CLUSTERING",
        adaptive_cluster_target_polys=5000,
        chunk_cell_size=10.0,
        chunk_split_z=True,
        chunk_cell_size_z=5.0,
        enable_hierarchical_hlod=False,
        hlod_start_tier=2,
        hlod_proxy_voxel_size=0.2,
        preserve_hierarchy=True,
        preserve_armature=True,
        keep_lods_in_root=False,
        strict_draw_calls=False,
        enable_slender_protection=False,
        pin_lod0_materials=True,
        auto_split_chunking=False,
        enable_hlod=True,
        hlod_proxy_remesh=True,
        enable_impostor_lod=True,
        auto_impostor_resolution=True,
        impostor_render_underside=False,
        impostor_grid_size=8,
        impostor_resolution="2048",
        impostor_atlas_resolution=2048,
        impostor_replace_last_lod=False,
        impostor_mode="OCTAHEDRAL",
        lods=[tier_item],
        pbr_export_preset="custom_exp",
        pbr_export_texture_strategy="SMART_AUTO",
        texture_max_resolution="2048",
        pbr_export_bit_depth="8",
        pbr_export_naming_pattern="{material}_{map}",
        export_packed_textures=True,
        bake_animations=False,
        target_engine="MSFS_2024",
        msfs_export_full_package=True,
        msfs_preserve_decals=True,
        msfs_with_exterior_show_interior=True,
        msfs_with_exterior_show_interior_hide_first_lod=False,
        msfs_with_interior_force_first_lod=False,
        msfs_with_interior_show_exterior=False,
        pbr_export_active_maps=[map_item],
        pbr_export_active_map_index=0,
        cleanup_auto_apply_transforms=True,
        cleanup_apply_modifiers=True,
        cleanup_enable_split_non_manifold=True,
        cleanup_normal_policy="KEEP",
        cleanup_enable_weld=True,
        cleanup_weld_distance=0.001,
        cleanup_enable_fill_holes=True,
        cleanup_hole_max_edges=4,
        cleanup_enable_triangulate_ngons=True,
        cleanup_cull_interior_faces=True,
        occlusion_ray_density=8,
        occlusion_evaluate_alpha=False,
        occlusion_remove_unused_materials=True,
        cleanup_merge_materials=False,
        collision_method="COACD",
        collision_decomposition_mode="PER_OBJECT",
        collision_concavity_threshold=0.05,
        collision_max_verts_per_hull=32,
        collision_hull_count=4,
        collision_resolution=100000,
        collision_auto_naming=True,
        mat_cleanup_purge_unused_slots=True,
        mat_cleanup_deduplicate_slots=True,
        mat_cleanup_merge_duplicate_datablocks=True,
        mat_cleanup_remove_orphan_nodes=True,
        mat_cleanup_enable_micro_consolidation=True,
        mat_cleanup_micro_area_pct=0.5,
        mat_cleanup_repair_missing_textures=False,
        mat_cleanup_purge_orphans_blendfile=False,
        hierarchy_mode="MERGE_AT_TIER",
        merge_start_tier=2,
        preserve_slot_indexing=True,
        max_bone_influences=4,
        enable_bone_pruning=True,
        purge_shape_keys=True,
        pin_uv_seams=True,
        pin_material_borders=True,
        config_presets=None,
    )
    props.config_presets = props
    ctx = SimpleNamespace(scene=SimpleNamespace(name="Scene", lod_tool=props))

    with (
        patch.object(pop_mod, "bpy", fake_bpy),
        patch.object(pop_mod, "_get_popover_props", return_value=props),
        patch.object(workflow_pop_mod, "bpy", fake_bpy),
        patch.object(workflow_pop_mod, "_get_popover_props", return_value=props),
    ):
        for panel_cls in (*pop_mod.PRESET_POPOVER_CLASSES, *workflow_pop_mod.WORKFLOW_POPOVER_CLASSES):
            p: Any = panel_cls()
            p.layout = _SpyLayout()
            p.draw(ctx)
        # Also test non-empty import map list and empty export map list
        props.pbr_active_maps = [map_item]
        props.pbr_export_active_maps = []
        for panel_cls in (OMNIMESH_PT_popover_import_preset, OMNIMESH_PT_popover_export_preset):
            p = panel_cls()
            p.layout = _SpyLayout()
            p.draw(ctx)

    assert op_calls == []
    fake_bpy.app.timers.register.assert_not_called()


def test_reentrancy_guard_nested_and_thread_isolation() -> None:
    """Verify _ReentrancyGuard tracks nested depth deterministically and isolates threads."""
    assert not PresetSyncGuard.is_locked()
    with PresetSyncGuard():
        assert PresetSyncGuard.is_locked()
        with PresetSyncGuard():
            assert PresetSyncGuard.is_locked()
        assert PresetSyncGuard.is_locked()
    assert not PresetSyncGuard.is_locked()

    # Exception unwinds lock cleanly
    with pytest.raises(RuntimeError, match="boom"):
        with MapSyncGuard():
            assert MapSyncGuard.is_active()
            raise RuntimeError("boom")
    assert not MapSyncGuard.is_active()

    # Concurrent threads hold independent locks without starving or corrupting state
    results: list[bool] = []

    def _worker() -> None:
        with StateRestorationGuard():
            results.append(StateRestorationGuard.is_locked())

    t = threading.Thread(target=_worker)
    t.start()
    t.join(timeout=2.0)
    assert results == [True]
    assert not StateRestorationGuard.is_locked()


def test_import_msfs_attachments_file_negative_paths(tmp_path: Path) -> None:
    """Verify import_msfs_attachments_file fails closed on missing bpy or missing/invalid cfg file."""
    with patch("ui.vehicle_attachment_ops.bpy", None):
        assert import_msfs_attachments_file(MagicMock(), str(tmp_path / "attached_objects.cfg")) == 0

    with patch("ui.vehicle_attachment_ops.bpy", MagicMock()):
        assert import_msfs_attachments_file(MagicMock(), str(tmp_path / "does_not_exist.cfg")) == 0
