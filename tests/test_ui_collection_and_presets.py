"""
Unit, negative, and boundary tests for OmniMesh collection-first asset resolution,
preset operators, enum contracts, and property synchronization callbacks.
"""

from __future__ import annotations

import importlib
from pathlib import Path
import typing
from typing import Any, cast
from unittest.mock import MagicMock, patch

import pytest

from ui.lod_preset_ops import LOD_PRESET_OPERATOR_CLASSES
from ui.panel import SUBPANEL_CLASSES
from ui.pbr_preset_ops import PBR_PRESET_OPERATOR_CLASSES
from ui.preset_ops import PRESET_OPERATOR_CLASSES
from ui.properties.enums import (
    ASSET_CATEGORY_ITEMS,
    IMPOSTOR_MODE_ITEMS,
    PROGRESSION_MODE_ITEMS,
    TARGET_ENGINE_ITEMS,
)
from ui.properties.guards import (
    ExportMapSyncGuard,
    MapSyncGuard,
    PresetSyncGuard,
    StateRestorationGuard,
)


def test_collection_first_tier_projection_and_reset():
    """Verify collection-first tier projection, state badges, and reset operator."""
    from ui.lod_ops import LOD_OT_reset_to_preset

    mock_context, mock_props = MagicMock(), MagicMock()
    mock_context.scene.lod_tool = mock_props
    created_tiers = []

    def mock_add():
        tier = MagicMock(name=f"LOD{len(created_tiers)}")
        tier.target_tris_pct = 100.0 if not created_tiers else 50.0
        tier.screen_size_pct = 100.0 if not created_tiers else 50.0
        tier.actual_tris, tier.state, tier.last_baked_target_pct = 0, "PLANNED", -1.0
        created_tiers.append(tier)
        return tier

    mock_props.lods.add = mock_add
    mock_props.lods.clear = lambda: created_tiers.clear()
    mock_props.lods.__iter__ = lambda self: iter(created_tiers)
    mock_props.lods.__len__ = lambda self: len(created_tiers)

    op_reset = LOD_OT_reset_to_preset()
    assert op_reset.execute(None) == {"FINISHED"}
    assert op_reset.execute(mock_context) == {"FINISHED"}


def test_panel2_modify_collection_first_and_lod0_only(monkeypatch):
    """Verify Panel 2 Modify draws cleanly without selection and operators target LOD0 only."""
    import ui.cleanup_ops as cleanup_ops
    import ui.panel as panel_mod
    import ui.utils as ui_utils
    from ui.cleanup_ops import (
        LOD_OT_apply_all_modifiers,
        LOD_OT_apply_transforms,
        LOD_OT_clean_and_repair_materials,
        LOD_OT_clean_and_repair_mesh,
    )
    from ui.panel import OMNIMESH_PT_modify
    from ui.utils import get_lod0_mesh_objects

    mock_bpy = MagicMock()
    monkeypatch.setattr(ui_utils, "bpy", mock_bpy)
    monkeypatch.setattr(cleanup_ops, "bpy", mock_bpy)
    monkeypatch.setattr(panel_mod, "bpy", mock_bpy)

    mesh_lod0 = MagicMock(type="MESH")
    mesh_lod0.name = "Suzanne"
    mesh_lod0.get.return_value = False
    mesh_lod0.data = MagicMock(users=1, shape_keys=None)
    mesh_lod0.animation_data = None
    mesh_lod0.material_slots = []

    mesh_lod1 = MagicMock(type="MESH")
    mesh_lod1.name = "Suzanne_LOD1"
    mesh_lod1.get.return_value = False

    coll_root = MagicMock()
    coll_root.name = "Suzanne"
    coll_root.objects = [mesh_lod0]
    mock_bpy.data.collections.get.side_effect = lambda name: coll_root if name in {"Suzanne", "Suzanne_LOD0"} else None

    mock_context = MagicMock()
    mock_context.scene.collection = MagicMock()
    mock_context.active_object = None
    mock_context.selected_objects = []
    mock_props = MagicMock(active_asset="Suzanne", export_base_name="Suzanne")
    mock_context.scene.lod_tool = mock_props

    lod0_meshes = get_lod0_mesh_objects(mock_context)
    assert len(lod0_meshes) == 1
    assert lod0_meshes[0].name == "Suzanne"

    panel_modify = OMNIMESH_PT_modify()
    mock_layout = MagicMock()
    cast(Any, panel_modify).layout = mock_layout
    panel_modify.draw(mock_context)
    assert mock_layout.row.called

    assert LOD_OT_clean_and_repair_mesh.poll(mock_context) is True
    assert LOD_OT_clean_and_repair_materials.poll(mock_context) is True
    assert LOD_OT_apply_all_modifiers.poll(mock_context) is True
    assert LOD_OT_apply_transforms.poll(mock_context) is True


