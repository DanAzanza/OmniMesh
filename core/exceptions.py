"""
Typed Domain Exceptions for OmniMesh.
Enforces the Fail-Fast principle (AGENTS.md Section 3 & 4) across decimation,
topology sanitization, and collection hierarchy operations.
"""

from __future__ import annotations


class OmniMeshError(Exception):
    """Base exception for all domain errors raised by OmniMesh."""


class DecimationError(OmniMeshError):
    """Raised when geometric decimation, modifier application, or planar dissolve fails."""


class TopologyError(OmniMeshError):
    """Raised when mesh topology is corrupt, non-manifold, or unfixable."""


class CollectionHierarchyError(OmniMeshError):
    """Raised when collection hierarchy, cloning, or Outliner isolation operations fail."""


class ExportPipelineError(OmniMeshError):
    """Raised when engine export generation, packing, or file writing fails."""


class ImpostorBakeError(OmniMeshError):
    """Raised when billboard impostor rendering, camera rig setup, or texture atlas baking fails."""


class RiggingError(OmniMeshError):
    """Raised when skeletal bone weight normalization, clamping, or kinematic pruning fails."""


class DependencyInjectionError(OmniMeshError):
    """Raised when a required database dependency (e.g. blend_data) is missing or invalid."""


__all__ = [
    "OmniMeshError",
    "DecimationError",
    "TopologyError",
    "CollectionHierarchyError",
    "ExportPipelineError",
    "ImpostorBakeError",
    "RiggingError",
    "DependencyInjectionError",
]
