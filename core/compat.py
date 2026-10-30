"""
Unified Headless Fallback & Blender 5.0+ / 5.2 LTS Compatibility Layer for OmniMesh.
Consolidates headless mathematical primitives (Vector, safe_invert_matrix),
Blender 5.2+ Slotted/Layered Action F-Curve access, and EEVEE Next material helpers.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
import logging
import math
from typing import TYPE_CHECKING, Any, Protocol, TypeVar, cast

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


def safe_invert_matrix(mat: M | None, identity_fallback: bool = True) -> M | None:
    """Safely inverts a transform matrix, guarding against singular or zero-determinant matrices."""
    if mat is None:
        return None
    if hasattr(mat, "inverted"):
        try:
            if hasattr(mat, "determinant"):
                det = mat.determinant()
                if not math.isfinite(det) or abs(det) < 1e-8:
                    logger.warning("Singular matrix detected in inversion (det=%s). Returning fallback.", det)
                    if identity_fallback:
                        if Matrix is not None and isinstance(mat, Matrix):
                            return cast(M, Matrix.Identity(4))
                        arr = getattr(mat, "arr", None)
                        if isinstance(arr, np.ndarray):
                            return cast(M, type(mat)(np.eye(arr.shape[0])))  # type: ignore[call-arg]
                    return cast(M, mat.copy() if hasattr(mat, "copy") else mat)
            return cast(M, mat.inverted())
        except (ValueError, AttributeError, RuntimeError) as exc:
            logger.warning("Matrix inversion failed (%s). Returning fallback.", exc)
            if identity_fallback:
                if Matrix is not None and isinstance(mat, Matrix):
                    return cast(M, Matrix.Identity(4))
                arr = getattr(mat, "arr", None)
                if isinstance(arr, np.ndarray):
                    return cast(M, type(mat)(np.eye(arr.shape[0])))  # type: ignore[call-arg]
            return cast(M, mat.copy() if hasattr(mat, "copy") else mat)
    return mat


def extract_action_fcurves(action: bpy.types.Action | None) -> list[bpy.types.FCurve]:
    """Extracts all F-Curves from an Action, supporting legacy Actions and Blender 5.2+ Slotted/Layered Actions."""
    if not action:
        return []
    act_any: Any = action
    raw_fcurves: list[bpy.types.FCurve] = []
    if hasattr(act_any, "fcurves") and act_any.fcurves is not None:
        try:
            raw_fcurves.extend(list(act_any.fcurves))
        except (AttributeError, RuntimeError, ReferenceError) as exc:
            logger.debug("Legacy fcurves extraction skipped: %s", exc)
    if hasattr(act_any, "layers"):
        try:
            for layer in getattr(act_any, "layers", []):
                for strip in getattr(layer, "strips", []):
                    for cb in getattr(strip, "channelbags", []):
                        if hasattr(cb, "fcurves") and cb.fcurves is not None:
                            raw_fcurves.extend(list(cb.fcurves))
        except (AttributeError, RuntimeError, ReferenceError) as exc:
            logger.debug("Layered fcurves extraction skipped: %s", exc)

    seen: set[tuple[str, int]] = set()
    unique_fcurves: list[bpy.types.FCurve] = []
    for fc in raw_fcurves:
        fc_key = (getattr(fc, "data_path", ""), getattr(fc, "array_index", 0))
        if fc_key not in seen:
            seen.add(fc_key)
            unique_fcurves.append(fc)
    return unique_fcurves


def ensure_action_fcurve(
    action: bpy.types.Action | None,
    data_path: str,
    index: int,
    slot_name: str = "ArmatureSlot",
) -> bpy.types.FCurve | None:
    """Creates an FCurve on an Action, supporting both legacy Actions and Blender 5.2+ Slotted/Layered Actions."""
    if not action:
        return None
    act_any: Any = action

    if hasattr(act_any, "fcurves") and act_any.fcurves is not None:
        try:
            return act_any.fcurves.new(data_path=data_path, index=index)
        except (RuntimeError, TypeError, AttributeError) as exc:
            logger.debug("action.fcurves.new failed, attempting layered fallback: %s", exc)

    if hasattr(act_any, "layers") or hasattr(act_any, "slots"):
        try:
            slot = None
            if hasattr(act_any, "slots"):
                if not act_any.slots:
                    try:
                        slot = act_any.slots.new(id_type="OBJECT", name=slot_name)
                    except TypeError:
                        try:
                            slot = act_any.slots.new(name=slot_name)
                        except TypeError:
                            slot = act_any.slots.new(slot_name)
                else:
                    slot = act_any.slots[0]

            layer = act_any.layers.new(name="BaseLayer") if not act_any.layers else act_any.layers[0]
            strip: Any = layer.strips.new(type="KEYFRAME") if not layer.strips else layer.strips[0]

            cb = None
            if hasattr(strip, "channelbag_for_slot") and slot:
                cb = strip.channelbag_for_slot(slot)

            if not cb and hasattr(strip, "channelbags"):
                for c in strip.channelbags:
                    if getattr(c, "slot", None) == slot or slot is None:
                        cb = c
                        break
                if not cb:
                    cb = strip.channelbags.new(slot=slot) if slot else strip.channelbags.new()

            if cb and hasattr(cb, "fcurves"):
                return cb.fcurves.new(data_path=data_path, index=index)
        except (RuntimeError, TypeError, AttributeError) as exc:
            logger.error("Failed to create slotted FCurve: %s", exc)

    return None


__all__ = [
    "MatrixLike",
    "Vector",
    "ensure_action_fcurve",
    "extract_action_fcurves",
    "safe_invert_matrix",
]
