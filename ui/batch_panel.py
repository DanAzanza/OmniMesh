"""
OmniMesh Batch Processing Modal Operator and UI Orchestrator.
Provides non-blocking, timer-driven batch asset ingestion with global undo protection
and live progress feedback.
"""

from __future__ import annotations

import logging
from typing import Any

try:
    import bpy
    from bpy.types import Operator
except ImportError:
    bpy = None
    Operator = object

try:
    from ..core.batch import BatchProcessorEngine
except (ImportError, ValueError):
    from core.batch import BatchProcessorEngine

logger = logging.getLogger(__name__)


class OMNIMESH_OT_batch_process(Operator):
    """Batch-process all 3D assets in source directory with automated LOD generation and export"""

    bl_idname = "lod_tool.batch_process"
    bl_label = "Start Batch Processing"
    bl_description = "Process all FBX, OBJ, glTF models in the selected folder with LOD generation and export"
    bl_options = {"REGISTER"}  # Omit UNDO to avoid polluting undo stack

    _timer: Any = None
    _files_queue: list[str] = []
    _total_count: int = 0
    _processed_count: int = 0
    _orig_global_undo: bool = True

    @classmethod
    def poll(cls, context: Any) -> bool:
        if not bpy or not context or not hasattr(context.scene, "lod_tool"):
            return False
        props = context.scene.lod_tool
        return bool(props.batch_source_directory and props.batch_source_directory.strip())

    def invoke(self, context: Any, _event: Any) -> set[str]:
        if not bpy or not context:
            return {"CANCELLED"}
        props = context.scene.lod_tool
        src_dir = bpy.path.abspath(props.batch_source_directory)
        if not src_dir or not src_dir.strip():
            self.report({"ERROR"}, "Batch source directory path is empty.")
            return {"CANCELLED"}

        # Discover files
        files = BatchProcessorEngine.discover_assets(src_dir, recursive=props.batch_recursive_scan)
        if not files:
            self.report({"WARNING"}, f"No 3D asset files (.fbx, .obj, .gltf, .glb) found in '{src_dir}'.")
            return {"CANCELLED"}

        self._files_queue = list(files)
        self._total_count = len(files)
        self._processed_count = 0

        # Memory & Undo protection: disable global undo during batch run
        if hasattr(context.preferences.edit, "use_global_undo"):
            self._orig_global_undo = context.preferences.edit.use_global_undo
            context.preferences.edit.use_global_undo = False

        props.is_batch_running = True
        props.batch_total_count = self._total_count
        props.batch_processed_count = 0
        props.batch_status_text = f"Starting batch processing of {self._total_count} assets..."

        wm = context.window_manager
        self._timer = wm.event_timer_add(0.05, window=context.window)
        wm.modal_handler_add(self)

        self.report({"INFO"}, f"Batch Processor started ({self._total_count} assets queued). Press ESC to abort.")
        return {"RUNNING_MODAL"}

    def modal(self, context: Any, event: Any) -> set[str]:
        if event.type == "ESC":
            return self.cancel_batch(context, "Batch processing aborted by user (ESC).")

        if event.type == "TIMER":
            if not self._files_queue:
                return self.finish_batch(context)

            # Process next asset
            filepath = self._files_queue.pop(0)
            self._processed_count += 1

            props = context.scene.lod_tool
            props.batch_processed_count = self._processed_count
            props.batch_current_asset = filepath
            props.batch_status_text = f"[{self._processed_count}/{self._total_count}] Processing {filepath}..."

            export_dir = (
                bpy.path.abspath(props.batch_export_directory)
                if props.batch_export_directory
                else bpy.path.abspath(props.export_directory)
            )

            num_lods_val = getattr(props, "lod_count", getattr(props, "num_lods", 4))
            tau_sse_val = getattr(props, "tau_sse", 0.8)
            cull_pct_val = getattr(props, "cull_screen_size_pct", 0.5)

            res = BatchProcessorEngine.process_single_asset(
                context=context,
                filepath=filepath,
                export_base_dir=export_dir,
                target_engine=props.target_engine,
                num_lods=num_lods_val,
                tau_sse=tau_sse_val,
                cull_screen_size_pct=cull_pct_val,
            )

            if res["success"]:
                logger.info(
                    "Batch processed '%s' in %.2fs: %d -> %d tris (-%.1f%%)",
                    res["asset_name"],
                    res["duration_sec"],
                    res["initial_tris"],
                    res["final_tris"],
                    res["reduction_pct"],
                )
            else:
                logger.warning("Batch asset '%s' failed: %s", res["asset_name"], res["message"])

            # Redraw UI
            for area in context.screen.areas:
                if area.type == "VIEW_3D":
                    area.tag_redraw()

        return {"PASS_THROUGH"}

    def finish_batch(self, context: Any) -> set[str]:
        self.cleanup_modal(context)
        props = context.scene.lod_tool
        props.batch_status_text = f"Batch complete: Successfully processed {self._total_count} assets."
        self.report({"INFO"}, f"OmniMesh Batch Processing Complete ({self._total_count} assets processed).")
        return {"FINISHED"}

    def cancel_batch(self, context: Any, reason: str) -> set[str]:
        self.cleanup_modal(context)
        props = context.scene.lod_tool
        props.batch_status_text = f"Batch cancelled: {reason}"
        self.report({"WARNING"}, reason)
        return {"CANCELLED"}

    def cleanup_modal(self, context: Any) -> None:
        if context and hasattr(context.scene, "lod_tool"):
            context.scene.lod_tool.is_batch_running = False

        if self._timer and context and context.window_manager:
            try:
                context.window_manager.event_timer_remove(self._timer)
            except (RuntimeError, ValueError, AttributeError) as exc:
                logger.debug("Batch timer removal exception: %s", exc)
            self._timer = None

        # Restore global undo
        if context and hasattr(context.preferences.edit, "use_global_undo"):
            context.preferences.edit.use_global_undo = self._orig_global_undo


def register_batch_ops() -> None:
    if not bpy:
        return
    try:
        bpy.utils.unregister_class(OMNIMESH_OT_batch_process)
    except Exception as exc:
        logger.debug("Safe unregister skipped OMNIMESH_OT_batch_process: %s", exc)
    bpy.utils.register_class(OMNIMESH_OT_batch_process)


def unregister_batch_ops() -> None:
    if not bpy:
        return
    bpy.utils.unregister_class(OMNIMESH_OT_batch_process)
