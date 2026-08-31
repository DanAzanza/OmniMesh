"""
OmniMesh Multi-Engine Live Bridge Package.
Provides real-time non-destructive asset, material, and animation sync for
Unreal Engine 5, Unity 6, MSFS 2024, and Godot 4.
"""

from .base import EngineBridgeBase
from .unreal_bridge import UnrealLiveBridge
from .unity_bridge import UnityLiveBridge
from .msfs_bridge import MSFS2024LiveBridge
from .godot_bridge import GodotLiveBridge
from .manager import BridgeManager

__all__ = [
    "EngineBridgeBase",
    "UnrealLiveBridge",
    "UnityLiveBridge",
    "MSFS2024LiveBridge",
    "GodotLiveBridge",
    "BridgeManager",
]
