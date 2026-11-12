"""
UIList components for OmniMesh LOD tiers with responsive column layout.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    import bpy
    from bpy.types import UIList
else:
    try:
        import bpy
        from bpy.types import UIList
    except ImportError:
        bpy = None
        UIList = object


class OMNIMESH_UL_preset_maps(UIList):
    """Interactive list displaying PBR map definitions in the active preset."""

    def draw_item(
        self,
        context: Any,
        layout: Any,
        data: Any,
        item: Any,
        icon: Any,
        active_data: Any,
        active_property: Any,
        index: Any = 0,
        flt_flag: Any = 0,
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
        context: Any,
        layout: Any,
        data: Any,
        item: Any,
        icon: Any,
        active_data: Any,
        active_property: Any,
        index: Any = 0,
        flt_flag: Any = 0,
    ) -> None:
        if not item:
            return
        if self.layout_type in {"DEFAULT", "COMPACT"}:
            row = layout.row(align=True)

            # Column 1: Export toggle checkbox (~12% width)
            col_toggle = row.split(factor=0.12, align=True)
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

            # Column 2: Map Name + Icon (~65% of remainder)
            col_name = row.split(factor=0.65, align=True)
            col_name.label(text=getattr(item, "name", "Map"), icon=icon)

            # Column 3: Suffix badge (remainder)
            suffix = getattr(item, "export_suffix", "").strip()
            row.label(text=f"({suffix})" if suffix else "")


class OMNIMESH_UL_preset_tiers(UIList):
    """Interactive list displaying LOD tier curve templates in the active preset."""

    def draw_item(
        self,
        context: Any,
        layout: Any,
        data: Any,
        item: Any,
        icon: Any,
        active_data: Any,
        active_property: Any,
        index: Any = 0,
        flt_flag: Any = 0,
    ) -> None:
        if not item:
            return
        if self.layout_type in {"DEFAULT", "COMPACT"}:
            row = layout.row(align=True)

            tier_name = getattr(item, "name", f"LOD{index}")

            # Column 1: Tier Name (~28% width)
            col_name = row.split(factor=0.28, align=True)
            col_name.label(text=tier_name, icon="MESH_DATA")

            # Column 2: Screen Size % (~50% of remainder -> ~36% total)
            col_screen = row.split(factor=0.50, align=True)
            col_screen.prop(item, "screen_size_pct", text="", slider=True)

            # Column 3: Budget (% slider, remaining ~36% total)
            row.prop(item, "target_tris_pct", text="", slider=True)


classes = (
    OMNIMESH_UL_preset_maps,
    OMNIMESH_UL_export_preset_maps,
    OMNIMESH_UL_preset_tiers,
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