def test_panel2_modify_active_asset_dropdown_and_scoping(monkeypatch):
    """Verify that OMNIMESH_PT_main renders the active_asset dropdown in non-IMPORT tabs and scopes LOD0."""
    import ui.panel as panel_mod
    import ui.utils as ui_utils
    from ui.panel import OMNIMESH_PT_main
    from ui.utils import get_lod0_mesh_objects

    mock_bpy = MagicMock()
    monkeypatch.setattr(panel_mod, "bpy", mock_bpy)
    monkeypatch.setattr(ui_utils, "bpy", mock_bpy)

    plane_mesh, pilot_mesh = MagicMock(type="MESH"), MagicMock(type="MESH")
    plane_mesh.name, pilot_mesh.name = "Airframe", "Pilot"
    plane_mesh.get.return_value, pilot_mesh.get.return_value = False, False

    coll_plane = MagicMock(name="Airframe_LOD0", objects=[plane_mesh])
    coll_pilot = MagicMock(name="Pilot_LOD0", objects=[pilot_mesh])

    def mock_get_coll(name):
        if name in {"Airframe", "Airframe_LOD0"}:
            return coll_plane
        if name in {"Pilot", "Pilot_LOD0"}:
            return coll_pilot
        return None

    mock_bpy.data.collections.get.side_effect = mock_get_coll

    mock_context = MagicMock()
    mock_context.scene.collection = MagicMock()
    mock_context.active_object = None
    mock_context.selected_objects = []

    mock_props = MagicMock()
    mock_props.ui_active_tab = "MODIFY"
    mock_props.active_asset = "Airframe"
    mock_props.export_base_name = "Airframe"
    mock_context.scene.lod_tool = mock_props

    # 1. OMNIMESH_PT_main draw renders active_asset prop in MODIFY tab
    main_panel = OMNIMESH_PT_main()
    main_panel.draw(None)
    mock_layout = MagicMock()
    mock_main_row, mock_col_tabs, mock_col_content, mock_row = (
        MagicMock(),
        MagicMock(),
        MagicMock(),
        MagicMock(),
    )
    mock_layout.row.return_value = mock_main_row
    mock_main_row.column.side_effect = lambda *args, **kwargs: (
        mock_col_tabs if kwargs.get("align", False) else mock_col_content
    )
    mock_col_content.row.return_value = mock_row

    cast(Any, main_panel).layout = mock_layout
    monkeypatch.setattr(panel_mod, "resolve_lod_context", lambda _ctx: (None, None, False))
    main_panel.draw(mock_context)

    # Verify vertical icon tab prop is rendered in left column
    mock_col_tabs.prop.assert_any_call(mock_props, "ui_active_tab", expand=True, icon_only=True)

    # Verify active_asset is rendered in the content area for MODIFY tab
    mock_row.prop.assert_any_call(mock_props, "active_asset", text="Asset", icon="OUTLINER_COLLECTION")

    # Verify active_asset is NOT rendered when ui_active_tab is IMPORT
    mock_props.ui_active_tab = "IMPORT"
    mock_row.reset_mock()
    main_panel.draw(mock_context)
    call_active_asset = [c for c in mock_row.prop.call_args_list if len(c.args) > 1 and c.args[1] == "active_asset"]
    assert len(call_active_asset) == 0

    # 2. Verify scoping to active_asset
    mock_props.ui_active_tab = "MODIFY"
    meshes = get_lod0_mesh_objects(mock_context)
    assert len(meshes) == 1
    assert meshes[0].name == "Airframe"

    # Switch active_asset to Pilot
    mock_props.active_asset = "Pilot"
    mock_props.export_base_name = "Pilot"
    meshes_pilot = get_lod0_mesh_objects(mock_context)
    assert len(meshes_pilot) == 1
    assert meshes_pilot[0].name == "Pilot"


