"""
OmniMesh Base Engine Exporter Interface and Shared Export Transaction Helpers.
"""

from __future__ import annotations

import abc
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
import logging
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    import bpy

try:
    from ..core.exceptions import ExportPipelineError
except (ImportError, ValueError):
    try:
        from core.exceptions import ExportPipelineError
    except (ImportError, ValueError):
        ExportPipelineError = RuntimeError  # type: ignore

logger = logging.getLogger(__name__)


def _collect_target_layer_collections(
    layer_col: bpy.types.LayerCollection,
    target_cols: set[bpy.types.Collection],
    out_lcs: list[bpy.types.LayerCollection],
) -> bool:
    """Collects ancestor and matching LayerCollections containing any target Collection."""
    matched = layer_col.collection in target_cols
    for child in layer_col.children:
        if _collect_target_layer_collections(child, target_cols, out_lcs):
            matched = True
    if matched and layer_col not in out_lcs:
        out_lcs.append(layer_col)
    return matched


def _reveal_collection_hierarchy(
    vl: bpy.types.ViewLayer | None,
    objects: Sequence[bpy.types.Object],
    warnings: list[str],
) -> tuple[dict[bpy.types.Collection, bool], dict[bpy.types.LayerCollection, tuple[bool, bool]]]:
    """Unhides ancestor Collections and ViewLayer LayerCollections for exportable objects."""
    target_cols: set[bpy.types.Collection] = set()
    for obj in objects:
        target_cols.update(obj.users_collection)

    orig_cols: dict[bpy.types.Collection, bool] = {}
    orig_lcs: dict[bpy.types.LayerCollection, tuple[bool, bool]] = {}

    if target_cols and vl is not None:
        matched_lcs: list[bpy.types.LayerCollection] = []
        _collect_target_layer_collections(vl.layer_collection, target_cols, matched_lcs)
        for lc in reversed(matched_lcs):
            orig_lcs[lc] = (lc.hide_viewport, lc.exclude)
            try:
                if lc.exclude:
                    lc.exclude = False
                if lc.hide_viewport:
                    lc.hide_viewport = False
            except (RuntimeError, AttributeError, ReferenceError) as exc:
                warnings.append(f"unhide layer_collection {lc.name}: {exc}")

    for col in target_cols:
        orig_cols[col] = col.hide_viewport
        try:
            if col.hide_viewport:
                col.hide_viewport = False
        except (RuntimeError, AttributeError, ReferenceError) as exc:
            warnings.append(f"unhide collection {col.name}: {exc}")

    return orig_cols, orig_lcs


@contextmanager
def scoped_export_visibility(
    context: bpy.types.Context,
    objects: Sequence[bpy.types.Object],
    warnings: list[str] | None = None,
) -> Iterator[None]:
    """Temporarily reveals objects and their owning Collections/LayerCollections, restoring all on exit."""
    local_warnings = warnings if warnings is not None else []
    vl = context.view_layer
    valid_objs = [o for o in objects if o is not None]

    orig_obj_states: dict[bpy.types.Object, tuple[bool, bool]] = {}
    orig_billboards: list[tuple[bpy.types.Object, bpy.types.Constraint, bool, tuple[float, float, float]]] = []
    for obj in valid_objs:
        hv = obj.hide_viewport
        hg = obj.hide_get(view_layer=vl) if vl else hv
        orig_obj_states[obj] = (hv, hg)
        for constraint in obj.constraints:
            if constraint.name == "OmniMesh_Viewport_Billboard":
                rot = obj.rotation_euler
                orig_billboards.append((obj, constraint, bool(constraint.mute), (rot[0], rot[1], rot[2])))

    orig_cols, orig_lcs = _reveal_collection_hierarchy(vl, valid_objs, local_warnings)

    try:
        for obj, constraint, _mute, _rot in orig_billboards:
            try:
                constraint.mute = True
                obj.rotation_euler = (0.0, 0.0, 0.0)  # type: ignore[assignment]
            except (RuntimeError, AttributeError, ReferenceError) as exc:
                local_warnings.append(f"mute billboard {obj.name}: {exc}")

        for obj in valid_objs:
            try:
                if vl is not None:
                    obj.hide_set(False, view_layer=vl)
                obj.hide_viewport = False
            except (RuntimeError, AttributeError, ReferenceError) as exc:
                local_warnings.append(f"unhide {obj.name}: {exc}")
        yield
    finally:
        for obj, constraint, orig_mute, orig_rot in orig_billboards:
            try:
                constraint.mute = orig_mute
                obj.rotation_euler = orig_rot  # type: ignore[assignment]
            except (RuntimeError, AttributeError, ReferenceError) as exc:
                local_warnings.append(f"restore billboard {obj.name}: {exc}")

        for obj, (hv, hg) in orig_obj_states.items():
            try:
                obj.hide_viewport = hv
                if vl is not None:
                    obj.hide_set(hg, view_layer=vl)
            except (RuntimeError, AttributeError, ReferenceError) as exc:
                local_warnings.append(f"restore object {obj.name}: {exc}")

        for lc, (lc_hv, lc_ex) in orig_lcs.items():
            try:
                lc.hide_viewport = lc_hv
                lc.exclude = lc_ex
            except (RuntimeError, AttributeError, ReferenceError) as exc:
                local_warnings.append(f"restore layer_collection: {exc}")

        for col, col_hv in orig_cols.items():
            try:
                col.hide_viewport = col_hv
            except (RuntimeError, AttributeError, ReferenceError) as exc:
                local_warnings.append(f"restore collection: {exc}")


class EngineExporterBase(abc.ABC):
    """Abstract Base Class for all OmniMesh Multi-Engine Exporters."""

    @classmethod
    @abc.abstractmethod
    def export_asset(
        cls,
        context: Optional[bpy.types.Context],
        export_dir: str,
        asset_name: str,
        **kwargs: object,
    ) -> tuple[bool, str]:
        """
        Exports asset and associated LODs/colliders to target engine format.

        Returns (success, result_message).
        """
