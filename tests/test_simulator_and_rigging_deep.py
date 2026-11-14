"""Deep unit and negative boundary tests for core.simulator and core.rigging."""

from __future__ import annotations

import math
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock, patch

import pytest

from core import rigging, simulator
from core.compat import Vector


def _make_obj(name: str, obj_type: str = "MESH", polygons: int = 10, hidden: bool = False) -> Any:
    verts = [
        SimpleNamespace(co=Vector((-1.0, -1.0, -1.0))),
        SimpleNamespace(co=Vector((1.0, 1.0, 1.0))),
    ]
    mat = MagicMock()
    mat.__matmul__.side_effect = lambda v: v
    state = {"hidden": hidden}

    def hide_get(view_layer: object = None) -> bool:
        return state["hidden"]

    def hide_set(val: bool, view_layer: object = None) -> None:
        state["hidden"] = val

    return SimpleNamespace(
        name=name,
        type=obj_type,
        matrix_world=mat,
        data=(
            SimpleNamespace(vertices=verts, polygons=[None] * polygons, loops=[None] * (3 * polygons))
            if obj_type == "MESH"
            else None
        ),
        hide_get=hide_get,
        hide_set=hide_set,
    )


def test_simulator_pure_distance_and_camera_params() -> None:
    """Verify calculate_effective_distance_pure edge cases and extract_viewport_camera_params modes."""
    # NaN / Inf radius and object attribute fallback (.x/.y/.z)
    p_attr = SimpleNamespace(x=10.0, y=0.0, z=0.0)
    c_attr = SimpleNamespace(x=0.0, y=0.0, z=0.0)
    assert simulator.calculate_effective_distance_pure(p_attr, c_attr, float("nan")) == pytest.approx(10.0)
    assert simulator.calculate_effective_distance_pure((float("inf"), 0.0, 0.0), (0.0, 0.0, 0.0), 1.0) == pytest.approx(
        0.01
    )
    assert simulator.calculate_effective_distance_pure(object(), object(), "bad") == pytest.approx(0.01)  # type: ignore[arg-type]

    # Scene CAMERA PERSP VERTICAL & HORIZONTAL
    cam_mat = MagicMock()
    cam_mat.translation = Vector((0.0, -20.0, 0.0))
    cam_data = SimpleNamespace(
        type="PERSP", sensor_fit="AUTO", angle=math.radians(60.0), angle_y=math.radians(40.0), ortho_scale=12.0
    )
    cam = SimpleNamespace(type="CAMERA", matrix_world=cam_mat, data=cam_data)
    render_wide = SimpleNamespace(resolution_x=1920, resolution_y=1080, pixel_aspect_x=1.0, pixel_aspect_y=1.0)
    render_tall = SimpleNamespace(resolution_x=800, resolution_y=1200, pixel_aspect_x=1.0, pixel_aspect_y=1.0)
    scene_wide: Any = SimpleNamespace(camera=cam, render=render_wide)
    scene_tall: Any = SimpleNamespace(camera=cam, render=render_tall)
    space_cam = SimpleNamespace(use_local_camera=False, camera=None, lens=50.0)
    reg3d_cam = SimpleNamespace(is_perspective=True, view_perspective="CAMERA")

    with patch.object(simulator, "Vector", Vector):
        pos, fov, is_p = simulator.extract_viewport_camera_params(space_cam, reg3d_cam, None, scene_wide)
        assert is_p is True and 0.1 < fov < 2.0 and [pos[0], pos[1], pos[2]] == pytest.approx([0.0, -20.0, 0.0])

        pos2, fov2, is_p2 = simulator.extract_viewport_camera_params(space_cam, reg3d_cam, None, scene_tall)
        assert is_p2 is True and fov2 == pytest.approx(math.radians(40.0))

        # Scene CAMERA ORTHO
        cam_data.type = "ORTHO"
        _, ortho_scale, is_po = simulator.extract_viewport_camera_params(space_cam, reg3d_cam, None, scene_wide)
        assert is_po is False and ortho_scale == pytest.approx(12.0)

        # Free viewport portrait PERSP & ORTHO
        inv_m = MagicMock()
        inv_m.translation = Vector((0.0, -5.0, 1.0))
        reg3d_free = SimpleNamespace(
            is_perspective=True,
            view_perspective="PERSP",
            view_matrix=SimpleNamespace(inverted=lambda: inv_m),
            view_distance=8.0,
        )
        region_tall = SimpleNamespace(width=500, height=1000)
        _, fov_free, is_pf = simulator.extract_viewport_camera_params(space_cam, reg3d_free, region_tall, scene_wide)
        assert is_pf is True and fov_free > 0.4

        reg3d_free.is_perspective = False
        _, ortho_ext, is_pfo = simulator.extract_viewport_camera_params(space_cam, reg3d_free, region_tall, scene_wide)
        assert is_pfo is False and ortho_ext == pytest.approx(16.0)


