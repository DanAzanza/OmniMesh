"""
UIList components for OmniMesh LOD tiers with responsive column layout.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

try:
    import bpy
    from bpy.types import UIList
except ImportError:
    bpy = None
    UIList = object


class LOD_UL_tier_list(UIList):
    """Responsive 3-column UIList for LOD tiers."""

    def draw_item(
        self,
        context: Any,
        layout: Any,
        data: Any,
        item: Any,
        icon: Any,
        active_data: Any,
        active_propname: Any,
        index: int = 0,
        flt_flag: int = 0,
    ) -> None:
        if self.layout_type in {"DEFAULT", "COMPACT"}:
            row = layout.row(align=True)

            # Column 1: LOD Tier Badge & Mesh Icon (~30% width)
            col_lod = row.split(factor=0.30, align=True)
            col_lod.label(text=f"LOD{item.lod_index}", icon="MESH_DATA")

            # Column 2: Screen Size Percentage (~35% width)
            col_pct = col_lod.split(factor=0.50, align=True)
            col_pct.prop(item, "screen_size_pct", text="", emboss=False)

            # Column 3: Triangle Count badge (~35% width)
            if item.actual_tris > 0:
                tris_label = f"{item.actual_tris:,} tris"
            else:
                tris_label = f"~{item.target_tris:,} tris"
            col_pct.label(text=tris_label)


class OMNIMESH_UL_preset_maps(UIList):
    """Interactive list displaying PBR map definitions in the active preset."""

    def draw_item(
        self,
        _context: Any,
        layout: Any,
        _data: Any,
        item: Any,
        _icon: Any,
        _active_data: Any,
        _active_propname: Any,
        _index: int = 0,
        _flt_flag: int = 0,
    ) -> None:
        if not item:
            return
        if self.layout_type in {"DEFAULT", "COMPACT"}:
            row = layout.row(align=True)
            is_normal = getattr(item, "is_normal_map", False)
            color_space = getattr(item, "color_space", "Non-Color")
            is_packed = getattr(item, "is_packed", False)

            if is_normal:
                icon = "SNAP_NORMAL"
            elif is_packed:
                icon = "IMAGE_RGB_ALPHA"
            elif color_space == "sRGB":
                icon = "COLOR"
            else:
                icon = "IMAGE_DATA"

            col_name = row.split(factor=0.55, align=True)
            col_name.label(text=getattr(item, "name", "Map"), icon=icon)

            suffixes = getattr(item, "suffixes_str", "").strip()
            if suffixes:
                s_list = [s.strip() for s in suffixes.split(",") if s.strip()]
                if len(s_list) <= 2:
                    abbr = ", ".join(s_list)
                else:
                    abbr = f"{s_list[0]}, {s_list[1]} (+{len(s_list) - 2})"
                col_name.label(text=f"({abbr})")
            else:
                col_name.label(text="")


class OMNIMESH_UL_export_preset_maps(UIList):
    """Interactive list displaying PBR map rules in the active export preset."""

    def draw_item(
        self,
        _context: Any,
        layout: Any,
        _data: Any,
        item: Any,
        _icon: Any,
        _active_data: Any,
        _active_propname: Any,
        _index: int = 0,
        _flt_flag: int = 0,
    ) -> None:
        if not item:
            return
        if self.layout_type in {"DEFAULT", "COMPACT"}:
            row = layout.row(align=True)

            # Column 1: Export toggle checkbox (~15% width)
            col_toggle = row.split(factor=0.15, align=True)
            col_toggle.prop(item, "export", text="")

            is_normal = getattr(item, "is_normal_map", False)
            color_space = getattr(item, "color_space", "Non-Color")
            is_packed = getattr(item, "is_packed", False)

            if is_normal:
                icon = "SNAP_NORMAL"
            elif is_packed:
                icon = "IMAGE_RGB_ALPHA"
            elif color_space == "sRGB":
                icon = "COLOR"
            else:
                icon = "IMAGE_DATA"

            # Column 2: Map Name + Icon (~60% of remainder)
            col_name = col_toggle.split(factor=0.60, align=True)
            col_name.label(text=getattr(item, "name", "Map"), icon=icon)

            # Column 3: Suffix badge
            suffix = getattr(item, "export_suffix", "").strip()
            col_name.label(text=f"({suffix})" if suffix else "")


classes = (
    LOD_UL_tier_list,
    OMNIMESH_UL_preset_maps,
    OMNIMESH_UL_export_preset_maps,
)


def register_lists() -> None:
    if not bpy:
        return
    for cls in classes:
        existing = getattr(bpy.types, cls.__name__, None)
        if existing is not None:
            try:
                bpy.utils.unregister_class(existing)
            except Exception as exc:
                logger.debug("Safe unregister skipped %s: %s", cls.__name__, exc)
        try:
            bpy.utils.register_class(cls)
        except Exception as exc:
            logger.warning("Could not register %s: %s", cls.__name__, exc)


def unregister_lists() -> None:
    if not bpy:
        return
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
