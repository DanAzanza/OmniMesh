"""
Discrete Generator-Based Batch Mesh Iterator for OmniMesh.
Blender 4.2+ and 5.2 LTS Compatible.

Provides:
- BatchProgress: Dataclass tracking step-by-step progress and triangle counts.
- BatchMeshIterator: Pure engine generator processing one mesh per step,
  guaranteeing deterministic BMesh cleanup and periodic orphan purging.
"""

from __future__ import annotations

from dataclasses import dataclass
import gc
import logging
from typing import Any, Iterator, Optional

logger = logging.getLogger(__name__)

try:
    import bmesh
    import bpy
except ImportError:
    bpy = None
    bmesh = None

try:
    from .decimator import MeshDecimator
    from .sanitizer import MeshSanitizer
except (ImportError, ValueError):
    from core.decimator import MeshDecimator
    from core.sanitizer import MeshSanitizer


@dataclass
class BatchProgress:
    """Progress snapshot for a single step in batch mesh processing."""

    index: int
    total: int
    asset_name: str
    stage: str
    initial_tris: int = 0
    final_tris: int = 0
    success: bool = True
    error_message: str = ""


class BatchMeshIterator:
    """
    Generator yielding progressive simplification steps for a collection of meshes.
    Completely decoupled from window manager / modal events so it can be consumed
    either by a modal operator in interactive Blender or by headless CLI runners.
    """

    def __init__(
        self,
        objects: list[Any],
        target_ratio: float = 0.5,
        preserve_boundaries: bool = True,
        planar_dissolve: bool = True,
    ) -> None:
        self.objects = [o for o in objects if getattr(o, "type", "") == "MESH"]
        self.total = len(self.objects)
        self.target_ratio = max(0.01, min(1.0, float(target_ratio)))
        self.preserve_boundaries = preserve_boundaries
        self.planar_dissolve = planar_dissolve

    def iterate(self, context: Optional[Any] = None) -> Iterator[BatchProgress]:
        """
        Yields BatchProgress for each mesh processed.
        Performs periodic orphan cleanup and explicit garbage collection.
        """
        if not bpy:
            return

        for idx, obj in enumerate(self.objects):
            name = getattr(obj, "name", f"Mesh_{idx}")
            initial_tris = 0
            final_tris = 0

            try:
                mesh_data = getattr(obj, "data", None)
                if not mesh_data:
                    yield BatchProgress(
                        index=idx + 1,
                        total=self.total,
                        asset_name=name,
                        stage="SKIPPED",
                        success=False,
                        error_message="Object has no mesh datablock",
                    )
                    continue

                initial_tris = len(mesh_data.polygons)

                # Execute mesh cleanup and decimation
                bm = bmesh.new()
                try:
                    bm.from_mesh(mesh_data)
                    MeshSanitizer.clean_and_repair(bm)
                    MeshDecimator.decimate_ratio(
                        bm,
                        ratio=self.target_ratio,
                        preserve_boundaries=self.preserve_boundaries,
                        planar_dissolve=self.planar_dissolve,
                    )
                    bm.to_mesh(mesh_data)
                    mesh_data.update()
                finally:
                    bm.free()

                final_tris = len(mesh_data.polygons)

                # Clean orphans every 10 meshes to prevent memory bloat
                if (idx + 1) % 10 == 0:
                    try:
                        bpy.data.orphans_purge(do_recursive=True)
                    except Exception as exc:
                        logger.debug("Orphans purge exception during batch: %s", exc)
                    gc.collect()

                yield BatchProgress(
                    index=idx + 1,
                    total=self.total,
                    asset_name=name,
                    stage="COMPLETED",
                    initial_tris=initial_tris,
                    final_tris=final_tris,
                    success=True,
                )

            except Exception as exc:
                logger.warning("Batch processing failed on mesh '%s': %s", name, exc)
                yield BatchProgress(
                    index=idx + 1,
                    total=self.total,
                    asset_name=name,
                    stage="FAILED",
                    initial_tris=initial_tris,
                    final_tris=initial_tris,
                    success=False,
                    error_message=str(exc),
                )


__all__ = ["BatchProgress", "BatchMeshIterator"]