def test_config_sibling_collection_and_active_asset_resolution(monkeypatch):
    """Verify that selecting technical objects in _Config resolves the root asset cleanly."""
    import core.asset_scanner as asset_scanner
    import ui.utils as ui_utils

    mock_bpy = MagicMock()
    monkeypatch.setattr(ui_utils, "bpy", mock_bpy)
    monkeypatch.setattr(asset_scanner, "bpy", mock_bpy)

    f_mesh = MagicMock(type="MESH", name="Fuselage")
    f_mesh.get.side_effect = lambda k, d=False: False

    col_plane = MagicMock()
    col_plane.name = "Simple_Aircraft"
    col_plane.objects = [f_mesh]
    col_plane.all_objects = col_plane.objects
    col_plane.get = lambda k, d=None: "MODEL_ROOT" if k == "_omnimesh_role" else d

    col_config = MagicMock()
    col_config.name = "Simple_Aircraft_Config"
    col_config.objects = []
    col_config.all_objects = []
    col_config.get = lambda k, d=None: "CONFIG" if k == "_omnimesh_role" else d

    col_spatial = MagicMock()
    col_spatial.name = "Simple_Aircraft_Spatial"
    datum_empty = MagicMock(type="EMPTY", name="MSFS_Datum")
    col_spatial.objects = [datum_empty]
    col_spatial.all_objects = col_spatial.objects
    col_spatial.get = lambda k, d=None: "SPATIAL" if k == "_omnimesh_role" else d

    datum_empty.users_collection = [col_spatial]

    col_helpers = MagicMock()
    col_helpers.name = "Simple_Aircraft_Helpers"
    ref_mesh = MagicMock(type="MESH", name="Blueprint_Guide")
    ref_mesh.get.side_effect = lambda k, d=False: False
    col_helpers.objects = [ref_mesh]
    col_helpers.all_objects = col_helpers.objects
    col_helpers.get = lambda k, d=None: "HELPERS" if k == "_omnimesh_role" else d
    ref_mesh.users_collection = [col_helpers]

    mock_scene = MagicMock()
    mock_scene.collection = MagicMock(name="Scene Collection")
    mock_bpy.data.collections = [col_plane, col_config, col_spatial, col_helpers]

    mock_context = MagicMock()
    mock_context.blend_data = mock_bpy.data
    mock_context.scene = mock_scene
    mock_context.view_layer.active_layer_collection = None
    mock_context.active_object = datum_empty

    # Available assets must exclude _Config, _Spatial, and _Helpers
    avail = ui_utils.get_available_asset_names(mock_context)
    assert "Simple_Aircraft" in avail
    assert "Simple_Aircraft_Config" not in avail
    assert "Simple_Aircraft_Spatial" not in avail
    assert "Simple_Aircraft_Helpers" not in avail

    # Selecting datum empty should resolve to Simple_Aircraft
    eff_asset = ui_utils.resolve_effective_asset_name(mock_context)
    assert eff_asset == "Simple_Aircraft"

    eff_scanner = asset_scanner.resolve_effective_asset_name(mock_context, blend_data=mock_bpy.data)
    assert eff_scanner == "Simple_Aircraft"

    # Selecting helper mesh should also resolve to Simple_Aircraft
    mock_context.active_object = ref_mesh
    eff_helper_asset = ui_utils.resolve_effective_asset_name(mock_context)
    assert eff_helper_asset == "Simple_Aircraft"


