"""
Unit tests for OmniMesh Decimation & Simplification Engine.
"""

from __future__ import annotations

from core.decimator import MeshDecimator


def test_tag_boundaries_and_uv_seams_null():
    assert MeshDecimator.tag_boundaries_and_uv_seams(None) == set()


def test_apply_planar_limited_dissolve_null_or_zero():
    # Should not raise exception
    MeshDecimator.apply_planar_limited_dissolve(None, 0.0)
    MeshDecimator.apply_planar_limited_dissolve(None, 0.5)


def test_inject_curvature_weights_null():
    # Should not raise exception
    MeshDecimator.inject_curvature_weights(None, None, set())


def test_execute_decimate_qem_null_or_identity():
    # Should return early and not raise
    MeshDecimator.execute_decimate_qem(None, 1.0)
    MeshDecimator.execute_decimate_qem(None, 0.5)


def test_prepare_and_clean_shape_keys_null():
    # Should not raise exception
    MeshDecimator.prepare_and_clean_shape_keys(None, purge=True)
    MeshDecimator.prepare_and_clean_shape_keys(None, purge=False)
