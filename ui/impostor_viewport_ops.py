"""
OmniMesh Live Impostor Viewport Tracker Operator and Timer Service.
Blender 4.2+ and 5.0+ LTS Compatible.

Provides non-blocking background synchronization between active 3D Viewport perspective
navigation and the impostor preview billboard rig with zero dependency graph churn.
"""

from __future__ import annotations

import functools
import logging
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

try:
    import bpy
    from bpy.types import Operator
    from mathutils import Vector
except ImportError:
    bpy = None
    Operator = object  # type: ignore
    Vector = None  # type: ignore

_ACTIVE_TIMERS: dict[str, Callable[[], Optional[float]]] = {}


def sync_rig_to_viewport(base_name: str) -> Optional[float]:
    """
    Syncs the preview rig target empty and camera to the current 3D Viewport eye position.
    Runs non-blocking via bpy.app.timers at 30 FPS.
    """
    if not bpy:
        return None

    rig_coll = bpy.data.collections.get(f"{base_name}_Preview_Rig")
    if not rig_coll:
        _ACTIVE_TIMERS.pop(base_name, None)
        return None

    target_name = f"{base_name}_Preview_Tracker_Target"
    target_empty = bpy.data.objects.get(target_name)
    if not target_empty:
        _ACTIVE_TIMERS.pop(base_name, None)
        return None

    # Resolve active 3D Viewport
    region_3d = None
    view_persp = "PERSP"
    wm = getattr(bpy.context, "window_manager", None)
    if wm and hasattr(wm, "windows"):
        for window in wm.windows:
            if not window.screen:
                continue
            for area in window.screen.areas:
                if area.type == "VIEW_3D":
                    for space in area.spaces:
                        if space.type == "VIEW_3D" and hasattr(space, "region_3d"):
                            region_3d = space.region_3d
                            view_persp = getattr(region_3d, "view_perspective", "PERSP")
                            break
                    if region_3d:
                        break
            if region_3d:
                break

    if not region_3d or not hasattr(region_3d, "view_matrix"):
        return 1.0 / 30.0

    scene = getattr(bpy.context, "scene", None)
    if view_persp == "CAMERA" and scene and scene.camera:
        eye_pos = scene.camera.matrix_world.translation.copy()
    else:
        view_inv = region_3d.view_matrix.inverted()
        eye_pos = view_inv.translation.copy()

    # Epsilon gating prevents depsgraph churn when user is not moving the viewport
    if (eye_pos - target_empty.location).length_squared < 1e-4:
        return 1.0 / 30.0

    target_empty.location = eye_pos

    # If preview camera is free (no turntable keyframes), sync its matrix as well
    cam_name = f"{base_name}_Preview_Camera"
    cam_obj = bpy.data.objects.get(cam_name)
    if cam_obj and not cam_obj.animation_data:
        cam_obj.location = eye_pos
        if hasattr(region_3d.view_matrix.inverted(), "to_euler"):
            cam_obj.rotation_euler = region_3d.view_matrix.inverted().to_euler()

    return 1.0 / 30.0


def start_impostor_viewport_timer(base_name: str) -> bool:
    """Registers a persistent background timer to sync the impostor rig to the 3D Viewport."""
    if not bpy or getattr(bpy.app, "background", False):
        return False

    if base_name in _ACTIVE_TIMERS:
        return True

    timer_fn = functools.partial(sync_rig_to_viewport, base_name)
    _ACTIVE_TIMERS[base_name] = timer_fn

    try:
        bpy.app.timers.register(timer_fn, first_interval=0.01)
        logger.debug("Started impostor viewport sync timer for '%s'", base_name)
        return True
    except Exception as exc:
        logger.debug("Failed registering impostor viewport timer: %s", exc)
        _ACTIVE_TIMERS.pop(base_name, None)
        return False


def stop_impostor_viewport_timer(base_name: str) -> bool:
    """Stops and unregisters the impostor viewport sync timer."""
    if not bpy:
        return False

    timer_fn = _ACTIVE_TIMERS.pop(base_name, None)
    if timer_fn and bpy.app.timers.is_registered(timer_fn):
        try:
            bpy.app.timers.unregister(timer_fn)
            logger.debug("Stopped impostor viewport sync timer for '%s'", base_name)
            return True
        except Exception as exc:
            logger.debug("Failed unregistering impostor viewport timer: %s", exc)
            return False
    return False


def is_impostor_viewport_timer_running(base_name: str) -> bool:
    """Checks whether the viewport tracker timer is currently active for the given asset."""
    if not bpy or base_name not in _ACTIVE_TIMERS:
        return False
    timer_fn = _ACTIVE_TIMERS.get(base_name)
    return bool(timer_fn and bpy.app.timers.is_registered(timer_fn))


class LOD_OT_impostor_viewport_tracker(Operator):
    """Dynamically synchronizes the preview rig to free 3D Viewport perspective navigation"""

    bl_idname = "lod_tool.impostor_viewport_tracker"
    bl_label = "Toggle Impostor Viewport Tracker"
    bl_description = "Continuously tracks free 3D Viewport camera navigation for the impostor preview rig"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context: Any) -> bool:
        if not bpy or getattr(bpy.app, "background", False):
            return False
        return bool(context and hasattr(context, "window_manager") and context.scene)

    def execute(self, context: Any) -> set[str]:
        if not bpy or not context:
            return {"CANCELLED"}

        # Resolve asset base name
        base_name = ""
        scene = context.scene
        if hasattr(scene, "lod_tool"):
            base_name = getattr(scene.lod_tool, "asset_name", "")

        if not base_name:
            for coll in bpy.data.collections:
                if coll.name.endswith("_Preview_Rig"):
                    base_name = coll.name[:-12]
                    break

        if not base_name:
            if hasattr(self, "report"):
                self.report({"WARNING"}, "No active Impostor Preview Rig found to track.")
            return {"CANCELLED"}

        if is_impostor_viewport_timer_running(base_name):
            stop_impostor_viewport_timer(base_name)
            if hasattr(self, "report"):
                self.report({"INFO"}, f"Stopped Viewport Tracker for '{base_name}'.")
        else:
            start_impostor_viewport_timer(base_name)
            if hasattr(self, "report"):
                self.report({"INFO"}, f"Started Viewport Tracker for '{base_name}'.")

        return {"FINISHED"}