def test_preset_operator_classes_integrity():
    """Verify preset operator classes have unique idnames and valid Blender metadata."""
    assert len(PBR_PRESET_OPERATOR_CLASSES) >= 10
    assert len(LOD_PRESET_OPERATOR_CLASSES) >= 5
    assert len(PRESET_OPERATOR_CLASSES) == len(PBR_PRESET_OPERATOR_CLASSES) + len(LOD_PRESET_OPERATOR_CLASSES)

    # Invariant: Every operator class must have a unique bl_idname and bl_label
    idnames = [cls.bl_idname for cls in PRESET_OPERATOR_CLASSES]
    assert len(idnames) == len(set(idnames)), "Operator bl_idname entries must be strictly unique."
    for cls in PRESET_OPERATOR_CLASSES:
        assert hasattr(cls, "bl_idname") and cls.bl_idname.startswith("lod_tool.")
        assert hasattr(cls, "bl_label") and len(cls.bl_label) > 0


def test_ui_properties_enums():
    """Verify enum items in modularized ui.properties.enums enforce strict invariants."""
    # 1. Target engines structural contract
    engine_ids = {item[0] for item in TARGET_ENGINE_ITEMS}
    expected_engines = {"MSFS_2024", "UE5", "UNITY_6"}
    assert engine_ids == expected_engines, f"Engine mismatch: {engine_ids} != {expected_engines}"
    assert "UNSUPPORTED_ENGINE" not in engine_ids

    # 2. Asset category structural contract
    category_ids = {item[0] for item in ASSET_CATEGORY_ITEMS}
    expected_categories = {"HERO_CHARACTER", "BUILDING", "PROP", "FOLIAGE"}
    assert expected_categories.issubset(category_ids), f"Missing asset categories: {expected_categories - category_ids}"

    # 3. Impostor mode structural contract
    impostor_ids = {item[0] for item in IMPOSTOR_MODE_ITEMS}
    expected_impostors = {"ORTHO_3_AXES", "OCTAHEDRAL_HEMI"}
    assert expected_impostors.issubset(impostor_ids), f"Missing impostor modes: {expected_impostors - impostor_ids}"

    # 4. Progression mode structural contract
    prog_ids = {item[0] for item in PROGRESSION_MODE_ITEMS}
    assert {"EXPONENTIAL", "LOGARITHMIC", "AGGRESSIVE", "LINEAR"}.issubset(prog_ids)

    # 5. Invariant: Each enum item must be a 3-tuple with non-empty (id, name, description)
    for enum_list in (TARGET_ENGINE_ITEMS, ASSET_CATEGORY_ITEMS, IMPOSTOR_MODE_ITEMS, PROGRESSION_MODE_ITEMS):
        for item in enum_list:
            assert len(item) == 3, f"Enum item must be a 3-tuple: {item}"
            ident, name, desc = item
            assert isinstance(ident, str) and len(ident) > 0
            assert isinstance(name, str) and len(name) > 0
            assert isinstance(desc, str) and len(desc) > 0


def test_sync_guards_reentrancy():
    """Verify that reentrancy guards lock and unlock cleanly."""
    assert PresetSyncGuard.is_locked() is False
    with PresetSyncGuard():
        assert PresetSyncGuard.is_locked() is True
    assert PresetSyncGuard.is_locked() is False

    assert MapSyncGuard.is_active() is False
    with MapSyncGuard():
        assert MapSyncGuard.is_active() is True
    assert MapSyncGuard.is_active() is False

    assert ExportMapSyncGuard.is_active() is False
    with ExportMapSyncGuard():
        assert ExportMapSyncGuard.is_active() is True
    assert ExportMapSyncGuard.is_active() is False


def test_resolve_lod_context_reference_error_safeguard():
    """Verify resolve_lod_context handles invalid/removed objects without ReferenceError."""
    from ui.utils import resolve_lod_context

    ctx = MagicMock()
    ctx.scene.lod_tool = MagicMock()
    ctx.scene.lod_tool.lods = []

    # Mock active_object that raises ReferenceError when accessing attributes
    class DeletedObject:
        @property
        def name(self):
            raise ReferenceError("StructRNA of type Object has been removed")

        @property
        def type(self):
            raise ReferenceError("StructRNA of type Object has been removed")

    ctx.active_object = DeletedObject()
    props, master, is_deriv = resolve_lod_context(ctx)
    assert props == ctx.scene.lod_tool
    assert master is None
    assert is_deriv is False


