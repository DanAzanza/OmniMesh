"""
Deep unit tests for core/animations.py.
Covers functional RDP reduction edge cases, quaternion continuity enforcement,
subframe snapping guards, boundary validation, clean NLA export,
and FK deform animation baking pipeline.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from core.animations import AnimationRigSanitizer
from core.compat import Matrix

try:
    from mathutils import Quaternion
except ImportError:
    Quaternion = None


# ==============================================================================
# Helper Mock Objects for Animation Rig Sanitizer
# ==============================================================================


class MockBone:
    def __init__(self, name: str, use_deform: bool = True):
        self.name = name
        self.use_deform = use_deform
        self.matrix_local = Matrix.Identity(4) if Matrix else MagicMock()


class MockArmatureData:
    def __init__(self, bones: list[MockBone]):
        self.bones = bones


class MockPoseBone:
    def __init__(self, name: str, parent: Any = None):
        self.name = name
        self.parent = parent
        self.bone = MockBone(name, use_deform=True)
        self.matrix = Matrix.Identity(4) if Matrix else MagicMock()
        self.rotation_mode = "QUATERNION"


class MockPose:
    def __init__(self, bones: dict[str, MockPoseBone]):
        self.bones = bones


class MockVec3:
    def __init__(self, x: float, y: float, z: float = 0.0):
        self.x = float(x)
        self.y = float(y)
        self.z = float(z)

    def __getitem__(self, idx: int) -> float:
        return [self.x, self.y, self.z][idx]


class MockKeyframePoint:
    def __init__(self, x: float, y: float):
        self.co = MockVec3(x, y, 0.0)
        self.handle_left = MockVec3(x - 0.5, y, 0.0)
        self.handle_right = MockVec3(x + 0.5, y, 0.0)


class MockFCurve:
    def __init__(self, data_path: str = "location", index: int = 0, keys: list[tuple[float, float]] | None = None):
        self.data_path = data_path
        self.array_index = index
        self.keyframe_points = [MockKeyframePoint(k[0], k[1]) for k in (keys or [])]
        self._updated = False

    def range(self) -> tuple[float, float]:
        if not self.keyframe_points:
            return (0.0, 0.0)
        xs = [kp.co.x for kp in self.keyframe_points]
        return (min(xs), max(xs))

    def update(self) -> None:
        self._updated = True


class MockKeyframeCollection:
    def __init__(self):
        self._points: list[Any] = []

    def __iter__(self):
        return iter(self._points)

    def __len__(self):
        return len(self._points)

    def __getitem__(self, idx: int) -> Any:
        return self._points[idx]

    def insert(self, frame: float, value: float) -> Any:
        kp = MockKeyframePoint(frame, value)
        self._points.append(kp)
        return kp

    def remove(self, point: Any) -> None:
        if point in self._points:
            self._points.remove(point)


class MockBakedFCurve:
    def __init__(self, data_path: str, index: int):
        self.data_path = data_path
        self.array_index = index
        self.keyframe_points = MockKeyframeCollection()
        self.updated = False

    def update(self) -> None:
        self.updated = True


class MockAction:
    def __init__(self, name: str = "Test_Action", fcurves: list[MockFCurve] | None = None):
        self.name = name
        self.fcurves = fcurves or []
        self.frame_range = (1.0, 10.0)


class MockActionCollection:
    def __init__(self):
        self.actions: dict[str, Any] = {}

    def new(self, name: str) -> Any:
        act = MockAction(name)
        self.actions[name] = act
        return act

    def remove(self, action: Any, do_unlink: bool = True) -> None:
        self.actions.pop(getattr(action, "name", ""), None)


class MockBlendData:
    def __init__(self):
        self.actions = MockActionCollection()


class MockNLATrack:
    def __init__(self, name: str = "Track"):
        self.name = name
        self.is_solo = False
        self.strips = MockNLAStrips()


class MockNLAStrips:
    def __init__(self):
        self.strip_list: list[Any] = []

    def new(self, name: str, start: int, action: Any) -> Any:
        strip = MagicMock(name=name, start=start, action=action)
        self.strip_list.append(strip)
        return strip


class MockNLATracks:
    def __init__(self):
        self._tracks: list[MockNLATrack] = []

    def __iter__(self):
        return iter(self._tracks)

    def new(self) -> MockNLATrack:
        t = MockNLATrack()
        self._tracks.append(t)
        return t

    def remove(self, track: MockNLATrack) -> None:
        if track in self._tracks:
            self._tracks.remove(track)


class MockAnimData:
    def __init__(self):
        self.action = None
        self.nla_tracks = MockNLATracks()


class MockArmatureObject:
    def __init__(self, name: str = "Armature", bone_names: list[str] | None = None):
        self.name = name
        self.type = "ARMATURE"
        bones = [MockBone(n) for n in (bone_names or ["Root", "Spine"])]
        self.data = MockArmatureData(bones)
        pose_bones = {n: MockPoseBone(n) for n in (bone_names or ["Root", "Spine"])}
        self.pose = MockPose(pose_bones)
        self.animation_data = MockAnimData()

    def animation_data_create(self) -> MockAnimData:
        self.animation_data = MockAnimData()
        return self.animation_data

    def evaluated_get(self, depsgraph: Any) -> MockArmatureObject:
        return self


# ==============================================================================
# Functional RDP Edge Cases
# ==============================================================================


def test_functional_rdp_short_and_degenerate():
    # Length <= 2 points
    pts = [(1.0, 10.0), (2.0, 20.0)]
    assert AnimationRigSanitizer.functional_rdp_reduce(pts, 0.1) == pts

    # Epsilon <= 1e-7
    assert AnimationRigSanitizer.functional_rdp_reduce(pts, 1e-8) == pts

    # Delta time dt < 1e-6
    degenerate_pts = [(1.0, 5.0), (1.00000001, 10.0), (1.00000002, 15.0)]
    res = AnimationRigSanitizer.functional_rdp_reduce(degenerate_pts, 0.1)
    assert len(res) == 2
    assert res[0] == degenerate_pts[0]
    assert res[-1] == degenerate_pts[-1]


def test_functional_rdp_significant_reduction():
    # Linear curve with middle points on the line
    linear_pts = [(float(i), float(i * 2)) for i in range(10)]
    reduced = AnimationRigSanitizer.functional_rdp_reduce(linear_pts, epsilon=0.01)
    assert len(reduced) == 2
    assert reduced[0] == (0.0, 0.0)
    assert reduced[-1] == (9.0, 18.0)


# ==============================================================================
# Quaternion Continuity Edge Cases
# ==============================================================================


def test_enforce_quaternion_continuity_none_and_tuples():
    assert AnimationRigSanitizer.enforce_quaternion_continuity(None, (1.0, 0.0, 0.0, 0.0)) is None
    assert AnimationRigSanitizer.enforce_quaternion_continuity((1.0, 0.0, 0.0, 0.0), None) == (1.0, 0.0, 0.0, 0.0)

    # Shortest arc: opposite sign should be flipped
    q_prev = (1.0, 0.0, 0.0, 0.0)
    q_flipped = (-1.0, 0.0, 0.0, 0.0)
    res = AnimationRigSanitizer.enforce_quaternion_continuity(q_flipped, q_prev)
    assert res == (1.0, -0.0, -0.0, -0.0)

    # Same sign: no flip
    q_same = (0.9, 0.1, 0.0, 0.0)
    res_same = AnimationRigSanitizer.enforce_quaternion_continuity(q_same, q_prev)
    assert res_same == q_same


def test_enforce_quaternion_continuity_mathutils_objects():
    if Quaternion is None:
        return
    q1 = Quaternion((1.0, 0.0, 0.0, 0.0))
    q2 = Quaternion((-1.0, 0.0, 0.0, 0.0))
    res = AnimationRigSanitizer.enforce_quaternion_continuity(q2, q1)
    assert isinstance(res, Quaternion)
    assert res.w == 1.0


# ==============================================================================
# Bounds Validation & Snapping Edge Cases
# ==============================================================================


def test_validate_action_bounds_fcurve_exceptions():
    mock_action = MagicMock()
    mock_fc = MagicMock()
    mock_fc.keyframe_points = [MagicMock()]
    mock_fc.range.side_effect = RuntimeError("Curve corrupted")

    with patch.object(AnimationRigSanitizer, "get_action_fcurves", return_value=[mock_fc]):
        res = AnimationRigSanitizer.validate_action_bounds(mock_action)  # type: ignore[arg-type]
        assert res["valid"] is False
        assert "invalid keyframe ranges" in res["error"]


def test_snap_action_to_integer_frames_safeties():
    assert AnimationRigSanitizer.snap_action_to_integer_frames(None) == 0

    fc = MockFCurve("location", 0, [(1.000001, 10.0), (2.3, 20.0), (float("nan"), 30.0)])
    act = MockAction("TestAction", [fc])

    # With safe threshold 0.5, 2.3 should snap to 2.0 (dx = -0.3, abs <= 0.5)
    snapped = AnimationRigSanitizer.snap_action_to_integer_frames(act, drift_threshold=0.5)  # type: ignore[arg-type]
    assert snapped == 1
    assert fc.keyframe_points[1].co.x == 2.0


# ==============================================================================
# NLA Export Setup Tests
# ==============================================================================


def test_setup_clean_nla_export_success():
    arm = MockArmatureObject("HeroRig")
    act = MockAction("RunCycle")
    act.frame_range = (5.0, 25.0)

    mock_bpy = MagicMock()
    with patch("core.animations.bpy", mock_bpy):
        ok = AnimationRigSanitizer.setup_clean_nla_export(arm, act)  # type: ignore[arg-type]
        assert ok is True
        assert len(arm.animation_data.nla_tracks._tracks) == 1
        track = arm.animation_data.nla_tracks._tracks[0]
        assert track.name == "NLA_Export_Track"
        assert track.is_solo is True
        assert arm.animation_data.action is None


def test_setup_clean_nla_export_null_guards():
    mock_bpy = MagicMock()
    with patch("core.animations.bpy", mock_bpy):
        assert AnimationRigSanitizer.setup_clean_nla_export(None, MockAction()) is False  # type: ignore[arg-type]
        assert AnimationRigSanitizer.setup_clean_nla_export(MockArmatureObject(), None) is False  # type: ignore[arg-type]


# ==============================================================================
# Deform Animation Baking Tests
# ==============================================================================


def test_bake_deform_animation_guards():
    bdata = MockBlendData()
    mock_ctx = MagicMock()
    mock_bpy = MagicMock()

    with patch("core.animations.bpy", mock_bpy):
        # Armature is None
        res = AnimationRigSanitizer.bake_deform_animation(
            mock_ctx,
            None,
            MockAction(),  # type: ignore[arg-type]
            blend_data=bdata,  # type: ignore[arg-type]
        )
        assert res is None

        # Non-armature object
        mesh_obj = MockArmatureObject()
        mesh_obj.type = "MESH"
        res = AnimationRigSanitizer.bake_deform_animation(
            mock_ctx,
            mesh_obj,  # type: ignore[arg-type]
            MockAction(),  # type: ignore[arg-type]
            blend_data=bdata,  # type: ignore[arg-type]
        )
        assert res is None

        # Armature with no deform bones
        no_deform_arm = MockArmatureObject(bone_names=[])
        res = AnimationRigSanitizer.bake_deform_animation(
            mock_ctx,
            no_deform_arm,  # type: ignore[arg-type]
            MockAction(),  # type: ignore[arg-type]
            blend_data=bdata,  # type: ignore[arg-type]
        )
        assert res is None


def test_bake_deform_animation_success_flow():
    bdata = MockBlendData()
    arm = MockArmatureObject("HeroArmature", bone_names=["Root", "Spine"])

    # Action with integer frames 1 to 3
    fc = MockFCurve("location", 0, [(1.0, 0.0), (3.0, 10.0)])
    act = MockAction("WalkAction", [fc])

    mock_scene = MagicMock()
    mock_scene.frame_current = 1
    mock_scene.frame_subframe = 0.0

    mock_context = MagicMock()
    mock_context.scene = mock_scene

    mock_bpy = MagicMock()

    mock_mat = MagicMock()
    mock_mat.determinant.return_value = 1.0
    mock_mat.inverted.return_value = mock_mat
    mock_quat = MagicMock(w=1.0, x=0.0, y=0.0, z=0.0)
    mock_quat.__iter__.return_value = [1.0, 0.0, 0.0, 0.0]
    mock_quat.__getitem__.side_effect = lambda i: [1.0, 0.0, 0.0, 0.0][i]
    mock_mat.decompose.return_value = ([0.0, 0.0, 0.0], mock_quat, [1.0, 1.0, 1.0])
    mock_mat.__matmul__.return_value = mock_mat
    for b in arm.data.bones:
        b.matrix_local = mock_mat
    for pb in arm.pose.bones.values():
        pb.matrix = mock_mat
        pb.bone.matrix_local = mock_mat

    created_fcurves: dict[tuple[str, int], MockBakedFCurve] = {}

    def mock_create_fcurve(action: Any, data_path: str, index: int, slot_name: str = "") -> MockBakedFCurve:
        key = (data_path, index)
        if key not in created_fcurves:
            created_fcurves[key] = MockBakedFCurve(data_path, index)
        return created_fcurves[key]

    with (
        patch("core.animations.bpy", mock_bpy),
        patch.object(AnimationRigSanitizer, "create_action_fcurve", side_effect=mock_create_fcurve),
    ):
        baked_act = AnimationRigSanitizer.bake_deform_animation(
            context=mock_context,
            source_armature=arm,  # type: ignore[arg-type]
            action=act,  # type: ignore[arg-type]
            bake_step=1.0,
            keyframe_reduction_tolerance=0.01,
            blend_data=bdata,  # type: ignore[arg-type]
        )

        assert baked_act is not None
        assert "WalkAction_Baked_Deform" in baked_act.name
        # Verify keyframes were written
        loc_curve = created_fcurves.get(('pose.bones["Root"].location', 0))
        assert loc_curve is not None
        assert len(loc_curve.keyframe_points) > 0
