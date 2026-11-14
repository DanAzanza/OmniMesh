"""
Unified Headless Fallback & Blender 5.0+ / 5.2 LTS Compatibility Layer for OmniMesh.
Consolidates headless mathematical primitives (Vector, safe_invert_matrix),
Blender 5.2+ Slotted/Layered Action F-Curve access, and EEVEE Next material helpers.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
import logging
import math
import os
from typing import TYPE_CHECKING, Protocol, TypeVar, cast, runtime_checkable

import numpy as np

if TYPE_CHECKING:
    import bpy
    from mathutils import Matrix, Vector
else:
    try:
        import bpy
    except ImportError:
        bpy = None

    try:
        from mathutils import Matrix
    except ImportError:
        Matrix = None

    try:
        from mathutils import Vector
    except ImportError:

        class Vector(tuple):  # type: ignore[no-redef]
            """Pure Python 3D vector fallback for standalone headless test environments."""

            def __new__(cls, coords: Iterable[float | int]) -> Vector:
                return super().__new__(cls, tuple(float(x) for x in coords))

            @property
            def x(self) -> float:
                return float(self[0])

            @property
            def y(self) -> float:
                return float(self[1])

            @property
            def z(self) -> float:
                return float(self[2])

            @property
            def length(self) -> float:
                return math.sqrt(self[0] * self[0] + self[1] * self[1] + self[2] * self[2])

            @property
            def length_squared(self) -> float:
                return float(self[0] * self[0] + self[1] * self[1] + self[2] * self[2])

            def copy(self) -> Vector:
                return Vector((self[0], self[1], self[2]))

            def normalized(self) -> Vector:
                l_val = self.length
                if l_val < 1e-9:
                    return Vector((0.0, 0.0, 0.0))
                return Vector((self[0] / l_val, self[1] / l_val, self[2] / l_val))

            def dot(self, other: Sequence[float]) -> float:
                return float(self[0] * other[0] + self[1] * other[1] + self[2] * other[2])

            def cross(self, other: Sequence[float]) -> Vector:
                return Vector(
                    (
                        self[1] * other[2] - self[2] * other[1],
                        self[2] * other[0] - self[0] * other[2],
                        self[0] * other[1] - self[1] * other[0],
                    )
                )

            def __neg__(self) -> Vector:
                return Vector((-self[0], -self[1], -self[2]))

            def __add__(self, other: Sequence[float]) -> Vector:
                return Vector((self[0] + other[0], self[1] + other[1], self[2] + other[2]))

            def __sub__(self, other: Sequence[float]) -> Vector:
                return Vector((self[0] - other[0], self[1] - other[1], self[2] - other[2]))

            def __mul__(self, scalar: float | int) -> Vector:
                s = float(scalar)
                return Vector((self[0] * s, self[1] * s, self[2] * s))

            def __rmul__(self, scalar: float | int) -> Vector:
                return self.__mul__(scalar)

            def __truediv__(self, scalar: float | int) -> Vector:
                s = float(scalar)
                return Vector((self[0] / s, self[1] / s, self[2] / s))


logger = logging.getLogger(__name__)


class MatrixLike(Protocol):
    """Structural protocol for mathutils.Matrix and headless test matrix doubles."""

    def determinant(self) -> float: ...
    def inverted(self) -> MatrixLike: ...
    def copy(self) -> MatrixLike: ...


M = TypeVar("M", bound=MatrixLike)


@runtime_checkable
class _HasDeterminant(Protocol):
    def determinant(self) -> float: ...


@runtime_checkable
class _HasInverted(Protocol):
    def inverted(self) -> object: ...


@runtime_checkable
class _HasCopy(Protocol):
    def copy(self) -> object: ...


@runtime_checkable
class _HasArr(Protocol):
    arr: np.ndarray


@runtime_checkable
class _HasLegacyFCurves(Protocol):
    fcurves: object


@runtime_checkable
class _HasActionLayers(Protocol):
    layers: object


@runtime_checkable
class _HasActionSlots(Protocol):
    slots: object


@runtime_checkable
class _HasActionLayerStrips(Protocol):
    strips: object


@runtime_checkable
class _HasStripChannelbags(Protocol):
    channelbags: object


@runtime_checkable
class _HasChannelbagForSlot(Protocol):
    def channelbag_for_slot(self, slot: object) -> object: ...


@runtime_checkable
class _HasChannelbagMethod(Protocol):
    def channelbag(self, slot: object, ensure: bool = False) -> object: ...


def _matrix_fallback(mat: M, identity_fallback: bool) -> M:
    """Returns an identity matrix matching ``mat`` type or a safe copy on failure."""
    if identity_fallback:
        if Matrix is not None and isinstance(mat, Matrix):
            return cast(M, Matrix.Identity(4))
        if isinstance(mat, _HasArr) and isinstance(mat.arr, np.ndarray):
            return cast(M, type(mat)(np.eye(mat.arr.shape[0])))  # type: ignore[call-arg]
    return cast(M, mat.copy() if isinstance(mat, _HasCopy) else mat)


def safe_invert_matrix(mat: M | None, identity_fallback: bool = True) -> M | None:
    """Safely inverts a transform matrix, guarding against singular or zero-determinant matrices."""
    if mat is None or not isinstance(mat, _HasInverted):
        return mat
    try:
        if isinstance(mat, _HasDeterminant):
            det = mat.determinant()
            if not math.isfinite(det) or abs(det) < 1e-8:
                logger.warning("Singular matrix detected in inversion (det=%s). Returning fallback.", det)
                return _matrix_fallback(mat, identity_fallback)
        return cast(M, mat.inverted())
    except (ValueError, AttributeError, RuntimeError) as exc:
        logger.warning("Matrix inversion failed (%s). Returning fallback.", exc)
        return _matrix_fallback(mat, identity_fallback)


def _collect_strip_fcurves(strip: object) -> list[bpy.types.FCurve]:
    """Collects all F-Curves from a strip's channelbags using Blender RNA attributes directly."""
    collected: list[bpy.types.FCurve] = []
    cbags = cast("_HasStripChannelbags", strip).channelbags
    for cb in cast("Iterable[object]", cbags):
        fcs = cast("_HasLegacyFCurves", cb).fcurves
        collected.extend(cast("Iterable[bpy.types.FCurve]", fcs))
    return collected


