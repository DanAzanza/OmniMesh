"""Unit and negative boundary tests for core.preset_anchor and ui.impostor_viewport_ops."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from core.compat import Vector
from core.preset_anchor import compute_preset_anchor_position
from ui import impostor_viewport_ops


def _approx_vec(actual: object, expected: tuple[float, float, float]) -> None:
    coords = tuple(actual)  # type: ignore[arg-type]
    assert len(coords) == 3
    assert coords == pytest.approx(expected, abs=1e-5)


ALL_ANCHOR_NAMES = [
    "EXTREMA_NOSE",
    "EXTREMA_TAIL",
    "EXTREMA_WING_L",
    "EXTREMA_WING_R",
    "EXTREMA_FIN",
    "COCKPIT_ESTIMATE",
    "EXTREMA_COCKPIT",
    "AABB_MIN_Z",
    "EXTREMA_BELLY",
    "WHEEL_NOSE",
    "WHEEL_FRONT",
    "WHEEL_LEFT",
    "WHEEL_RIGHT",
    "WHEEL_FRONT_L",
    "WHEEL_FRONT_R",
    "WHEEL_REAR_L",
    "WHEEL_REAR_R",
    "WHEEL_TAIL",
    "EXTREMA_BUMPER_F_L",
    "EXTREMA_BUMPER_F_R",
    "EXTREMA_BUMPER_R_L",
    "EXTREMA_BUMPER_R_R",
    "EXTREMA_ROOF",
    "HEADLIGHT_L",
    "HEADLIGHT_R",
    "TAILLIGHT_L",
    "TAILLIGHT_R",
    "DRIVER_SEAT",
    "PASSENGER_SEAT",
    "CHASE_CAMERA",
    "ROTOR_HUB_MAIN",
    "ROTOR_HUB_TAIL",
    "FLOAT_LEFT_KEEL",
    "FLOAT_RIGHT_KEEL",
    "TOW_HOOK",
    "AABB_ORIGIN",
    "AABB_CENTER",
    "UNKNOWN_FALLBACK",
]


@pytest.mark.parametrize("anchor_name", ALL_ANCHOR_NAMES)
def test_compute_preset_anchor_position_all_variants_without_extrema(anchor_name: str) -> None:
    """Verify every anchor mode computes finite 3D coordinates when extrema/wheels are empty."""
    bbox_min = Vector((-2.0, -4.0, -1.0))
    bbox_max = Vector((2.0, 4.0, 3.0))
    pos = compute_preset_anchor_position(
        anchor_name=anchor_name,
        offset_norm=[0.0, 0.0, 0.0],
        extrema={},
        bbox_min=bbox_min,
        bbox_max=bbox_max,
        detected_wheels={},
    )
    assert len(pos) == 3
    for val in pos:
        assert isinstance(val, float)


def test_compute_preset_anchor_position_with_extrema_and_detected_wheels() -> None:
    """Verify extrema overrides and detected_wheels snapping with zero vs non-zero offset_norm."""
    bbox_min = Vector((-2.0, -4.0, -1.0))
    bbox_max = Vector((2.0, 4.0, 3.0))
    extrema = {
        "Scrape_Nose": (0.1, 4.5, 0.2),
        "Scrape_Tail": (0.0, -4.5, 0.5),
        "Scrape_Wing_L": (-3.0, 0.0, 0.4),
        "Scrape_Wing_R": (3.0, 0.0, 0.4),
        "Scrape_Fin": (0.0, -4.2, 3.4),
    }
    wheels = {"WHEEL_NOSE": (0.0, 3.1, -0.95), "WHEEL_LEFT": (-1.1, -0.5, -0.95)}

    _approx_vec(
        compute_preset_anchor_position("EXTREMA_NOSE", [0.0, 0.0, 0.0], extrema, bbox_min, bbox_max, wheels),
        (0.1, 4.5, 0.2),
    )
    _approx_vec(
        compute_preset_anchor_position("EXTREMA_TAIL", [0.0, 0.0, 0.0], extrema, bbox_min, bbox_max, wheels),
        (0.0, -4.5, 0.5),
    )
    _approx_vec(
        compute_preset_anchor_position("EXTREMA_WING_L", [0.0, 0.0, 0.0], extrema, bbox_min, bbox_max, wheels),
        (-3.0, 0.0, 0.4),
    )
    _approx_vec(
        compute_preset_anchor_position("EXTREMA_WING_R", [0.0, 0.0, 0.0], extrema, bbox_min, bbox_max, wheels),
        (3.0, 0.0, 0.4),
    )
    _approx_vec(
        compute_preset_anchor_position("EXTREMA_FIN", [0.0, 0.0, 0.0], extrema, bbox_min, bbox_max, wheels),
        (0.0, -4.2, 3.4),
    )
    _approx_vec(
        compute_preset_anchor_position("AABB_ORIGIN", [0.0, 0.0, 0.0], extrema, bbox_min, bbox_max, wheels),
        (0.0, 0.0, 0.0),
    )

    # Zero offset on detected wheel hits wheel center directly
    _approx_vec(
        compute_preset_anchor_position("WHEEL_NOSE", [0.0, 0.0, 0.0], extrema, bbox_min, bbox_max, wheels),
        (0.0, 3.1, -0.95),
    )
    # Non-zero offset shifts relative to bounding extents (half-X=2, full-Y=8, full-Z=4)
    _approx_vec(
        compute_preset_anchor_position("WHEEL_NOSE", [0.5, 0.25, 0.1], extrema, bbox_min, bbox_max, wheels),
        (1.0, 5.1, -0.55),
    )


def _clear_active_timers() -> None:
    impostor_viewport_ops._ACTIVE_TIMERS.clear()


def test_impostor_viewport_sync_missing_collection_or_target() -> None:
    """Verify sync_rig_to_viewport stops timer cleanly when bpy, rig collection, or target is missing."""
    _clear_active_timers()
    with patch.object(impostor_viewport_ops, "bpy", None):
        assert impostor_viewport_ops.sync_rig_to_viewport("Any") is None

    fake_bpy = MagicMock()
    impostor_viewport_ops._ACTIVE_TIMERS["MissingColl"] = lambda: None
    fake_bpy.data.collections.get.return_value = None
    with patch.object(impostor_viewport_ops, "bpy", fake_bpy):
        assert impostor_viewport_ops.sync_rig_to_viewport("MissingColl") is None
        assert "MissingColl" not in impostor_viewport_ops._ACTIVE_TIMERS

    impostor_viewport_ops._ACTIVE_TIMERS["MissingTarget"] = lambda: None
    fake_bpy.data.collections.get.return_value = MagicMock()
    fake_bpy.data.objects.get.return_value = None
    with patch.object(impostor_viewport_ops, "bpy", fake_bpy):
        assert impostor_viewport_ops.sync_rig_to_viewport("MissingTarget") is None
        assert "MissingTarget" not in impostor_viewport_ops._ACTIVE_TIMERS


def test_impostor_viewport_sync_persp_camera_and_epsilon_gate() -> None:
    """Verify sync_rig_to_viewport handles PERSP, CAMERA, no-VIEW_3D, and epsilon gating."""
    _clear_active_timers()
    target_empty = SimpleNamespace(location=Vector((0.0, 0.0, 0.0)))
    cam_obj = SimpleNamespace(animation_data=None, location=Vector((0.0, 0.0, 0.0)), rotation_euler=None)

    def _get_obj(name: str) -> object | None:
        if name.endswith("_Preview_Tracker_Target"):
            return target_empty
        if name.endswith("_Preview_Camera"):
            return cam_obj
        return None

    inv_view = MagicMock()
    inv_view.translation = Vector((3.0, -10.0, 2.0))
    inv_view.to_euler.return_value = (0.1, 0.0, 0.2)
    reg3d_persp = SimpleNamespace(view_perspective="PERSP", view_matrix=MagicMock())
    reg3d_persp.view_matrix.inverted.return_value = inv_view

    space = SimpleNamespace(type="VIEW_3D", region_3d=reg3d_persp)
    area = SimpleNamespace(type="VIEW_3D", spaces=[space])
    win_no_screen = SimpleNamespace(screen=None)
    win_valid = SimpleNamespace(screen=SimpleNamespace(areas=[area]))

    fake_bpy = MagicMock()
    fake_bpy.data.collections.get.return_value = MagicMock()
    fake_bpy.data.objects.get.side_effect = _get_obj
    fake_bpy.context.window_manager = SimpleNamespace(windows=[win_no_screen, win_valid])
    fake_bpy.context.scene = SimpleNamespace(camera=None)

    with patch.object(impostor_viewport_ops, "bpy", fake_bpy):
        # Perspective update moves target and camera
        interval = impostor_viewport_ops.sync_rig_to_viewport("Oak")
        assert interval == pytest.approx(1.0 / 30.0)
        assert tuple(target_empty.location) == pytest.approx((3.0, -10.0, 2.0))
        assert tuple(cam_obj.location) == pytest.approx((3.0, -10.0, 2.0))
        assert cam_obj.rotation_euler == (0.1, 0.0, 0.2)

        # Second call with identical eye triggers epsilon gating early return
        interval2 = impostor_viewport_ops.sync_rig_to_viewport("Oak")
        assert interval2 == pytest.approx(1.0 / 30.0)

        # CAMERA perspective uses scene.camera.matrix_world.translation
        reg3d_persp.view_perspective = "CAMERA"
        scene_cam_inv = MagicMock()
        scene_cam_inv.translation = Vector((5.0, 6.0, 7.0))
        fake_bpy.context.scene = SimpleNamespace(camera=SimpleNamespace(matrix_world=scene_cam_inv))
        interval3 = impostor_viewport_ops.sync_rig_to_viewport("Oak")
        assert interval3 == pytest.approx(1.0 / 30.0)
        assert tuple(target_empty.location) == pytest.approx((5.0, 6.0, 7.0))

        # No VIEW_3D returns polling interval without touching locations
        fake_bpy.context.window_manager = SimpleNamespace(windows=[win_no_screen])
        assert impostor_viewport_ops.sync_rig_to_viewport("Oak") == pytest.approx(1.0 / 30.0)


def test_impostor_viewport_timer_lifecycle_and_operator() -> None:
    """Verify timer start/stop/running checks, background guard, registration error, and operator."""
    _clear_active_timers()

    # No-bpy negative paths
    with patch.object(impostor_viewport_ops, "bpy", None):
        assert impostor_viewport_ops.start_impostor_viewport_timer("Oak") is False
        assert impostor_viewport_ops.stop_impostor_viewport_timer("Oak") is False
        assert impostor_viewport_ops.is_impostor_viewport_timer_running("Oak") is False
        assert impostor_viewport_ops.LOD_OT_impostor_viewport_tracker.poll(None) is False
        assert impostor_viewport_ops.LOD_OT_impostor_viewport_tracker().execute(None) == {"CANCELLED"}

    fake_bpy = MagicMock()
    fake_bpy.app.background = True
    with patch.object(impostor_viewport_ops, "bpy", fake_bpy):
        assert impostor_viewport_ops.start_impostor_viewport_timer("Oak") is False
        assert impostor_viewport_ops.LOD_OT_impostor_viewport_tracker.poll(SimpleNamespace(scene=MagicMock())) is False

    fake_bpy.app.background = False
    registered: set[object] = set()
    fake_bpy.app.timers.register.side_effect = lambda fn, **kw: registered.add(fn)
    fake_bpy.app.timers.is_registered.side_effect = lambda fn: fn in registered
    fake_bpy.app.timers.unregister.side_effect = lambda fn: registered.discard(fn)

    with patch.object(impostor_viewport_ops, "bpy", fake_bpy):
        assert impostor_viewport_ops.is_impostor_viewport_timer_running("Test") is False
        assert impostor_viewport_ops.start_impostor_viewport_timer("Test") is True
        assert impostor_viewport_ops.is_impostor_viewport_timer_running("Test") is True
        # Duplicate start short-circuits without double register
        assert impostor_viewport_ops.start_impostor_viewport_timer("Test") is True
        assert fake_bpy.app.timers.register.call_count == 1

        assert impostor_viewport_ops.stop_impostor_viewport_timer("Test") is True
        assert impostor_viewport_ops.is_impostor_viewport_timer_running("Test") is False
        assert impostor_viewport_ops.stop_impostor_viewport_timer("NeverStarted") is False

        # Registration & unregistration error boundaries
        fake_bpy.app.timers.register.side_effect = RuntimeError("timer fail")
        assert impostor_viewport_ops.start_impostor_viewport_timer("FailReg") is False
        assert "FailReg" not in impostor_viewport_ops._ACTIVE_TIMERS

        fake_bpy.app.timers.register.side_effect = lambda fn, **kw: registered.add(fn)
        assert impostor_viewport_ops.start_impostor_viewport_timer("FailUnreg") is True
        fake_bpy.app.timers.unregister.side_effect = RuntimeError("unreg fail")
        assert impostor_viewport_ops.stop_impostor_viewport_timer("FailUnreg") is False

        # Operator poll & execute: missing asset name -> CANCELLED, fallback collection name -> toggle
        fake_bpy.app.timers.unregister.side_effect = lambda fn: registered.discard(fn)
        ctx_valid = SimpleNamespace(
            window_manager=MagicMock(), scene=SimpleNamespace(lod_tool=SimpleNamespace(asset_name=""))
        )
        assert impostor_viewport_ops.LOD_OT_impostor_viewport_tracker.poll(ctx_valid) is True

        op = impostor_viewport_ops.LOD_OT_impostor_viewport_tracker()
        op.report = MagicMock()
        fake_bpy.data.collections = []
        assert op.execute(ctx_valid) == {"CANCELLED"}
        op.report.assert_called_once()

        # Collection fallback resolution ("OakTree_Preview_Rig" -> "OakTree")
        fake_bpy.data.collections = [SimpleNamespace(name="OakTree_Preview_Rig")]
        op.report.reset_mock()
        assert op.execute(ctx_valid) == {"FINISHED"}
        assert impostor_viewport_ops.is_impostor_viewport_timer_running("OakTree") is True
        assert op.execute(ctx_valid) == {"FINISHED"}
        assert impostor_viewport_ops.is_impostor_viewport_timer_running("OakTree") is False
        assert op.report.call_count == 2
