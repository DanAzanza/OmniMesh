"""
Pure mathematical foundations for spherical and octahedral directional mappings in OmniMesh.
Blender-independent: operates with native math, NumPy, and mathutils.Vector (or headless Vector fallback).
"""

from __future__ import annotations

import logging
import math
from typing import Any, Tuple

import numpy as np

logger = logging.getLogger(__name__)

try:
    from mathutils import Vector
except ImportError:

    class Vector(tuple):  # type: ignore
        """Fallback Vector for headless testing."""

        def __new__(cls, coords: Any) -> Vector:
            return super().__new__(cls, tuple(float(x) for x in coords))

        @property
        def x(self) -> float:
            return self[0]

        @property
        def y(self) -> float:
            return self[1]

        @property
        def z(self) -> float:
            return self[2]

        @property
        def length(self) -> float:
            return math.sqrt(self[0] * self[0] + self[1] * self[1] + self[2] * self[2])

        def normalized(self) -> Vector:
            l_val = self.length
            if l_val < 1e-9:
                return Vector((0.0, 0.0, 0.0))
            return Vector((self[0] / l_val, self[1] / l_val, self[2] / l_val))

        def dot(self, o: Any) -> float:
            return self[0] * o[0] + self[1] * o[1] + self[2] * o[2]

        def cross(self, o: Any) -> Vector:
            return Vector(
                (self[1] * o[2] - self[2] * o[1], self[2] * o[0] - self[0] * o[2], self[0] * o[1] - self[1] * o[0])
            )

        def __neg__(self) -> Vector:
            return Vector((-self[0], -self[1], -self[2]))

        def __sub__(self, o: Any) -> Vector:
            return Vector((self[0] - o[0], self[1] - o[1], self[2] - o[2]))

        def __add__(self, o: Any) -> Vector:
            return Vector((self[0] + o[0], self[1] + o[1], self[2] + o[2]))

        def __mul__(self, scalar: Any) -> Vector:
            s = float(scalar)
            return Vector((self[0] * s, self[1] * s, self[2] * s))

        def __rmul__(self, scalar: Any) -> Vector:
            s = float(scalar)
            return Vector((self[0] * s, self[1] * s, self[2] * s))