def _collect_mock_layered_fcurves(layers: Iterable[object]) -> list[bpy.types.FCurve]:
    """Collects F-Curves from protocol-compatible headless mock action layers."""
    collected: list[bpy.types.FCurve] = []
    for layer in layers:
        if not isinstance(layer, _HasActionLayerStrips) or not isinstance(layer.strips, Iterable):
            continue
        for strip in layer.strips:
            if not isinstance(strip, _HasStripChannelbags) or not isinstance(strip.channelbags, Iterable):
                continue
            for cb in strip.channelbags:
                if isinstance(cb, _HasLegacyFCurves) and isinstance(cb.fcurves, Iterable):
                    collected.extend(cast("Iterable[bpy.types.FCurve]", cb.fcurves))
    return collected


def _is_blender_action(obj: object) -> bool:
    """Returns True when running in Blender and ``obj`` is a live ``bpy.types.Action``."""
    return bpy is not None and isinstance(obj, bpy.types.Action)


def extract_action_fcurves(action: object) -> list[bpy.types.FCurve]:
    """Extracts all F-Curves from an Action, supporting legacy Actions and Blender 5.0+ Slotted/Layered Actions."""
    if not action:
        return []
    raw_fcurves: list[bpy.types.FCurve] = []
    if not _is_blender_action(action):
        if isinstance(action, _HasLegacyFCurves) and isinstance(action.fcurves, Iterable):
            try:
                raw_fcurves.extend(cast("Iterable[bpy.types.FCurve]", action.fcurves))
            except (AttributeError, RuntimeError, ReferenceError) as exc:
                logger.debug("Legacy fcurves extraction skipped: %s", exc)

    if _is_blender_action(action) or (isinstance(action, _HasActionLayers) and isinstance(action.layers, Iterable)):
        # Blender bpy_struct RNA properties resolve dynamically and fail runtime_checkable attribute checks.
        try:
            if _is_blender_action(action):
                for layer in cast("Iterable[object]", cast("_HasActionLayers", action).layers):
                    for strip in cast("Iterable[object]", cast("_HasActionLayerStrips", layer).strips):
                        raw_fcurves.extend(_collect_strip_fcurves(strip))
            else:
                raw_fcurves.extend(_collect_mock_layered_fcurves(cast("_HasActionLayers", action).layers))  # type: ignore[arg-type]
        except (AttributeError, RuntimeError, ReferenceError, TypeError) as exc:
            logger.debug("Layered fcurves extraction skipped: %s", exc)

    seen: set[tuple[str, int]] = set()
    unique_fcurves: list[bpy.types.FCurve] = []
    for fc in raw_fcurves:
        fc_key = (fc.data_path, fc.array_index)
        if fc_key not in seen:
            seen.add(fc_key)
            unique_fcurves.append(fc)
    return unique_fcurves


def _ensure_action_slot_direct(slot_owner: _HasActionSlots, slot_name: str) -> object:
    """Retrieves or creates the primary ActionSlot on an object known to expose Action.slots."""
    slots = cast("Sequence[object]", slot_owner.slots)
    if slots:
        return slots[0]
    try:
        return slot_owner.slots.new(id_type="OBJECT", name=slot_name)  # type: ignore[attr-defined]
    except TypeError:
        try:
            return slot_owner.slots.new(name=slot_name)  # type: ignore[attr-defined]
        except TypeError:
            return slot_owner.slots.new(slot_name)  # type: ignore[attr-defined]


