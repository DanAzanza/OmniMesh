"""
Unit tests for Rigging & Skinning Weight Sanitization.
"""

import pytest

from core.rigging import normalize_weights_pure


def test_weight_normalization_basic():
    # 3 weights, sum = 0.8
    raw = {0: 0.4, 1: 0.3, 2: 0.1}
    normalized = normalize_weights_pure(raw, max_influences=4, micro_epsilon=0.01)

    assert len(normalized) == 3
    assert abs(sum(normalized.values()) - 1.0) < 1e-5
    assert normalized[0] == pytest.approx(0.4 / 0.8, rel=1e-3)


def test_max_influences_clamping():
    # 6 weights, should clamp to top 4
    raw = {0: 0.35, 1: 0.25, 2: 0.15, 3: 0.10, 4: 0.08, 5: 0.07}
    normalized = normalize_weights_pure(raw, max_influences=4, micro_epsilon=0.01)

    assert len(normalized) == 4
    assert 4 not in normalized
    assert 5 not in normalized
    assert abs(sum(normalized.values()) - 1.0) < 1e-5


def test_micro_weight_pruning():
    # Weights below 0.01 should be dropped
    raw = {0: 0.70, 1: 0.29, 2: 0.005, 3: 0.005}
    normalized = normalize_weights_pure(raw, max_influences=4, micro_epsilon=0.01)

    assert 2 not in normalized
    assert 3 not in normalized
    assert len(normalized) == 2
    assert abs(sum(normalized.values()) - 1.0) < 1e-5


def test_zero_sum_singularity_fallback():
    # All weights below epsilon or empty
    raw_all_micro = {0: 0.002, 1: 0.003}
    fallback_1 = normalize_weights_pure(raw_all_micro, max_influences=4, micro_epsilon=0.01)
    # Should retain best non-zero index
    assert sum(fallback_1.values()) == 1.0
    assert fallback_1[1] == 1.0

    raw_empty = {}
    fallback_2 = normalize_weights_pure(raw_empty, max_influences=4, micro_epsilon=0.01, anchor_idx=99)
    assert fallback_2 == {99: 1.0}
