"""
Viewport HUD and Statistics Overlay for OmniMesh & Real-Time Simulator.
"""

from __future__ import annotations

from typing import Any

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

    @classmethod
    def update_cache(cls, context):
        if not bpy or not context:
            return
        props = getattr(context.scene, "lod_tool", None)
        if not props or len(props.lods) == 0:
            cls._cached_data = {}
            return

        active_tier = props.lods[props.active_lod_index] if props.active_lod_index < len(props.lods) else props.lods[0]
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
    ):
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
    def clear_simulation_hud(cls):
        if cls._cached_data:
            cls._cached_data["is_simulating"] = False

    @classmethod
    def draw_callback_px(cls):
        if not cls._cached_data or not cls._cached_data.get("is_active") or not gpu or not blf:
            return

        font_id = 0
        x_offset = 40
        y_offset = 120
        box_w = 340
        box_h = 100

        vertices = (
            (x_offset - 10, y_offset + 10),
            (x_offset + box_w, y_offset + 10),
            (x_offset - 10, y_offset - box_h),
            (x_offset + box_w, y_offset - box_h),
        )
        indices = ((0, 1, 2), (2, 1, 3))

        shader = gpu.shader.from_builtin("UNIFORM_COLOR")
        batch = batch_for_shader(shader, "TRIS", {"pos": vertices}, indices=indices)

        gpu.state.blend_set("ALPHA")
        shader.bind()
        shader.uniform_float("color", (0.04, 0.07, 0.11, 0.88))
        batch.draw(shader)
        gpu.state.blend_set("NONE")

        is_sim = cls._cached_data.get("is_simulating", False)

        if is_sim:
            blf.size(font_id, 13)
            blf.color(font_id, 0.2, 1.0, 0.6, 1.0)
            blf.position(font_id, x_offset, y_offset - 15, 0)
            blf.draw(font_id, f"● OMNIMESH SIMULATOR ACTIVE ({cls._cached_data.get('sim_mode', 'LIVE')})")

            blf.size(font_id, 11)
            blf.color(font_id, 1.0, 1.0, 1.0, 0.9)
            blf.position(font_id, x_offset, y_offset - 35, 0)
            blf.draw(
                font_id, f"Target: {cls._cached_data['active_name']}  (Screen: {cls._cached_data['screen_pct']:.1f}%)"
            )

            blf.position(font_id, x_offset, y_offset - 55, 0)
            blf.draw(
                font_id,
                f"Distance: {cls._cached_data['distance_m']:.1f}m | Assets: {cls._cached_data['tracked_count']}",
            )

            blf.color(font_id, 0.3, 0.9, 1.0, 1.0)
            blf.position(font_id, x_offset, y_offset - 75, 0)
            blf.draw(font_id, f"Active Geometry : {cls._cached_data['curr_tris']:,} tris")

        else:
            blf.size(font_id, 13)
            blf.color(font_id, 0.2, 0.8, 1.0, 1.0)
            blf.position(font_id, x_offset, y_offset - 15, 0)
            blf.draw(font_id, f"OMNIMESH MONITOR ({cls._cached_data.get('engine', 'MSFS')})")

            blf.size(font_id, 11)
            blf.color(font_id, 1.0, 1.0, 1.0, 0.9)
            blf.position(font_id, x_offset, y_offset - 35, 0)
            blf.draw(
                font_id,
                f"Active Tier: {cls._cached_data['active_name']}  (Screen: {cls._cached_data['screen_pct']:.1f}%)",
            )

            blf.position(font_id, x_offset, y_offset - 55, 0)
            blf.draw(
                font_id,
                f"Switch Dist: {cls._cached_data['distance_m']:.1f}m | Mat Slots: {cls._cached_data.get('mat_slots', 1)}",
            )

            blf.color(font_id, 0.3, 1.0, 0.4, 1.0)
            blf.position(font_id, x_offset, y_offset - 75, 0)
            blf.draw(
                font_id,
                f"Triangles  : {cls._cached_data['curr_tris']:,}  (-{cls._cached_data.get('reduction_pct', 0.0):.1f}%)",
            )

    @classmethod
    def register(cls):
        if not bpy:
            return
        if cls._handler is None:
            cls._handler = bpy.types.SpaceView3D.draw_handler_add(cls.draw_callback_px, (), "WINDOW", "POST_PIXEL")

    @classmethod
    def unregister(cls):
        if not bpy:
            return
        if cls._handler is not None:
            bpy.types.SpaceView3D.draw_handler_remove(cls._handler, "WINDOW")
            cls._handler = None
