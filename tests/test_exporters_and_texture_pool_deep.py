"""Deep unit and negative boundary tests for UE5/Unity exporters, TexturePoolManager, and refactored MSFS/preset helpers."""

from __future__ import annotations

import concurrent.futures
import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from core.lod_presets import LODPresetManager
from core.msfs.project_scanner import _safe_glob
from core.msfs.spatial_parsers import _parse_legacy_light_fields
from core.msfs.transforms import parse_float_triple, parse_float_value
from core.texture_pool import TexturePoolManager
from core.texture_resolver import PBRTextureResolver
from exporters import ue5_export, unity_export
from exporters.engine_export import AssetMeshResolver


class _ObjMock:
    def __init__(self, name: str, parent: object = None) -> None:
        self.name = name
        self.parent = parent
        self.hide_viewport = False
        self.matrix_world = MagicMock()
        self.matrix_world.copy.return_value = self.matrix_world
        self.selected = False
        self.hidden_vl = False
        self.users_collection: tuple[Any, ...] = ()
        self._idprops: dict[str, object] = {}

    def __setitem__(self, key: str, value: object) -> None:
        self._idprops[key] = value

    def __getitem__(self, key: str) -> object:
        return self._idprops[key]

    def hide_set(self, val: bool, view_layer: object = None) -> None:
        self.hidden_vl = val

    def hide_get(self, view_layer: object = None) -> bool:
        return self.hidden_vl

    def select_set(self, val: bool) -> None:
        self.selected = val


class _FakeBDataObjs(dict):
    def __init__(self) -> None:
        super().__init__()
        self.removed: list[str] = []

    def __bool__(self) -> bool:
        return True

    def new(self, name: str, data: object) -> _ObjMock:
        obj = _ObjMock(name)
        self[name] = obj
        return obj

    def remove(self, obj: _ObjMock, do_unlink: bool = True) -> None:
        self.removed.append(obj.name)
        self.pop(obj.name, None)


class _SceneObjs(list):
    def link(self, obj: object) -> None:
        self.append(obj)

    def __contains__(self, item: object) -> bool:
        return any(getattr(o, "name", None) == item or o is item for o in self)


def _make_ue5_context(bdata_objs: _FakeBDataObjs) -> Any:
    scene_objs = _SceneObjs()
    scene_collection = SimpleNamespace(name="Scene Collection", objects=scene_objs, hide_viewport=False)
    layer_col = SimpleNamespace(
        name="Scene Collection",
        collection=scene_collection,
        children=[],
        hide_viewport=False,
        exclude=False,
    )
    vl = SimpleNamespace(objects=SimpleNamespace(active=None), layer_collection=layer_col)
    scene = SimpleNamespace(collection=scene_collection)
    bdata = SimpleNamespace(objects=bdata_objs)
    return SimpleNamespace(
        mode="EDIT_MESH",
        selected_objects=[],
        active_object=None,
        view_layer=vl,
        scene=scene,
        blend_data=bdata,
    )


