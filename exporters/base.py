"""
OmniMesh Base Engine Exporter Interface.
"""

from __future__ import annotations

import abc
import logging
from typing import Any

logger = logging.getLogger(__name__)


class EngineExporterBase(abc.ABC):
    """Abstract Base Class for all OmniMesh Multi-Engine Exporters."""

    @classmethod
    @abc.abstractmethod
    def export_asset(
        cls,
        context: Any,
        export_dir: str,
        asset_name: str,
        **kwargs: Any,
    ) -> tuple[bool, str]:
        """
        Exports asset and associated LODs/colliders to target engine format.

        Returns (success, result_message).
        """
        pass
