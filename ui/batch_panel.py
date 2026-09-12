"""
OmniMesh Batch Processing Modal Operator and UI Orchestrator.

Provides non-blocking, timer-driven batch asset ingestion with isolated background
processes, mirrored directory structure, and live progress feedback.
"""

from __future__ import annotations

import logging
import os
import subprocess
import time
from typing import Any, Optional

try:
    import bpy
    from bpy.types import Operator
except ImportError:
    bpy = None
    Operator = object

try:
    from ..bridges.manager import BridgeManager
    from ..core.batch import BatchProcessorEngine
except (ImportError, ValueError):
    from bridges.manager import BridgeManager
    from core.batch import BatchProcessorEngine

logger = logging.getLogger(__name__)


class OMNIMESH_OT_batch_cancel(Operator):
    """Cancels active batch processing run"""

    bl_idname = "lod_tool.batch_cancel"
    bl_label = "Cancel Batch"
    bl_description = "Cancel currently running batch export queue"
    bl_options = {"INTERNAL"}

    def execute(self, context: Any) -> set[str]:
        OMNIMESH_OT_batch_process._abort_requested = True
        return {"FINISHED"}


class OMNIMESH_OT_batch_process(Operator):
    """Batch-process all .blend models in source directory with automated LOD generation and export"""

    bl_idname = "lod_tool.batch_process"
    bl_label = "Start Batch Export"
    bl_description = "Process all .blend files in the source folder with mirrored export directory"
    bl_options = {"REGISTER"}

    _timer: Any = None
    _files_queue: list[str] = []
    _total_count: int = 0
    _processed_count: int = 0
    _orig_global_undo: bool = True
    _current_proc: Optional[subprocess.Popen] = None
    _current_file: str = ""
    _abort_requested: bool = False
    _source_root: str = ""
    _export_root: str = ""

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
        if not src_dir or not os.path.exists(src_dir):
            self.report({"ERROR"}, "Batch source directory does not exist or is empty.")
            return {"CANCELLED"}

        export_dir = bpy.path.abspath(props.export_directory)
        if not export_dir or not export_dir.strip():
            self.report({"ERROR"}, "Export directory is empty.")
            return {"CANCELLED"}

        # Prevent source directory from being equal to export directory
        if os.path.normpath(os.path.abspath(src_dir)) == os.path.normpath(os.path.abspath(export_dir)):
            self.report({"ERROR"}, "Source folder and Export folder cannot be identical.")
            return {"CANCELLED"}

        # Discover .blend files
        files = BatchProcessorEngine.discover_blend_files(
            src_dir, recursive=props.batch_recursive_scan, export_dir=export_dir
        )
        if not files:
            self.report({"WARNING"}, f"No .blend files found in '{src_dir}'.")
            return {"CANCELLED"}

        self._files_queue = list(files)
        self._total_count = len(files)
        self._processed_count = 0
        self._current_proc = None
        self._current_proc_start_time = 0.0
        self._current_file = ""
        type(self)._abort_requested = False
        self._source_root = src_dir
        self._export_root = export_dir

        # Memory & Undo protection: disable global undo during batch run
        if hasattr(context.preferences.edit, "use_global_undo"):
            self._orig_global_undo = context.preferences.edit.use_global_undo
            context.preferences.edit.use_global_undo = False

        props.is_batch_running = True
        props.batch_total_count = self._total_count
        props.batch_processed_count = 0
        props.batch_status_text = f"Starting batch of {self._total_count} assets..."

        wm = context.window_manager
        if hasattr(wm, "progress_begin"):
            wm.progress_begin(0, self._total_count)

        self._timer = wm.event_timer_add(0.05, window=context.window)
        wm.modal_handler_add(self)

        self.report({"INFO"}, f"Batch Export started ({self._total_count} .blend files). Press ESC to abort.")
        return {"RUNNING_MODAL"}

    def modal(self, context: Any, event: Any) -> set[str]:
        if event.type == "ESC" or type(self)._abort_requested:
            type(self)._abort_requested = False
            return self.cancel_batch(context, "Batch processing aborted by user.")

        if event.type == "TIMER":
            # 1. Check active background worker process
            if self._current_proc is not None:
                # Timeout watchdog (300s default)
                if self._current_proc_start_time > 0 and (time.time() - self._current_proc_start_time) > 300.0:
                    logger.warning("Batch worker timed out for '%s' (>300s), killing process.", self._current_file)
                    try:
                        self._current_proc.kill()
                    except Exception as exc:
                        logger.debug("Failed killing timed-out batch worker: %s", exc)
                    retcode = -999
                else:
                    retcode = self._current_proc.poll()

                if retcode is None:
                    # Still working
                    return {"PASS_THROUGH"}

                # Cleanly close log file handle if attached
                log_file = getattr(self._current_proc, "_om_log_file", None)
                log_path = getattr(self._current_proc, "_om_log_path", None)
                if log_file and hasattr(log_file, "close"):
                    try:
                        log_file.close()
                    except Exception as exc:
                        logger.debug("Failed closing worker log file: %s", exc)

                # Finished
                if retcode == 0:
                    logger.info("Batch worker finished: %s", self._current_file)
                else:
                    error_tail = ""
                    if log_path and os.path.exists(log_path):
                        try:
                            with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                                lines = f.readlines()
                                error_tail = "".join(lines[-20:])
                        except Exception as exc:
                            logger.debug("Reading worker log tail failed: %s", exc)
                    elif getattr(self._current_proc, "stderr", None):
                        try:
                            error_tail = self._current_proc.stderr.read()
                        except Exception as exc:
                            logger.debug("Reading worker stderr failed: %s", exc)
                    logger.warning(
                        "Batch worker failed (exit code %d) for '%s':\n%s",
                        retcode,
                        self._current_file,
                        error_tail,
                    )

                self._current_proc = None
                self._current_proc_start_time = 0.0
                wm = context.window_manager
                if hasattr(wm, "progress_update"):
                    wm.progress_update(self._processed_count)

            # 2. If queue is empty and no active worker, complete the batch
            if not self._files_queue:
                return self.finish_batch(context)

            # 3. Pop next file from queue and spawn worker
            filepath = self._files_queue.pop(0)
            self._processed_count += 1
            self._current_file = filepath

            props = context.scene.lod_tool
            props.batch_processed_count = self._processed_count
            props.batch_current_asset = os.path.basename(filepath)
            props.batch_status_text = f"[{self._processed_count}/{self._total_count}] {os.path.basename(filepath)}"

            target_export_dir, asset_name = BatchProcessorEngine.compute_mirrored_export_path(
                filepath, self._source_root, self._export_root
            )

            preset_id = getattr(props, "pbr_export_preset", "") or "unreal_engine_5"
            engine = getattr(props, "target_engine", "UE5")

            try:
                self._current_proc_start_time = time.time()
                self._current_proc = BatchProcessorEngine.spawn_batch_worker(
                    blend_path=filepath,
                    export_dir=target_export_dir,
                    preset_id=preset_id,
                    target_engine=engine,
                    asset_name=asset_name,
                )
            except Exception as exc:
                logger.error("Failed spawning batch worker for '%s': %s", filepath, exc)
                self._current_proc = None
                self._current_proc_start_time = 0.0

            # Redraw active area only
            if context.area:
                context.area.tag_redraw()

        return {"PASS_THROUGH"}

    def finish_batch(self, context: Any) -> set[str]:
        self.cleanup_modal(context)
        props = context.scene.lod_tool
        props.batch_status_text = f"Batch complete: {self._total_count} assets exported."
        self.report({"INFO"}, f"[OmniMesh] Batch Export Complete: {self._total_count} .blend files processed.")

        # Deferred Bulk Live Link Sync on completion if enabled
        if getattr(props, "enable_live_sync", False):
            export_dir = bpy.path.abspath(props.export_directory)
            target = props.target_engine
            proj_dir = bpy.path.abspath(props.engine_project_path) if props.engine_project_path else ""
            bridge_ok, bridge_msg = BridgeManager.sync_asset(context, target, export_dir, "Batch_Library", proj_dir)
            props.bridge_connected = bridge_ok
            if bridge_ok:
                self.report({"INFO"}, f"[Live Bridge Bulk Sync] {bridge_msg}")
            else:
                self.report({"WARNING"}, f"[Live Bridge Bulk Sync] {bridge_msg}")

        return {"FINISHED"}

    def cancel_batch(self, context: Any, reason: str) -> set[str]:
        self.cleanup_modal(context)
        props = context.scene.lod_tool
        props.batch_status_text = f"Batch cancelled: {reason}"
        self.report({"WARNING"}, reason)
        return {"CANCELLED"}

    def cleanup_modal(self, context: Any) -> None:
        if self._current_proc is not None and self._current_proc.poll() is None:
            try:
                self._current_proc.terminate()
                self._current_proc.wait(timeout=1.0)
            except (subprocess.TimeoutExpired, OSError):
                try:
                    self._current_proc.kill()
                except OSError:
                    pass
        self._current_proc = None
        type(self)._abort_requested = False

        if context and hasattr(context.scene, "lod_tool"):
            context.scene.lod_tool.is_batch_running = False

        if context and hasattr(context, "window_manager"):
            wm = context.window_manager
            if hasattr(wm, "progress_end"):
                try:
                    wm.progress_end()
                except Exception as exc:
                    logger.debug("Progress end cleanup exception: %s", exc)
            if self._timer:
                try:
                    wm.event_timer_remove(self._timer)
                except (RuntimeError, ValueError, AttributeError) as exc:
                    logger.debug("Batch timer removal exception: %s", exc)
                self._timer = None

        # Restore global undo
        if context and hasattr(context.preferences.edit, "use_global_undo"):
            context.preferences.edit.use_global_undo = self._orig_global_undo


def register_batch_ops() -> None:
    if not bpy:
        return
    for cls in (OMNIMESH_OT_batch_cancel, OMNIMESH_OT_batch_process):
        existing = getattr(bpy.types, cls.__name__, None)
        if existing is not None:
            try:
                bpy.utils.unregister_class(existing)
            except Exception as exc:
                logger.debug("Safe unregister skipped %s: %s", cls.__name__, exc)
        bpy.utils.register_class(cls)


def unregister_batch_ops() -> None:
    if not bpy:
        return
    for cls in (OMNIMESH_OT_batch_process, OMNIMESH_OT_batch_cancel):
        existing = getattr(bpy.types, cls.__name__, None)
        if existing is not None:
            try:
                bpy.utils.unregister_class(existing)
            except Exception as exc:
                logger.debug("Safe unregister skipped %s: %s", cls.__name__, exc)
