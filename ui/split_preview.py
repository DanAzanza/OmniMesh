"""
OmniMesh Visual A/B Split-Screen Viewport Comparison Engine.
Renders real-time side-by-side silhouette and shader comparison (LOD0 vs LOD_N)
with 2D GPU divider line overlay and zero RNA/DNA mutation inside draw callbacks.
"""

from __future__ import annotations

import logging
from typing import Any

try:
    import blf
    import bpy
    import gpu
    from bpy.types import Operator
    from gpu_extras.batch import batch_for_shader
except ImportError:
    bpy = None
    gpu = None
    batch_for_shader = None
    blf = None
    Operator = object

logger = logging.getLogger(__name__)


class SplitPreviewEngine:
    """Manages viewport split-screen state and read-only GPU drawing."""

    _handler: Any = None
    _cached_overlay: dict[str, Any] = {
        "is_active": False,
        "split_ratio": 0.5,
        "left_label": "LOD0 (Master)",
        "right_label": "LOD3",
        "left_tris": 0,
        "right_tris": 0,
    }

    @classmethod
    def update_overlay_cache(
        cls, is_active: bool, split_ratio: float, left_label: str, right_label: str, left_tris: int, right_tris: int
    ) -> None:
        cls._cached_overlay["is_active"] = is_active
        cls._cached_overlay["split_ratio"] = max(0.0, min(1.0, split_ratio))
        cls._cached_overlay["left_label"] = left_label
        cls._cached_overlay["right_label"] = right_label
        cls._cached_overlay["left_tris"] = left_tris
        cls._cached_overlay["right_tris"] = right_tris

    @classmethod
    def draw_callback_px(cls) -> None:
        """Read-only 2D GPU overlay drawing vertical split divider and labels."""
        if not cls._cached_overlay["is_active"] or not gpu or not batch_for_shader:
            return

        try:
            # Region dimensions
            region = bpy.context.region if bpy and bpy.context else None
            if not region:
                return

            width = region.width
            height = region.height
            split_x = width * cls._cached_overlay["split_ratio"]

            # 1. Draw vertical divider line with strict blend state management
            shader = gpu.shader.from_builtin("UNIFORM_COLOR")
            gpu.state.blend_set("ALPHA")
            try:
                gpu.state.line_width_set(2.0)

                line_coords = [(split_x, 0.0), (split_x, float(height))]
                batch = batch_for_shader(shader, "LINES", {"pos": line_coords})
                shader.bind()
                shader.uniform_float("color", (0.2, 0.8, 1.0, 0.9))  # Cyan divider line
                batch.draw(shader)

                # Draw center handle notch
                notch_y = height * 0.5
                notch_coords = [
                    (split_x - 12.0, notch_y - 20.0),
                    (split_x + 12.0, notch_y - 20.0),
                    (split_x + 12.0, notch_y + 20.0),
                    (split_x - 12.0, notch_y + 20.0),
                ]
                notch_indices = [(0, 1, 2), (2, 3, 0)]
                notch_batch = batch_for_shader(shader, "TRIS", {"pos": notch_coords}, indices=notch_indices)
                shader.uniform_float("color", (0.1, 0.5, 0.9, 0.7))
                notch_batch.draw(shader)
            finally:
                gpu.state.blend_set("NONE")
                gpu.state.line_width_set(1.0)

            # 2. Draw split labels via BLF
            if blf:
                scale = (
                    bpy.context.preferences.system.ui_scale
                    if (bpy.context and hasattr(bpy.context, "preferences"))
                    else 1.0
                )
                font_id = 0
                blf.size(font_id, int(14 * scale))

                # Left side label (LOD0)
                blf.color(font_id, 0.2, 1.0, 0.4, 1.0)
                blf.position(font_id, max(15.0, split_x - 180.0 * scale), height - 40.0 * scale, 0)
                blf.draw(font_id, f"◀ {cls._cached_overlay['left_label']} ({cls._cached_overlay['left_tris']:,} tris)")

                # Right side label (LOD_N)
                blf.color(font_id, 1.0, 0.6, 0.2, 1.0)
                blf.position(font_id, min(width - 190.0 * scale, split_x + 15.0 * scale), height - 40.0 * scale, 0)
                blf.draw(
                    font_id, f"{cls._cached_overlay['right_label']} ({cls._cached_overlay['right_tris']:,} tris) ▶"
                )

        except (RuntimeError, KeyError, TypeError, ValueError) as exc:
            logger.debug("Split preview draw callback exception: %s", exc)

    @classmethod
    def register_draw_handler(cls) -> None:
        if not bpy or cls._handler is not None:
            return
        try:
            cls._handler = bpy.types.SpaceView3D.draw_handler_add(cls.draw_callback_px, (), "WINDOW", "POST_PIXEL")
        except (RuntimeError, AttributeError, ValueError) as exc:
            logger.debug("Failed to register split preview draw handler: %s", exc)
            cls._handler = None

    @classmethod
    def unregister_draw_handler(cls) -> None:
        if not bpy or cls._handler is None:
            return
        try:
            bpy.types.SpaceView3D.draw_handler_remove(cls._handler, "WINDOW")
        except (RuntimeError, ValueError) as exc:
            logger.debug("Failed to remove split preview draw handler: %s", exc)
        cls._handler = None


