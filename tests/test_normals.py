"""
Unit tests for OmniMesh Normal Management Module.
"""

from __future__ import annotations

from core.normals import NormalManager


def test_ensure_sharp_edge_attribute_null():
    assert NormalManager.ensure_sharp_edge_attribute(None) is None


def test_reproject_custom_split_normals_null_or_identical():
    assert NormalManager.reproject_custom_split_normals(None, None) is False

    dummy_obj = object()
    assert NormalManager.reproject_custom_split_normals(dummy_obj, dummy_obj) is False


def test_kdtree_normal_transfer_fallback_guards():
    assert NormalManager._kdtree_normal_transfer_fallback(None, None) is False
    assert NormalManager._kdtree_normal_transfer_fallback(object(), None) is False
    assert NormalManager._kdtree_normal_transfer_fallback(None, object()) is False
