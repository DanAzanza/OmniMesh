"""
OmniMesh Upward Project Detector.

Automatically identifies target game engine project roots by crawling upward
from export directories, guarding against UNC loops, symlink escape, and unsaved states.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

try:
    import bpy
except ImportError:
    bpy = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


def detect_engine_project(export_dir: str, target_engine: str, max_depth: int = 8) -> Optional[str]:
    """Crawls upward from export directory to identify engine project root.

    Args:
        export_dir: Destination path or relative path (e.g. '//Export').
        target_engine: Target engine identifier ('UE5', 'UNITY_6', 'GODOT_4', 'MSFS_2024').
        max_depth: Maximum number of parent directory levels to inspect.

    Returns:
        Absolute normalized directory path to engine project root, or None if not detected.
    """
    if not export_dir or not target_engine:
        return None

    # Guard 1: Blender relative paths with unsaved file
    if export_dir.startswith("//"):
        if bpy is not None:
            is_saved = getattr(bpy.data, "is_saved", False)
            filepath = getattr(bpy.data, "filepath", "")
            if not is_saved or not filepath:
                return None
            try:
                abs_dir = bpy.path.abspath(export_dir)
            except Exception as exc:
                logger.debug("Failed resolving relative export dir '%s': %s", export_dir, exc)
                return None
        else:
            return None
    else:
        abs_dir = export_dir

    abs_dir = os.path.normpath(abs_dir)
    if not os.path.exists(abs_dir):
        return None

    # Use pure lexical traversal without resolve() to preserve directory junctions
    curr = Path(abs_dir)
    if not curr.is_dir():
        curr = curr.parent

    visited: set[Path] = set()
    depth = 0

    while depth < max_depth:
        # Avoid symlink cycles and UNC root loops
        if curr in visited or curr == curr.parent:
            break
        visited.add(curr)
        depth += 1

        try:
            if target_engine == "UE5":
                uproject_files = [f for f in curr.glob("*.uproject") if f.is_file()]
                clean_projects = [
                    f
                    for f in uproject_files
                    if not any(x in f.name.lower() for x in ("backup", "test", "template", "sample"))
                ]
                if clean_projects:
                    return str(curr)

            elif target_engine == "UNITY_6":
                # Strict check: Assets folder AND ProjectVersion.txt or ProjectSettings.asset
                has_assets = (curr / "Assets").is_dir()
                proj_settings = curr / "ProjectSettings"
                has_version = (proj_settings / "ProjectVersion.txt").is_file()
                has_settings = (proj_settings / "ProjectSettings.asset").is_file()
                if has_assets and (has_version or has_settings):
                    return str(curr)

            elif target_engine == "GODOT_4":
                if (curr / "project.godot").is_file():
                    return str(curr)

            elif target_engine == "MSFS_2024":
                if (
                    (curr / "PackageDefinitions").is_dir()
                    or (curr / "PackageSources").is_dir()
                    or (curr / "Project.xml").is_file()
                ):
                    return str(curr)

        except (PermissionError, OSError) as exc:
            logger.debug("Upward project scan permission error at %s: %s", curr, exc)
            break

        curr = curr.parent

    return None
