"""
MSFS Project Scanner Re-export Facade.
Provides backward compatibility while delegating to the unified core.msfs package.
"""

from __future__ import annotations

from core.msfs.project_scanner import *  # noqa: F403
from core.msfs.project_scanner import (
    MSFSLODInfo,
    MSFSModelTargetInfo,
    MSFSProjectManifest,
    MSFSProjectScanner,
    find_package_root,
    parse_model_cfg,
    parse_model_xml,
    resolve_path_ci,
    sanitize_asset_name,
)

__all__ = [
    "MSFSLODInfo",
    "MSFSModelTargetInfo",
    "MSFSProjectManifest",
    "MSFSProjectScanner",
    "find_package_root",
    "parse_model_cfg",
    "parse_model_xml",
    "resolve_path_ci",
    "sanitize_asset_name",
]
