"""
OmniMesh Bridge Manager & Engine Router.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple, Type

from .base import EngineBridgeBase
from .godot_bridge import GodotLiveBridge
from .msfs_bridge import MSFS2024LiveBridge
from .unity_bridge import UnityLiveBridge
from .unreal_bridge import UnrealLiveBridge

logger = logging.getLogger(__name__)


class BridgeManager:
    """Master router dispatching sync and ping requests across target game engines."""

    _BRIDGES: Dict[str, Type[EngineBridgeBase]] = {
        "UE5": UnrealLiveBridge,
        "UNITY_6": UnityLiveBridge,
        "MSFS_2024": MSFS2024LiveBridge,
        "GODOT_4": GodotLiveBridge,
    }

    @classmethod
    def get_bridge(cls, target_engine: str) -> Optional[Type[EngineBridgeBase]]:
        """Returns corresponding bridge class for target engine identifier."""
        return cls._BRIDGES.get(target_engine)

    @classmethod
    def ping_engine(cls, target_engine: str, project_dir: str = "") -> Tuple[bool, str]:
        """Pings connection or verifies SDK/project for target engine."""
        bridge = cls.get_bridge(target_engine)
        if not bridge:
            return False, f"Unknown target engine: {target_engine}"
        return bridge.ping_engine(project_dir)

    @classmethod
    def install_companion_scripts(cls, target_engine: str, project_dir: str) -> Tuple[bool, str]:
        """Installs engine companion scripts (postprocessors, GDScripts, etc.)."""
        bridge = cls.get_bridge(target_engine)
        if not bridge:
            return False, f"Unknown target engine: {target_engine}"
        return bridge.install_companion_scripts(project_dir)

    @classmethod
    def sync_asset(
        cls,
        context: Any,
        target_engine: str,
        export_dir: str,
        asset_name: str,
        project_dir: str = "",
    ) -> Tuple[bool, str]:
        """Synchronizes asset and textures with target engine editor or compiler."""
        bridge = cls.get_bridge(target_engine)
        if not bridge:
            return False, f"Unknown target engine: {target_engine}"
        return bridge.sync_asset(context, export_dir, asset_name, project_dir)
