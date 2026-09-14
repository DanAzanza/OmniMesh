"""
OmniMesh Base Engine Bridge Interface.
"""

from __future__ import annotations

import abc
import logging
from typing import Any, Tuple

logger = logging.getLogger(__name__)


class EngineBridgeBase(abc.ABC):
    """Abstract Base Class for all OmniMesh Engine Bridges."""

    @classmethod
    @abc.abstractmethod
    def get_engine_name(cls) -> str:
        """Returns human-readable name of the target engine."""
        pass

    @classmethod
    @abc.abstractmethod
    def ping_engine(cls, project_dir: str = "") -> Tuple[bool, str]:
        """Pings active engine process or checks SDK installation.

        Returns (is_available, status_message).
        """
        pass

    @classmethod
    @abc.abstractmethod
    def install_companion_scripts(cls, project_dir: str) -> Tuple[bool, str]:
        """Installs non-destructive post-processors or scripts into target project directory."""
        pass

    @classmethod
    @abc.abstractmethod
    def sync_asset(
        cls,
        context: Any,
        export_dir: str,
        asset_name: str,
        project_dir: str = "",
    ) -> Tuple[bool, str]:
        """Synchronizes exported asset with engine editor or compiles package.

        Returns (success, result_message).
        """
        pass

    @classmethod
    def sync_asset_headless(
        cls,
        export_dir: str,
        asset_name: str,
        project_dir: str = "",
        extra_options: Any = None,
    ) -> Tuple[bool, str]:
        """Headless synchronization without Blender UI or context dependencies.

        Safe to execute from worker threads.
        """
        # Default fallback calls sync_asset with None context
        return cls.sync_asset(None, export_dir, asset_name, project_dir)
