"""
Modal Operators and Live Handlers for Viewport LOD Simulator.
"""

from __future__ import annotations

import logging
import math
from typing import Any

logger = logging.getLogger(__name__)

try:
    import bpy
    from bpy.types import Operator
except ImportError:
    bpy = None
    Operator = object

try:
    from ..core.simulator import LODSimulatorEngine, extract_viewport_camera_params
    from .hud import LODViewportHUD
except (ImportError, ValueError):
    from core.simulator import LODSimulatorEngine, extract_viewport_camera_params
    from ui.hud import LODViewportHUD


class LOD_OT_toggle_simulator(Operator):
    """Start or Stop Real-Time LOD Simulation in 3D Viewport"""

    bl_idname = "lod_tool.toggle_simulator"
    bl_label = "Toggle LOD Simulator"
    bl_options = {"REGISTER"}  # Omit UNDO for modal execution

    _timer: Any = None
    _is_running: bool = False

    @classmethod
    def poll(cls, context: Any) -> bool:
        return bool(bpy and context and hasattr(context.scene, "lod_tool"))

    def modal(self, context: Any, event: Any) -> set[str]:
        props = getattr(context.scene, "lod_tool", None) if (context and context.scene) else None
        if not props or not self._is_running:
            return self.cancel_simulation(context)

        if not props.is_simulator_active and not props.is_simulator_running:
            return self.cancel_simulation(context)

        if event.type in {"ESC", "RIGHTMOUSE"} and event.value == "PRESS":
            return self.cancel_simulation(context)

        if event.type == "TIMER":
            try:
                self.tick_simulation(context, props)
            except Exception as exc:
                logger.debug("Simulation tick exception: %s", exc)
                return self.cancel_simulation(context)

        return {"PASS_THROUGH"}

    def tick_simulation(self, context: Any, props: Any) -> None:
        if not context or not context.window_manager:
            return

        space_3d = None
        region_3d = None
        region = None

        if hasattr(context.window_manager, "windows"):
            for window in context.window_manager.windows:
                if not window.screen:
                    continue
                for area in window.screen.areas:
                    if area.type == "VIEW_3D":
                        for space in area.spaces:
                            if space.type == "VIEW_3D":
                                space_3d = space
                                region_3d = getattr(space, "region_3d", None)
                                for reg in area.regions:
                                    if reg.type == "WINDOW":
                                        region = reg
                                        break
                        if space_3d:
                            break
                if space_3d:
                    break

        cam_pos, fov_v, is_persp = extract_viewport_camera_params(space_3d, region_3d, region, context.scene)

        virtual_override = None
        if getattr(props, "virtual_distance_override", 0.0) > 0.0:
            virtual_dist = props.virtual_distance_override
            # Convert virtual distance to equivalent screen size percentage
            radius = 1.0
            tracked = LODSimulatorEngine.get_tracked_assets()
            if tracked:
                first_record = next(iter(tracked.values()))
                radius = getattr(first_record, "radius", 1.0)
            s_frac = (
                radius / max(0.001, virtual_dist * math.tan(fov_v / 2.0))
                if is_persp
                else (2.0 * radius) / max(0.01, fov_v)
            )
            virtual_override = min(100.0, max(0.01, s_frac * 100.0))
        elif getattr(props, "simulator_camera_mode", "VIEWPORT") == "ACTIVE_SCENE" and context.scene.camera:
            cam_pos = context.scene.camera.matrix_world.translation.copy()

        updates = LODSimulatorEngine.update_simulation_tick(
            context, cam_pos=cam_pos, fov_v_rad=fov_v, is_perspective=is_persp, virtual_override_pct=virtual_override
        )

        if updates:
            primary = updates[0]
            mode_tag = "VIRTUAL" if virtual_override is not None else getattr(props, "simulator_camera_mode", "LIVE")
            LODViewportHUD.update_simulation_hud(
                context,
                mode=mode_tag,
                active_name=f"{primary['root_name']} (LOD{primary['current_tier']})",
                screen_pct=primary["screen_pct"],
                distance_m=primary["distance_m"],
                active_tris=primary["active_tris"],
                tracked_count=len(updates),
            )

        # Redraw viewport areas
        if context and hasattr(context, "screen") and context.screen:
            for area in context.screen.areas:
                if area.type == "VIEW_3D":
                    area.tag_redraw()

    def execute(self, context: Any) -> set[str]:
        if not context or not context.scene:
            return {"CANCELLED"}
        props = getattr(context.scene, "lod_tool", None)
        if not props:
            return {"CANCELLED"}

        if self._is_running or props.is_simulator_active or props.is_simulator_running:
            return self.cancel_simulation(context)

        tracked_count = LODSimulatorEngine.index_scene_assets(context.scene)
        if tracked_count == 0:
            if hasattr(self, "report"):
                self.report({"WARNING"}, "No LOD collections found in scene. Generate LODs first.")
            props.is_simulator_active = False
            props.is_simulator_running = False
            return {"CANCELLED"}

        props.is_simulator_active = True
        props.is_simulator_running = True
        self._is_running = True

        wm = context.window_manager
        self._timer = wm.event_timer_add(0.04, window=context.window)
        wm.modal_handler_add(self)

        if hasattr(self, "report"):
            self.report({"INFO"}, f"LOD Simulator started (Tracking {tracked_count} asset groups at 25Hz)")
        return {"RUNNING_MODAL"}

    def cancel_simulation(self, context: Any) -> set[str]:
        self._is_running = False
        if context and hasattr(context.scene, "lod_tool"):
            context.scene.lod_tool.is_simulator_active = False
            context.scene.lod_tool.is_simulator_running = False

        if self._timer and context and hasattr(context, "window_manager") and context.window_manager:
            try:
                context.window_manager.event_timer_remove(self._timer)
            except (RuntimeError, ValueError, AttributeError) as exc:
                logger.debug("Timer removal exception: %s", exc)
            self._timer = None

        if context:
            LODSimulatorEngine.restore_all_visibility(context)
            LODViewportHUD.clear_simulation_hud()
            if hasattr(context, "screen") and context.screen:
                for area in context.screen.areas:
                    if area.type == "VIEW_3D":
                        area.tag_redraw()

        if hasattr(self, "report"):
            self.report({"INFO"}, "LOD Simulator stopped. Restored scene visibility.")
        return {"FINISHED"}


# Alias class for backward compatibility
class LOD_OT_toggle_live_simulator(LOD_OT_toggle_simulator):
    bl_idname = "lod_tool.toggle_live_simulator"


def register_simulator_ops() -> None:
    if not bpy:
        return
    bpy.utils.register_class(LOD_OT_toggle_simulator)
    bpy.utils.register_class(LOD_OT_toggle_live_simulator)


def unregister_simulator_ops() -> None:
    if not bpy:
        return
    bpy.utils.unregister_class(LOD_OT_toggle_live_simulator)
    bpy.utils.unregister_class(LOD_OT_toggle_simulator)
