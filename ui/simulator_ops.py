"""
Modal Operators and Live Handlers for Viewport LOD Simulator.
"""

from __future__ import annotations

import logging

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


class LOD_OT_toggle_live_simulator(Operator):
    """Start or Stop Real-Time LOD Simulation in 3D Viewport"""

    bl_idname = "lod_tool.toggle_live_simulator"
    bl_label = "Toggle LOD Simulator"
    bl_options = {"REGISTER"}

    _timer = None
    _is_running = False

    @classmethod
    def poll(cls, context):
        return bpy is not None

    def modal(self, context, event):
        props = getattr(context.scene, "lod_tool", None) if (context and context.scene) else None
        if not props or not self._is_running:
            return self.cancel_simulation(context)

        if not props.is_simulator_running:
            return self.cancel_simulation(context)

        if event.type in {"ESC", "RIGHTMOUSE"} and event.value == "PRESS":
            return self.cancel_simulation(context)

        if event.type == "TIMER":
            try:
                self.tick_simulation(context, props)
            except Exception:
                return self.cancel_simulation(context)

        return {"PASS_THROUGH"}

    def tick_simulation(self, context, props):
        if not context or not context.window_manager:
            return

        space_3d = None
        region_3d = None
        region = None

        for window in context.window_manager.windows:
            if not window.screen:
                continue
            for area in window.screen.areas:
                if area.type == "VIEW_3D":
                    for space in area.spaces:
                        if space.type == "VIEW_3D":
                            space_3d = space
                            region_3d = space.region_3d
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
        if props.simulator_mode == "VIRTUAL_SLIDER":
            virtual_override = props.virtual_screen_size_pct
        elif props.simulator_mode == "CAMERA_LOCKED" and context.scene.camera:
            cam_pos = context.scene.camera.matrix_world.translation.copy()

        updates = LODSimulatorEngine.update_simulation_tick(
            context, cam_pos=cam_pos, fov_v_rad=fov_v, is_perspective=is_persp, virtual_override_pct=virtual_override
        )

        if updates:
            primary = updates[0]
            LODViewportHUD.update_simulation_hud(
                context,
                mode=props.simulator_mode,
                active_name=f"{primary['root_name']} (LOD{primary['current_tier']})",
                screen_pct=primary["screen_pct"],
                distance_m=primary["distance_m"],
                active_tris=primary["active_tris"],
                tracked_count=len(updates),
            )

    def execute(self, context):
        if not context or not context.scene:
            return {"CANCELLED"}
        props = getattr(context.scene, "lod_tool", None)
        if not props:
            return {"CANCELLED"}

        if self._is_running or props.is_simulator_running:
            props.is_simulator_running = False
            return self.cancel_simulation(context)

        tracked_count = LODSimulatorEngine.index_scene_assets(context.scene)
        if tracked_count == 0:
            self.report({"WARNING"}, "No LOD collections found in scene. Generate LODs first.")
            props.is_simulator_running = False
            return {"CANCELLED"}

        props.is_simulator_running = True
        self._is_running = True

        wm = context.window_manager
        self._timer = wm.event_timer_add(0.04, window=context.window)
        wm.modal_handler_add(self)

        self.report({"INFO"}, f"LOD Simulator started (Tracking {tracked_count} asset groups at 25Hz)")
        return {"RUNNING_MODAL"}

    def cancel_simulation(self, context):
        self._is_running = False
        if context and hasattr(context.scene, "lod_tool"):
            context.scene.lod_tool.is_simulator_running = False

        if self._timer and context and context.window_manager:
            try:
                context.window_manager.event_timer_remove(self._timer)
            except (RuntimeError, ValueError, AttributeError) as exc:
                logger.debug("Timer removal exception: %s", exc)
            self._timer = None

        if context:
            LODSimulatorEngine.restore_all_visibility(context)
            LODViewportHUD.clear_simulation_hud()
        self.report({"INFO"}, "LOD Simulator stopped. Restored scene visibility.")
        return {"FINISHED"}


def register_simulator_ops():
    if not bpy:
        return
    bpy.utils.register_class(LOD_OT_toggle_live_simulator)


def unregister_simulator_ops():
    if not bpy:
        return
    bpy.utils.unregister_class(LOD_OT_toggle_live_simulator)