def test_ue5_exporter_skinned_impostor_chunked_and_existing_empty(tmp_path: Path) -> None:
    """Verify UE5Exporter handles armature, impostor tier renaming, chunked bypass, and existing LODGroup reuse."""
    bdata_objs = _FakeBDataObjs()
    lod0 = _ObjMock("SM_Vehicle_LOD0")
    lod1 = _ObjMock("SM_Vehicle_LOD1")
    imp = _ObjMock("SM_Vehicle_Impostor")
    col = _ObjMock("Hull_01")
    arm = _ObjMock("Vehicle_Rig")
    ctx = _make_ue5_context(bdata_objs)
    ctx.selected_objects = [lod0]
    ctx.active_object = lod0

    payload = SimpleNamespace(
        export_objects=[lod0, lod1, imp],
        lod_tiers={0: [lod0], 1: [lod1], 2: [imp]},
        collider_objects=[col],
        has_impostor_tier=True,
        armature_obj=arm,
    )

    fake_bpy = MagicMock()
    with (
        patch.object(ue5_export, "bpy", fake_bpy),
        patch.object(AssetMeshResolver, "resolve_payload", return_value=payload),
    ):
        ok, msg = ue5_export.UE5Exporter.export_asset(ctx, str(tmp_path), "SM_Vehicle")

    assert ok is True
    assert "SM_Vehicle.fbx" in msg
    fake_bpy.ops.object.mode_set.assert_called_with(mode="OBJECT")
    fbx_kwargs = fake_bpy.ops.export_scene.fbx.call_args.kwargs
    assert fbx_kwargs["add_leaf_bones"] is False
    assert "ARMATURE" in fbx_kwargs["object_types"]
    # Transactional restore checks
    assert col.name == "Hull_01"
    assert imp.name == "SM_Vehicle_Impostor"
    assert lod0.selected is True

    # Chunked asset (tier has 2 meshes -> bypasses LODGroup_ empty)
    payload_chunked = SimpleNamespace(
        export_objects=[lod0, lod1],
        lod_tiers={0: [lod0, lod1]},
        collider_objects=[],
        has_impostor_tier=False,
        armature_obj=None,
    )
    with (
        patch.object(ue5_export, "bpy", fake_bpy),
        patch.object(AssetMeshResolver, "resolve_payload", return_value=payload_chunked),
    ):
        ok_chunk, _ = ue5_export.UE5Exporter.export_asset(ctx, str(tmp_path), "SM_Chunked")
    assert ok_chunk is True
    chunk_kwargs = fake_bpy.ops.export_scene.fbx.call_args.kwargs
    assert chunk_kwargs["bake_space_transform"] is True  # no armature & no lod_group_empty
    assert ctx.view_layer.objects.active == arm  # restored orig_active in finally

    # Existing LODGroup empty reuse + already linked RuntimeError handled gracefully
    existing_empty = _ObjMock("LODGroup_SM_Reuse")
    bdata_objs["LODGroup_SM_Reuse"] = existing_empty
    ctx_err = _make_ue5_context(bdata_objs)

    def _raise_linked(_o: object) -> None:
        raise RuntimeError("already in collection")

    ctx_err.scene.collection.objects.link = _raise_linked
    payload_single = SimpleNamespace(
        export_objects=[lod0],
        lod_tiers={0: [lod0]},
        collider_objects=[col],
        has_impostor_tier=False,
        armature_obj=None,
    )
    col.parent = existing_empty
    with (
        patch.object(ue5_export, "bpy", fake_bpy),
        patch.object(AssetMeshResolver, "resolve_payload", return_value=payload_single),
    ):
        ok_reuse, _ = ue5_export.UE5Exporter.export_asset(ctx_err, str(tmp_path), "SM_Reuse")
    assert ok_reuse is True
    assert "LODGroup_SM_Reuse" not in bdata_objs.removed  # reused, not deleted


