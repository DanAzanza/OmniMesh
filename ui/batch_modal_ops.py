"""
Non-Blocking Modal Batch Decimation Operator for OmniMesh.
Blender 4.2+ and 5.2 LTS Compatible.

Provides:
- LOD_OT_batch_generate_modal: Modal timer-driven operator that iteratively simplifies
  selected scene meshes without freezing the Blender UI.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

try:
    import bpy
    from bpy.types import Operator
except ImportError:
    bpy = None
    Operator = object

try:
    from ..core.batch_iterator import BatchMeshIterator, BatchProgress
    from .utils import safe_report
except (ImportError, ValueError):
    from core.batch_iterator import BatchMeshIterator, BatchProgress
    from ui.utils import safe_report


class LOD_OT_batch_generate_modal(Operator):
    """Non-blocking modal batch decimation across selected meshes."""

    bl_idname = "lod_tool.batch_generate_modal"
    bl_label = "Modal Batch Decimate"
    bl_description = "Sequentially decimate selected meshes with interactive progress and cancel support"
    bl_options = {"REGISTER", "UNDO"}

    _iterator: Optional[Any] = None
    _timer: Optional[Any] = None
    _prev_undo: bool = True
    _completed_count: int = 0
    _failed_count: int = 0
    _total_count: int = 0

    def invoke(self, context: Any, event: Any) -> set[str]:
        if not bpy or not context:
            return {"CANCELLED"}

        selected_meshes = [
            obj for obj in getattr(context, "selected_objects", []) if getattr(obj, "type", "") == "MESH"
        ]

        if not selected_meshes:
            safe_report(self, {"WARNING"}, "No mesh objects selected for batch decimation.")
            return {"CANCELLED"}

        props = getattr(context.scene, "lod_tool", None)
        target_ratio = getattr(props, "global_target_ratio", 0.5) if props else 0.5

        iterator_obj = BatchMeshIterator(selected_meshes, target_ratio=target_ratio)
        self._iterator = iterator_obj.iterate(context)
        self._total_count = iterator_obj.total
        self._completed_count = 0
        self._failed_count = 0

        # Isolate global undo to prevent pollution of user undo stack during intermediate steps
        edit_prefs = getattr(context.preferences, "edit", None)
        if edit_prefs and hasattr(edit_prefs, "use_global_undo"):
            self._prev_undo = edit_prefs.use_global_undo
            edit_prefs.use_global_undo = False

        wm = context.window_manager
        wm.progress_begin(0, self._total_count)
        self._timer = wm.event_timer_add(0.02, window=context.window)
        wm.modal_handler_add(self)

        safe_report(
            self,
            {"INFO"},
            f"Starting modal batch decimation across {self._total_count} meshes (ESC to abort)...",
        )
        return {"RUNNING_MODAL"}

    def modal(self, context: Any, event: Any) -> set[str]:
        if event.type == "ESC":
            self._cleanup(context)
            safe_report(
                self,
                {"WARNING"},
                f"Batch aborted by user. Processed {self._completed_count}/{self._total_count} meshes.",
            )
            return {"CANCELLED"}

        if event.type == "TIMER" and self._iterator:
            try:
                progress: BatchProgress = next(self._iterator)
                if progress.success:
                    self._completed_count += 1
                else:
                    self._failed_count += 1

                wm = context.window_manager
                wm.progress_update(progress.index)

                if getattr(context, "area", None):
                    context.area.tag_redraw()

            except StopIteration:
                self._cleanup(context)
                msg = f"Batch decimation finished: {self._completed_count} succeeded"
                if self._failed_count > 0:
                    msg += f", {self._failed_count} failed"
                safe_report(self, {"INFO"}, msg)
                return {"FINISHED"}

            except Exception as exc:
                logger.exception("Unexpected error in modal batch decimation: %s", exc)
                self._cleanup(context)
                safe_report(self, {"ERROR"}, f"Batch decimation terminated with error: {exc}")
                return {"CANCELLED"}

        return {"PASS_THROUGH"}

    def _cleanup(self, context: Any) -> None:
        if not bpy:
            return

        edit_prefs = getattr(context.preferences, "edit", None)
        if edit_prefs and hasattr(edit_prefs, "use_global_undo"):
            edit_prefs.use_global_undo = self._prev_undo

        wm = getattr(context, "window_manager", None)
        if wm:
            if self._timer:
                try:
                    wm.event_timer_remove(self._timer)
                except Exception as exc:
                    logger.debug("Failed removing event timer: %s", exc)
                self._timer = None
            try:
                wm.progress_end()
            except Exception as exc:
                logger.debug("Failed ending progress: %s", exc)

        self._iterator = None


__all__ = ["LOD_OT_batch_generate_modal"]
