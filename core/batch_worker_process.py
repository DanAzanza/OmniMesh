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
from typing import Any

try:
    import bpy
except ImportError:
    bpy = None  # type: ignore

logger = logging.getLogger(__name__)


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
    norm_blend = os.path.normpath(blend_path)
    norm_source = os.path.normpath(source_root)
    norm_export = os.path.normpath(export_root)

    try:
        rel_path = os.path.relpath(norm_blend, norm_source)
    except ValueError:
        rel_path = os.path.basename(norm_blend)

    rel_dir = os.path.dirname(rel_path)
    clean_parts = [re.sub(r"[^\w\-]", "_", part) for part in Path(rel_dir).parts if part and part != "."]
    target_dir = os.path.join(norm_export, *clean_parts) if clean_parts else norm_export
    stem = Path(norm_blend).stem
    asset_name = re.sub(r"[^\w\-]", "_", stem)

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
    ) -> subprocess.Popen:
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
            log_file = open(log_path, "w", encoding="utf-8")
            popen_kwargs["stdout"] = log_file
            popen_kwargs["stderr"] = subprocess.STDOUT
        except Exception as exc:
            logger.debug("Failed opening worker log file, falling back to DEVNULL: %s", exc)
            popen_kwargs["stdout"] = subprocess.DEVNULL
            popen_kwargs["stderr"] = subprocess.DEVNULL

        if sys.platform == "win32":
            popen_kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW

        proc = subprocess.Popen(cmd, **popen_kwargs)
        if log_file is not None:
            proc._om_log_file = log_file  # type: ignore[attr-defined]
            proc._om_log_path = log_path  # type: ignore[attr-defined]
        return proc
