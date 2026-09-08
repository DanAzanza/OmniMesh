"""
Viewport HUD and Statistics Overlay for OmniMesh & Real-Time Simulator.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

try:
    import blf
    import bpy
    import gpu
    from gpu_extras.batch import batch_for_shader
except ImportError:
    bpy = None
    gpu = None
    batch_for_shader = None
    blf = None


class LODViewportHUD:
    _handler = None
    _cached_data = {}
    _toast_message: str = ""
    _toast_time: float = 0.0
    _toast_duration: float = 3.5

    @classmethod
    def show_toast(cls, message: str, duration: float = 3.5) -> None:
        """Display a transient notification badge at the bottom of the 3D Viewport."""
        import time

        cls._toast_message = message
        cls._toast_time = time.time()
        cls._toast_duration = duration
        cls.tag_redraw()

        if bpy and hasattr(bpy, "app") and hasattr(bpy.app, "timers"):

            def _auto_dismiss() -> None:
                if cls._toast_message and time.time() - cls._toast_time >= cls._toast_duration:
                    cls.clear_toast()

            try:
                bpy.app.timers.register(_auto_dismiss, first_interval=duration + 0.05)
            except Exception as exc:
                logger.debug("Failed registering auto_dismiss timer: %s", exc)

    @classmethod
    def clear_toast(cls) -> None:
        """Dismiss the toast notification immediately."""
        if cls._toast_message:
            cls._toast_message = ""
            cls._toast_time = 0.0
            cls.tag_redraw()

    @classmethod
    def tag_redraw(cls) -> None:
        """Tag all 3D viewports for redraw."""
        if not bpy or not hasattr(bpy, "context"):
            return
        try:
            wm = getattr(bpy.context, "window_manager", None)
            if wm and hasattr(wm, "windows"):
                for window in wm.windows:
                    for area in getattr(getattr(window, "screen", None), "areas", []):
                        if getattr(area, "type", "") == "VIEW_3D":
                            area.tag_redraw()
        except Exception as exc:
            logger.debug("Failed tagging viewport redraw: %s", exc)

    @classmethod
    def update_cache(cls, context: Any) -> None:
        if not bpy or not context:
            return
        props = getattr(context.scene, "lod_tool", None)
        if not props or len(props.lods) == 0:
            cls._cached_data = {}
            return

        active_idx = max(0, min(props.active_lod_index, len(props.lods) - 1))
        active_tier = props.lods[active_idx]
        base_tris = props.lods[0].actual_tris or props.lods[0].target_tris or 1
        curr_tris = active_tier.actual_tris or active_tier.target_tris or 1
        reduction_pct = max(0.0, (1.0 - curr_tris / float(base_tris)) * 100.0)

        cls._cached_data = {
            "is_active": True,
            "engine": props.target_engine,
            "active_name": active_tier.name,
            "screen_pct": active_tier.screen_size_pct,
            "distance_m": active_tier.distance_m,
            "curr_tris": curr_tris,
            "base_tris": base_tris,
            "reduction_pct": reduction_pct,
            "mat_slots": active_tier.mat_slots_count,
            "is_simulating": False,
        }

    @classmethod
    def update_simulation_hud(
        cls,
        context: Any,
        mode: str,
        active_name: str,
        screen_pct: float,
        distance_m: float,
        active_tris: int,
        tracked_count: int,
    ) -> None:
        cls._cached_data = {
            "is_active": True,
            "is_simulating": True,
            "sim_mode": mode,
            "active_name": active_name,
            "screen_pct": screen_pct,
            "distance_m": distance_m,
            "curr_tris": active_tris,
            "tracked_count": tracked_count,
        }

    @classmethod
    def clear_simulation_hud(cls) -> None:
        if cls._cached_data:
            cls._cached_data["is_simulating"] = False

    @classmethod
    def _draw_toast_px(cls, scale: float) -> None:
        if not cls._toast_message or not blf or not gpu or not bpy:
            return
        try:
            font_id = 0
            text = cls._toast_message
            blf.size(font_id, int(12 * scale))
            dims = blf.dimensions(font_id, text)
            text_w = dims[0]
            text_h = dims[1]

            region = getattr(bpy.context, "region", None) if bpy.context else None
            reg_w = getattr(region, "width", 800)
            pad_x = int(14 * scale)
            pad_y = int(6 * scale)
            box_w = int(text_w + pad_x * 2)
            box_h = int(text_h + pad_y * 2)
            x_pos = int((reg_w - box_w) / 2)
            y_pos = int(25 * scale)

            vertices = (
                (x_pos, y_pos),
                (x_pos + box_w, y_pos),
                (x_pos, y_pos + box_h),
                (x_pos + box_w, y_pos + box_h),
            )
            indices = ((0, 1, 2), (2, 1, 3))
            shader = gpu.shader.from_builtin("UNIFORM_COLOR")
            batch = batch_for_shader(shader, "TRIS", {"pos": vertices}, indices=indices)

            gpu.state.blend_set("ALPHA")
            try:
                shader.bind()
                shader.uniform_float("color", (0.05, 0.08, 0.12, 0.88))
                batch.draw(shader)
            finally:
                gpu.state.blend_set("NONE")

            blf.position(font_id, x_pos + pad_x, y_pos + pad_y + int(1 * scale), 0)
            blf.color(font_id, 0.35, 0.95, 0.65, 1.0)
            blf.draw(font_id, text)
        except Exception as exc:
            logger.debug("Toast draw exception: %s", exc)

    @classmethod
    def draw_callback_px(cls) -> None:
        if not gpu or not blf or not bpy:
            return

        scale = (
            bpy.context.preferences.system.ui_scale if (bpy.context and hasattr(bpy.context, "preferences")) else 1.0
        )

        # 1. Draw transient toast notification at bottom of viewport
        if cls._toast_message:
            import time

            elapsed = time.time() - cls._toast_time
            if elapsed > cls._toast_duration:
                cls._toast_message = ""
            else:
                cls._draw_toast_px(scale)

        # 2. Draw persistent monitor HUD if active
        if not cls._cached_data or not cls._cached_data.get("is_active"):
            return

        # Check if HUD is toggled off in scene properties
        props = getattr(bpy.context.scene, "lod_tool", None) if (bpy.context and bpy.context.scene) else None
        if props and not getattr(props, "show_viewport_hud", True):
            return

        try:
            font_id = 0
            x_offset = int(40 * scale)
            y_offset = int(120 * scale)
            box_w = int(340 * scale)
            box_h = int(100 * scale)

            vertices = (
                (x_offset - 10, y_offset + 10),
                (x_offset + box_w, y_offset + 10),
                (x_offset - 10, y_offset - box_h),
                (x_offset + box_w, y_offset - box_h),
            )
            indices = ((0, 1, 2), (2, 1, 3))

            shader = gpu.shader.from_builtin("UNIFORM_COLOR")
            batch = batch_for_shader(shader, "TRIS", {"pos": vertices}, indices=indices)

            # GPU blend state management with strict try...finally guard
            gpu.state.blend_set("ALPHA")
            try:
                shader.bind()
                shader.uniform_float("color", (0.04, 0.07, 0.11, 0.88))
                batch.draw(shader)
            finally:
                gpu.state.blend_set("NONE")

            is_sim = cls._cached_data.get("is_simulating", False)

            if is_sim:
                blf.size(font_id, int(13 * scale))
                blf.color(font_id, 0.2, 1.0, 0.6, 1.0)
                blf.position(font_id, x_offset, int(y_offset - 15 * scale), 0)
                blf.draw(font_id, f"● OMNIMESH SIMULATOR ACTIVE ({cls._cached_data.get('sim_mode', 'LIVE')})")

                blf.size(font_id, int(11 * scale))
                blf.color(font_id, 1.0, 1.0, 1.0, 0.9)
                blf.position(font_id, x_offset, int(y_offset - 35 * scale), 0)
                blf.draw(
                    font_id,
                    f"Target: {cls._cached_data['active_name']}  (Screen: {cls._cached_data['screen_pct']:.1f}%)",
                )

                blf.position(font_id, x_offset, int(y_offset - 55 * scale), 0)
                blf.draw(
                    font_id,
                    f"Distance: {cls._cached_data['distance_m']:.1f}m | Assets: {cls._cached_data['tracked_count']}",
                )

                blf.color(font_id, 0.3, 0.9, 1.0, 1.0)
                blf.position(font_id, x_offset, int(y_offset - 75 * scale), 0)
                blf.draw(font_id, f"Active Geometry : {cls._cached_data['curr_tris']:,} tris")

            else:
                blf.size(font_id, int(13 * scale))
                blf.color(font_id, 0.2, 0.8, 1.0, 1.0)
                blf.position(font_id, x_offset, int(y_offset - 15 * scale), 0)
                blf.draw(font_id, f"OMNIMESH MONITOR ({cls._cached_data.get('engine', 'MSFS')})")

                blf.size(font_id, int(11 * scale))
                blf.color(font_id, 1.0, 1.0, 1.0, 0.9)
                blf.position(font_id, x_offset, int(y_offset - 35 * scale), 0)
                blf.draw(
                    font_id,
                    f"Active Tier: {cls._cached_data['active_name']}  (Screen: {cls._cached_data['screen_pct']:.1f}%)",
                )

                blf.position(font_id, x_offset, int(y_offset - 55 * scale), 0)
                blf.draw(
                    font_id,
                    f"Switch Dist: {cls._cached_data['distance_m']:.1f}m | Mat Slots: {cls._cached_data.get('mat_slots', 1)}",
                )

                blf.color(font_id, 0.3, 1.0, 0.4, 1.0)
                blf.position(font_id, x_offset, int(y_offset - 75 * scale), 0)
                blf.draw(
                    font_id,
                    f"Triangles  : {cls._cached_data['curr_tris']:,}  (-{cls._cached_data.get('reduction_pct', 0.0):.1f}%)",
                )
        except (RuntimeError, KeyError, TypeError, ValueError) as exc:
            logger.debug("HUD draw callback exception: %s", exc)

    @classmethod
    def register(cls) -> None:
        if not bpy:
            return
        if cls._handler is None:
            try:
                cls._handler = bpy.types.SpaceView3D.draw_handler_add(cls.draw_callback_px, (), "WINDOW", "POST_PIXEL")
            except (RuntimeError, AttributeError, ValueError) as exc:
                logger.debug("HUD register failed: %s", exc)
                cls._handler = None
        if hasattr(bpy.app, "handlers") and hasattr(bpy.app.handlers, "depsgraph_update_post"):
            if on_depsgraph_clear_toast not in bpy.app.handlers.depsgraph_update_post:
                bpy.app.handlers.depsgraph_update_post.append(on_depsgraph_clear_toast)

    @classmethod
    def unregister(cls) -> None:
        if not bpy:
            return
        if cls._handler is not None:
            try:
                bpy.types.SpaceView3D.draw_handler_remove(cls._handler, "WINDOW")
            except (RuntimeError, ValueError) as exc:
                logger.debug("HUD draw handler removal exception: %s", exc)
            cls._handler = None
        if hasattr(bpy.app, "handlers") and hasattr(bpy.app.handlers, "depsgraph_update_post"):
            if on_depsgraph_clear_toast in bpy.app.handlers.depsgraph_update_post:
                bpy.app.handlers.depsgraph_update_post.remove(on_depsgraph_clear_toast)


def on_depsgraph_clear_toast(scene: Any = None, depsgraph: Any = None) -> None:
    """Safely check if toast duration has expired upon depsgraph updates."""
    if LODViewportHUD._toast_message:
        import time

        if time.time() - LODViewportHUD._toast_time >= LODViewportHUD._toast_duration:
            LODViewportHUD.clear_toast()


if bpy and hasattr(bpy, "app") and hasattr(bpy.app, "handlers"):
    on_depsgraph_clear_toast = bpy.app.handlers.persistent(on_depsgraph_clear_toast)