def _ensure_action_slot(action: object, slot_name: str) -> object:
    """Retrieves or creates the primary ActionSlot on a Blender 5.0+ Action."""
    if not isinstance(action, _HasActionSlots):
        return None
    return _ensure_action_slot_direct(action, slot_name)


def _get_or_create_blender_channelbag(strip: object, slot: object) -> object:
    """Retrieves or creates a channelbag on a Blender 5.0+ ActionKeyframeStrip."""
    if isinstance(strip, _HasChannelbagMethod) and slot is not None:
        return strip.channelbag(slot, ensure=True)
    if isinstance(strip, _HasChannelbagForSlot) and slot is not None:
        cb = strip.channelbag_for_slot(slot)
        if cb:
            return cb
    cbags = cast("_HasStripChannelbags", strip).channelbags
    return cbags.new(slot=slot) if slot else cbags.new()  # type: ignore[attr-defined]


def _create_blender_layered_fcurve(
    action: bpy.types.Action,
    data_path: str,
    index: int,
    slot_name: str,
) -> bpy.types.FCurve | None:
    """Creates an FCurve on a live Blender 5.0+ Action via direct RNA attribute access."""
    slot = _ensure_action_slot_direct(cast("_HasActionSlots", action), slot_name)
    layers_col = cast("Sequence[object]", cast("_HasActionLayers", action).layers)
    layer = layers_col[0] if layers_col else layers_col.new(name="BaseLayer")  # type: ignore[attr-defined]
    strips_col = cast("Sequence[object]", cast("_HasActionLayerStrips", layer).strips)
    strip: object = strips_col[0] if strips_col else strips_col.new(type="KEYFRAME")  # type: ignore[attr-defined]
    cb = _get_or_create_blender_channelbag(strip, slot)
    fcs = cast("_HasLegacyFCurves", cb).fcurves
    return cast("bpy.types.FCurve", fcs.new(data_path=data_path, index=index))  # type: ignore[attr-defined]


def ensure_action_fcurve(
    action: object,
    data_path: str,
    index: int,
    slot_name: str = "ArmatureSlot",
) -> bpy.types.FCurve | None:
    """Creates an FCurve on an Action, supporting both legacy Actions and Blender 5.0+ Slotted/Layered Actions."""
    if not action:
        return None

    if isinstance(action, _HasLegacyFCurves) and action.fcurves is not None:
        try:
            return action.fcurves.new(data_path=data_path, index=index)  # type: ignore[attr-defined]
        except (RuntimeError, TypeError, AttributeError) as exc:
            logger.debug("action.fcurves.new failed, attempting layered fallback: %s", exc)

    if (bpy is not None and isinstance(action, bpy.types.Action)) or isinstance(
        action, (_HasActionLayers, _HasActionSlots)
    ):
        try:
            if bpy is not None and isinstance(action, bpy.types.Action):
                return _create_blender_layered_fcurve(action, data_path, index, slot_name)

            slot = _ensure_action_slot(action, slot_name)
            layers = cast("Sequence[object]", cast("_HasActionLayers", action).layers)
            layer = layers.new(name="BaseLayer") if not layers else layers[0]  # type: ignore[attr-defined]
            layer_strips = cast("Sequence[object]", cast("_HasActionLayerStrips", layer).strips)
            strip: object = layer_strips.new(type="KEYFRAME") if not layer_strips else layer_strips[0]  # type: ignore[attr-defined]

            cb: object = None
            if isinstance(strip, _HasChannelbagForSlot) and slot is not None:
                cb = strip.channelbag_for_slot(slot)

            if not cb and isinstance(strip, _HasStripChannelbags):
                channelbags = cast("Iterable[object]", strip.channelbags)
                for c in channelbags:
                    c_slot = getattr(c, "slot", None)
                    if c_slot == slot or slot is None:
                        cb = c
                        break
                if not cb:
                    cb = strip.channelbags.new(slot=slot) if slot else strip.channelbags.new()  # type: ignore[attr-defined]

            if isinstance(cb, _HasLegacyFCurves) and cb.fcurves is not None:
                return cb.fcurves.new(data_path=data_path, index=index)  # type: ignore[attr-defined]
        except (RuntimeError, TypeError, AttributeError) as exc:
            logger.error("Failed to create slotted FCurve: %s", exc)

    return None