def test_simulator_record_evaluate_scrub_and_reset() -> None:
    """Verify LODAssetRecord invalid states, evaluate_all, evaluate_distance_scrub, and snapshot restore."""
    simulator.LODSimulatorEngine._tracked_assets.clear()
    simulator.LODSimulatorEngine._visibility_snapshot.clear()

    with patch.object(simulator, "bpy", MagicMock()), patch.object(simulator, "Vector", Vector):
        rec_invalid = simulator.LODAssetRecord("Missing", "Hero")
        rec_invalid.update_bounds_and_tiers(blend_data=None)  # type: ignore[arg-type]
        assert rec_invalid.is_valid is False

        bdata_empty = SimpleNamespace(collections={"EmptyCol": SimpleNamespace(objects=[])})
        rec_empty = simulator.LODAssetRecord("EmptyCol", "Hero")
        rec_empty.update_bounds_and_tiers(blend_data=bdata_empty)  # type: ignore[arg-type]
        assert rec_empty.is_valid is False

        o_lod0 = _make_obj("Hero_LOD0", polygons=100)
        o_lod1 = _make_obj("Hero_LOD1", polygons=40)
        o_nonmesh = _make_obj("Hero_Empty", obj_type="EMPTY")

        rec = simulator.LODAssetRecord("Hero_LOD0", "Hero")
        rec.tier_objects = {0: [o_lod0], 1: [o_lod1, o_nonmesh]}
        rec.center = Vector((0.0, 0.0, 0.0))
        rec.radius = 2.0
        rec.tier_screen_pcts = [100.0, 30.0]
        rec.is_valid = True

        simulator.LODSimulatorEngine._tracked_assets["Hero"] = rec
        simulator.LODSimulatorEngine._tracked_assets["Invalid"] = rec_invalid

        ctx: Any = SimpleNamespace(
            view_layer=MagicMock(),
            scene=SimpleNamespace(camera=None),
            window_manager=SimpleNamespace(windows=[]),
            active_object=o_lod1,
        )

        # evaluate_all in virtual_override, perspective, and ortho modes
        ups_virt = simulator.LODSimulatorEngine.update_simulation_tick(
            ctx, Vector((0, -10, 0)), math.radians(60), True, virtual_override_pct=15.0
        )
        assert ups_virt[0]["current_tier"] == 1 and ups_virt[0]["active_tris"] == 40
        assert o_lod0.hide_get() is True and o_lod1.hide_get() is False

        ups_persp = simulator.LODSimulatorEngine.update_simulation_tick(ctx, Vector((0, -2, 0)), math.radians(60), True)
        assert ups_persp[0]["current_tier"] == 0

        ups_ortho = simulator.LODSimulatorEngine.update_simulation_tick(ctx, Vector((0, -50, 0)), 40.0, False)
        assert ups_ortho[0]["current_tier"] == 1

        # evaluate_distance_scrub focuses primary asset and snapshots visibility
        simulator.LODSimulatorEngine._visibility_snapshot = {"Hero_LOD0": False, "Hero_LOD1": True}
        scrub = simulator.LODSimulatorEngine.evaluate_distance_scrub(ctx, 20.0, blend_data=bdata_empty)  # type: ignore[arg-type]
        assert scrub["root_name"] == "Hero"

        # reset_distance_scrub with blend_data=None builds map from tracked assets
        simulator.LODSimulatorEngine.reset_distance_scrub(ctx, blend_data=None)  # type: ignore[arg-type]
        assert o_lod0.hide_get() is False and o_lod1.hide_get() is True
        assert simulator.LODSimulatorEngine._visibility_snapshot == {}

        # Empty snapshot triggers restore_all_visibility -> unhides everything
        simulator.LODSimulatorEngine.reset_distance_scrub(ctx, blend_data=SimpleNamespace(objects={}))  # type: ignore[arg-type]
        assert o_lod0.hide_get() is False and o_lod1.hide_get() is False

        simulator.LODSimulatorEngine._tracked_assets.clear()


