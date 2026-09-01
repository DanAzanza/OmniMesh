"""
Unit tests for Rigging & Skinning Weight Sanitization, Matrix Math Traps & Kinematic Bone Pruning.
"""

import numpy as np
import pytest

from core.rigging import (
    KinematicBonePruner,
    WeightSanitizer,
    _safe_invert_matrix,
    armature_rest_pose_context,
    compute_rest_pose_inverted_matrix,
    normalize_weights_pure,
)


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


def test_max_influences_edge_limits():
    raw = {0: 0.5, 1: 0.3, 2: 0.2}
    # Max influence = 1 (rigid skinning / LOD5)
    norm_1 = normalize_weights_pure(raw, max_influences=1)
    assert len(norm_1) == 1
    assert norm_1 == {0: 1.0}

    # Zero or negative max_influences clamped to 1
    norm_zero = normalize_weights_pure(raw, max_influences=0)
    assert len(norm_zero) == 1
    assert norm_zero == {0: 1.0}

    norm_neg = normalize_weights_pure(raw, max_influences=-5)
    assert len(norm_neg) == 1
    assert norm_neg == {0: 1.0}


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


def test_nan_inf_and_negative_weight_sanitization():
    # Non-finite or corrupt GPU skinning inputs
    raw_corrupt = {0: float("nan"), 1: float("inf"), 2: -0.5, 3: 0.8, 4: 0.2}
    normalized = normalize_weights_pure(raw_corrupt, max_influences=4, anchor_idx=0)
    assert len(normalized) == 2
    assert 3 in normalized and 4 in normalized
    assert abs(sum(normalized.values()) - 1.0) < 1e-5
    assert normalized[3] == pytest.approx(0.8, rel=1e-3)
    assert normalized[4] == pytest.approx(0.2, rel=1e-3)

    # Completely non-finite weights
    raw_all_nan = {0: float("nan"), 1: float("-inf")}
    fallback_nan = normalize_weights_pure(raw_all_nan, anchor_idx=7)
    assert fallback_nan == {7: 1.0}

    # None or non-dict input
    assert normalize_weights_pure(None, anchor_idx=3) == {3: 1.0}  # type: ignore
    assert normalize_weights_pure("invalid", anchor_idx=2) == {2: 1.0}  # type: ignore


def test_negative_bone_index_sanitization():
    # Negative bone indices are illegal and must be pruned
    raw_neg_indices = {-1: 0.5, -2: 0.3, 0: 0.8}
    normalized = normalize_weights_pure(raw_neg_indices, anchor_idx=0)
    assert -1 not in normalized
    assert -2 not in normalized
    assert normalized == {0: 1.0}


def test_invalid_and_non_finite_parameter_guards():
    raw = {0: 0.5, 1: 0.5}
    # Non-finite max_influences
    norm_nan_inf = normalize_weights_pure(raw, max_influences=float("nan"))  # type: ignore
    assert abs(sum(norm_nan_inf.values()) - 1.0) < 1e-5

    # Non-finite micro_epsilon
    norm_nan_eps = normalize_weights_pure(raw, micro_epsilon=float("nan"))  # type: ignore
    assert abs(sum(norm_nan_eps.values()) - 1.0) < 1e-5

    # Negative anchor index
    norm_neg_anchor = normalize_weights_pure({}, anchor_idx=-10)
    assert norm_neg_anchor == {0: 1.0}


def test_exact_one_sum_rounding_absorption():
    # 3 equal weights 1/3 (0.333333, 0.333333, 0.333333) normally sum to 0.999999
    raw = {0: 1.0, 1: 1.0, 2: 1.0}
    normalized = normalize_weights_pure(raw, max_influences=3)
    # Sum must strictly equal 1.0
    assert sum(normalized.values()) == 1.0
    assert len(normalized) == 3


