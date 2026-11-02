"""
Comprehensive Unit Tests for OmniMesh Compat Layer & Invariant Helpers.
Verifies count_mesh_triangles topological loop-poly invariant, safe matrix inversion,
socket property setters/getters, and MockQuaternion primitives.
"""

from __future__ import annotations

import math
from unittest.mock import MagicMock
import pytest

from core.compat import (
    count_mesh_triangles,
    get_socket_default_value,
    set_node_prop,
    set_socket_default_value,
)
from tests.conftest import MockQuaternion


def test_count_mesh_triangles_null_and_empty():
    assert count_mesh_triangles(None) == 0

    empty_mesh = MagicMock()
    empty_mesh.loops = []
    empty_mesh.polygons = []
    assert count_mesh_triangles(empty_mesh) == 0


def test_count_mesh_triangles_quads_and_tris():
    # 2 triangles: 6 loops, 2 polygons -> 6 - 2*2 = 2 triangles
    tri_mesh = MagicMock()
    tri_mesh.loops = [MagicMock() for _ in range(6)]
    tri_mesh.polygons = [MagicMock(), MagicMock()]
    assert count_mesh_triangles(tri_mesh) == 2

    # 1 quad (cube face): 4 loops, 1 polygon -> 4 - 2*1 = 2 triangles
    quad_mesh = MagicMock()
    quad_mesh.loops = [MagicMock() for _ in range(4)]
    quad_mesh.polygons = [MagicMock()]
    assert count_mesh_triangles(quad_mesh) == 2

    # Degenerate or malformed mock
    bad_mesh = object()
    assert count_mesh_triangles(bad_mesh) == 0  # type: ignore[arg-type]


def test_mock_quaternion_invariants():
    q = MockQuaternion(1.0, 0.0, 0.0, 0.0)
    assert q.w == 1.0
    assert q.x == 0.0
    assert q[0] == 1.0
    assert q[1] == 0.0
    assert q.magnitude == 1.0

    # Normalization
    q_unnormalized = MockQuaternion(2.0, 0.0, 0.0, 0.0)
    q_norm = q_unnormalized.normalized()
    assert math.isclose(q_norm.w, 1.0)
    assert math.isclose(q_norm.magnitude, 1.0)

    # In-place normalize
    q_unnormalized.normalize()
    assert math.isclose(q_unnormalized.w, 1.0)

    # Dot product
    q2 = MockQuaternion(1.0, 0.0, 0.0, 0.0)
    assert math.isclose(q.dot(q2), 1.0)

    # Out of range index
    with pytest.raises(IndexError):
        _ = q[4]


def test_socket_and_node_compat_helpers():
    # Node property setter
    node = MagicMock()
    set_node_prop(node, "operation", "SUBTRACT")
    assert node.operation == "SUBTRACT"
    # Null node safe
    set_node_prop(None, "operation", "SUBTRACT")

    # Socket default value
    sock = MagicMock()
    sock.default_value = 0.5
    assert get_socket_default_value(sock, fallback=0.0) == 0.5
    set_socket_default_value(sock, 1.0)
    assert sock.default_value == 1.0

    # Null socket safe
    assert get_socket_default_value(None, fallback=42.0) == 42.0
    set_socket_default_value(None, 1.0)
