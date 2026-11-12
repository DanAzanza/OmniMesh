"""Deep tests for ui/properties/callbacks.py, ui/export_ops.py, and ui/lod_ops.py."""

from __future__ import annotations

from typing import TYPE_CHECKING as _TC, Any as _Any
from unittest.mock import MagicMock, patch

if _TC:
    _MockBase: type[_Any] = object
else:
    _MockBase = object


def test_callbacks_and_presets_deep() -> None:
    """Exercise callbacks in ui/properties/callbacks.py."""
    from ui.properties import callbacks

    ctx = MagicMock()
    props = ctx.scene.lod_tool
    props.target_engine = "UE5"
    props.export_directory = "//exports"
    props.pbr_export_preset = "unreal_engine_5"
    props.pbr_import_preset = "unreal_engine_5"
    props.pbr_preset = "unreal_engine_5"
    props.pbr_export_texture_strategy = "SMART_AUTO"
    props.pbr_export_bit_depth = "8"
    props.pbr_export_naming_pattern = "{asset}_{material}{suffix}{udim}"
    props.lod_preset = "unreal_engine_5"
    props.engine_import_preset = "msfs_2024_aircraft"

    # 1. Dynamic enum item getters
    assert len(callbacks.get_lod_preset_items(props, ctx)) > 0
    assert len(callbacks.get_pbr_import_preset_items(props, ctx)) > 0
    assert len(callbacks.get_pbr_export_preset_items(props, ctx)) > 0
    assert len(callbacks.get_engine_import_preset_items(props, ctx)) > 0

    # 2. on_target_engine_updated across engines
    with patch.object(callbacks, "sync_export_maps_from_preset"):
        for eng in ("UE5", "UNITY_6", "MSFS_2024"):
            props.target_engine = eng
            props.pbr_export_preset = ""
            callbacks.on_target_engine_updated(props, ctx)

    # 3. on_export_preset_updated & on_import_preset_updated & on_legacy_preset_updated
    with (
        patch("core.pbr_presets.PBRExportPresetManager.set_last_active_preset"),
        patch.object(callbacks, "sync_export_maps_from_preset"),
        patch.object(callbacks, "sync_maps_from_preset"),
        patch("core.pbr_presets.PBRImportPresetManager.set_last_active_preset"),
    ):
        props.pbr_export_preset = "unreal_engine_5"
        callbacks.on_export_preset_updated(props, ctx)

        props.pbr_import_preset = "unreal_engine_5"
        callbacks.on_import_preset_updated(props, ctx)

        props.pbr_preset = "unity_hdrp_maskmap"
        callbacks.on_legacy_preset_updated(props, ctx)

    # 5. CoW export setting handlers (builtin & custom)
    with (
        patch("core.pbr_presets.PBRExportPresetManager.is_builtin", return_value=True),
        patch("core.pbr_presets.PBRExportPresetManager.duplicate_preset", return_value="ue5_custom"),
        patch("core.pbr_presets.PBRExportPresetManager.set_last_active_preset"),
    ):
        callbacks.on_export_strategy_updated(props, ctx)
        callbacks.on_export_bit_depth_updated(props, ctx)
        callbacks.on_export_naming_updated(props, ctx)

    with (
        patch("core.pbr_presets.PBRExportPresetManager.is_builtin", return_value=False),
        patch("core.pbr_presets.PBRExportPresetManager.get_preset", return_value={"id": "ue5_custom"}),
        patch("core.pbr_presets.PBRExportPresetManager.save_custom_preset"),
    ):
        callbacks.on_export_strategy_updated(props, ctx)

    # 6. Pipeline persistence & directory callbacks
    with patch.object(callbacks, "set_pipeline_setting"):
        callbacks.on_import_directory_updated(props, ctx)
        callbacks.on_import_path_mode_updated(props, ctx)
        callbacks.on_export_directory_updated(props, ctx)
        callbacks.on_import_ao_mode_updated(props, ctx)
        callbacks.on_import_preserve_updated(props, ctx)
        callbacks.on_engine_import_directory_updated(props, ctx)

    # 7. Engine import preset callbacks
    with (
        patch("core.engine_import_presets.EngineImportPresetManager.is_builtin", return_value=False),
        patch("core.engine_import_presets.EngineImportPresetManager.get_preset", return_value={"id": "custom_eng"}),
        patch("core.engine_import_presets.EngineImportPresetManager.save_custom_preset"),
    ):
        callbacks.on_engine_import_preset_updated(props, ctx)
        callbacks.on_engine_import_setting_updated(props, ctx)

    # 8. restore_preset_state_on_load
    mock_bpy = MagicMock()
    mock_scene = MagicMock()
    mock_scene.lod_tool = props
    props.is_state_restored = False
    props.pbr_active_maps = []
    props.pbr_export_active_maps = []
    mock_bpy.data.scenes = [mock_scene]
    with (
        patch.object(callbacks, "bpy", mock_bpy),
        patch.object(callbacks, "get_pipeline_state", return_value={"export_directory": "//saved"}),
        patch.object(callbacks, "sync_export_maps_from_preset"),
        patch.object(callbacks, "sync_maps_from_preset"),
        patch.object(callbacks, "sync_preset_tiers_from_preset"),
    ):
        callbacks.restore_preset_state_on_load()
        assert props.is_state_restored is True


