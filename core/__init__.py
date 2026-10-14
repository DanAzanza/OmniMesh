"""
OmniMesh Core Optimization & LOD Engine.
Blender 4.2+ and 5.2 LTS Compatible.

Provides modular mathematical metrics, mesh sanitization, decimation,
material optimization, collision decomposition, and normal handling.
"""

from .exceptions import (
    BridgeConnectionError,
    CollectionHierarchyError,
    DecimationError,
    ExportPipelineError,
    ImpostorBakeError,
    OmniMeshError,
    RiggingError,
    TopologyError,
)

__all__ = [
    "OmniMeshError",
    "DecimationError",
    "TopologyError",
    "CollectionHierarchyError",
    "BridgeConnectionError",
    "ExportPipelineError",
    "ImpostorBakeError",
    "RiggingError",
]