def set_node_prop(node: bpy.types.Node | None, prop_name: str, value: object) -> None:
    """Safely assigns a dynamic property to a Node across Blender versions and stub definitions."""
    if node is None:
        return
    try:
        setattr(node, prop_name, value)
    except (AttributeError, TypeError, ValueError) as exc:
        logger.debug("Failed setting %s on node %s: %s", prop_name, node, exc)


def set_socket_default_value(socket: bpy.types.NodeSocket | None, value: object) -> None:
    """Safely assigns default_value to a NodeSocket across Blender versions and stub types."""
    if socket is None:
        return
    try:
        setattr(socket, "default_value", value)  # noqa: B010
    except (AttributeError, TypeError, ValueError) as exc:
        logger.debug("Failed to set default_value on socket %s: %s", socket, exc)


def get_socket_default_value(socket: bpy.types.NodeSocket | None, fallback: object = 0.0) -> object:
    """Safely retrieves default_value from a NodeSocket across Blender versions and stub types."""
    if socket is None:
        return fallback
    return getattr(socket, "default_value", fallback)  # noqa: B009


def count_mesh_triangles(mesh_data: bpy.types.Mesh | None) -> int:
    """Computes accurate triangle count in O(1) via loop-poly invariant (n_loops - 2 * n_polys)."""
    if mesh_data is None:
        return 0
    try:
        loops = mesh_data.loops
        polys = mesh_data.polygons
        if loops is not None and polys is not None:
            n_loops = len(loops)
            n_polys = len(polys)
            if n_polys == 0:
                return 0
            return max(0, n_loops - 2 * n_polys)
    except (AttributeError, TypeError) as exc:
        logger.debug("Loop-poly triangle count invariant fallback triggered: %s", exc)
    return 0


def import_scene_asset(filepath: str) -> bool:
    """Dispatches to the appropriate Blender 5.0+ scene import operator by file extension."""
    if bpy is None:
        return False

    ext = os.path.splitext(filepath)[1].lower()
    if ext == ".fbx":
        bpy.ops.import_scene.fbx(filepath=filepath)
        return True
    if ext == ".obj":
        bpy.ops.wm.obj_import(filepath=filepath)
        return True
    if ext in (".gltf", ".glb"):
        bpy.ops.import_scene.gltf(filepath=filepath)
        return True
    return False


def ensure_unique_mesh_data(obj: bpy.types.Object | None) -> bool:
    """Isolates shared multi-user mesh data (Copy-on-Write) prior to in-place mutations."""
    if obj is None or obj.data is None:
        return False
    if obj.data.users <= 1:
        return True
    try:
        copied = obj.data.copy()
        if copied is None:
            return False
        obj.data = copied
        logger.info("Unlinked multi-user mesh data for '%s' prior to in-place mutation", obj.name)
        return True
    except (RuntimeError, AttributeError) as exc:
        logger.warning("Failed unlinking multi-user mesh for '%s': %s", obj.name, exc)
        return False


def recenter_pivot_stationary(obj: bpy.types.Object | None) -> None:
    """Recenters an object's origin to its local AABB midpoint without moving world geometry."""
    if not obj or obj.type != "MESH" or obj.data is None:
        return
    mesh = cast("bpy.types.Mesh", obj.data)
    if not mesh.vertices or len(mesh.vertices) == 0:
        return

    verts = mesh.vertices
    min_co = [min(v.co[i] for v in verts) for i in range(3)]
    max_co = [max(v.co[i] for v in verts) for i in range(3)]
    center_coords = [(min_co[i] + max_co[i]) * 0.5 for i in range(3)]
    center_len = math.sqrt(sum(c * c for c in center_coords))
    if center_len < 1e-5:
        return

    center_offset = Vector(center_coords) if Vector is not None else center_coords
    for v in verts:
        try:
            v.co -= center_offset
        except (TypeError, AttributeError):
            v.co = type(v.co)([v.co[i] - center_coords[i] for i in range(3)])

    if obj.matrix_world is not None and Matrix is not None:
        trans_mat = Matrix.Translation((center_coords[0], center_coords[1], center_coords[2]))
        obj.matrix_world = obj.matrix_world @ trans_mat

    mesh.update()


def run_cleanup_step(warnings: list[str], label: str, fn: Callable[[], object]) -> None:
    """Runs an isolated cleanup step and captures non-fatal Blender/runtime rollback failures."""
    try:
        fn()
    except (RuntimeError, ReferenceError, AttributeError) as exc:
        warnings.append(f"{label}: {exc}")


__all__ = [
    "MatrixLike",
    "Vector",
    "count_mesh_triangles",
    "ensure_action_fcurve",
    "ensure_unique_mesh_data",
    "extract_action_fcurves",
    "get_socket_default_value",
    "import_scene_asset",
    "recenter_pivot_stationary",
    "run_cleanup_step",
    "safe_invert_matrix",
    "set_node_prop",
    "set_socket_default_value",
]