def test_callbacks_asset_state_and_tiers_deep() -> None:
    """Exercise asset state serialization and tier projection in ui/properties/callbacks.py."""
    from ui.properties import callbacks

    ctx = MagicMock()
    ctx.scene.render.resolution_x = 1920
    ctx.scene.render.resolution_y = 1080
    ctx.scene.camera.type = "CAMERA"
    ctx.scene.camera.data.angle = 1.04
    ctx.scene.camera.data.sensor_fit = "AUTO"

    props = ctx.scene.lod_tool
    props.lod_preset = "unreal_engine_5"
    props.export_base_name = "HeroAsset"
    props.active_asset = "HeroAsset"
    props.is_simulator_running = False
    props.virtual_distance_override = 25.0

    class FakeLodsCollection(list):
        def add(self):
            item = MagicMock()
            self.append(item)
            return item

        def clear(self):
            del self[:]

    t0 = MagicMock()
    t0.name = "LOD0"
    t0.lod_index = 0
    t0.level_index = 0
    t0.screen_size_pct = 100.0
    t0.target_tris_pct = 100.0
    t0.target_tris = 1000
    t0.triangle_target = 1000
    t0.is_impostor = False
    t0.last_baked_target_pct = 100.0
    t0.last_baked_screen_pct = 100.0
    t0.state = "SOURCE"
    t0.show_details = False

    props.lods = FakeLodsCollection([t0])

    # serialize_asset_lod_state
    callbacks.serialize_asset_lod_state(props, "HeroAsset")

    # project_preset_tiers with base_meshes & existing_lods
    base_obj = MagicMock()
    poly = MagicMock()
    poly.vertices = [0, 1, 2, 3]
    base_obj.data.polygons = [poly] * 100
    v0 = MagicMock()
    v0.co = (0.0, 0.0, 0.0)
    base_obj.data.vertices = [v0]
    base_obj.bound_box = None
    base_obj.matrix_world = None
    base_obj.material_slots = [MagicMock(), MagicMock()]

    exist_lods = {1: {"meshes": [MagicMock()], "actual_tris": 200}}
    with (
        patch.object(callbacks, "get_asset_base_meshes", return_value=[base_obj]),
        patch.object(callbacks, "get_asset_existing_lods", return_value=exist_lods),
    ):
        callbacks.project_preset_tiers(props, ctx, asset_name="HeroAsset", ignore_cache=True)
        assert len(props.lods) > 0
        callbacks.on_active_asset_updated(props, ctx)

    # on_lod_preset_updated & on_lod_budget_mode_updated & on_active_lod_index_updated & on_virtual_distance_updated
    with (
        patch("core.lod_presets.LODPresetManager.set_last_active_preset"),
        patch.object(callbacks, "sync_preset_tiers_from_preset"),
        patch.object(callbacks, "project_preset_tiers"),
    ):
        callbacks.on_lod_preset_updated(props, ctx)
        callbacks.on_lod_budget_mode_updated(props, ctx)
        assert props.lod_preset_is_dirty is True

    with patch("ui.hud.LODViewportHUD.update_cache"), patch("ui.hud.LODViewportHUD.tag_redraw"):
        callbacks.on_active_lod_index_updated(props, ctx)

    with patch(
        "core.simulator.LODSimulatorEngine.evaluate_distance_scrub",
        return_value={"root_name": "Hero", "current_tier": 1, "active_tris": 500, "distance_m": 25.0},
    ):
        callbacks.on_virtual_distance_updated(props, ctx)
        assert "Hero" in props.last_scrub_status