def test_ue5_and_unity_negative_boundaries_and_rollback_warnings(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Verify UE5 & Unity exporter negative paths: missing bpy, invalid target dir, empty payload, and rollback warnings."""
    with patch.object(ue5_export, "bpy", None):
        ok, _ = ue5_export.UE5Exporter.export_asset(None, str(tmp_path), "X")
        assert ok is False

    with patch.object(unity_export, "bpy", None):
        ok, _ = unity_export.UnityExporter.export_asset(None, str(tmp_path), "X")
        assert ok is False

    # OSError creating export_dir (file blocking directory creation)
    blocking_file = tmp_path / "blocker"
    blocking_file.write_text("file", encoding="utf-8")
    fake_bpy = MagicMock()
    ctx = _make_ue5_context(_FakeBDataObjs())
    with patch.object(ue5_export, "bpy", fake_bpy):
        ok, msg = ue5_export.UE5Exporter.export_asset(ctx, str(blocking_file), "Asset")
        assert ok is False and "Failed creating export directory" in msg
    with patch.object(unity_export, "bpy", fake_bpy):
        ok, msg = unity_export.UnityExporter.export_asset(ctx, str(blocking_file), "Asset")
        assert ok is False and "Failed creating export directory" in msg

    # Missing lod_group_empty when blend_data has no objects collection
    ctx_no_bdata: Any = SimpleNamespace(
        mode="OBJECT",
        selected_objects=[],
        active_object=None,
        view_layer=SimpleNamespace(objects=SimpleNamespace(active=None)),
        scene=SimpleNamespace(collection=SimpleNamespace(objects=SimpleNamespace(link=lambda o: None))),
        blend_data=SimpleNamespace(objects=None),
    )
    mesh_obj = _ObjMock("M0")
    payload_single = SimpleNamespace(
        export_objects=[mesh_obj],
        lod_tiers={0: [mesh_obj]},
        collider_objects=[],
        has_impostor_tier=False,
        armature_obj=None,
    )
    with (
        patch.object(ue5_export, "bpy", fake_bpy),
        patch.object(AssetMeshResolver, "resolve_payload", return_value=payload_single),
    ):
        ok_no_empty, msg_no_empty = ue5_export.UE5Exporter.export_asset(ctx_no_bdata, str(tmp_path), "Asset")
        assert ok_no_empty is False and "Could not create or retrieve LODGroup empty" in msg_no_empty

    # FBX operator failure + failing rollback calls log warnings safely
    broken_mesh = MagicMock()
    broken_mesh.name = "M_Broken"
    broken_mesh.parent = None
    broken_mesh.matrix_world.copy.return_value = MagicMock()
    broken_mesh.hide_viewport = False
    broken_mesh.hide_get.return_value = False
    type(broken_mesh).parent = property(
        lambda s: None, lambda s, v: (_ for _ in ()).throw(RuntimeError("parent locked"))
    )  # type: ignore[misc]
    fake_bpy.ops.export_scene.fbx.side_effect = RuntimeError("FBX crash")

    payload_err = SimpleNamespace(
        export_objects=[broken_mesh],
        lod_tiers={0: [broken_mesh]},
        collider_objects=[],
        has_impostor_tier=True,
        armature_obj=None,
    )
    with caplog.at_level(logging.WARNING):
        with (
            patch.object(ue5_export, "bpy", fake_bpy),
            patch.object(AssetMeshResolver, "resolve_payload", return_value=payload_err),
        ):
            ok_err, msg_err = ue5_export.UE5Exporter.export_asset(ctx, str(tmp_path), "CrashAsset")
            assert ok_err is False and "parent locked" in msg_err

        with (
            patch.object(unity_export, "bpy", fake_bpy),
            patch.object(AssetMeshResolver, "resolve_payload", return_value=payload_err),
        ):
            ok_uerr, msg_uerr = unity_export.UnityExporter.export_asset(ctx, str(tmp_path), "CrashAsset")
            assert ok_uerr is False and "FBX crash" in msg_uerr


def test_texture_pool_manager_roundtrip_and_negative_boundaries(tmp_path: Path) -> None:
    """Verify TexturePoolManager async PNG save, invalid inputs, worker failure, timeout, and shutdown."""
    try:
        # Invalid inputs return resolved Future(False)
        assert (
            TexturePoolManager.submit_save(np.empty((0, 0, 4), dtype=np.uint8), str(tmp_path / "e.png")).result()
            is False
        )
        assert TexturePoolManager.submit_save(np.zeros((2, 2, 4), dtype=np.uint8), "").result() is False
        assert TexturePoolManager.wait_all([]) == []

        # Valid 8-bit PNG write via thread pool
        out_png = tmp_path / "pool_out.png"
        img_arr = np.full((4, 4, 4), 128, dtype=np.uint8)
        fut = TexturePoolManager.submit_save(img_arr, str(out_png), 8)
        assert TexturePoolManager.wait_all([fut]) == [True]
        assert out_png.is_file() and out_png.stat().st_size > 0

        # Failing future + never-finishing (timeout) future
        err_fut: concurrent.futures.Future[bool] = concurrent.futures.Future()
        err_fut.set_exception(OSError("disk full"))
        hang_fut: concurrent.futures.Future[bool] = concurrent.futures.Future()
        assert TexturePoolManager.wait_all([err_fut, hang_fut], timeout=0.01) == [False, False]

        # Recovery after executor shutdown
        TexturePoolManager.shutdown()
        TexturePoolManager._executor = MagicMock()
        TexturePoolManager._executor.submit.side_effect = [RuntimeError("pool closed")]
        with patch("core.texture_pool.concurrent.futures.ThreadPoolExecutor") as mock_pool:
            mock_pool.return_value.submit.return_value = err_fut
            res_fut = TexturePoolManager.submit_save(img_arr, str(tmp_path / "retry.png"))
            assert res_fut is err_fut
    finally:
        TexturePoolManager._executor = None


def test_megascans_naming_and_refactored_msfs_preset_guards(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """Verify realistic FabLibrary/MSFS PBR texture resolution and newly extracted parser/preset guards."""
    dummy_node = SimpleNamespace(label="", name="TexNode", outputs=[])
    assert PBRTextureResolver.deduce_texture_type(dummy_node, "Concrete_Basecolor.JPG") == "ALBEDO"  # type: ignore[arg-type]
    assert PBRTextureResolver.deduce_texture_type(dummy_node, "Concrete_Normal.JPG") == "NORMAL"  # type: ignore[arg-type]
    assert PBRTextureResolver.deduce_texture_type(dummy_node, "Concrete_Roughness.JPG") == "ROUGHNESS"  # type: ignore[arg-type]
    assert PBRTextureResolver.deduce_texture_type(dummy_node, "Concrete_Metalness.JPG") == "METALLIC"  # type: ignore[arg-type]
    assert PBRTextureResolver.deduce_texture_type(dummy_node, "Concrete_AO.JPG") == "OCCLUSION"  # type: ignore[arg-type]
    assert PBRTextureResolver.deduce_texture_type(dummy_node, "Concrete_Displacement.JPG") == "HEIGHT"  # type: ignore[arg-type]
    assert PBRTextureResolver.deduce_texture_type(dummy_node, "Foliage_Opacity.PNG") == "ALPHA"  # type: ignore[arg-type]
    assert PBRTextureResolver.deduce_texture_type(dummy_node, "T_Wing_COMP.PNG") == "COMP"  # type: ignore[arg-type]

    # parse_float_value & parse_float_triple malformed boundaries
    with caplog.at_level(logging.WARNING):
        assert parse_float_value("12.5", "test_ctx") == pytest.approx(12.5)
        assert parse_float_value("nan_bad", "test_ctx") is None
        assert parse_float_triple(["1.0", "2.0"], "test_ctx") is None
        assert parse_float_triple(["1.0", "bad", "3.0"], "test_ctx") is None
        assert parse_float_triple(["1.0", "2.0", "3.0"], "test_ctx") == (1.0, 2.0, 3.0)

    # _safe_glob handles PermissionError cleanly
    bad_dir = MagicMock(spec=Path)
    bad_dir.glob.side_effect = PermissionError("access denied")
    assert _safe_glob(bad_dir, "*") == []

    # _parse_legacy_light_fields legacy token count (< 6 vs >= 6 vs malformed)
    assert _parse_legacy_light_fields(["4", "1.0", "2.0"], "light.0") is None
    assert _parse_legacy_light_fields(["4", "bad", "0.0", "0.0", "fx_nav", "extra"], "light.0") is None
    parsed_light = _parse_legacy_light_fields(["4", "1.5", "-2.0", "0.5", "fx_nav", "1"], "light.0")
    assert parsed_light == (4, (1.5, -2.0, 0.5))

    # LODPresetManager save_custom_preset + numeric/non-numeric target_tris coercion
    preset_dir = tmp_path / "user_lod_presets"
    preset_dir.mkdir(parents=True, exist_ok=True)
    with patch.object(LODPresetManager, "get_user_dir", return_value=preset_dir):
        pid = LODPresetManager.save_custom_preset(
            {
                "name": "MSFS_GA_Test",
                "tiers": [
                    {"name": "LOD0", "screen_size_pct": 100.0, "target_tris_pct": 100.0, "target_tris": "invalid_num"},
                    {"name": "LOD1", "screen_size_pct": 50.0, "target_tris_pct": 50.0, "target_tris": "2500"},
                ],
            }
        )
        loaded = LODPresetManager.load_presets(force_reload=True)
        assert pid in loaded
        assert "target_tris" not in loaded[pid]["tiers"][0]
        assert loaded[pid]["tiers"][1]["target_tris"] == 2500
