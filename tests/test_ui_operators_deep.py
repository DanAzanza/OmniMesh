"""Deep unit and boundary tests for UI preset popovers, PBR preset operators, engine import operators, and MSFS spatial/camera/attachment/lighting operators."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import ui.engine_import_ops as eng_ops_mod
import ui.msfs_attachment_ops as att_ops_mod
import ui.msfs_camera_ops as cam_ops_mod
import ui.msfs_lighting_ops as lit_ops_mod
import ui.msfs_spatial_ops as spat_ops_mod
import ui.pbr_preset_ops as pbr_ops_mod
import ui.popover_presets as pop_mod
from ui.engine_import_ops import (
    OMNIMESH_OT_create_engine_import_preset,
    OMNIMESH_OT_delete_engine_import_preset,
    OMNIMESH_OT_duplicate_engine_import_preset,
    OMNIMESH_OT_import_engine_project,
    OMNIMESH_OT_rename_engine_import_preset,
)
from ui.msfs_attachment_ops import (
    OMNIMESH_OT_add_msfs_attachment,
    find_attachments_collection,
    find_mounting_socket_node,
    get_or_create_attachments_collection,
)
from ui.msfs_camera_ops import (
    OMNIMESH_OT_align_msfs_camera_to_view,
    OMNIMESH_OT_look_through_msfs_camera,
    OMNIMESH_OT_restore_scene_camera,
    find_cameras_collection,
    get_or_create_cameras_collection,
)
from ui.msfs_lighting_ops import (
    find_lights_collection,
    get_or_create_lights_collection,
)
from ui.msfs_spatial_ops import (
    OMNIMESH_OT_mirror_msfs_marker,
    find_spatial_collection,
    get_or_create_spatial_collection,
)
from ui.pbr_preset_ops import (
    LOD_OT_create_export_preset,
    LOD_OT_create_import_preset,
    LOD_OT_delete_export_preset,
    LOD_OT_delete_import_preset,
    LOD_OT_duplicate_preset,
    LOD_OT_open_presets_directory,
    LOD_OT_reload_pbr_presets,
    LOD_OT_rename_export_preset,
    LOD_OT_rename_import_preset,
    LOD_OT_reset_pbr_preset,
    LOD_OT_save_export_preset,
    LOD_OT_save_import_preset,
)
from ui.popover_presets import (
    OMNIMESH_PT_popover_config_preset,
    OMNIMESH_PT_popover_engine_import_preset,
    OMNIMESH_PT_popover_export_preset,
    OMNIMESH_PT_popover_import_preset,
    OMNIMESH_PT_popover_lod_preset,
)


def _make_layout() -> Any:
    layout = MagicMock()
    layout.row.side_effect = lambda **kw: _make_layout()
    layout.column.side_effect = lambda **kw: _make_layout()
    layout.box.side_effect = lambda **kw: _make_layout()
    return layout


# =========================================================================
# 1. Preset Popover Panels Draw Tests
# =========================================================================


def test_all_five_preset_popovers_draw() -> None:
    """Verify all 5 preset popover panels draw cleanly for both built-in and custom presets."""
    fake_bpy = MagicMock()
    ctx = MagicMock()

    map_item = MagicMock()
    map_item.is_normal_map = True
    map_item.is_packed = True
    tier_item = MagicMock()
    tier_item.screen_size_pct = 10.0

    props = MagicMock()
    props.engine_import_preset = "msfs_2024_aircraft"
    props.pbr_import_preset = "standard_pbr_split"
    props.pbr_active_maps = [map_item]
    props.pbr_active_map_index = 0
    props.config_presets.config_preset = "cessna_172"
    props.lod_preset = "ue5_hero"
    props.lod_preset_active_tiers = [tier_item]
    props.lod_preset_active_tier_index = 0
    props.enable_occlusion_culling = True
    props.enable_spatial_chunking = True
    props.chunk_partitioning_mode = "ADAPTIVE_CLUSTERING"
    props.chunk_split_z = True
    props.enable_hlod = True
    props.hlod_proxy_remesh = True
    props.enable_impostor_lod = True
    props.auto_impostor_resolution = True
    props.lods = [tier_item]
    props.pbr_export_preset = "unreal_engine_5"
    props.pbr_export_texture_strategy = "SMART_AUTO"
    props.target_engine = "MSFS_2024"
    props.pbr_export_active_maps = [map_item]
    props.pbr_export_active_map_index = 0

    with (
        patch.object(pop_mod, "bpy", fake_bpy),
        patch.object(pop_mod, "_get_popover_props", return_value=props),
    ):
        for panel_cls in (
            OMNIMESH_PT_popover_engine_import_preset,
            OMNIMESH_PT_popover_import_preset,
            OMNIMESH_PT_popover_config_preset,
            OMNIMESH_PT_popover_lod_preset,
            OMNIMESH_PT_popover_export_preset,
        ):
            p: Any = panel_cls()
            p.layout = _make_layout()
            p.draw(ctx)
            assert p.layout.prop.called or p.layout.box.called

        # Test unpacked map branch & empty active_maps branches
        map_item.is_packed = False
        props.auto_impostor_resolution = False
        for panel_cls in (
            OMNIMESH_PT_popover_import_preset,
            OMNIMESH_PT_popover_lod_preset,
            OMNIMESH_PT_popover_export_preset,
        ):
            p = panel_cls()
            p.layout = _make_layout()
            p.draw(ctx)

        props.pbr_active_maps = []
        props.pbr_export_active_maps = []
        for panel_cls in (OMNIMESH_PT_popover_import_preset, OMNIMESH_PT_popover_export_preset):
            p = panel_cls()
            p.layout = _make_layout()
            p.draw(ctx)


# =========================================================================
# 2. PBR Preset CRUD Operators Tests
# =========================================================================


def test_pbr_preset_crud_operators(tmp_path: Path) -> None:
    """Verify reload, reset, create, rename, duplicate, save, delete, and open folder PBR preset operators."""
    fake_bpy = MagicMock()
    ctx = MagicMock()
    props = MagicMock()
    props.pbr_import_preset = "custom_imp"
    props.pbr_export_preset = "custom_exp"
    props.pbr_preset = "custom_exp"
    props.lod_preset = "custom_lod"
    props.target_engine = "UE5"
    props.pbr_export_texture_strategy = "CONVERT_PNG"
    props.pbr_export_bit_depth = "8"
    props.pbr_export_naming_pattern = "{asset}_{material}{suffix}"
    ctx.scene.lod_tool = props

    with (
        patch.object(pbr_ops_mod, "bpy", fake_bpy),
        patch.object(pbr_ops_mod, "resolve_lod_context", return_value=(props, [], None)),
        patch.object(pbr_ops_mod, "sync_maps_from_preset"),
        patch.object(pbr_ops_mod, "sync_export_maps_from_preset"),
        patch.object(pbr_ops_mod, "sync_maps_to_preset"),
        patch.object(pbr_ops_mod, "sync_preset_tiers_from_preset"),
    ):
        # 1. Reload & Reset
        assert LOD_OT_reload_pbr_presets().execute(ctx) == {"FINISHED"}
        assert LOD_OT_reset_pbr_preset().execute(ctx) == {"FINISHED"}

        # 2. Create Import Preset
        op_ci: Any = LOD_OT_create_import_preset()
        op_ci.preset_name = "Test Imp"
        op_ci.template_type = "standard_pbr_split"
        op_ci.layout = _make_layout()
        op_ci.draw(ctx)
        with patch.object(pbr_ops_mod.PBRImportPresetManager, "create_new_preset", return_value="test_imp"):
            assert op_ci.execute(ctx) == {"FINISHED"}

        # 3. Rename Import Preset (negative built-in check + positive custom rename)
        op_ri = LOD_OT_rename_import_preset()
        op_ri.new_name = "Renamed Imp"
        with patch.object(pbr_ops_mod.PBRImportPresetManager, "is_builtin", return_value=True):
            assert op_ri.invoke(ctx, MagicMock()) == {"CANCELLED"}
            assert op_ri.execute(ctx) == {"CANCELLED"}
        with (
            patch.object(pbr_ops_mod.PBRImportPresetManager, "is_builtin", return_value=False),
            patch.object(pbr_ops_mod.PBRImportPresetManager, "rename_custom_preset", return_value="renamed_imp"),
        ):
            op_ri.invoke(ctx, MagicMock())
            assert op_ri.execute(ctx) == {"FINISHED"}

        # 4. Create & Rename Export Preset
        op_ce: Any = LOD_OT_create_export_preset()
        op_ce.preset_name = "Test Exp"
        op_ce.template_type = "unreal_engine_5"
        op_ce.layout = _make_layout()
        op_ce.draw(ctx)
        with patch.object(pbr_ops_mod.PBRExportPresetManager, "create_new_preset", return_value="test_exp"):
            assert op_ce.execute(ctx) == {"FINISHED"}

        op_re = LOD_OT_rename_export_preset()
        op_re.new_name = "Renamed Exp"
        with (
            patch.object(pbr_ops_mod.PBRExportPresetManager, "is_builtin", return_value=False),
            patch.object(pbr_ops_mod.PBRExportPresetManager, "rename_custom_preset", return_value="renamed_exp"),
        ):
            assert op_re.execute(ctx) == {"FINISHED"}

        # 5. Duplicate Preset (IMPORT, LOD, EXPORT)
        for ptype in ("IMPORT", "LOD", "EXPORT"):
            op_dup = LOD_OT_duplicate_preset()
            op_dup.preset_type = ptype
            op_dup.new_name = f"Dup {ptype}"
            with (
                patch.object(pbr_ops_mod.PBRImportPresetManager, "duplicate_preset", return_value="dup_id"),
                patch.object(pbr_ops_mod.LODPresetManager, "duplicate_preset", return_value="dup_id"),
                patch.object(pbr_ops_mod.PBRExportPresetManager, "duplicate_preset", return_value="dup_id"),
            ):
                op_dup.invoke(ctx, MagicMock())
                assert op_dup.execute(ctx) == {"FINISHED"}

        # 6. Save & Delete Import/Export Presets
        with (
            patch.object(pbr_ops_mod.PBRImportPresetManager, "is_builtin", return_value=False),
            patch.object(pbr_ops_mod.PBRImportPresetManager, "delete_custom_preset", return_value=True),
            patch.object(pbr_ops_mod.PBRExportPresetManager, "is_builtin", return_value=False),
            patch.object(pbr_ops_mod.PBRExportPresetManager, "save_custom_preset"),
            patch.object(pbr_ops_mod.PBRExportPresetManager, "delete_custom_preset", return_value=True),
        ):
            assert LOD_OT_save_import_preset().execute(ctx) == {"FINISHED"}
            assert LOD_OT_save_export_preset().execute(ctx) == {"FINISHED"}
            assert LOD_OT_delete_import_preset().execute(ctx) == {"FINISHED"}
            assert LOD_OT_delete_export_preset().execute(ctx) == {"FINISHED"}

        # 7. Open Presets Directory
        op_open = LOD_OT_open_presets_directory()
        op_open.category = "IMPORTER"
        with (
            patch.object(pbr_ops_mod.PBRImportPresetManager, "get_user_dir", return_value=tmp_path),
            patch("os.startfile", create=True),
        ):
            assert op_open.execute(ctx) == {"FINISHED"}


# =========================================================================
# 3. Engine Import Operators Tests
# =========================================================================


def test_engine_import_project_and_preset_operators(tmp_path: Path) -> None:
    """Verify OMNIMESH_OT_import_engine_project and engine import preset CRUD operators."""
    fake_bpy = MagicMock()
    fake_bpy.path.abspath.side_effect = lambda p: p
    ctx = MagicMock()
    props = MagicMock()
    props.engine_import_directory = str(tmp_path)
    props.engine_import_preset = "custom_eng"
    props.engine_import_model_target = "EXTERIOR_ONLY"
    ctx.scene.lod_tool = props

    manifest = MagicMock()
    manifest.asset_name = "C172"
    manifest.has_geometry = True
    lod0 = MagicMock(index=0, exists=True, gltf_path=str(tmp_path / "c172_lod0.gltf"))
    manifest.exterior_model.lods = [lod0]
    manifest.interior_model = None
    manifest.variants = {}

    mesh_obj = MagicMock(type="MESH")
    arm_obj = MagicMock(type="ARMATURE")

    with (
        patch.object(eng_ops_mod, "bpy", fake_bpy),
        patch.object(eng_ops_mod.MSFSProjectScanner, "scan", return_value=manifest),
        patch.object(eng_ops_mod, "get_or_create_engine_import_collection", return_value=MagicMock()),
        patch.object(eng_ops_mod, "safe_remove_collection_objects"),
        patch.object(
            eng_ops_mod.GLTFAssemblyEngine,
            "import_gltf_into_collection",
            return_value=[mesh_obj, arm_obj],
        ),
        patch.object(eng_ops_mod, "classify_imported_mesh_node", return_value="RENDER_MESH"),
        patch.object(eng_ops_mod.GLTFAssemblyEngine, "retarget_armatures_to_master", return_value=1),
        patch.object(eng_ops_mod.GLTFAssemblyEngine, "deduplicate_materials", return_value=2),
        patch.object(eng_ops_mod, "bind_manifest_to_omnimesh"),
        patch.object(eng_ops_mod.PBRTextureResolver, "extract_unique_materials_from_objects", return_value=[]),
        patch.object(eng_ops_mod, "import_spatial_points", return_value=(4, MagicMock())),
        patch.object(eng_ops_mod, "import_lighting_points", return_value=3),
        patch.object(eng_ops_mod, "import_cameras", return_value=2),
        patch.object(eng_ops_mod, "import_attachments", return_value=1),
    ):
        op_imp = OMNIMESH_OT_import_engine_project()
        op_imp.report = MagicMock()
        # Negative guard: invalid directory
        op_imp.directory = str(tmp_path / "nonexistent")
        assert op_imp.execute(ctx) == {"CANCELLED"}

        # Positive invoke & execute
        assert op_imp.invoke(ctx, MagicMock()) == {"RUNNING_MODAL"}
        ctx.window_manager.fileselect_add.assert_called_with(op_imp)
        op_imp.directory = str(tmp_path)
        assert op_imp.execute(ctx) == {"FINISHED"}

        # Preset CRUD operators
        op_c = OMNIMESH_OT_create_engine_import_preset()
        op_c.preset_name = "Custom Aircraft"
        op_c.report = MagicMock()
        with patch.object(eng_ops_mod.EngineImportPresetManager, "create_new_preset", return_value="custom_ac"):
            assert op_c.execute(ctx) == {"FINISHED"}

        op_r = OMNIMESH_OT_rename_engine_import_preset()
        op_r.new_name = "Renamed Aircraft"
        op_r.report = MagicMock()
        with (
            patch.object(eng_ops_mod.EngineImportPresetManager, "is_builtin", return_value=False),
            patch.object(eng_ops_mod.EngineImportPresetManager, "rename_custom_preset", return_value="ren_ac"),
        ):
            assert op_r.execute(ctx) == {"FINISHED"}

        op_d = OMNIMESH_OT_duplicate_engine_import_preset()
        op_d.new_name = "Dup Aircraft"
        op_d.report = MagicMock()
        with patch.object(eng_ops_mod, "duplicate_engine_import_preset", return_value="dup_ac"):
            assert op_d.execute(ctx) == {"FINISHED"}

        op_del = OMNIMESH_OT_delete_engine_import_preset()
        op_del.report = MagicMock()
        with (
            patch.object(eng_ops_mod.EngineImportPresetManager, "is_builtin", return_value=False),
            patch.object(eng_ops_mod, "delete_engine_import_preset", return_value=True),
        ):
            assert OMNIMESH_OT_delete_engine_import_preset.poll(ctx) is True
            assert op_del.execute(ctx) == {"FINISHED"}


# =========================================================================
# 4. MSFS Spatial, Camera, Attachment & Lighting Operators Tests
# =========================================================================


def test_msfs_spatial_camera_attachment_and_lighting_ops() -> None:
    """Verify MSFS spatial mirror/snap, camera look-through/restore/align, and attachment spawn operators."""
    fake_bpy = MagicMock()
    ctx = MagicMock()

    # 1. Spatial marker mirroring (centerline guard + counterpart spawn)
    with patch.object(spat_ops_mod, "bpy", fake_bpy):
        find_spatial_collection(ctx, "C172")
        get_or_create_spatial_collection(ctx, "C172")

        op_mir = OMNIMESH_OT_mirror_msfs_marker()
        op_mir.report = MagicMock()

        marker: dict[str, Any] = {
            "msfs_id": "CONTACT_POINTS:point.1",
            "msfs_type": "CONTACT_POINT",
            "msfs_name_tag": "Gear_Left",
        }
        empty = MagicMock()
        empty.name = "Wheel_Left"
        empty.get.side_effect = lambda k, d=None: marker.get(k, d)
        empty.location = MagicMock(x=0.01, y=1.0, z=-0.5)
        ctx.active_object = empty

        # Centerline guard (< 0.05m)
        assert op_mir.execute(ctx) == {"CANCELLED"}

        # Valid lateral coordinate -> spawns counterpart
        empty.location = MagicMock(x=-1.5, y=1.0, z=-0.5)
        empty.rotation_mode = "XYZ"
        empty.rotation_euler = MagicMock(x=0.1, y=0.2, z=0.3)
        col_mock = MagicMock()
        col_mock.objects.__iter__.return_value = [empty]
        empty.users_collection = [col_mock]
        new_mir = MagicMock()
        new_mir.name = "Wheel_Right"
        fake_bpy.data.objects.new.return_value = new_mir
        assert op_mir.execute(ctx) == {"FINISHED"}
        assert OMNIMESH_OT_mirror_msfs_marker._compute_mirrored_name("Nav_Port") == "Nav_Stbd"

    # 2. Camera look-through, restore, and align to view
    with patch.object(cam_ops_mod, "bpy", fake_bpy):
        find_cameras_collection(ctx, "C172")
        get_or_create_cameras_collection(ctx, "C172")

        cam_obj = MagicMock()
        cam_obj.name = "CAM_Pilot"
        cam_obj.type = "CAMERA"
        cam_obj.get.side_effect = lambda k, d=None: 0 if k == "msfs_camera_index" else d
        cam_obj.parent = None
        ctx.active_object = cam_obj

        area = MagicMock(type="VIEW_3D")
        space = MagicMock(type="VIEW_3D")
        area.spaces = [space]
        ctx.screen.areas = [area]
        scene_dict: dict[str, Any] = {}
        ctx.scene.__getitem__.side_effect = lambda k: scene_dict[k]
        ctx.scene.__setitem__.side_effect = lambda k, v: scene_dict.__setitem__(k, v)
        ctx.scene.__contains__.side_effect = lambda k: k in scene_dict
        ctx.scene.get.side_effect = lambda k, d=None: scene_dict.get(k, d)

        op_look = OMNIMESH_OT_look_through_msfs_camera()
        op_look.report = MagicMock()
        assert OMNIMESH_OT_look_through_msfs_camera.poll(ctx) is True
        assert op_look.execute(ctx) == {"FINISHED"}
        assert space.region_3d.view_perspective == "CAMERA"

        op_align = OMNIMESH_OT_align_msfs_camera_to_view()
        op_align.report = MagicMock()
        assert op_align.execute(ctx) == {"FINISHED"}

        op_rest = OMNIMESH_OT_restore_scene_camera()
        op_rest.report = MagicMock()
        assert op_rest.execute(ctx) == {"FINISHED"}

    # 3. Attachment hotspot creation & mounting socket lookup
    with (
        patch.object(att_ops_mod, "bpy", fake_bpy),
        patch.object(att_ops_mod, "get_or_create_engine_import_collection", return_value=MagicMock()),
    ):
        find_attachments_collection(ctx, "C172")
        get_or_create_attachments_collection(ctx, "C172", is_interior=True)

        sock_obj = MagicMock(name="ATTACH_Yoke", type="EMPTY")
        sock_obj.name = "ATTACH_Yoke"
        fake_bpy.data.objects.get.return_value = sock_obj
        found_obj, found_bone = find_mounting_socket_node(ctx, "ATTACH_Yoke")
        assert found_obj is sock_obj and found_bone is None

        ctx.active_object = sock_obj
        op_add_att = OMNIMESH_OT_add_msfs_attachment()
        op_add_att.alias = "G1000"
        op_add_att.attachment_path = "model/g1000.xml"
        op_add_att.attach_to_model = "Interior"
        op_add_att.report = MagicMock()
        assert op_add_att.execute(ctx) == {"FINISHED"}

    # 4. Lighting collection helpers
    with patch.object(lit_ops_mod, "bpy", fake_bpy):
        find_lights_collection(ctx, "C172")
        get_or_create_lights_collection(ctx, "C172")


def test_setup_and_simulator_ops_deep() -> None:
    """Exercise ui/setup_ops.py and ui/simulator_ops.py."""
    from ui import setup_ops, simulator_ops

    mock_bpy = MagicMock()
    ctx = MagicMock()
    props = ctx.scene.lod_tool
    props.is_simulator_active = False
    props.is_simulator_running = False
    props.virtual_screen_override_active = False
    props.virtual_distance_override = 15.0
    props.simulator_camera_mode = "ACTIVE_SCENE"

    space_3d = MagicMock()
    space_3d.type = "VIEW_3D"
    space_3d.overlay.show_face_orientation = False
    space_3d.overlay.show_stats = False
    space_3d.shading.show_cavity = False
    space_3d.shading.show_backface_culling = False
    reg = MagicMock()
    reg.type = "WINDOW"

    class FakeSpaces(list[Any]):
        active: Any = None

    area = MagicMock()
    area.type = "VIEW_3D"
    area.spaces = FakeSpaces([space_3d])
    area.spaces.active = space_3d
    area.regions = [reg]
    win = MagicMock()
    win.screen.areas = [area]
    ctx.window_manager.windows = [win]
    ctx.screen.areas = [area]

    colls = {"root": MagicMock(), "lod0": MagicMock()}
    ctx.view_layer.layer_collection.collection = colls["lod0"]
    with (
        patch.object(setup_ops, "bpy", mock_bpy),
        patch.object(setup_ops, "configure_game_scene_settings", return_value={"viewports_updated": 1}),
        patch.object(setup_ops, "setup_asset_collections", return_value=colls),
        patch.object(
            setup_ops,
            "assign_objects_to_asset_hierarchy",
            return_value={"moved_to_lod0": ["m1"], "skipped_library": ["lib1"]},
        ),
        patch.object(setup_ops, "project_preset_tiers"),
    ):
        op_init = MagicMock()
        op_init.asset_name = "HeroAsset"
        op_init.configure_scene = True
        op_init.create_colliders = True
        op_init.create_helpers = True
        op_init.create_config = True
        op_init.apply_color_tags = True
        op_init.move_selected = True
        assert setup_ops.OMNIMESH_OT_initialize_asset.invoke(op_init, ctx, MagicMock()) is not None
        setup_ops.OMNIMESH_OT_initialize_asset.draw(op_init, ctx)
        assert setup_ops.OMNIMESH_OT_initialize_asset.execute(op_init, ctx) == {"FINISHED"}

        op_quick = MagicMock()
        assert setup_ops.OMNIMESH_OT_quick_scene_setup.execute(op_quick, ctx) == {"FINISHED"}

        for mode in ("FACE_ORIENTATION", "STATS", "CAVITY", "BACKFACE"):
            op_ov = MagicMock(mode=mode)
            assert setup_ops.OMNIMESH_OT_toggle_viewport_overlay.execute(op_ov, ctx) == {"FINISHED"}

    with (
        patch.object(simulator_ops, "bpy", mock_bpy),
        patch.object(simulator_ops.LODSimulatorEngine, "index_scene_assets", return_value=2),
        patch.object(
            simulator_ops,
            "extract_viewport_camera_params",
            return_value=((0.0, 0.0, 5.0), 1.0, True),
        ),
        patch.object(
            simulator_ops.LODSimulatorEngine,
            "get_tracked_assets",
            return_value={"Hero": MagicMock(radius=2.0)},
        ),
        patch.object(
            simulator_ops.LODSimulatorEngine,
            "update_simulation_tick",
            return_value=[
                {"root_name": "Hero", "current_tier": 1, "screen_pct": 40.0, "distance_m": 15.0, "active_tris": 500}
            ],
        ),
        patch.object(simulator_ops.LODViewportHUD, "update_simulation_hud"),
        patch.object(simulator_ops.LODSimulatorEngine, "restore_all_visibility"),
        patch.object(simulator_ops.LODViewportHUD, "clear_simulation_hud"),
        patch.object(simulator_ops.LODSimulatorEngine, "reset_distance_scrub"),
    ):
        sim_op = simulator_ops.LOD_OT_toggle_simulator()
        assert sim_op.execute(ctx) == {"RUNNING_MODAL"}
        ev_timer = MagicMock(type="TIMER", value="NOTHING")
        assert sim_op.modal(ctx, ev_timer) == {"PASS_THROUGH"}
        ev_esc = MagicMock(type="ESC", value="PRESS")
        assert sim_op.modal(ctx, ev_esc) == {"FINISHED"}

        rst_op = simulator_ops.LOD_OT_reset_virtual_distance()
        assert rst_op.execute(ctx) == {"FINISHED"}