def test_lod_ops_deep() -> None:
    """Exercise operators in ui/lod_ops.py."""
    from ui import lod_ops

    mock_bpy = MagicMock()
    ctx = MagicMock()
    ctx.scene.render.resolution_x = 1920
    ctx.scene.render.resolution_y = 1080
    ctx.scene.camera.type = "CAMERA"
    ctx.scene.camera.data.angle = 1.04
    ctx.scene.camera.data.sensor_fit = "AUTO"

    props = ctx.scene.lod_tool
    props.export_base_name = "Building"
    props.base_triangles = 4000
    props.bounding_radius = 5.0
    props.active_lod_index = 1

    class FakeTierCollection(list):
        def add(self):
            item = MagicMock()
            item.name = f"LOD{len(self)}"
            item.screen_size_pct = 50.0
            item.target_tris_pct = 50.0
            item.is_soloed = False
            self.append(item)
            return item

        def remove(self, idx: int):
            del self[idx]

    t0 = MagicMock()
    t0.name = "LOD0"
    t0.screen_size_pct = 100.0
    t0.target_tris_pct = 100.0
    t0.is_soloed = False
    t1 = MagicMock()
    t1.name = "LOD1"
    t1.screen_size_pct = 50.0
    t1.target_tris_pct = 50.0
    t1.is_soloed = False
    tiers = FakeTierCollection([t0, t1])
    props.lods = tiers

    mesh_obj = MagicMock()
    mesh_obj.name = "Building_LOD0"
    mesh_obj.type = "MESH"
    ctx.active_object = mesh_obj
    ctx.selected_objects = [mesh_obj]

    with (
        patch.object(lod_ops, "bpy", mock_bpy),
        patch.object(lod_ops, "resolve_lod_context", return_value=(props, mesh_obj, False)),
        patch.object(lod_ops, "project_preset_tiers"),
        patch.object(lod_ops.LODViewportHUD, "update_cache"),
        patch.object(lod_ops.LODViewportHUD, "tag_redraw"),
    ):
        # 1. Add and remove LOD tier
        op_add = MagicMock()
        assert lod_ops.LOD_OT_add_lod_tier.execute(op_add, ctx) == {"FINISHED"}
        assert len(tiers) == 3

        op_rem = MagicMock()
        op_rem.tier_index = 2
        assert lod_ops.LOD_OT_remove_lod_tier.execute(op_rem, ctx) == {"FINISHED"}
        assert len(tiers) == 2

        # 2. Reset to preset & Analyze and configure
        op_reset = MagicMock()
        assert lod_ops.LOD_OT_reset_to_preset.execute(op_reset, ctx) == {"FINISHED"}

        op_analyze = MagicMock()
        assert lod_ops.LOD_OT_analyze_and_configure.execute(op_analyze, ctx) == {"FINISHED"}

        # 3. Generate all LODs
        op_gen = MagicMock()
        op_gen.only_out_of_sync = False
        with (
            patch.object(lod_ops, "get_asset_base_meshes", return_value=[mesh_obj]),
            patch.object(lod_ops, "generate_all_lods", return_value=(True, "Generated 2 LODs")),
        ):
            assert lod_ops.LOD_OT_generate_all.execute(op_gen, ctx) == {"FINISHED"}

        # 4. Solo tier (solo, un-solo, and reset -1)
        coll0 = MagicMock()
        coll0.objects = [mesh_obj]
        mock_bpy.data.collections.get.return_value = coll0

        # 5. Sync selection settings & Select master asset
        other_mesh = MagicMock()
        other_mesh.type = "MESH"
        ctx.selected_objects = [mesh_obj, other_mesh]
        props.lod_preset_active_tiers = [t0]
        op_sync = MagicMock()
        assert lod_ops.LOD_OT_sync_selection_settings.execute(op_sync, ctx) == {"FINISHED"}

        mesh_obj.lod_tool.lod_root_object = "MasterObj"
        mock_bpy.data.objects.get.return_value = other_mesh
        op_sel = MagicMock()
        assert lod_ops.LOD_OT_select_master_asset.execute(op_sel, ctx) == {"FINISHED"}