def test_rigging_weights_rest_pose_and_transfer_guards() -> None:
    """Verify normalize_weights_pure negative cases, armature_rest_pose_context, matrix helper, and _transfer_weights."""
    assert rigging.normalize_weights_pure({}) == {0: 1.0}
    assert rigging.normalize_weights_pure({-1: -5.0, 2: float("nan")}, anchor_idx=3) == {3: 1.0}
    # All below micro_epsilon -> highest weight promoted to 1.0
    assert rigging.normalize_weights_pure({1: 0.002, 2: 0.004}, micro_epsilon=0.01) == {2: 1.0}
    # Non-finite max_influences & micro_epsilon gracefully coerce to defaults
    res = rigging.normalize_weights_pure({0: 0.3, 1: 0.7}, max_influences=float("nan"), micro_epsilon="bad")  # type: ignore[arg-type]
    assert sum(res.values()) == pytest.approx(1.0)

    # armature_rest_pose_context restores POSE even on inner exception
    arm_data = SimpleNamespace(pose_position="POSE")
    arm_obj = SimpleNamespace(data=arm_data)
    vl = MagicMock()
    ctx = SimpleNamespace(view_layer=vl)
    with pytest.raises(ValueError, match="boom"):
        with rigging.armature_rest_pose_context(arm_obj, ctx):  # type: ignore[arg-type]
            assert arm_data.pose_position == "REST"
            raise ValueError("boom")
    assert arm_data.pose_position == "POSE"

    # Error restoring pose_position caught gracefully
    class _BrokenData:
        @property
        def pose_position(self) -> str:
            return "POSE"

        @pose_position.setter
        def pose_position(self, val: str) -> None:
            raise RuntimeError("readonly")

    broken_ctx_arm = SimpleNamespace(data=_BrokenData())
    with rigging.armature_rest_pose_context(broken_ctx_arm, None):  # type: ignore[arg-type]
        pass

    # compute_rest_pose_inverted_matrix fallbacks & matrix multiplication error
    assert rigging.compute_rest_pose_inverted_matrix(None, None, None, None, "fallback") == "fallback"  # type: ignore[arg-type]
    bad_mat = MagicMock()
    bad_mat.__matmul__.side_effect = ValueError("shape mismatch")
    assert rigging.compute_rest_pose_inverted_matrix(bad_mat, bad_mat, bad_mat, bad_mat, cast(Any, "tgt")) == "tgt"

    # WeightSanitizer guards
    with patch.object(rigging, "bpy", None):
        assert rigging.WeightSanitizer.normalize_and_clamp_weights(None) == {
            "normalized": 0,
            "singularities_fixed": 0,
            "purged_vgs": 0,
        }

    # KinematicBonePruner._transfer_weights merges weights and handles new VG failure
    src_vg = SimpleNamespace(index=0, remove=MagicMock())
    tgt_vg = SimpleNamespace(index=1, add=MagicMock())
    v0 = SimpleNamespace(index=0, groups=[SimpleNamespace(group=0, weight=0.4), SimpleNamespace(group=1, weight=0.5)])
    mesh_obj = SimpleNamespace(
        data=SimpleNamespace(vertices=[v0]),
        vertex_groups=SimpleNamespace(
            get=lambda n: src_vg if n == "Bone_Tip" else None,
            new=lambda name: tgt_vg,
        ),
    )
    with patch.object(rigging, "bpy", MagicMock()):
        rigging.KinematicBonePruner._transfer_weights(mesh_obj, "Bone_Tip", "Bone_Parent")  # type: ignore[arg-type]
        tgt_vg.add.assert_called_once_with([0], pytest.approx(0.9), "REPLACE")
        src_vg.remove.assert_called_once_with([0])

        # Failing vertex_groups.new aborts cleanly
        mesh_obj.vertex_groups = SimpleNamespace(
            get=lambda n: src_vg if n == "Bone_Tip" else None,
            new=MagicMock(side_effect=RuntimeError("no vgs")),
        )
        rigging.KinematicBonePruner._transfer_weights(mesh_obj, "Bone_Tip", "Bone_Parent")  # type: ignore[arg-type]
