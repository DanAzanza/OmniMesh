"""
OmniMesh MSFS Configuration Settings Properties.
Maintains MSFS 2020 & 2024 flight model, lighting, cameras, options, and attached_objects.cfg path and status.
Kept in a dedicated submodule to enforce AGENTS.md < 750 LOC limit on settings.py.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

try:
    import bpy
    from bpy.props import BoolProperty, EnumProperty, FloatProperty, StringProperty
    from bpy.types import PropertyGroup
except ImportError:
    bpy = None
    PropertyGroup = object

    def _mock_prop(**kwargs: Any) -> Any:
        return None

    BoolProperty = EnumProperty = FloatProperty = StringProperty = _mock_prop

try:
    from .enums import MSFS_GEAR_STATE_ITEMS, MSFS_TARGET_VERSION_ITEMS
except (ImportError, ValueError):
    from ui.properties.enums import MSFS_GEAR_STATE_ITEMS, MSFS_TARGET_VERSION_ITEMS


class OMNIMESH_MSFSConfigSettings(PropertyGroup):
    """Configuration properties for MSFS 2020 & 2024 spatial, lights, cameras, and modular attachments."""

    # Package & Options
    export_full_package: BoolProperty(name="Export Full Package", default=True)
    target_version: EnumProperty(name="Target Version", items=MSFS_TARGET_VERSION_ITEMS, default="2024")
    with_exterior_show_interior: BoolProperty(name="Show Interior with Exterior", default=True)
    with_exterior_show_interior_hide_first_lod: BoolProperty(name="Hide First LOD Int", default=False)
    with_interior_force_first_lod: BoolProperty(name="Force First LOD Int", default=False)
    with_interior_show_exterior: BoolProperty(name="Show Exterior with Interior", default=True)
    preserve_decals: BoolProperty(name="Preserve Decals", default=True)

    # Spatial & Flight Model
    spatial_cfg_path: StringProperty(name="Flight Model", subtype="FILE_PATH", default="")
    systems_cfg_path: StringProperty(name="Systems / Lights", subtype="FILE_PATH", default="")
    cameras_cfg_path: StringProperty(name="Cameras", subtype="FILE_PATH", default="")
    spatial_status: StringProperty(name="Status", default="Ready")
    scrape_margin_m: FloatProperty(name="Scrape Margin (m)", default=0.0, min=-0.5, max=0.5)
    gear_state: EnumProperty(name="Gear State", items=MSFS_GEAR_STATE_ITEMS, default="STATIC_COMPRESSED")
    gear_compression_m: FloatProperty(name="Strut Compression (m)", default=0.12, min=0.0, max=1.0)
    calculated_cg_height_ft: FloatProperty(name="Static CG Height (ft)", default=0.0, precision=3)

    # Modular Attachments & Submodels (MSFS 2024 attached_objects.cfg)
    attached_objects_cfg_path: StringProperty(name="attached_objects.cfg", subtype="FILE_PATH", default="")
    auto_parent_to_socket: BoolProperty(name="Auto-Parent Sockets", default=True)
    show_submodel_previews: BoolProperty(name="Show Previews", default=False)
    attachment_status: StringProperty(name="Attachment Status", default="Ready")


def register():
    if bpy and hasattr(bpy.utils, "register_class"):
        try:
            bpy.utils.register_class(OMNIMESH_MSFSConfigSettings)
        except Exception as exc:
            logger.debug("Register skipped OMNIMESH_MSFSConfigSettings: %s", exc)


def unregister():
    if bpy and hasattr(bpy.utils, "unregister_class"):
        try:
            bpy.utils.unregister_class(OMNIMESH_MSFSConfigSettings)
        except Exception as exc:
            logger.debug("Unregister skipped OMNIMESH_MSFSConfigSettings: %s", exc)


__all__ = ["OMNIMESH_MSFSConfigSettings", "register", "unregister"]