def test_export_ops_deep(tmp_path) -> None:
    """Exercise operators in ui/export_ops.py."""
    from ui import export_ops

    mock_bpy = MagicMock()
    mock_bpy.path.abspath.side_effect = lambda p: str(tmp_path / p.lstrip("/"))
    ctx = MagicMock()
    props = ctx.scene.lod_tool
    props.export_directory = str(tmp_path)
    props.target_engine = "UE5"
    props.pbr_export_preset = "unreal_engine_5"
    props.texture_max_resolution = "1024"
    props.pbr_export_texture_strategy = "CONVERT_PNG"
    props.pbr_export_bit_depth = "8"
    props.pbr_export_naming_pattern = "{asset}_{material}{suffix}{udim}"
    props.export_base_name = "Hero"
    props.export_packed_textures = True
    props.bake_animations = False

    mat = MagicMock()
    mat.name = "M_Hero"
    slot = MagicMock()
    slot.material = mat
    mesh_obj = MagicMock()
    mesh_obj.name = "Hero_LOD0"
    mesh_obj.type = "MESH"
    mesh_obj.material_slots = [slot]
    ctx.selected_objects = [mesh_obj]
    ctx.active_object = mesh_obj

    with (
        patch.object(export_ops, "bpy", mock_bpy),
        patch.object(export_ops, "resolve_lod_context", return_value=(props, mesh_obj, False)),
    ):
        # 1. Pack PBR textures
        op_pack = MagicMock()
        with (
            patch.object(export_ops.PBRExportPresetManager, "get_preset", return_value={"name": "UE5"}),
            patch.object(export_ops.TextureChannelPacker, "pack_material_preset", return_value=["fut1"]),
            patch.object(export_ops.TexturePoolManager, "wait_all", return_value=[True]),
        ):
            assert export_ops.LOD_OT_pack_pbr_textures.execute(op_pack, ctx) == {"FINISHED"}

        # 2. Bake rig animation
        arm_obj = MagicMock()
        arm_obj.type = "ARMATURE"
        arm_obj.animation_data.action.name = "Run"
        ctx.active_object = arm_obj
        op_bake = MagicMock()
        with (
            patch.object(
                export_ops.AnimationRigSanitizer, "bake_deform_animation", return_value=MagicMock(name="Baked")
            ),
            patch.object(export_ops.AnimationRigSanitizer, "setup_clean_nla_export"),
        ):
            assert export_ops.LOD_OT_bake_rig_animation.execute(op_bake, ctx) == {"FINISHED"}

        # 3. Export engine package
        op_exp = MagicMock()
        with (
            patch.object(export_ops.PreFlightValidator, "run_checks", return_value=[]),
            patch.object(export_ops.ExporterManager, "export_asset", return_value=(True, "Exported OK")),
        ):
            assert export_ops.LOD_OT_export_engine_package.execute(op_exp, ctx) == {"FINISHED"}