def test_msfs_panel_removed():
    """Verify that legacy ui/msfs_panel.py is eliminated and not in sys.modules or SUBPANEL_CLASSES."""
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("ui.msfs_panel")

    subpanel_names = [cls.bl_idname for cls in SUBPANEL_CLASSES]
    assert "OMNIMESH_PT_export_msfs_spatial" not in subpanel_names
    assert len(subpanel_names) == 0


def test_lods_compact_card_show_details(monkeypatch):
    """Verify that OMNIMESH_PT_lods renders compact cards (sliders hidden) when show_details is False and renders sliders when True."""
    from ui.panel import OMNIMESH_PT_lods
    from ui.properties.lod_properties import LODLevelItem, LODTierItem

    monkeypatch.setattr("ui.panel.bpy", MagicMock())

    assert LODTierItem is LODLevelItem

    tier0 = MagicMock()
    tier0.name = "LOD0"
    tier0.actual_tris = 10000
    tier0.target_tris_pct = 100.0
    tier0.screen_size_pct = 100.0
    tier0.distance_m = 0.0
    tier0.is_impostor = False
    tier0.is_soloed = False
    tier0.show_details = False
    tier0.state = "SOURCE"
    tier0.last_baked_target_pct = 100.0

    tier1 = MagicMock()
    tier1.name = "LOD1"
    tier1.actual_tris = 5000
    tier1.target_tris_pct = 50.0
    tier1.screen_size_pct = 40.0
    tier1.distance_m = 12.0
    tier1.is_impostor = False
    tier1.is_soloed = False
    tier1.show_details = False
    tier1.state = "BAKED"
    tier1.last_baked_target_pct = 50.0

    mock_layout = MagicMock()
    mock_box = MagicMock()
    mock_card = MagicMock()
    mock_layout.box.return_value = mock_box
    mock_box.box.return_value = mock_card

    mock_row = MagicMock()
    mock_card.row.return_value = mock_row

    ctx = MagicMock()
    ctx.selected_objects = []
    ctx.active_object = None
    ctx.scene.lod_tool.lods = [tier0, tier1]
    ctx.scene.lod_tool.base_triangles = 10000
    ctx.scene.lod_tool.lod_preset = "unreal_engine_5"
    ctx.scene.lod_tool.tau_sse = 2.0
    ctx.scene.lod_tool.active_asset = ""

    panel = OMNIMESH_PT_lods()

    # Case 1: show_details is False -> sliders are not drawn
    cast(Any, panel).layout = mock_layout
    panel.draw(ctx)

    prop_names_called = [call.args[1] for call in mock_row.prop.call_args_list if len(call.args) > 1]
    assert "target_tris_pct" not in prop_names_called
    assert "screen_size_pct" not in prop_names_called

    # Case 2: show_details is True -> sliders are drawn
    tier1.show_details = True
    mock_row.reset_mock()
    panel.draw(ctx)

    prop_names_called = [call.args[1] for call in mock_row.prop.call_args_list if len(call.args) > 1]
    assert "target_tris_pct" in prop_names_called
    assert "screen_size_pct" in prop_names_called


def test_pbr_maps_hydration_without_draw_mutation():
    """Verify that restore_preset_state_on_load hydrates pbr_active_maps and pbr_export_active_maps without draw()."""
    from ui.properties.callbacks import restore_preset_state_on_load

    mock_scene = MagicMock()
    mock_props = MagicMock()
    mock_props.is_state_restored = False
    mock_props.pbr_active_maps = MagicMock()
    mock_props.pbr_export_active_maps = MagicMock()
    mock_scene.lod_tool = mock_props

    mock_bpy = MagicMock()
    mock_bpy.data.scenes = [mock_scene]

    with patch("ui.properties.callbacks.bpy", mock_bpy):
        restore_preset_state_on_load(None)

    assert mock_props.is_state_restored is True


