"""
OmniMesh MSFS Spatial, Lighting & Modular Attachments Panel.
Extracting MSFS subpanels to dedicated file enforces AGENTS.md < 750 LOC rule on ui/panel.py.
"""

from __future__ import annotations

import logging
from typing import Any

try:
    import bpy
    from bpy.types import Panel
except ImportError:
    bpy = None
    Panel = object

logger = logging.getLogger(__name__)


class OMNIMESH_PT_export_msfs_spatial(Panel):
    """Subpanel: MSFS 2020 & 2024 Aircraft Spatial Configuration (Contact Points, Fuel, Lights, Cameras, Attachments)."""

    bl_label = "MSFS Spatial, Lights & Attachments"
    bl_idname = "OMNIMESH_PT_export_msfs_spatial"
    bl_parent_id = "OMNIMESH_PT_export"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "OmniMesh"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context: Any) -> None:
        if not bpy or not context:
            return
        layout = self.layout
        props = context.scene.lod_tool
        msfs_cfg = getattr(props, "msfs_configs", None)

        # 1. Flight Model (Points & Tanks)
        box_fm = layout.box()
        box_fm.label(text="Flight Model (Points & Tanks)", icon="SNAP_NORMAL")
        box_fm.use_property_split = True
        box_fm.use_property_decorate = False
        box_fm.prop(props, "msfs_spatial_cfg_path", text="flight_model.cfg")

        row_fm = box_fm.row(align=True)
        row_fm.use_property_split = False
        row_fm.scale_y = 1.15
        row_fm.operator("omnimesh.import_msfs_spatial", text="Import Points", icon="IMPORT")
        row_sync = row_fm.row(align=True)
        row_sync.enabled = bool(props.msfs_spatial_cfg_path)
        row_sync.operator("omnimesh.export_msfs_spatial", text="Sync to CFG", icon="FILE_REFRESH")

        # 2. Lighting (systems.cfg / light.cfg)
        box_light = layout.box()
        box_light.label(text="Aircraft Lighting", icon="LIGHT")
        box_light.use_property_split = True
        box_light.use_property_decorate = False
        box_light.prop(props, "msfs_systems_cfg_path", text="systems.cfg")

        row_lt = box_light.row(align=True)
        row_lt.use_property_split = False
        row_lt.scale_y = 1.15
        row_lt.operator("omnimesh.import_msfs_lights", text="Import Lights", icon="LIGHT_SUN")
        row_sync_lt = row_lt.row(align=True)
        row_sync_lt.enabled = bool(getattr(props, "msfs_systems_cfg_path", ""))
        row_sync_lt.operator("omnimesh.export_msfs_lights", text="Sync Lights", icon="FILE_REFRESH")

        # 3. Spatial Alignment Tools (Mirror & Snap)
        box_tools = layout.box()
        box_tools.label(text="Spatial Alignment Tools", icon="ORIENTATION_GIMBAL")
        row_tools = box_tools.row(align=True)
        row_tools.use_property_split = False
        row_tools.scale_y = 1.1
        row_tools.operator("omnimesh.mirror_msfs_marker", text="Mirror (L <-> R)", icon="MOD_MIRROR")
        row_tools.operator("omnimesh.snap_msfs_point_to_vertex", text="Snap to Vertex", icon="SNAP_VERTEX")

        # 4. Geometry & Ground Alignment (Auto Scrape & Static CG Height)
        box_geo = layout.box()
        box_geo.label(text="Geometry & Ground Alignment", icon="MOD_PHYSICS")
        box_geo.use_property_split = True
        box_geo.use_property_decorate = False

        box_geo.prop(props, "msfs_scrape_margin_m", text="Scrape Margin")
        row_scrape = box_geo.row(align=True)
        row_scrape.use_property_split = False
        row_scrape.scale_y = 1.15
        row_scrape.operator(
            "omnimesh.generate_msfs_scrape_points", text="Auto-Detect Scrape Points", icon="FORCE_CHARGE"
        )

        box_geo.prop(props, "msfs_gear_state", text="Gear State")
        if props.msfs_gear_state == "UNCOMPRESSED_EXTENDED":
            box_geo.prop(props, "msfs_gear_compression_m", text="Strut Deflection")

        row_gear = box_geo.row(align=True)
        row_gear.use_property_split = False
        row_gear.scale_y = 1.15
        row_gear.operator("omnimesh.align_gear_ground_level", text="Align Gear & Calc CG Height", icon="EMPTY_AXIS")

        if getattr(props, "msfs_calculated_cg_height_ft", 0.0) > 0.0:
            row_cg = box_geo.row(align=True)
            row_cg.use_property_split = True
            row_cg.enabled = False
            row_cg.prop(props, "msfs_calculated_cg_height_ft", text="Static CG Height")

        # 5. Aircraft Cameras (cameras.cfg)
        box_cam = layout.box()
        box_cam.label(text="Aircraft Cameras (Cockpit & External)", icon="CAMERA_DATA")
        box_cam.use_property_split = True
        box_cam.use_property_decorate = False
        box_cam.prop(props, "msfs_cameras_cfg_path", text="cameras.cfg")

        row_cam = box_cam.row(align=True)
        row_cam.use_property_split = False
        row_cam.scale_y = 1.15
        row_cam.operator("omnimesh.import_msfs_cameras", text="Import Cameras", icon="IMPORT")
        row_sync_cam = row_cam.row(align=True)
        row_sync_cam.enabled = bool(getattr(props, "msfs_cameras_cfg_path", ""))
        row_sync_cam.operator("omnimesh.export_msfs_cameras", text="Sync Cameras", icon="FILE_REFRESH")

        # Camera viewport tools
        row_cam_tools = box_cam.row(align=True)
        row_cam_tools.use_property_split = False
        row_cam_tools.scale_y = 1.1
        row_cam_tools.operator("omnimesh.look_through_msfs_camera", text="Look Through", icon="VIEW_CAMERA")
        row_cam_tools.operator("omnimesh.restore_scene_camera", text="Restore View", icon="LOOP_BACK")
        row_cam_tools.operator("omnimesh.align_msfs_camera_to_view", text="Align to View", icon="CON_CAMERATARGET")

        # Cockpit Bank indicator
        active_obj = getattr(context, "active_object", None)
        if active_obj and active_obj.get("msfs_camera_category") == "Cockpit":
            box_note = box_cam.box()
            box_note.label(text="Cockpit camera: Roll/Bank is ignored by MSFS engine", icon="INFO")

        # 6. MSFS 2024 Modular Attachments & Submodels (attached_objects.cfg)
        box_att = layout.box()
        box_att.label(text="MSFS 2024 Modular Attachments", icon="HOOK")
        box_att.use_property_split = True
        box_att.use_property_decorate = False

        if msfs_cfg:
            box_att.prop(msfs_cfg, "attached_objects_cfg_path", text="attached_objects.cfg")
            box_att.prop(msfs_cfg, "auto_parent_to_socket", text="Auto-Parent Sockets")

        row_att = box_att.row(align=True)
        row_att.use_property_split = False
        row_att.scale_y = 1.15
        row_att.operator("omnimesh.import_msfs_attachments", text="Import Attachments", icon="IMPORT")
        row_sync_att = row_att.row(align=True)
        row_sync_att.enabled = bool(msfs_cfg and msfs_cfg.attached_objects_cfg_path)
        row_sync_att.operator("omnimesh.export_msfs_attachments", text="Sync to CFG", icon="FILE_REFRESH")

        row_add_att = box_att.row(align=True)
        row_add_att.use_property_split = False
        row_add_att.scale_y = 1.1
        row_add_att.operator("omnimesh.add_msfs_attachment", text="Add Attachment Hotspot", icon="PLUS")

        if msfs_cfg and msfs_cfg.attachment_status:
            box_att_stat = box_att.box()
            box_att_stat.label(text=msfs_cfg.attachment_status, icon="INFO")

        if props.msfs_spatial_status:
            box_status = layout.box()
            box_status.label(text=props.msfs_spatial_status, icon="INFO")


def register():
    if bpy and hasattr(bpy.utils, "register_class"):
        try:
            bpy.utils.register_class(OMNIMESH_PT_export_msfs_spatial)
        except Exception as exc:
            logger.debug("Register skipped for OMNIMESH_PT_export_msfs_spatial: %s", exc)


def unregister():
    if bpy and hasattr(bpy.utils, "unregister_class"):
        try:
            bpy.utils.unregister_class(OMNIMESH_PT_export_msfs_spatial)
        except Exception as exc:
            logger.debug("Unregister skipped for OMNIMESH_PT_export_msfs_spatial: %s", exc)


__all__ = ["OMNIMESH_PT_export_msfs_spatial", "register", "unregister"]
