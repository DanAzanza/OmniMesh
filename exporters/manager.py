"""
OmniMesh Exporter Manager & Master Engine Dispatcher.
"""

from __future__ import annotations

import logging
from typing import Any

from .msfs_export import MSFSExporter
from .ue5_export import UE5Exporter
from .unity_export import UnityExporter

try:
    from ..core.exceptions import ExportPipelineError
except (ImportError, ValueError):
    try:
        from core.exceptions import ExportPipelineError
    except (ImportError, ValueError):
        ExportPipelineError = RuntimeError  # type: ignore

logger = logging.getLogger(__name__)


class ExporterManager:
    """Master router dispatching export requests across target game engines."""

    _EXPORTERS: dict[str, Any] = {
        "UE5": UE5Exporter,
        "UNITY_6": UnityExporter,
        "MSFS_2024": MSFSExporter,
    }

    @classmethod
    def get_exporter(cls, target_engine: str) -> Any | None:
        """Returns corresponding exporter class for target engine identifier."""
        return cls._EXPORTERS.get(target_engine)

    @classmethod
    def export_asset(
        cls,
        context: Any,
        target_engine: str,
        export_dir: str,
        asset_name: str,
        **kwargs: Any,
    ) -> tuple[bool, str]:
        """Dispatches export request to the registered engine exporter."""
        exporter = cls.get_exporter(target_engine)
        if not exporter:
            return False, f"Unknown target engine exporter: {target_engine}"

        try:
            # Support full project package option for MSFS 2024
            if (
                target_engine == "MSFS_2024"
                and kwargs.get("full_package", True)
                and hasattr(exporter, "export_project_package")
            ):
                pkg_base = kwargs.get("package_name") or asset_name
                return exporter.export_project_package(context, export_dir, pkg_base, **kwargs)

            return exporter.export_asset(context, export_dir, asset_name, **kwargs)
        except ExportPipelineError as exc:
            logger.error("Export pipeline error for %s (%s): %s", asset_name, target_engine, exc)
            return False, str(exc)
