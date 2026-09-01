"""
Unit tests for OmniMesh Animation Rig Sanitizer, Action Validator & Blender 5.2+ Action Slots.
"""

from __future__ import annotations

import math
import numpy as np

from core.animations import AnimationRigSanitizer, _safe_invert_matrix


class DummyKeyframePoint:
    def __init__(self, x: float, y: float):
        class Co:
            def __init__(self, x: float, y: float):
                self.x = float(x)
                self.y = float(y)

        self.co = Co(x, y)
        self.handle_left = Co(x - 1.0, y)
        self.handle_right = Co(x + 1.0, y)


class DummyFCurve:
    def __init__(self, data_path: str, key_x_list: list[float], index: int = 0):
        self.data_path = data_path
        self.array_index = index
        self.keyframe_points = [DummyKeyframePoint(x, 0.0) for x in key_x_list]

    def range(self) -> tuple[float, float]:
        xs = [kp.co.x for kp in self.keyframe_points if math.isfinite(kp.co.x)]
        if not xs:
            return (0.0, 0.0)
        return min(xs), max(xs)

    def update(self):
        pass


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
    assert AnimationRigSanitizer.sanitize_action_name("") == "Anim_Action"
    assert AnimationRigSanitizer.sanitize_action_name(None) == "Anim_Action"  # type: ignore
    assert AnimationRigSanitizer.sanitize_action_name("!@#$%^&*()") == "Anim_Action"
    assert AnimationRigSanitizer.sanitize_action_name("Attack_01") == "Attack_01"


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

    # Edge cases
    assert AnimationRigSanitizer.get_deform_bone_names(None) == []
    assert AnimationRigSanitizer.get_deform_bone_names(object()) == []

    class NonArmature:
        type = "MESH"

    assert AnimationRigSanitizer.get_deform_bone_names(NonArmature()) == []


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


def test_validate_action_bounds_empty_and_invalid():
    assert AnimationRigSanitizer.validate_action_bounds(None)["valid"] is False
    assert AnimationRigSanitizer.validate_action_bounds(DummyAction("Empty", []))["valid"] is False

    fc_empty = DummyFCurve("dummy", [])
    assert AnimationRigSanitizer.validate_action_bounds(DummyAction("NoKeys", [fc_empty]))["valid"] is False


def test_snap_action_to_integer_frames():
    fc = DummyFCurve('pose.bones["DEF-spine"].location', [0.0, 10.2, 20.4, 30.05])
    action = DummyAction("Mocap_Drift", [fc])

    assert AnimationRigSanitizer.validate_action_bounds(action)["has_subframe_drift"] is True

    snapped = AnimationRigSanitizer.snap_action_to_integer_frames(action, drift_threshold=0.5)
    assert snapped == 3

    # All keys should now be exact integer frames: 0, 10, 20, 30
    post_check = AnimationRigSanitizer.validate_action_bounds(action)
    assert post_check["has_subframe_drift"] is False
    assert post_check["subframe_drift_keys"] == 0
    assert fc.keyframe_points[1].co.x == 10.0
    assert fc.keyframe_points[2].co.x == 20.0
    assert fc.keyframe_points[3].co.x == 30.0

    # Handles should have shifted by dx
    assert fc.keyframe_points[1].handle_left.x == 9.0
    assert fc.keyframe_points[1].handle_right.x == 11.0


def test_blender_52_slotted_actions():
    # Mock Blender 5.2+ layered and slotted action data structures
    class DummyChannelBag:
        def __init__(self, slot=None):
            self.slot = slot
            self.fcurves_list = []

        @property
        def fcurves(self):
            class FCurvesContainer:
                def __init__(self, parent):
                    self.parent = parent

                def __iter__(self):
                    return iter(self.parent.fcurves_list)

                def new(self, data_path, index=0):
                    fc = DummyFCurve(data_path, [0.0, 10.0, 20.0], index=index)
                    self.parent.fcurves_list.append(fc)
                    return fc

            return FCurvesContainer(self)

    class DummyStrip:
        def __init__(self):
            self.channelbags = []

        def channelbag_for_slot(self, slot):
            for cb in self.channelbags:
                if cb.slot == slot:
                    return cb
            cb = DummyChannelBag(slot=slot)
            self.channelbags.append(cb)
            return cb

    class DummyLayer:
        def __init__(self, name="BaseLayer"):
            self.name = name
            self.strips = [DummyStrip()]

    class DummySlot:
        def __init__(self, name="ArmatureSlot"):
            self.name = name

    class DummySlotsCollection:
        def __init__(self):
            self._slots = []

        def __iter__(self):
            return iter(self._slots)

        def __getitem__(self, idx):
            return self._slots[idx]

        def __bool__(self):
            return bool(self._slots)

        def new(self, id_type="OBJECT", name="ArmatureSlot"):
            s = DummySlot(name)
            self._slots.append(s)
            return s

    class DummyLayersCollection:
        def __init__(self):
            self._layers = []

        def __iter__(self):
            return iter(self._layers)

        def __getitem__(self, idx):
            return self._layers[idx]

        def __bool__(self):
            return bool(self._layers)

        def new(self, name="BaseLayer"):
            layer = DummyLayer(name)
            self._layers.append(layer)
            return layer

    class DummySlottedAction:
        def __init__(self, name="Slotted_Action"):
            self.name = name
            self.fcurves = None  # Blender 5.2 layered actions may have None fcurves
            self.slots = DummySlotsCollection()
            self.layers = DummyLayersCollection()

    action = DummySlottedAction("Test_52_Slotted")

    # Create F-Curve in slotted action
    fc = AnimationRigSanitizer.create_action_fcurve(
        action, data_path='pose.bones["Root"].location', index=0, slot_name="TestSlot"
    )
    assert fc is not None
    assert fc.data_path == 'pose.bones["Root"].location'
    assert fc.array_index == 0

    # Extract F-Curves
    extracted = AnimationRigSanitizer.get_action_fcurves(action)
    assert len(extracted) == 1
    assert extracted[0] is fc

    # Bounds validation on slotted action
    bounds = AnimationRigSanitizer.validate_action_bounds(action)
    assert bounds["valid"] is True
    assert bounds["start_frame"] == 0
    assert bounds["end_frame"] == 20


def test_safe_invert_matrix_singularity():
    class SingularMatrix:
        def __init__(self, arr: np.ndarray):
            self.arr = arr

        def determinant(self):
            return float(np.linalg.det(self.arr))

        def copy(self):
            return SingularMatrix(self.arr.copy())

        def inverted(self):
            raise ValueError("Inversion failed")

    # Zero scale matrix
    zero_mat = np.zeros((4, 4))
    mat = SingularMatrix(zero_mat)

    # Must safely return copy without crashing
    inv = _safe_invert_matrix(mat)
    assert inv is not None
    assert _safe_invert_matrix(None) is None


def test_bake_and_nla_guards():
    # Calling bake / nla with null arguments returns None / False gracefully
    assert AnimationRigSanitizer.bake_deform_animation(None, None, None) is None
    assert AnimationRigSanitizer.setup_clean_nla_export(None, None) is False