def test_compute_rest_pose_inverted_matrix():
    class MockMatrix:
        def __init__(self, arr: np.ndarray):
            self.arr = arr

        def __matmul__(self, other):
            return MockMatrix(self.arr @ other.arr)

        def determinant(self):
            return float(np.linalg.det(self.arr))

        def copy(self):
            return MockMatrix(self.arr.copy())

        def inverted(self):
            det = np.linalg.det(self.arr)
            if abs(det) < 1e-8:
                raise ValueError("Singular matrix cannot be inverted")
            return MockMatrix(np.linalg.inv(self.arr))

        def __eq__(self, other):
            return np.allclose(self.arr, other.arr, atol=1e-5)

    m_arm_world = MockMatrix(np.eye(4))
    m_bone_rest = MockMatrix(np.eye(4))
    m_parent_inv = MockMatrix(np.eye(4))
    m_basis = MockMatrix(np.eye(4))

    result = compute_rest_pose_inverted_matrix(m_arm_world, m_bone_rest, m_parent_inv, m_basis)
    assert np.allclose(result.arr, np.eye(4))

    # Target mesh with translation
    t_mat = np.eye(4)
    t_mat[0, 3] = 10.0  # translate X by +10
    target_rest = MockMatrix(t_mat)

    res_local = compute_rest_pose_inverted_matrix(
        m_arm_world, m_bone_rest, m_parent_inv, m_basis, target_mesh_rest_world=target_rest
    )
    # Target inverted should have translation X = -10
    assert np.isclose(res_local.arr[0, 3], -10.0)


def test_singular_matrix_inversion_guard():
    class SingularMatrix:
        def __init__(self, arr: np.ndarray):
            self.arr = arr

        def __matmul__(self, other):
            return SingularMatrix(self.arr @ other.arr)

        def determinant(self):
            return float(np.linalg.det(self.arr))

        def copy(self):
            return SingularMatrix(self.arr.copy())

        def inverted(self):
            raise ValueError("Singular matrix invert failed")

    # Singular matrix with 0 scale on X axis
    zero_scale_mat = np.eye(4)
    zero_scale_mat[0, 0] = 0.0
    singular_target = SingularMatrix(zero_scale_mat)

    m_arm = SingularMatrix(np.eye(4))
    m_bone = SingularMatrix(np.eye(4))
    m_parent = SingularMatrix(np.eye(4))
    m_basis = SingularMatrix(np.eye(4))

    # Should not throw ValueError; falls back gracefully
    res = compute_rest_pose_inverted_matrix(m_arm, m_bone, m_parent, m_basis, target_mesh_rest_world=singular_target)
    assert res is not None

    # Safe invert helper directly
    assert _safe_invert_matrix(None) is None
    inv_sing = _safe_invert_matrix(singular_target)
    assert inv_sing is not None


def test_armature_rest_pose_context_manager():
    class DummyArmatureData:
        def __init__(self, initial_pos="POSE"):
            self.pose_position = initial_pos

    class DummyArmature:
        def __init__(self, initial_pos="POSE"):
            self.data = DummyArmatureData(initial_pos)

    arm = DummyArmature("POSE")
    with armature_rest_pose_context(arm):
        assert arm.data.pose_position == "REST"
    assert arm.data.pose_position == "POSE"

    # Context manager restores on exception
    try:
        with armature_rest_pose_context(arm):
            assert arm.data.pose_position == "REST"
            raise RuntimeError("Test Error")
    except RuntimeError:
        pass
    assert arm.data.pose_position == "POSE"

    # None armature safely yields
    with armature_rest_pose_context(None):
        pass


def test_weight_sanitizer_and_pruner_guards():
    # Null / non-mesh guards
    assert WeightSanitizer.normalize_and_clamp_weights(None) == {
        "normalized": 0,
        "singularities_fixed": 0,
        "purged_vgs": 0,
    }

    class NonMesh:
        type = "CAMERA"

    assert WeightSanitizer.normalize_and_clamp_weights(NonMesh()) == {
        "normalized": 0,
        "singularities_fixed": 0,
        "purged_vgs": 0,
    }

    assert KinematicBonePruner.prune_kinematic_subtrees(None, None, 10.0, 1.0, 1080) == 0
    assert KinematicBonePruner.prune_kinematic_subtrees(NonMesh(), None, float("nan"), float("inf"), -100) == 0