def test_operator_classes_type_hints_clean():
    """Verify that typing.get_type_hints evaluates cleanly across all UI operator classes without SyntaxError."""
    from ui import (
        chunk_ops,
        cleanup_ops,
        config_preset_ops,
        engine_import_ops,
        hull_impostor_ops,
        msfs_camera_ops,
        msfs_lighting_ops,
        msfs_spatial_ops,
        operators,
        setup_ops,
    )

    tested = 0
    modules = [
        operators,
        config_preset_ops,
        engine_import_ops,
        msfs_camera_ops,
        msfs_lighting_ops,
        msfs_spatial_ops,
        setup_ops,
        cleanup_ops,
        chunk_ops,
        hull_impostor_ops,
    ]
    for mod in modules:
        for attr in dir(mod):
            val = getattr(mod, attr)
            cls_list = (
                val
                if isinstance(val, (list, tuple))
                and any(
                    kw in attr
                    for kw in (
                        "classes",
                        "OPERATOR_CLASSES",
                        "CONFIG_PRESET_OPERATOR_CLASSES",
                        "CHUNK_OPERATOR_CLASSES",
                        "CLEANUP_OPERATOR_CLASSES",
                        "HULL_IMPOSTOR_OPERATOR_CLASSES",
                        "LOD_OPERATOR_CLASSES",
                        "PBR_OPERATOR_CLASSES",
                        "PRESET_OPERATOR_CLASSES",
                    )
                )
                else []
            )
            for cls in cls_list:
                if isinstance(cls, type):
                    hints = typing.get_type_hints(cls)
                    assert isinstance(hints, dict)
                    tested += 1

    assert tested >= 100, f"Expected at least 100 operator classes evaluated, got {tested}"


def test_callbacks_target_engine_and_export_preset_sync(monkeypatch):
    """Verify bidirectional target_engine <-> pbr_export_preset synchronization and reentrancy guard."""
    import ui.properties.callbacks as cb

    monkeypatch.setattr(cb, "sync_export_maps_from_preset", MagicMock())
    monkeypatch.setattr(cb, "update_bridge_status_cached", MagicMock())

    props = MagicMock()
    props.target_engine = "MSFS_2024"
    props.pbr_export_preset = "unreal_engine_5"
    props.pbr_preset = "unreal_engine_5"
    props.pbr_export_texture_strategy = "SMART_AUTO"
    props.pbr_export_bit_depth = "8"
    props.pbr_export_naming_pattern = "{material}{suffix}"
    props.export_directory = ""

    # 1. Switching target_engine to MSFS_2024 updates pbr_export_preset to msfs_2024_comp
    cb.on_target_engine_updated(props, None)
    assert props.pbr_export_preset == "msfs_2024_comp"
    assert props.pbr_preset == "msfs_2024_comp"

    # 2. When StateRestorationGuard is active, on_target_engine_updated is a no-op for preset switching
    props.target_engine = "UE5"
    with StateRestorationGuard():
        cb.on_target_engine_updated(props, None)
    assert props.pbr_export_preset == "msfs_2024_comp"

    # 3. Switching pbr_export_preset to unity_hdrp_maskmap updates target_engine to UNITY_6
    monkeypatch.setattr(cb.PBRExportPresetManager, "set_last_active_preset", MagicMock())
    props.pbr_export_preset = "unity_hdrp_maskmap"
    cb.on_export_preset_updated(props, None)
    assert props.target_engine == "UNITY_6"


