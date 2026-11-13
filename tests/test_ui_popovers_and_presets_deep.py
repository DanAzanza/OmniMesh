"""
Deep unit and negative boundary tests for ui/popovers.py, ui/config_preset_ops.py,
ui/lod_preset_ops.py, and ui/export_ops.py.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from core.config_presets import ConfigPresetManager
from core.lod_presets import LODPresetManager
from core.pbr_presets import PBRExportPresetManager
from core.preset_spawner import ConfigPresetSpawner
from exporters.engine_export import AssetMeshResolver
from exporters.manager import ExporterManager
from ui import config_preset_ops, export_ops, lod_preset_ops, popovers
from ui.export_ops import (
    LOD_OT_bake_rig_animation,
    LOD_OT_export_engine_package,
    LOD_OT_pack_pbr_textures,
    register_export_ops,
    unregister_export_ops,
)


def _make_layout() -> MagicMock:
    layout = MagicMock()
    layout.row.return_value = layout
    layout.column.return_value = layout
    layout.box.return_value = layout
    return layout


class _TierList(list):
    def add(self) -> Any:
        item = SimpleNamespace(name="", screen_size_pct=100.0, target_tris_pct=100.0, target_tris=1000)
        self.append(item)
        return item

    def remove(self, idx: Any) -> None:
        if isinstance(idx, int):
            super().pop(idx)
        else:
            super().remove(idx)


class TestPopoversDeep:
    def test_workflow_popovers_draw_all_branches(self) -> None:
        props = SimpleNamespace(
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
            mat_cleanup_purge_unused_slots=True,
            mat_cleanup_deduplicate_slots=True,
            mat_cleanup_merge_duplicate_datablocks=True,
            mat_cleanup_remove_orphan_nodes=True,
            mat_cleanup_enable_micro_consolidation=True,
            mat_cleanup_micro_area_pct=0.5,
            mat_cleanup_repair_missing_textures=False,
            mat_cleanup_purge_orphans_blendfile=False,
            collision_decomposition_mode="PER_OBJECT",
            collision_hull_count=4,
            collision_concavity_threshold=0.05,
            collision_max_verts_per_hull=32,
            hierarchy_mode="MERGE_AT_TIER",
            merge_start_tier=2,
            preserve_slot_indexing=True,
            max_bone_influences=4,
            enable_bone_pruning=True,
            purge_shape_keys=True,
            impostor_mode="OCTAHEDRAL",
            impostor_resolution=512,
            impostor_replace_last_lod=True,
        )
        ctx: Any = SimpleNamespace(scene=SimpleNamespace(lod_tool=props), active_object=None)

        with patch.object(popovers, "bpy", MagicMock()):
            for cls in popovers.WORKFLOW_POPOVER_CLASSES:
                panel: Any = cls.__new__(cls)
                panel.layout = None
                panel.draw(ctx)  # early exit when layout is None

                layout = _make_layout()
                panel.layout = layout
                panel.draw(None)  # early exit when context is None
                panel.draw(SimpleNamespace(scene=None, active_object=None))  # early exit when props is None
                panel.draw(ctx)
                assert layout.prop.call_count > 0 or layout.box.called


class TestConfigPresetOpsDeep:
    def test_add_create_rename_duplicate_delete_config_presets(self) -> None:
        cfg_props = SimpleNamespace(config_preset="custom_car")
        props = SimpleNamespace(active_asset="Rover", config_presets=cfg_props)
        wm = MagicMock()
        wm.invoke_props_dialog.side_effect = lambda op, **_kw: op.execute(ctx)
        wm.invoke_confirm.side_effect = lambda op, _ev: op.execute(ctx)
        ctx: Any = SimpleNamespace(
            scene=SimpleNamespace(lod_tool=props, collection=None),
            window_manager=wm,
            blend_data=SimpleNamespace(objects=[]),
            active_object=None,
            selected_objects=[],
            view_layer=None,
        )

        with patch.object(config_preset_ops, "bpy", MagicMock()):
            # Add config preset (missing preset -> CANCELLED, no bdata -> CANCELLED, valid -> FINISHED)
            add_op: Any = config_preset_ops.OMNIMESH_OT_add_config_preset.__new__(
                config_preset_ops.OMNIMESH_OT_add_config_preset
            )
            add_op.report = MagicMock()
            assert config_preset_ops.OMNIMESH_OT_add_config_preset.poll(ctx) is True

            with patch.object(ConfigPresetManager, "get_preset", return_value=None):
                assert add_op.execute(ctx) == {"CANCELLED"}

            with patch.object(ConfigPresetManager, "get_preset", return_value={"name": "Custom"}):
                with patch.object(ConfigPresetSpawner, "spawn_preset_objects", return_value=3):
                    assert add_op.execute(ctx) == {"FINISHED"}

            # Create config preset + draw + error path
            create_op: Any = config_preset_ops.OMNIMESH_OT_create_config_preset.__new__(
                config_preset_ops.OMNIMESH_OT_create_config_preset
            )
            create_op.preset_name = "MyJet"
            create_op.template_type = "minimal"
            create_op.report = MagicMock()
            create_op.layout = _make_layout()
            create_op.draw(ctx)
            with patch.object(ConfigPresetManager, "create_new_preset", return_value="my_jet"):
                assert create_op.invoke(ctx, None) == {"FINISHED"}
                assert cfg_props.config_preset == "my_jet"
            with patch.object(ConfigPresetManager, "create_new_preset", side_effect=OSError("disk")):
                assert create_op.execute(ctx) == {"CANCELLED"}

            # Rename (builtin block, empty name block, valid rename, exception)
            ren_op: Any = config_preset_ops.OMNIMESH_OT_rename_config_preset.__new__(
                config_preset_ops.OMNIMESH_OT_rename_config_preset
            )
            ren_op.report = MagicMock()
            ren_op.layout = _make_layout()
            ren_op.draw(ctx)
            with patch.object(ConfigPresetManager, "is_builtin", return_value=True):
                assert ren_op.invoke(ctx, None) == {"CANCELLED"}
                assert ren_op.execute(ctx) == {"CANCELLED"}
            with patch.object(ConfigPresetManager, "is_builtin", return_value=False):
                ren_op.new_name = "   "
                assert ren_op.execute(ctx) == {"CANCELLED"}
                with (
                    patch.object(ConfigPresetManager, "get_preset", return_value={"name": "Old"}),
                    patch.object(ConfigPresetManager, "rename_custom_preset", return_value="renamed_id"),
                ):
                    assert ren_op.invoke(ctx, None) == {"FINISHED"}
                    assert cfg_props.config_preset == "renamed_id"
                ren_op.new_name = "Fail"
                with patch.object(ConfigPresetManager, "rename_custom_preset", side_effect=ValueError("dup")):
                    assert ren_op.execute(ctx) == {"CANCELLED"}

            # Duplicate (valid + failure) & Delete (poll, confirm, failure)
            dup_op: Any = config_preset_ops.OMNIMESH_OT_duplicate_config_preset.__new__(
                config_preset_ops.OMNIMESH_OT_duplicate_config_preset
            )
            dup_op.report = MagicMock()
            dup_op.layout = _make_layout()
            dup_op.draw(ctx)
            with (
                patch.object(ConfigPresetManager, "get_preset", return_value={"name": "Orig"}),
                patch.object(ConfigPresetManager, "duplicate_preset", return_value="orig_copy"),
            ):
                assert dup_op.invoke(ctx, None) == {"FINISHED"}
            with patch.object(ConfigPresetManager, "duplicate_preset", return_value=None):
                assert dup_op.execute(ctx) == {"CANCELLED"}

            del_op: Any = config_preset_ops.OMNIMESH_OT_delete_config_preset.__new__(
                config_preset_ops.OMNIMESH_OT_delete_config_preset
            )
            del_op.report = MagicMock()
            with patch.object(ConfigPresetManager, "is_builtin", return_value=False):
                assert config_preset_ops.OMNIMESH_OT_delete_config_preset.poll(ctx) is True
                with patch.object(ConfigPresetManager, "delete_preset", return_value=True):
                    assert del_op.invoke(ctx, None) == {"FINISHED"}
                with patch.object(ConfigPresetManager, "delete_preset", return_value=False):
                    assert del_op.execute(ctx) == {"CANCELLED"}


class TestLodPresetOpsDeep:
    def test_lod_preset_create_rename_delete_and_tier_ops(self) -> None:
        tiers = _TierList(
            [SimpleNamespace(name="LOD0", screen_size_pct=100.0, target_tris_pct=100.0, target_tris=10000)]
        )
        lods = _TierList([SimpleNamespace(name="LOD0", screen_size_pct=100.0, target_tris_pct=100.0, target_tris=5000)])
        props = SimpleNamespace(
            lod_preset="custom_lod",
            lod_preset_active_tiers=tiers,
            lod_preset_active_tier_index=0,
            lod_preset_is_dirty=False,
            lods=lods,
        )
        wm = MagicMock()
        wm.invoke_props_dialog.side_effect = lambda op, **_kw: op.execute(ctx)
        wm.invoke_confirm.side_effect = lambda op, _ev: op.execute(ctx)
        ctx: Any = SimpleNamespace(scene=SimpleNamespace(lod_tool=props), window_manager=wm)

        fake_bpy = MagicMock()
        fake_bpy.ops.lod_tool.analyze_and_configure.return_value = {"FINISHED"}

        with (
            patch.object(lod_preset_ops, "bpy", fake_bpy),
            patch.object(lod_preset_ops, "resolve_lod_context", return_value=(props, None, None)),
            patch.object(lod_preset_ops, "sync_preset_tiers_from_preset"),
            patch.object(lod_preset_ops, "sync_preset_tiers_to_preset", return_value="custom_lod"),
        ):
            # Create & Rename
            create_op: Any = lod_preset_ops.LOD_OT_create_lod_preset.__new__(lod_preset_ops.LOD_OT_create_lod_preset)
            create_op.preset_name = "Arena"
            create_op.template_type = "minimal"
            create_op.report = MagicMock()
            create_op.layout = _make_layout()
            create_op.draw(ctx)
            with (
                patch.object(LODPresetManager, "create_new_preset", return_value="arena_lod"),
                patch.object(LODPresetManager, "get_preset", return_value={"name": "Arena", "tiers": []}),
                patch.object(LODPresetManager, "set_last_active_preset"),
            ):
                assert create_op.invoke(ctx, None) == {"FINISHED"}

            ren_op: Any = lod_preset_ops.LOD_OT_rename_lod_preset.__new__(lod_preset_ops.LOD_OT_rename_lod_preset)
            ren_op.report = MagicMock()
            ren_op.layout = _make_layout()
            ren_op.draw(ctx)
            with patch.object(LODPresetManager, "is_builtin", return_value=False):
                ren_op.new_name = ""
                assert ren_op.execute(ctx) == {"CANCELLED"}
                with (
                    patch.object(LODPresetManager, "get_preset", return_value={"name": "Arena"}),
                    patch.object(LODPresetManager, "rename_custom_preset", return_value="arena_v2"),
                    patch.object(LODPresetManager, "set_last_active_preset"),
                ):
                    assert ren_op.invoke(ctx, None) == {"FINISHED"}

            # Delete custom preset & not-found warning
            del_op: Any = lod_preset_ops.LOD_OT_delete_lod_preset.__new__(lod_preset_ops.LOD_OT_delete_lod_preset)
            del_op.report = MagicMock()
            with patch.object(LODPresetManager, "is_user_preset", return_value=False):
                assert del_op.invoke(ctx, None) == {"CANCELLED"}
            with (
                patch.object(LODPresetManager, "is_user_preset", return_value=True),
                patch.object(LODPresetManager, "delete_custom_preset", return_value=True),
                patch.object(LODPresetManager, "get_preset", return_value={"tiers": []}),
            ):
                assert del_op.invoke(ctx, None) == {"FINISHED"}

            # Add / Remove / Save / Apply / Capture tiers
            add_t: Any = lod_preset_ops.LOD_OT_add_preset_tier.__new__(lod_preset_ops.LOD_OT_add_preset_tier)
            add_t.report = MagicMock()
            with patch.object(LODPresetManager, "is_builtin", return_value=False):
                assert add_t.execute(ctx) == {"FINISHED"}
                assert len(tiers) == 2

            rem_t: Any = lod_preset_ops.LOD_OT_remove_preset_tier.__new__(lod_preset_ops.LOD_OT_remove_preset_tier)
            rem_t.report = MagicMock()
            with patch.object(LODPresetManager, "is_builtin", return_value=False):
                assert rem_t.execute(ctx) == {"FINISHED"}
                assert rem_t.execute(ctx) == {"CANCELLED"}  # floor of 1 tier

            save_t: Any = lod_preset_ops.LOD_OT_save_preset_tiers.__new__(lod_preset_ops.LOD_OT_save_preset_tiers)
            save_t.report = MagicMock()
            assert save_t.execute(ctx) == {"FINISHED"}

            apply_t: Any = lod_preset_ops.LOD_OT_apply_preset_tiers.__new__(lod_preset_ops.LOD_OT_apply_preset_tiers)
            assert apply_t.execute(ctx) == {"FINISHED"}

            cap_t: Any = lod_preset_ops.LOD_OT_capture_scene_tiers.__new__(lod_preset_ops.LOD_OT_capture_scene_tiers)
            cap_t.report = MagicMock()
            with patch.object(LODPresetManager, "is_builtin", return_value=False):
                assert cap_t.execute(ctx) == {"FINISHED"}
            props.lods.clear()
            assert cap_t.execute(ctx) == {"CANCELLED"}


class TestExportOpsDeep:
    def test_pack_pbr_bake_rig_and_export_package(self, tmp_path: pytest.TempPathFactory) -> None:
        fake_bpy = MagicMock()
        fake_bpy.path.abspath.return_value = str(tmp_path)

        mat = MagicMock()
        mat.name = "HullMat"
        obj = SimpleNamespace(
            type="MESH",
            name="Plane_Body",
            material_slots=[SimpleNamespace(material=mat)],
            parent=None,
            animation_data=None,
            modifiers=[],
        )
        props = SimpleNamespace(
            export_directory=str(tmp_path),
            texture_max_resolution="512",
            target_engine="MSFS_2024",
            pbr_export_preset="missing_preset_trigger_fallback",
            pbr_export_texture_strategy="CONVERT_PNG",
            pbr_export_bit_depth="8",
            pbr_export_naming_pattern="{asset}_{material}{suffix}{udim}",
            export_base_name="",
            export_packed_textures=True,
            bake_animations=True,
            msfs_export_full_package=True,
            lods=[SimpleNamespace(generated_obj=obj)],
        )
        ctx: Any = SimpleNamespace(
            scene=SimpleNamespace(lod_tool=props),
            selected_objects=[obj],
            active_object=obj,
            blend_data=SimpleNamespace(objects=[], collections={}),
        )

        with (
            patch.object(export_ops, "bpy", fake_bpy),
            patch.object(export_ops, "resolve_lod_context", return_value=(props, None, None)),
            patch.object(export_ops, "get_lod0_mesh_objects", return_value=[obj]),
            patch.object(export_ops, "resolve_effective_asset_name", return_value="Plane_Interior"),
            patch.object(export_ops, "resolve_export_asset_name", return_value="Plane_Interior"),
        ):
            # Pack PBR textures (missing preset fallback + future barrier + no materials negative branch)
            pack_op: Any = LOD_OT_pack_pbr_textures.__new__(LOD_OT_pack_pbr_textures)
            pack_op.report = MagicMock()
            assert LOD_OT_pack_pbr_textures.poll(ctx) is True

            with (
                patch.object(
                    PBRExportPresetManager,
                    "get_preset",
                    side_effect=[KeyError("nope"), {"name": "UE5"}],
                ),
                patch.object(export_ops.TextureChannelPacker, "pack_material_preset", return_value=[MagicMock()]),
                patch.object(export_ops.TexturePoolManager, "wait_all"),
            ):
                assert pack_op.execute(ctx) == {"FINISHED"}

            # Bake rig animation negative (no armature action -> CANCELLED) & positive
            bake_op: Any = LOD_OT_bake_rig_animation.__new__(LOD_OT_bake_rig_animation)
            bake_op.report = MagicMock()
            arm = SimpleNamespace(
                type="ARMATURE",
                animation_data=SimpleNamespace(action=SimpleNamespace(name="Act")),
                parent=None,
            )
            ctx_arm: Any = SimpleNamespace(active_object=arm, blend_data=ctx.blend_data)
            assert LOD_OT_bake_rig_animation.poll(ctx_arm) is True
            with (
                patch.object(
                    export_ops.AnimationRigSanitizer,
                    "bake_deform_animation",
                    return_value=SimpleNamespace(name="BakedAct"),
                ),
                patch.object(export_ops.AnimationRigSanitizer, "setup_clean_nla_export"),
            ):
                assert bake_op.execute(ctx_arm) == {"FINISHED"}
            assert bake_op.execute(ctx) == {"CANCELLED"}  # mesh has no animation_data

            # Export package (PreFlight failure, then MSFS export success + failure)
            exp_op: Any = LOD_OT_export_engine_package.__new__(LOD_OT_export_engine_package)
            exp_op.report = MagicMock()
            assert LOD_OT_export_engine_package.poll(ctx) is True

            with patch.object(export_ops.PreFlightValidator, "run_checks", return_value=["Missing UV"]):
                assert exp_op.execute(ctx) == {"CANCELLED"}

            with (
                patch.object(export_ops.PreFlightValidator, "run_checks", return_value=[]),
                patch.object(
                    AssetMeshResolver, "resolve_payload", return_value=SimpleNamespace(parent_asset_name="Plane")
                ),
                patch.object(ExporterManager, "export_asset", return_value=(True, "Exported glTF")),
            ):
                ctx.active_object = arm
                fake_bpy.ops.lod_tool.pack_pbr_textures.side_effect = OSError("pack skip")
                fake_bpy.ops.lod_tool.bake_rig_animation.side_effect = RuntimeError("bake skip")
                assert exp_op.execute(ctx) == {"FINISHED"}

            with (
                patch.object(export_ops.PreFlightValidator, "run_checks", return_value=[]),
                patch.object(ExporterManager, "export_asset", return_value=(False, "Disk full")),
            ):
                props.export_packed_textures = False
                props.bake_animations = False
                assert exp_op.execute(ctx) == {"CANCELLED"}

            # Register / Unregister
            register_export_ops()
            unregister_export_ops()