def test_engine_import_helpers_deep(tmp_path) -> None:
    """Exercise import_spatial_points, import_lighting_points, import_cameras, and import_attachments."""
    from ui import engine_import_helpers

    class FakeObjCollection(list):
        def link(self, obj):
            self.append(obj)

        def new(self, name, data=None):
            m = MagicMock(name=name, data=data)
            self.append(m)
            return m

        def get(self, name, default=None):
            return default

    mock_bpy = MagicMock()
    mock_bpy.data.objects = FakeObjCollection()
    mock_bpy.data.collections = FakeObjCollection()
    ctx = MagicMock()
    props = ctx.scene.lod_tool

    fm_cfg = tmp_path / "flight_model.cfg"
    fm_cfg.write_text("[WEIGHT_AND_BALANCE]\nreference_datum_position = 0, 0, 0\n", encoding="utf-8")
    sys_cfg = tmp_path / "systems.cfg"
    sys_cfg.write_text("[LIGHTS]\n", encoding="utf-8")
    cam_cfg = tmp_path / "cameras.cfg"
    cam_cfg.write_text("[VIEWS]\neyepoint = 0, 0, 0\n", encoding="utf-8")
    att_cfg = tmp_path / "attached_objects.cfg"
    att_cfg.write_text("[MERGE_MODEL.0]\n", encoding="utf-8")

    manifest = MagicMock()
    manifest.flight_model_cfg_path = str(fm_cfg)
    manifest.systems_cfg_path = str(sys_cfg)
    manifest.cameras_cfg_path = str(cam_cfg)
    manifest.attached_objects_cfg_path = str(att_cfg)
    manifest.interior_model = True

    def _make_point(ptype: str, pclass: int, key: str, tag: str = "Tag"):
        pt = MagicMock()
        pt.point_type = ptype
        pt.point_class = pclass
        pt.key = key
        pt.name_tag = tag
        pt.coords_blender_m = (0.0, 0.0, 0.0)
        pt.coords_msfs_rel_ft = (1.0, 2.0, 3.0)
        return pt

    parsed_fm = MagicMock()
    parsed_fm.points = [
        _make_point("DATUM", 0, "datum"),
        _make_point("CONTACT_POINT", 1, "point.0", "Wheel"),
        _make_point("CONTACT_POINT", 2, "point.1", "Scrape"),
        _make_point("CONTACT_POINT", 3, "point.2", "Skid"),
        _make_point("CONTACT_POINT", 4, "point.3", "Float"),
        _make_point("CONTACT_POINT", 5, "point.4", "WaterRudder"),
        _make_point("CONTACT_POINT", 9, "point.5", "Other"),
        _make_point("FUEL_TANK", 0, "fuel.0", "LeftMain"),
        _make_point("ENGINE", 0, "engine.0", "Eng1"),
        _make_point("PAYLOAD_STATION", 0, "station_load.0", "Pilot"),
        _make_point("OTHER", 0, "misc.0", "Misc"),
    ]

    parsed_lights = MagicMock()
    l1 = MagicMock()
    l1.light_type = 1
    l2 = MagicMock()
    l2.light_type = 4
    parsed_lights.lights = [l1, l2]

    parsed_cams = MagicMock()
    parsed_cams.eyepoint_ft = (1.0, 0.0, 2.0)
    c1 = MagicMock()
    c1.index = 0
    c1.title = "PilotView"
    c1.category = "Cockpit"
    c1.origin = "Virtual Cockpit"
    c1.guid = "{1234}"
    c1.initial_zoom = 0.5
    c1.initial_pbh_deg = (0.0, 0.0, 0.0)
    c1.initial_xyz_m = (0.1, 0.2, 0.3)
    c2 = MagicMock()
    c2.index = 1
    c2.title = "ExtView"
    c2.category = "Custom"
    c2.origin = "Center"
    c2.guid = "{5678}"
    c2.initial_zoom = 1.0
    c2.initial_pbh_deg = (5.0, 0.0, 90.0)
    c2.initial_xyz_m = (1.0, 2.0, 3.0)
    parsed_cams.cameras = [c1, c2]

    col_mock = MagicMock()
    col_mock.objects = FakeObjCollection()

    with (
        patch.object(engine_import_helpers, "bpy", mock_bpy),
        patch.object(engine_import_helpers, "get_or_create_engine_import_collection", return_value=col_mock),
        patch.object(engine_import_helpers.MSFSCSTParser, "parse_file", side_effect=[parsed_fm, parsed_lights]),
        patch.object(engine_import_helpers.MSFSCSTParser, "parse_cameras_file", return_value=parsed_cams),
        patch("ui.msfs_lighting_ops.OMNIMESH_OT_import_msfs_lights._ensure_light_object"),
        patch("ui.msfs_attachment_ops.OMNIMESH_OT_import_msfs_attachments") as mock_att_cls,
    ):
        mock_att_inst = mock_att_cls.return_value
        mock_att_inst.execute.return_value = {"FINISHED"}
        mock_att_inst.imported_count = 3

        sp_count, datum = engine_import_helpers.import_spatial_points(ctx, manifest, "Aircraft", props)
        assert sp_count == 10
        assert datum is not None

        lt_count = engine_import_helpers.import_lighting_points(ctx, manifest, "Aircraft", datum, props)
        assert lt_count == 2

        cm_count = engine_import_helpers.import_cameras(ctx, manifest, "Aircraft", datum, props)
        assert cm_count == 2

        at_count = engine_import_helpers.import_attachments(ctx, manifest)
        assert at_count == 3


