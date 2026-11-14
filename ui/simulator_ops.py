# pyright: reportInvalidTypeForm=none
"""
Modal Operators and Live Handlers for Viewport LOD Simulator.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    import bpy
    from bpy.types import Operator
else:
    try:
        import bpy
        from bpy.types import Operator
    except ImportError:
        bpy = None
        Operator = object

try:
    from ..core.simulator import LODSimulatorEngine, compute_virtual_screen_override_pct, extract_viewport_camera_params
    from .rna_helpers import register_classes, unregister_classes
except (ImportError, ValueError):
    from core.simulator import LODSimulatorEngine, compute_virtual_screen_override_pct, extract_viewport_camera_params
    from ui.rna_helpers import register_classes, unregister_classes


class LOD_OT_toggle_simulator(Operator):
    """Start or Stop Real-Time LOD Simulation in 3D Viewport"""

    bl_idname = "lod_tool.toggle_simulator"
    bl_label = "Toggle LOD Simulator"
    bl_description = "Start or stop live distance-based LOD visibility switching in the 3D Viewport"
    bl_options = {"REGISTER"}  # Omit UNDO for modal execution

    _timer: Any = None
    _is_running: bool = False

    @classmethod
    def poll(cls, context: Any) -> bool:
        return bool(bpy and context and hasattr(context.scene, "lod_tool"))

    def modal(self, context: Any, event: Any) -> set[Any]:
        props = getattr(context.scene, "lod_tool", None) if (context and context.scene) else None
        if not props or not self._is_running:
            return self.cancel_simulation(context)

        if not props.is_simulator_active and not props.is_simulator_running:
            return self.cancel_simulation(context)

        if event.type == "ESC" and event.value == "PRESS":
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
                        space_3d = area.spaces.active
                        for reg in area.regions:
                            if reg.type == "WINDOW":
                                region_3d = reg.data
                                region = reg
                                break
                        break
                if space_3d:
                    break

        cam_pos, fov_v, is_persp = extract_viewport_camera_params(space_3d, region_3d, region, context.scene)

        virtual_override = None
        if (
            getattr(props, "virtual_screen_override_active", False)
            and getattr(props, "virtual_screen_size_pct", 0.0) > 0.0
        ):
            virtual_override = min(100.0, max(0.01, float(props.virtual_screen_size_pct)))
        elif getattr(props, "virtual_distance_override", 0.0) > 0.0:
            virtual_dist = props.virtual_distance_override
            # Convert virtual distance to equivalent screen size percentage
            radius = 1.0
            tracked = LODSimulatorEngine.get_tracked_assets()
            if tracked:
                first_record = next(iter(tracked.values()))
                radius = getattr(first_record, "radius", 1.0)
            virtual_override = compute_virtual_screen_override_pct(radius, virtual_dist, fov_v, is_persp)
        elif getattr(props, "simulator_camera_mode", "VIEWPORT") == "ACTIVE_SCENE" and context.scene.camera:
            cam_pos = context.scene.camera.matrix_world.translation.copy()

        updates = LODSimulatorEngine.update_simulation_tick(
            context, cam_pos=cam_pos, fov_v_rad=fov_v, is_perspective=is_persp, virtual_override_pct=virtual_override
        )

        if updates:
            primary = updates[0]
            props.last_scrub_status = (
                f"Active: {primary['root_name']} (LOD{primary['current_tier']}, "
                f"{primary['active_tris']:,} tris, {primary['distance_m']:.1f}m)"
            )

        # Redraw viewport areas
        if context and hasattr(context, "screen") and context.screen:
            for area in context.screen.areas:
                if area.type == "VIEW_3D":
                    area.tag_redraw()

    def execute(self, context: Any) -> set[Any]:
        if not context or not context.scene:
            return {"CANCELLED"}
        props = getattr(context.scene, "lod_tool", None)
        if not props:
            return {"CANCELLED"}

        if self._is_running or props.is_simulator_active or props.is_simulator_running:
            return self.cancel_simulation(context)

        bdata = getattr(context, "blend_data", None) or (bpy.data if bpy and hasattr(bpy, "data") else None)
        if bdata is None:
            return {"CANCELLED"}
        tracked_count = LODSimulatorEngine.index_scene_assets(context.scene, blend_data=bdata)
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
            context.scene.lod_tool.virtual_distance_override = 0.0
            context.scene.lod_tool.last_scrub_status = ""

        if self._timer and context and hasattr(context, "window_manager") and context.window_manager:
            try:
                context.window_manager.event_timer_remove(self._timer)
            except (RuntimeError, ValueError, AttributeError) as exc:
                logger.debug("Timer removal exception: %s", exc)
            self._timer = None

        if context:
            LODSimulatorEngine.restore_all_visibility(context)
            if hasattr(context, "screen") and context.screen:
                for area in context.screen.areas:
                    if area.type == "VIEW_3D":
                        area.tag_redraw()

        if hasattr(self, "report"):
            self.report({"INFO"}, "LOD Simulator stopped. Restored scene visibility.")
        return {"FINISHED"}


class LOD_OT_reset_virtual_distance(Operator):
    """Reset virtual distance override and restore default viewport LOD visibility"""

    bl_idname = "lod_tool.reset_virtual_distance"
    bl_label = "Reset Distance"
    bl_description = "Reset virtual inspection distance to 0m and restore LOD0 viewport visibility"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context: Any) -> bool:
        return bool(bpy and context and hasattr(context.scene, "lod_tool"))

    def execute(self, context: Any) -> set[Any]:
        if not context or not context.scene:
            return {"CANCELLED"}
        props = getattr(context.scene, "lod_tool", None)
        if not props:
            return {"CANCELLED"}

        props.virtual_distance_override = 0.0
        props.last_scrub_status = ""
        bdata = getattr(context, "blend_data", None) or (bpy.data if bpy and hasattr(bpy, "data") else None)
        if bdata is not None:
            LODSimulatorEngine.reset_distance_scrub(context, blend_data=bdata)

        screen = getattr(context, "screen", None)
        if screen:
            for area in getattr(screen, "areas", []):
                if getattr(area, "type", "") == "VIEW_3D":
                    area.tag_redraw()

        return {"FINISHED"}


# Alias class for backward compatibility
class LOD_OT_toggle_live_simulator(Operator):
    """Alias operator for backward compatibility delegating to primary operator."""

    bl_idname = "lod_tool.toggle_live_simulator"
    bl_label = "Toggle LOD Simulator"
    bl_description = "Toggle real-time distance-based LOD visibility switching in the 3D Viewport"
    bl_options = {"INTERNAL"}

    def execute(self, context: Any) -> set[Any]:
        ops: Any = getattr(bpy, "ops", None)
        if ops and hasattr(ops.lod_tool, "toggle_simulator"):
            return ops.lod_tool.toggle_simulator()
        return {"CANCELLED"}


SIMULATOR_CLASSES = (
    LOD_OT_toggle_simulator,
    LOD_OT_toggle_live_simulator,
    LOD_OT_reset_virtual_distance,
)


def register_simulator_ops() -> None:
    register_classes(bpy, SIMULATOR_CLASSES, logger_inst=logger)


def unregister_simulator_ops() -> None:
    unregister_classes(bpy, SIMULATOR_CLASSES, logger_inst=logger)
