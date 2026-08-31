"""
Unit tests for OmniMesh Animation Rig Sanitizer & Action Validator.
"""

from __future__ import annotations

from core.animations import AnimationRigSanitizer


class DummyKeyframePoint:
    def __init__(self, x: float, y: float):
        class Co:
            def __init__(self, x: float, y: float):
                self.x = x
                self.y = y

        self.co = Co(x, y)


class DummyFCurve:
    def __init__(self, data_path: str, key_x_list: list[float]):
        self.data_path = data_path
        self.keyframe_points = [DummyKeyframePoint(x, 0.0) for x in key_x_list]

    def range(self) -> tuple[float, float]:
        xs = [kp.co.x for kp in self.keyframe_points]
        return min(xs), max(xs)


class DummyAction:
    def __init__(self, name: str, fcurves: list[DummyFCurve]):
        self.name = name
        self.fcurves = fcurves


class DummyBone:
    def __init__(self, name: str, use_deform: bool = True):
        self.name = name
        self.use_deform = use_deform


class DummyArmatureData:
    def __init__(self, bones: list[DummyBone]):
        self.bones = bones


class DummyArmature:
    def __init__(self, bones: list[DummyBone]):
        self.type = "ARMATURE"
        self.data = DummyArmatureData(bones)


def test_sanitize_action_name():
    assert AnimationRigSanitizer.sanitize_action_name("Run Cycle! 01") == "Run_Cycle__01"
    assert AnimationRigSanitizer.sanitize_action_name("Walk-Forward.001") == "Walk_Forward_001"
    assert AnimationRigSanitizer.sanitize_action_name("___") == "Anim_Action"


def test_get_deform_bone_names():
    arm = DummyArmature(
        [
            DummyBone("root", use_deform=False),
            DummyBone("DEF-spine", use_deform=True),
            DummyBone("DEF-head", use_deform=True),
            DummyBone("IK_foot.L", use_deform=False),
        ]
    )
    deforms = AnimationRigSanitizer.get_deform_bone_names(arm)
    assert deforms == ["DEF-spine", "DEF-head"]


def test_validate_action_bounds_integer_frames():
    fc1 = DummyFCurve('pose.bones["DEF-spine"].location', [0.0, 10.0, 20.0, 30.0])
    fc2 = DummyFCurve('pose.bones["DEF-head"].rotation_quaternion', [0.0, 15.0, 30.0])
    action = DummyAction("Walk_Action", [fc1, fc2])

    result = AnimationRigSanitizer.validate_action_bounds(action)
    assert result["valid"] is True
    assert result["start_frame"] == 0
    assert result["end_frame"] == 30
    assert result["total_keys"] == 7
    assert result["has_subframe_drift"] is False


def test_validate_action_bounds_subframe_drift():
    # Fractional keyframes from mocap imports
    fc = DummyFCurve('pose.bones["DEF-spine"].location', [0.0, 10.332, 20.45, 30.0])
    action = DummyAction("Mocap_Raw", [fc])

    result = AnimationRigSanitizer.validate_action_bounds(action)
    assert result["valid"] is True
    assert result["has_subframe_drift"] is True
    assert result["subframe_drift_keys"] == 2