def test_lod_preset_ops_deep(tmp_path) -> None:
    """Exercise LOD preset CRUD and tier template operators in ui/lod_preset_ops.py."""
    from ui import lod_preset_ops

    mock_bpy = MagicMock()
    ctx = MagicMock()
    props = ctx.scene.lod_tool
    props.lod_preset = "custom_lod"
    props.lod_preset_active_tier_index = 1

    class FakePresetTiers(list):
        def add(self):
            itm = MagicMock()
            itm.name = f"LOD{len(self)}"
            itm.screen_size_pct = 50.0
            itm.target_tris_pct = 50.0
            itm.target_tris = 5000
            self.append(itm)
            return itm

        def remove(self, idx: int):
            del self[idx]

        def clear(self):
            del self[:]

    pt0 = MagicMock(name="LOD0", screen_size_pct=100.0, target_tris_pct=100.0, target_tris=10000)
    pt1 = MagicMock(name="LOD1", screen_size_pct=50.0, target_tris_pct=50.0, target_tris=5000)
    props.lod_preset_active_tiers = FakePresetTiers([pt0, pt1])
    props.lods = [pt0, pt1]

    with (
        patch.object(lod_preset_ops, "bpy", mock_bpy),
        patch.object(lod_preset_ops, "resolve_lod_context", return_value=(props, None, False)),
        patch.object(lod_preset_ops, "sync_preset_tiers_from_preset"),
        patch.object(lod_preset_ops, "sync_preset_tiers_to_preset", return_value="custom_lod"),
        patch.object(lod_preset_ops.LODPresetManager, "create_new_preset", return_value="new_lod"),
        patch.object(lod_preset_ops.LODPresetManager, "get_preset", return_value={"name": "Custom"}),
        patch.object(lod_preset_ops.LODPresetManager, "set_last_active_preset"),
        patch.object(lod_preset_ops.LODPresetManager, "is_builtin", return_value=False),
        patch.object(lod_preset_ops.LODPresetManager, "rename_custom_preset", return_value="renamed_lod"),
        patch.object(lod_preset_ops.LODPresetManager, "is_user_preset", return_value=True),
        patch.object(lod_preset_ops.LODPresetManager, "get_builtin_dir", return_value=tmp_path),
        patch.object(lod_preset_ops.LODPresetManager, "delete_custom_preset", return_value=True),
    ):
        op_create = MagicMock(preset_name="My LOD", template_type="unreal_engine_5")
        assert lod_preset_ops.LOD_OT_create_lod_preset.execute(op_create, ctx) == {"FINISHED"}

        op_ren = MagicMock(new_name="Renamed LOD")
        assert lod_preset_ops.LOD_OT_rename_lod_preset.execute(op_ren, ctx) == {"FINISHED"}

        op_del = MagicMock()
        assert lod_preset_ops.LOD_OT_delete_lod_preset.execute(op_del, ctx) == {"FINISHED"}

        op_add = MagicMock()
        assert lod_preset_ops.LOD_OT_add_preset_tier.execute(op_add, ctx) == {"FINISHED"}

        op_rem = MagicMock()
        assert lod_preset_ops.LOD_OT_remove_preset_tier.execute(op_rem, ctx) == {"FINISHED"}

        op_save = MagicMock()
        assert lod_preset_ops.LOD_OT_save_preset_tiers.execute(op_save, ctx) == {"FINISHED"}

        op_apply = MagicMock()
        lod_preset_ops.LOD_OT_apply_preset_tiers.execute(op_apply, ctx)

        op_cap = MagicMock()
        assert lod_preset_ops.LOD_OT_capture_scene_tiers.execute(op_cap, ctx) == {"FINISHED"}