def test_callbacks_cow_export_setting_factory_vs_custom(monkeypatch):
    """Verify Copy-on-Write export setting duplicates factory presets and updates custom presets in-place."""
    import ui.properties.callbacks as cb

    dup_mock = MagicMock(return_value="unreal_engine_5_custom")
    save_mock = MagicMock()
    set_last_mock = MagicMock()
    monkeypatch.setattr(cb.PBRExportPresetManager, "duplicate_preset", dup_mock)
    monkeypatch.setattr(cb.PBRExportPresetManager, "save_custom_preset", save_mock)
    monkeypatch.setattr(cb.PBRExportPresetManager, "set_last_active_preset", set_last_mock)

    ctx = MagicMock()
    ctx.window_manager = MagicMock()
    props = MagicMock()

    # Negative boundary: missing window_manager or empty preset_id is a safe no-op
    cb._handle_cow_export_setting(props, None, "strategy", "CONVERT_PNG")
    dup_mock.assert_not_called()

    # Case 1: Factory preset triggers Copy-on-Write duplication
    props.pbr_export_preset = "unreal_engine_5"
    props.pbr_export_texture_strategy = "CONVERT_PNG"
    cb.on_export_strategy_updated(props, ctx)
    dup_mock.assert_called_once_with("unreal_engine_5", overrides={"strategy": "CONVERT_PNG"})
    assert props.pbr_export_preset == "unreal_engine_5_custom"

    # Case 2: Custom preset saves in-place without duplicating
    monkeypatch.setattr(cb.PBRExportPresetManager, "is_builtin", lambda pid: False)
    monkeypatch.setattr(
        cb.PBRExportPresetManager,
        "get_preset",
        lambda pid: {"name": "Custom", "strategy": "SMART_AUTO", "bit_depth": 8},
    )
    props.pbr_export_bit_depth = "16"
    cb.on_export_bit_depth_updated(props, ctx)
    save_mock.assert_called_once()
    saved_data = save_mock.call_args.args[0]
    assert saved_data["bit_depth"] == 16


def test_callbacks_asset_lod_state_cache_and_boundaries(monkeypatch):
    """Verify serialize_asset_lod_state and on_active_asset_updated cache roundtrip and AUTO/NONE boundaries."""
    import ui.properties.callbacks as cb

    cb._ASSET_LOD_STATE_CACHE.clear()
    cb._LAST_ACTIVE_ASSET_NAME = ""

    tier0 = MagicMock(
        lod_index=0,
        level_index=0,
        screen_size_pct=100.0,
        target_tris_pct=100.0,
        target_tris=5000,
        triangle_target=5000,
        is_impostor=False,
        last_baked_target_pct=100.0,
        last_baked_screen_pct=100.0,
        state="SOURCE",
        show_details=False,
    )
    tier0.name = "LOD0"
    tier1 = MagicMock(
        lod_index=1,
        level_index=1,
        screen_size_pct=42.5,
        target_tris_pct=37.0,
        target_tris=1850,
        triangle_target=1850,
        is_impostor=False,
        last_baked_target_pct=37.0,
        last_baked_screen_pct=42.5,
        state="BAKED",
        show_details=True,
    )
    tier1.name = "LOD1"

    props = MagicMock()
    props.lods = [tier0, tier1]

    # Negative boundary: AUTO, NONE, or empty asset_name must not pollute cache
    cb.serialize_asset_lod_state(props, "")
    cb.serialize_asset_lod_state(props, "AUTO")
    cb.serialize_asset_lod_state(props, "NONE")
    assert cb._ASSET_LOD_STATE_CACHE == {}

    # Valid asset serialization
    cb.serialize_asset_lod_state(props, "Cessna_172")
    assert "Cessna_172" in cb._ASSET_LOD_STATE_CACHE
    assert cb._ASSET_LOD_STATE_CACHE["Cessna_172"][1]["target_tris_pct"] == 37.0
    assert cb._ASSET_LOD_STATE_CACHE["Cessna_172"][1]["show_details"] is True

    # Switching active asset serializes previous asset and projects new asset
    proj_mock = MagicMock()
    monkeypatch.setattr(cb, "project_preset_tiers", proj_mock)
    props.export_base_name = "Cessna_172"
    props.active_asset = "Cessna_172_Interior"
    cb.on_active_asset_updated(props, None)
    proj_mock.assert_called_once_with(props, None, asset_name="Cessna_172_Interior")


