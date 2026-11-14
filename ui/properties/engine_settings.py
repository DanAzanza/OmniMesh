# pyright: reportInvalidTypeForm=none
"""
OmniMesh MSFS & Engine Import PropertyGroup Mixin.
"""

from typing import TYPE_CHECKING

from . import callbacks, enums

if TYPE_CHECKING:
    from bpy.props import BoolProperty, EnumProperty, FloatProperty, StringProperty
else:
    try:
        from bpy.props import BoolProperty, EnumProperty, FloatProperty, StringProperty
    except ImportError:
        from ..rna_helpers import mock_prop

        BoolProperty = EnumProperty = FloatProperty = StringProperty = mock_prop


class LODToolEngineSettingsMixin:
    """MSFS export/legacy and Engine Import properties mixed into LODToolSettings."""

    # MSFS Package & Export Settings
    msfs_export_full_package: BoolProperty(
        name="Export Full Package",
        default=True,
        description="Write complete MSFS 2024 package files (model XML, glTF tiers, and textures) rather than glTF geometry only",
    )
    msfs_target_version: EnumProperty(
        name="MSFS Target Version",
        items=enums.MSFS_TARGET_VERSION_ITEMS,
        default="2024",
        description="Target Microsoft Flight Simulator XML and package format version",
    )
    msfs_with_exterior_show_interior: BoolProperty(
        name="Show Interior with Exterior", default=True, description="Render interior when viewing exterior model"
    )
    msfs_with_exterior_show_interior_hide_first_lod: BoolProperty(
        name="Hide First LOD of Interior", default=False, description="Hide LOD0 interior when viewing exterior"
    )
    msfs_with_interior_force_first_lod: BoolProperty(
        name="Force First LOD Interior", default=False, description="Render interior at LOD0 in cockpit"
    )
    msfs_with_interior_show_exterior: BoolProperty(
        name="Show Exterior with Interior", default=True, description="Render exterior when inside cockpit"
    )
    msfs_preserve_decals: BoolProperty(
        name="Preserve Decals", default=True, description="Constrain decimation on decal meshes"
    )

    # Legacy MSFS properties preserved for API compatibility
    msfs_spatial_cfg_path: StringProperty(
        name="MSFS Flight Model File",
        subtype="FILE_PATH",
        default="",
        options={"PATH_SUPPORTS_BLEND_RELATIVE"},
    )
    msfs_systems_cfg_path: StringProperty(
        name="MSFS Systems File",
        subtype="FILE_PATH",
        default="",
        options={"PATH_SUPPORTS_BLEND_RELATIVE"},
    )
    msfs_cameras_cfg_path: StringProperty(
        name="MSFS Cameras File",
        subtype="FILE_PATH",
        default="",
        options={"PATH_SUPPORTS_BLEND_RELATIVE"},
    )
    msfs_spatial_status: StringProperty(name="MSFS Spatial Status", default="Ready")
    msfs_scrape_margin_m: FloatProperty(name="Scrape Margin (m)", default=0.0, min=-0.5, max=0.5)
    msfs_gear_state: EnumProperty(name="Gear State", items=enums.MSFS_GEAR_STATE_ITEMS, default="STATIC_COMPRESSED")
    msfs_gear_compression_m: FloatProperty(name="Strut Compression (m)", default=0.12, min=0.0, max=1.0)
    msfs_calculated_cg_height_ft: FloatProperty(name="Static CG Height (ft)", default=0.0, precision=3)

    # Engine / Project Importer Properties
    engine_import_preset: EnumProperty(
        name="Engine Import Preset",
        items=callbacks.get_engine_import_preset_items,
        description="Active import template",
        update=callbacks.on_engine_import_preset_updated,
    )
    engine_import_directory: StringProperty(
        name="Engine Project Path",
        subtype="DIR_PATH",
        default="",
        options={"PATH_SUPPORTS_BLEND_RELATIVE"},
        description="Root folder of project to ingest",
        update=callbacks.on_engine_import_directory_updated,
    )
    engine_import_geometry: BoolProperty(
        name="Import Geometry & LODs",
        default=True,
        description="Import LOD mesh files (glTF/GLB) found in the engine project folder",
        update=callbacks.on_engine_import_setting_updated,
    )
    engine_import_spatial: BoolProperty(
        name="Import Spatial Markers",
        default=True,
        description="Import spatial datum, contact points, wheels, and fuel tanks from flight_model.cfg",
        update=callbacks.on_engine_import_setting_updated,
    )
    engine_import_lights: BoolProperty(
        name="Import Lights",
        default=True,
        description="Import [LIGHTS] definitions from systems.cfg or light.cfg as Blender Point/Spot lights",
        update=callbacks.on_engine_import_setting_updated,
    )
    engine_import_cameras: BoolProperty(
        name="Import Cameras",
        default=True,
        description="Import pilot, cockpit, and external camera views from cameras.cfg as Blender cameras",
        update=callbacks.on_engine_import_setting_updated,
    )
    engine_import_model_target: EnumProperty(
        name="Model Target",
        items=enums.ENGINE_IMPORT_MODEL_TARGET_ITEMS,
        default="EXTERIOR_ONLY",
        description="Select which MSFS model XML target set (exterior, interior, or both) to import",
        update=callbacks.on_engine_import_setting_updated,
    )
    engine_import_use_lod0_suffix: BoolProperty(
        name="Use LOD0 Suffix",
        default=True,
        description="Place imported LOD0 meshes into the standard {AssetName}_LOD0 sub-collection",
        update=callbacks.on_engine_import_setting_updated,
    )
    engine_import_auto_assign_screen_pct: BoolProperty(
        name="Auto-Assign Screen %",
        default=True,
        description="Map MSFS XML minSize values directly to OmniMesh LOD screen-size percentages",
        update=callbacks.on_engine_import_setting_updated,
    )
    engine_import_deduplicate_materials: BoolProperty(
        name="Deduplicate Materials",
        default=True,
        description="Reuse and deduplicate matching materials across imported LOD tiers",
        update=callbacks.on_engine_import_setting_updated,
    )
    engine_import_reuse_master_rig: BoolProperty(
        name="Reuse Master Armature",
        default=True,
        description="Bind imported skinned LOD meshes to a shared master Armature instead of duplicating rigs",
        update=callbacks.on_engine_import_setting_updated,
    )
    last_engine_import_summary: StringProperty(name="Last Import Summary", default="")


__all__ = ["LODToolEngineSettingsMixin"]