class ImpostorMath:
    """Mathematical foundations for spherical/octahedral directional mappings."""

    @staticmethod
    def hemi_octahedral_to_vector(u: float, v: float) -> Any:
        """
        Maps 2D normalized UV coords [0, 1]^2 to upper-hemisphere 3D unit direction vector (Z >= 0).
        """
        nx = u * 2.0 - 1.0
        ny = v * 2.0 - 1.0

        x = (nx + ny) * 0.5
        y = (nx - ny) * 0.5
        z = max(0.0, 1.0 - abs(x) - abs(y))

        vec = Vector((x, y, z))
        return vec.normalized()

    @staticmethod
    def vector_to_hemi_octahedral(vec: Any) -> Tuple[float, float]:
        """
        Projects 3D unit direction vector (Z >= 0) to 2D normalized UV coords [0, 1]^2.
        Guards against nadir singularity when |x| + |y| + z < 1e-9 by falling back to horizon (0.5, 0.0).
        """
        x, y, z = float(vec[0]), float(vec[1]), max(0.0, float(vec[2]))
        denom = abs(x) + abs(y) + z
        if denom < 1e-9:
            return (0.5, 0.0)

        nx = x / denom
        ny = y / denom

        u = (nx + ny) * 0.5 + 0.5
        v = (nx - ny) * 0.5 + 0.5
        return max(0.0, min(1.0, u)), max(0.0, min(1.0, v))

    @staticmethod
    def full_octahedral_to_vector(u: float, v: float) -> Any:
        """
        Maps 2D normalized UV coords [0, 1]^2 to full 3D sphere unit direction vector.
        """
        px = u * 2.0 - 1.0
        py = v * 2.0 - 1.0

        x = px
        y = py
        z = 1.0 - abs(px) - abs(py)

        if z < 0.0:
            x_sign = 1.0 if px >= 0.0 else -1.0
            y_sign = 1.0 if py >= 0.0 else -1.0
            x = (1.0 - abs(py)) * x_sign
            y = (1.0 - abs(px)) * y_sign

        vec = Vector((x, y, z))
        return vec.normalized()

    @staticmethod
    def vector_to_full_octahedral(vec: Any) -> Tuple[float, float]:
        """
        Projects 3D unit direction vector across full sphere to 2D normalized UV coords [0, 1]^2.
        """
        x, y, z = float(vec[0]), float(vec[1]), float(vec[2])
        l1 = abs(x) + abs(y) + abs(z)
        if l1 < 1e-9:
            return (0.5, 0.5)

        nx = x / l1
        ny = y / l1

        if z < 0.0:
            x_sign = 1.0 if nx >= 0.0 else -1.0
            y_sign = 1.0 if ny >= 0.0 else -1.0
            ox = (1.0 - abs(ny)) * x_sign
            oy = (1.0 - abs(nx)) * y_sign
            nx, ny = ox, oy

        u = nx * 0.5 + 0.5
        v = ny * 0.5 + 0.5
        return max(0.0, min(1.0, u)), max(0.0, min(1.0, v))

    @staticmethod
    def compute_camera_basis(dir_vec: Any) -> Tuple[Any, Any, Any]:
        """
        Computes an orthonormal camera basis (right, up, forward) for a camera positioned
        at dir_vec looking toward origin, immune to polar singularity.
        """
        d = Vector(dir_vec).normalized()
        forward = -d

        # World up is +Z in Blender
        if abs(forward.z) < 0.999:
            up_ref = Vector((0.0, 0.0, 1.0))
        else:
            # At polar zenith/nadir, use +Y as reference to avoid degenerate cross product
            up_ref = Vector((0.0, 1.0, 0.0))

        right = up_ref.cross(-forward).normalized()
        up = (-forward).cross(right).normalized()
        return right, up, forward

    @staticmethod
    def compute_camera_space_tangent_normal(
        n_world: Any,
        cam_right: Any,
        cam_up: Any,
        cam_forward: Any,
        flip_green: bool = False,
    ) -> Tuple[float, float, float]:
        """
        Transforms world-space normal vector into Camera-Space Tangent coordinates.
        Guarantees that a surface facing directly toward the camera encodes to standard flat blue (0, 0, 1).
        """
        nx = (
            float(n_world[0]) * float(cam_right[0])
            + float(n_world[1]) * float(cam_right[1])
            + float(n_world[2]) * float(cam_right[2])
        )
        ny = (
            float(n_world[0]) * float(cam_up[0])
            + float(n_world[1]) * float(cam_up[1])
            + float(n_world[2]) * float(cam_up[2])
        )
        nz = -(
            float(n_world[0]) * float(cam_forward[0])
            + float(n_world[1]) * float(cam_forward[1])
            + float(n_world[2]) * float(cam_forward[2])
        )

        l_val = math.sqrt(nx * nx + ny * ny + nz * nz)
        if l_val > 1e-9:
            nx /= l_val
            ny /= l_val
            nz /= l_val
        else:
            nx, ny, nz = 0.0, 0.0, 1.0

        if flip_green:
            ny = -ny

        return nx, ny, nz

    @staticmethod
    def morphological_dilate_rgb(image_data: np.ndarray, iterations: int = 4) -> np.ndarray:
        """
        Vectorized push-pull morphological dilation to bleed RGB colors into transparent (Alpha=0) pixels.
        Prevents dark fringe mipmap bleeding at tile borders.
        Accumulates slice additions directly in-place without intermediate array copies.
        """
        if image_data.ndim != 3 or image_data.shape[2] < 4:
            return image_data

        result = image_data.copy()
        rgb = result[:, :, :3]
        alpha = result[:, :, 3]
        valid_mask = alpha > 0.01

        h, w = alpha.shape[:2]
        for _ in range(iterations):
            invalid_mask = ~valid_mask
            if not np.any(invalid_mask):
                break

            shifted_sum = np.zeros_like(rgb, dtype=np.float32)
            shifted_count = np.zeros((h, w), dtype=np.float32)

            for dy, dx in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                src_y = slice(max(0, -dy), min(h, h - dy))
                dst_y = slice(max(0, dy), min(h, h + dy))
                src_x = slice(max(0, -dx), min(w, w - dx))
                dst_x = slice(max(0, dx), min(w, w + dx))

                sub_valid = valid_mask[src_y, src_x]
                if not np.any(sub_valid):
                    continue

                shifted_sum[dst_y, dst_x] += rgb[src_y, src_x].astype(np.float32) * sub_valid[..., None]
                shifted_count[dst_y, dst_x] += sub_valid.astype(np.float32)

            fill_mask = invalid_mask & (shifted_count > 0)
            if not np.any(fill_mask):
                break

            rgb[fill_mask] = shifted_sum[fill_mask] / shifted_count[fill_mask, None]
            valid_mask = valid_mask | fill_mask

        result[:, :, :3] = rgb
        return result


__all__ = ["ImpostorMath", "Vector"]