def test_callbacks_virtual_distance_and_persist_helpers(monkeypatch):
    """Verify on_virtual_distance_updated and _persist_pipeline_prop respect simulator and restoration guards."""
    import core.simulator as sim_mod
    import ui.properties.callbacks as cb

    eval_mock = MagicMock(
        return_value={"root_name": "HeroProp", "current_tier": 2, "active_tris": 1250, "distance_m": 25.0}
    )
    monkeypatch.setattr(sim_mod.LODSimulatorEngine, "evaluate_distance_scrub", eval_mock)

    ctx = MagicMock()
    area_3d = MagicMock(type="VIEW_3D")
    ctx.screen.areas = [area_3d]
    props = MagicMock()
    props.is_simulator_running = True
    props.virtual_distance_override = 25.0
    ctx.scene.lod_tool = props

    # 1. While modal simulator is running, distance scrubber callback is suppressed
    cb.on_virtual_distance_updated(props, ctx)
    eval_mock.assert_not_called()

    # 2. When simulator is idle, distance scrubber evaluates and tags VIEW_3D redraw
    props.is_simulator_running = False
    cb.on_virtual_distance_updated(props, ctx)
    eval_mock.assert_called_once_with(ctx, 25.0, blend_data=ctx.blend_data)
    assert "HeroProp (LOD2, 1,250 tris, 25.0m)" in props.last_scrub_status
    area_3d.tag_redraw.assert_called_once()

    # 3. _persist_pipeline_prop skips persistence inside StateRestorationGuard
    persist_mock = MagicMock()
    monkeypatch.setattr(cb, "set_pipeline_setting", persist_mock)
    props.export_directory = "/tmp/out"
    with StateRestorationGuard():
        cb.on_export_directory_updated(props, ctx)
    persist_mock.assert_not_called()

    cb.on_import_directory_updated(props, ctx)
    persist_mock.assert_called_once()


def test_engine_import_preset_create_rename_and_autosave(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Verify EngineImportPresetManager create_new_preset, rename_custom_preset, and auto-save callback."""
    from core.engine_import_presets import EngineImportPresetManager
    import ui.properties.callbacks as cb

    monkeypatch.setattr(EngineImportPresetManager, "get_user_dir", classmethod(lambda cls: tmp_path))
    EngineImportPresetManager.load_presets(force_reload=True)

    new_id = EngineImportPresetManager.create_new_preset("My Aircraft Ingest", template_id="minimal")
    assert new_id == "my_aircraft_ingest"
    assert not EngineImportPresetManager.is_builtin(new_id)
    pdata = EngineImportPresetManager.get_preset(new_id)
    assert pdata["name"] == "My Aircraft Ingest"
    assert "description" not in pdata
    assert pdata["import_geometry"] is True
    assert pdata["import_lights"] is False

    # Test auto-save via on_engine_import_setting_updated
    props = MagicMock()
    props.engine_import_preset = new_id
    props.engine_import_geometry = True
    props.engine_import_spatial = True
    props.engine_import_lights = True
    props.engine_import_cameras = False
    props.engine_import_model_target = "BOTH_SEPARATE"
    props.engine_import_use_lod0_suffix = False
    props.engine_import_auto_assign_screen_pct = True
    props.engine_import_deduplicate_materials = True
    props.engine_import_reuse_master_rig = False

    cb.on_engine_import_setting_updated(props, None)
    updated_pdata = EngineImportPresetManager.get_preset(new_id)
    assert updated_pdata["import_lights"] is True
    assert updated_pdata["model_target"] == "BOTH_SEPARATE"
    assert updated_pdata["use_lod0_suffix"] is False

    # Rename custom preset
    renamed_id = EngineImportPresetManager.rename_custom_preset(new_id, "Renamed Ingest")
    assert renamed_id == "renamed_ingest"
    assert EngineImportPresetManager.get_preset(renamed_id)["name"] == "Renamed Ingest"

    # Negative: cannot rename built-in factory preset
    with pytest.raises(PermissionError, match="Cannot rename built-in factory preset"):
        EngineImportPresetManager.rename_custom_preset("msfs_2024_aircraft", "Forbidden")
