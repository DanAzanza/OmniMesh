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


classes = (LOD_UL_tier_list,)


def register_lists() -> None:
    if not bpy:
        return
    for cls in classes:
        try:
            bpy.utils.unregister_class(cls)
        except Exception as exc:
            logger.debug("Safe unregister skipped %s: %s", getattr(cls, "__name__", "cls"), exc)
        bpy.utils.register_class(cls)


def unregister_lists() -> None:
    if not bpy:
        return
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
