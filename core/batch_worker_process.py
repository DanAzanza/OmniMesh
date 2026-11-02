"""
Headless background worker process manager and launcher for OmniMesh batch pipeline.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import IO, TYPE_CHECKING, Any, TextIO

if TYPE_CHECKING:
    import bpy
else:
    try:
        import bpy
    except ImportError:
        bpy = None  # type: ignore

logger = logging.getLogger(__name__)


@dataclass
class WorkerProcessHandle:
    """Encapsulates an active headless Blender worker subprocess and its associated log handle."""

    proc: subprocess.Popen
    log_file: TextIO | None = None
    log_path: str | None = None

    def poll(self) -> int | None:
        """Checks if child process has terminated. Returns returncode or None."""
        return self.proc.poll()

    def wait(self, timeout: float | None = None) -> int:
        """Waits for child process to terminate. Returns returncode."""
        return self.proc.wait(timeout=timeout)

    def kill(self) -> None:
        """Kills the underlying worker process."""
        self.proc.kill()

    def terminate(self) -> None:
        """Gracefully terminates the underlying worker process."""
        self.proc.terminate()

    @property
    def pid(self) -> int:
        """Returns the PID of the worker process."""
        return self.proc.pid

    @property
    def returncode(self) -> int | None:
        """Returns the process exit code, or None if still running."""
        return self.proc.returncode

    @property
    def stderr(self) -> IO[str] | IO[bytes] | None:
        """Standard error stream of the worker process, if piped."""
        return self.proc.stderr

    @property
    def stdout(self) -> IO[str] | IO[bytes] | None:
        """Standard output stream of the worker process, if piped."""
        return self.proc.stdout

    @property
    def _om_log_file(self) -> TextIO | None:
        """Backward-compatibility property for legacy callers inspecting log handle."""
        return self.log_file

    @property
    def _om_log_path(self) -> str | None:
        """Backward-compatibility property for legacy callers inspecting log file path."""
        return self.log_path

    def read_log_tail(self, max_lines: int = 20) -> str:
        """Reads recent log entries for failure diagnostics."""
        if self.log_path and os.path.exists(self.log_path):
            try:
                with open(self.log_path, "r", encoding="utf-8", errors="replace") as f:
                    return "".join(f.readlines()[-max_lines:])
            except OSError as exc:
                logger.debug("Reading worker log tail failed: %s", exc)
        return ""

    def close_log(self) -> None:
        """Deterministically closes the worker log file handle if open."""
        if self.log_file is not None:
            if not getattr(self.log_file, "closed", False):
                try:
                    self.log_file.close()
                except OSError as exc:
                    logger.debug("Failed closing worker log file: %s", exc)
            self.log_file = None


def normalize_export_path_for_cli(path_str: str) -> str:
    """
    Normalizes export path for command-line arguments while preserving Windows UNC prefixes.
    Prevents conversion of '\\\\server\\share' into '//server/share' which Blender treats as blend-relative.
    """
    norm = os.path.normpath(path_str)
    if norm.startswith("\\\\"):
        return "\\\\" + norm[2:].replace("\\", "/")
    return norm.replace("\\", "/")


def build_hierarchical_export_path(blend_path: str, source_root: str, export_root: str) -> tuple[str, str]:
    """Derives output directory preserving source subfolder structure."""
    clean_blend = blend_path.replace("\\", "/")
    clean_source = source_root.replace("\\", "/")
    clean_export = export_root.replace("\\", "/")

    stem = Path(clean_blend).stem
    asset_name = re.sub(r"[^\w\-]", "_", stem)

    if clean_blend.lower().startswith(clean_source.lower().rstrip("/") + "/"):
        rel_path = clean_blend[len(clean_source.rstrip("/")) + 1 :]
    else:
        try:
            rel_path = os.path.relpath(clean_blend, clean_source)
        except ValueError:
            rel_path = os.path.basename(clean_blend)

    rel_dir = os.path.dirname(rel_path)
    clean_parts = [re.sub(r"[^\w\-]", "_", part) for part in Path(rel_dir).parts if part and part not in (".", "..")]
    target_dir = os.path.join(clean_export, *clean_parts) if clean_parts else clean_export

    return os.path.normpath(target_dir), asset_name


class BatchWorkerProcessManager:
    """Spawns and manages isolated background Blender processes for asset export."""

    @classmethod
    def spawn_batch_worker(
        cls,
        blend_path: str,
        export_dir: str,
        preset_id: str = "",
        target_engine: str = "UE5",
        asset_name: str = "",
    ) -> WorkerProcessHandle:
        """Launches an isolated headless background Blender process to export a single .blend asset."""
        blender_exe = bpy.app.binary_path if bpy else "blender"
        addon_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        scripts_worker = os.path.join(addon_dir, "scripts", "batch_worker.py")
        worker_script = (
            scripts_worker
            if os.path.exists(scripts_worker)
            else os.path.join(os.path.dirname(__file__), "batch_worker.py")
        )

        clean_export_dir = normalize_export_path_for_cli(export_dir)

        cmd = [
            blender_exe,
            "-b",
            blend_path,
            "--factory-startup",
            "--disable-autoexec",
            "-noaudio",
            "--python-exit-code",
            "1",
            "--python",
            worker_script,
            "--",
            "--export-dir",
            clean_export_dir,
            "--engine",
            target_engine,
        ]
        if preset_id:
            cmd.extend(["--preset", preset_id])
        if asset_name:
            cmd.extend(["--asset-name", asset_name])

        popen_kwargs: dict[str, Any] = {}
        log_file = None
        log_path = None
        try:
            os.makedirs(clean_export_dir, exist_ok=True)
            log_name = f"{asset_name or os.path.splitext(os.path.basename(blend_path))[0]}_export.log"
            log_path = os.path.join(clean_export_dir, log_name)
            for attempt in range(3):
                try:
                    log_file = open(log_path, "w", encoding="utf-8")
                    break
                except (PermissionError, OSError) as lock_exc:
                    if attempt < 2 and (isinstance(lock_exc, PermissionError) or "WinError 32" in str(lock_exc)):
                        time.sleep(0.05 * (2**attempt))
                        continue
                    unique_name = (
                        f"{asset_name or os.path.splitext(os.path.basename(blend_path))[0]}_{os.getpid()}_export.log"
                    )
                    log_path = os.path.join(clean_export_dir, unique_name)
                    log_file = open(log_path, "w", encoding="utf-8")
                    break
            popen_kwargs["stdout"] = log_file
            popen_kwargs["stderr"] = subprocess.STDOUT
        except (OSError, PermissionError) as exc:
            logger.debug("Failed opening worker log file, falling back to DEVNULL: %s", exc)
            popen_kwargs["stdout"] = subprocess.DEVNULL
            popen_kwargs["stderr"] = subprocess.DEVNULL

        if sys.platform == "win32":
            popen_kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW

        spawn_succeeded = False
        try:
            proc = subprocess.Popen(cmd, **popen_kwargs)
            spawn_succeeded = True
        finally:
            if not spawn_succeeded and log_file and not log_file.closed:
                try:
                    log_file.close()
                except OSError as exc:
                    logger.debug("Failed closing worker log file on spawn error: %s", exc)

        return WorkerProcessHandle(
            proc=proc,
            log_file=log_file,
            log_path=log_path,
        )