def test_msfs_ground_ops_deep(tmp_path) -> None:
    """Exercise OMNIMESH_OT_generate_msfs_scrape_points and OMNIMESH_OT_align_gear_ground_level."""
    import numpy as np
    from ui import msfs_ground_ops

    mock_bpy = MagicMock()
    ctx = MagicMock()
    props = ctx.scene.lod_tool
    props.msfs_scrape_margin_m = 0.05
    cfg_file = tmp_path / "flight_model.cfg"
    cfg_file.write_text("[CONTACT_POINTS]\nstatic_cg_height = 5.0\n", encoding="utf-8")
    props.msfs_spatial_cfg_path = str(cfg_file)
    props.msfs_gear_state = "UNCOMPRESSED_EXTENDED"
    props.msfs_gear_compression_m = 0.12

    mesh_obj = MagicMock()
    mesh_obj.type = "MESH"
    mesh_obj.matrix_world.translation.x = 0.0
    mesh_obj.matrix_world.translation.y = 0.0
    mesh_obj.matrix_world.translation.z = 0.0
    ctx.selected_objects = [mesh_obj]
    ctx.scene.objects = [mesh_obj]

    col_mock = MagicMock()
    wheel_empty = MagicMock()
    wheel_empty.get.side_effect = lambda k, d=None: {"msfs_type": "CONTACT_POINT", "msfs_class": 1}.get(k, d)
    wheel_empty.matrix_world.translation.x = 0.0
    wheel_empty.matrix_world.translation.y = 0.0
    wheel_empty.matrix_world.translation.z = -1.0
    wheel_empty.parent = None
    mesh_obj.matrix_world.translation.__sub__.return_value.length_squared = 0.1

    cg_empty = MagicMock()
    cg_empty.get.side_effect = lambda k, d=None: {"msfs_type": "CG"}.get(k, d)
    cg_empty.matrix_world.translation.z = 0.5

    class FakeColObjects(list):
        def link(self, obj):
            self.append(obj)

    col_mock.objects = FakeColObjects([wheel_empty, cg_empty])

    verts = np.array(
        [
            [-5.0, 0.0, 0.0],
            [5.0, 0.0, 0.0],
            [0.0, 6.0, 0.0],
            [0.0, -6.0, 0.0],
            [0.0, 0.0, -1.5],
            [0.0, 0.0, 2.5],
        ],
        dtype=np.float32,
    )

    with (
        patch.object(msfs_ground_ops, "bpy", mock_bpy),
        patch.object(msfs_ground_ops, "get_or_create_spatial_collection", return_value=col_mock),
        patch.object(msfs_ground_ops, "find_spatial_collection", return_value=col_mock),
        patch.object(msfs_ground_ops, "collect_airframe_vertices", return_value=verts),
        patch.object(msfs_ground_ops, "extract_world_vertices_numpy", return_value=verts),
        patch.object(msfs_ground_ops.MSFSCSTParser, "parse_file", return_value=MagicMock()),
        patch.object(msfs_ground_ops.MSFSCSTParser, "update_scalar_param", return_value=str(cfg_file) + ".bak"),
    ):
        op_scrape = MagicMock()
        assert msfs_ground_ops.OMNIMESH_OT_generate_msfs_scrape_points.execute(op_scrape, ctx) == {"FINISHED"}

        op_gear = MagicMock()
        assert msfs_ground_ops.OMNIMESH_OT_align_gear_ground_level.execute(op_gear, ctx) == {"FINISHED"}


def test_callbacks_custom_export_preset_target_engine_update(monkeypatch):
    """Verify changing target_engine on a custom export preset updates it in-place."""
    import ui.properties.callbacks as cb

    save_mock = MagicMock()
    monkeypatch.setattr(cb.PBRExportPresetManager, "is_builtin", lambda pid: False)
    monkeypatch.setattr(
        cb.PBRExportPresetManager,
        "get_preset",
        lambda pid: {"id": pid, "name": "My Custom", "target_engine": "UE5"},
    )
    monkeypatch.setattr(cb.PBRExportPresetManager, "save_custom_preset", save_mock)

    props = MagicMock()
    props.pbr_export_preset = "my_custom_export"
    props.target_engine = "UNITY_6"
    props.export_directory = ""

    cb.on_target_engine_updated(props, None)
    assert props.pbr_export_preset == "my_custom_export"
    save_mock.assert_called_once()
    saved_payload = save_mock.call_args.args[0]
    assert saved_payload["target_engine"] == "UNITY_6"
    assert save_mock.call_args.kwargs["custom_id"] == "my_custom_export"