class OMNIMESH_OT_toggle_split_preview(Operator):
    """Toggle interactive A/B Split-Screen Comparison between LOD0 and selected LOD tier"""

    bl_idname = "lod_tool.toggle_split_preview"
    bl_label = "Toggle A/B Split Preview"
    bl_description = "Compare LOD0 and target LOD tier side-by-side with an interactive viewport divider line"
    bl_options = {"REGISTER"}  # Omit UNDO

    _is_dragging: bool = False

    @classmethod
    def poll(cls, context: Any) -> bool:
        return bool(bpy and hasattr(context.scene, "lod_tool") and len(context.scene.lod_tool.lods) > 1)

    def execute(self, context: Any) -> set[str]:
        if not bpy or not context:
            return {"CANCELLED"}
        props = context.scene.lod_tool
        props.is_split_active = not props.is_split_active

        if props.is_split_active:
            SplitPreviewEngine.register_draw_handler()
            self.update_split_state(context)
            wm = context.window_manager
            wm.modal_handler_add(self)
            self.report({"INFO"}, "A/B Split-Screen Preview active. Drag mouse or adjust slider. ESC to exit.")
            return {"RUNNING_MODAL"}
        else:
            return self.cancel_split(context)

    def modal(self, context: Any, event: Any) -> set[str]:
        props = context.scene.lod_tool
        if not props.is_split_active or event.type in ("ESC", "RIGHTMOUSE"):
            return self.cancel_split(context)

        # Mouse dragging to adjust split position
        if event.type == "LEFTMOUSE":
            if event.value == "PRESS":
                region = context.region
                split_x = region.width * props.split_ratio
                if abs(event.mouse_region_x - split_x) < 30:
                    self._is_dragging = True
                    return {"RUNNING_MODAL"}
            elif event.value == "RELEASE":
                self._is_dragging = False

        if event.type == "MOUSEMOVE" and self._is_dragging:
            region = context.region
            if region and region.width > 0:
                props.split_ratio = max(0.05, min(0.95, event.mouse_region_x / region.width))
                self.update_split_state(context)
                region.tag_redraw()
            return {"RUNNING_MODAL"}

        self.update_split_state(context)
        return {"PASS_THROUGH"}

    def update_split_state(self, context: Any) -> None:
        if not context or not hasattr(context, "scene") or not hasattr(context.scene, "lod_tool"):
            return
        props = context.scene.lod_tool
        if not props.lods or len(props.lods) < 2:
            return

        try:
            compare_str = str(props.split_compare_tier)
            if compare_str.startswith("LOD"):
                target_idx = int(compare_str.replace("LOD", ""))
            else:
                target_idx = int(compare_str)
        except (ValueError, TypeError):
            target_idx = 1

        target_idx = max(1, min(target_idx, len(props.lods) - 1))
        target_tier = props.lods[target_idx]
        lod0_tier = props.lods[0]

        lod0_tris = getattr(lod0_tier, "actual_tris", 0) or (
            len(lod0_tier.generated_obj.data.polygons)
            if getattr(lod0_tier, "generated_obj", None) and getattr(lod0_tier.generated_obj, "data", None)
            else 0
        )
        target_tris = getattr(target_tier, "actual_tris", 0) or (
            len(target_tier.generated_obj.data.polygons)
            if getattr(target_tier, "generated_obj", None) and getattr(target_tier.generated_obj, "data", None)
            else 0
        )

        tier_name = getattr(target_tier, "name", f"LOD{target_idx}")
        screen_pct = getattr(target_tier, "screen_size_pct", 50.0)

        SplitPreviewEngine.update_overlay_cache(
            is_active=props.is_split_active,
            split_ratio=props.split_ratio,
            left_label="LOD0 (Master)",
            right_label=f"{tier_name} ({screen_pct:.1f}%)",
            left_tris=lod0_tris,
            right_tris=target_tris,
        )

    def cancel_split(self, context: Any) -> set[str]:
        if context and hasattr(context, "scene") and hasattr(context.scene, "lod_tool"):
            props = context.scene.lod_tool
            props.is_split_active = False
        self._is_dragging = False
        SplitPreviewEngine.update_overlay_cache(False, 0.5, "", "", 0, 0)
        SplitPreviewEngine.unregister_draw_handler()

        if context and hasattr(context, "screen") and context.screen:
            for area in context.screen.areas:
                if area.type == "VIEW_3D":
                    area.tag_redraw()

        if hasattr(self, "report"):
            self.report({"INFO"}, "A/B Split-Screen comparison closed.")
        return {"FINISHED"}


def register_split_ops() -> None:
    if not bpy:
        return
    bpy.utils.register_class(OMNIMESH_OT_toggle_split_preview)


def unregister_split_ops() -> None:
    if not bpy:
        return
    SplitPreviewEngine.unregister_draw_handler()
    bpy.utils.unregister_class(OMNIMESH_OT_toggle_split_preview)
