"""
Tests for core/impostor_ortho_baker.py covering Cycles orthographic face baking,
shared-mesh material rollback, datablock leak prevention, empty container guards,
and Unity MaskMap / UE5 ORM finalization.
"""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from core.compat import Vector
from core.exceptions import ImpostorBakeError
import core.impostor_ortho_baker as ortho_baker
from tests.conftest import MockBlendData, MockMeshObject, MockScene


class _UVLayerList(list[object]):
    active: object = None


def _make_six_face_quad_mesh() -> MockMeshObject:
    """Builds a minimal 2-face quad mesh with active UV layer for spec extraction."""
    obj = MockMeshObject("Asset_LOD_Impostor")
    verts = [
        SimpleNamespace(co=Vector((0.0, 0.0, 0.0))),
        SimpleNamespace(co=Vector((2.0, 0.0, 0.0))),
        SimpleNamespace(co=Vector((2.0, 0.0, 1.0))),
        SimpleNamespace(co=Vector((0.0, 0.0, 1.0))),
    ]
    loops = [SimpleNamespace(vertex_index=i) for i in range(4)]
    uv_data = [
        SimpleNamespace(uv=(0.0, 0.5)),
        SimpleNamespace(uv=(0.33, 0.5)),
        SimpleNamespace(uv=(0.33, 1.0)),
        SimpleNamespace(uv=(0.0, 1.0)),
    ]
    uv_layer = SimpleNamespace(data=uv_data)
    uv_layers = _UVLayerList([uv_layer])
    uv_layers.active = uv_layer
    tri_poly = SimpleNamespace(loop_indices=[0, 1, 2])
    quad_poly = SimpleNamespace(loop_indices=[0, 1, 2, 3])
    mesh = SimpleNamespace(
        vertices=verts,
        loops=loops,
        polygons=[tri_poly, quad_poly],
        uv_layers=uv_layers,
    )
    obj.data = mesh  # type: ignore[assignment]
    obj.matrix_world = MagicMock()
    obj.matrix_world.__matmul__ = lambda _self, v: v
    return obj


def test_extract_face_specs_rejects_missing_uvs_and_triangles() -> None:
    """Rejects missing mesh data/UVs and skips degenerate non-quad polygons."""
    obj_no_uv = MockMeshObject("NoUV")
    obj_no_uv.data.uv_layers = []  # type: ignore[assignment]
    assert ortho_baker._extract_face_specs(obj_no_uv, res=512, cam_distance=5.0) == []  # type: ignore[arg-type]

    obj = _make_six_face_quad_mesh()
    with patch.object(ortho_baker, "Matrix") as mock_mat_cls:
        mock_mat_cls.return_value.transposed.return_value.to_euler.return_value = (1.57, 0.0, 0.0)
        specs = ortho_baker._extract_face_specs(obj, res=512, cam_distance=5.0)  # type: ignore[arg-type]

    assert len(specs) == 1
    x0, y0, x1, y1 = specs[0].rect
    assert 0 <= x0 < x1 <= 512
    assert 0 <= y0 < y1 <= 512
    assert specs[0].ortho_scale >= 2.0


def test_apply_and_restore_override_materials_shared_mesh_and_cleanup() -> None:
    """Instanced objects sharing a Mesh datablock restore real materials and delete override datablocks."""
    bdata = MockBlendData()
    real_mat = bdata.materials.new("RealFuselageMat")
    shared_mesh = SimpleNamespace(materials=[real_mat])

    class _MatList(list[Any]):
        pass

    mat_list = _MatList([real_mat])
    shared_mesh.materials = mat_list

    obj1 = SimpleNamespace(name="Wing_L", data=shared_mesh)
    obj2 = SimpleNamespace(name="Wing_R", data=shared_mesh)

    with patch("core.impostor_harness.bpy", MagicMock()):
        saved = ortho_baker.apply_override_materials(
            [obj1, obj2],  # type: ignore[list-item]
            channel_layer="BASE_COLOR",
            target_engine="UE5",
            radius=2.0,
            cam_distance=10.0,
            blend_data=bdata,  # type: ignore[arg-type]
        )
        assert len(saved) == 1
        assert len(shared_mesh.materials) == 1
        assert shared_mesh.materials[0].name.startswith("OM_Bake_BASE_COLOR")

        ortho_baker.restore_override_materials(saved, bdata)  # type: ignore[arg-type]

    assert list(shared_mesh.materials) == [real_mat]
    assert "OM_Bake_BASE_COLOR" not in bdata.materials


def test_load_rendered_tile_u8_missing_zero_size_and_error_unlink(tmp_path: Path) -> None:
    """Unlinks loaded image datablocks even when pixel reading fails or dimensions are empty."""
    bdata = MockBlendData()
    assert ortho_baker.load_rendered_tile_u8(str(tmp_path / "does_not_exist.png"), bdata.images) is None  # type: ignore[arg-type]

    dummy_file = tmp_path / "tile.png"
    dummy_file.write_bytes(b"png")

    bad_img = MagicMock(name="tile.png", size=(0, 0))
    bdata_imgs_zero = MagicMock()
    bdata_imgs_zero.load.return_value = bad_img
    assert ortho_baker.load_rendered_tile_u8(str(dummy_file), bdata_imgs_zero) is None
    bdata_imgs_zero.remove.assert_called_once_with(bad_img, do_unlink=True)

    err_img = MagicMock(name="err.png", size=(4, 4))
    err_img.pixels.foreach_get.side_effect = RuntimeError("corrupt pixels")
    bdata_imgs_err = MagicMock()
    bdata_imgs_err.load.return_value = err_img
    with pytest.raises(RuntimeError, match="corrupt pixels"):
        ortho_baker.load_rendered_tile_u8(str(dummy_file), bdata_imgs_err)
    bdata_imgs_err.remove.assert_called_once_with(err_img, do_unlink=True)


def test_finalize_orm_tile_unity_and_ue5() -> None:
    """Packs Blue smoothness into Alpha for UNITY/UNITY_6 and keeps RGB+opaque Alpha for UE5."""
    raw = np.zeros((4, 4, 4), dtype=np.uint8)
    raw[:, :, 0] = 200  # Metallic (Unity) / AO (UE5)
    raw[:, :, 1] = 255  # AO (Unity) / Roughness (UE5)
    raw[:, :, 2] = 180  # Smoothness (Unity) / Metallic (UE5)
    raw[:, :, 3] = 255
    mask = np.zeros((4, 4), dtype=bool)
    mask[1:3, 1:3] = True

    unity6_out = ortho_baker.finalize_orm_tile(raw, mask, "UNITY_6", dilation_iterations=0)
    assert unity6_out[1, 1, 3] == 180
    assert unity6_out[1, 1, 2] == 0
    assert tuple(unity6_out[0, 0]) == (0, 255, 0, 128)

    ue5_out = ortho_baker.finalize_orm_tile(raw, mask, "UE5", dilation_iterations=0)
    assert tuple(ue5_out[1, 1]) == (200, 255, 180, 255)
    assert tuple(ue5_out[0, 0]) == (255, 128, 0, 255)


def test_bake_ortho_quads_atlas_empty_mock_bdata_and_render_failure_rollback(tmp_path: Path) -> None:
    """Runs cleanly against empty MockBlendData and rolls back materials + camera on render failure."""
    bdata = MockBlendData()
    real_mat = bdata.materials.new("PropBlur")
    mesh_obj = MockMeshObject("Prop")
    mesh_obj.data.materials = [real_mat]  # type: ignore[assignment]
    imp_obj = _make_six_face_quad_mesh()

    # Negative guard: blend_data is None -> {}
    with patch.object(ortho_baker, "bpy", MagicMock()):
        assert (
            ortho_baker.bake_ortho_quads_atlas(
                mesh_objs=[mesh_obj],  # type: ignore[list-item]
                target_impostor=imp_obj,  # type: ignore[arg-type]
                base_name="Asset",
                output_dir=str(tmp_path),
                res=64,
                max_span=2.0,
                target_engine="UE5",
                dilation_iterations=1,
                configure_cycles_fn=lambda _s, _c: ("CYCLES", []),
                set_view_transform_fn=lambda _s, _v: None,
                render_still_fn=lambda _s, _c: None,
                context=None,
                blend_data=cast("Any", None),
            )
            == {}
        )

    # Render exception rolls back materials, removes OM_Bake_* and OrthoCam datablocks
    def _failing_render(_scene: object, _ctx: object) -> None:
        raise RuntimeError("GPU OOM")

    with (
        patch.object(ortho_baker, "bpy", MagicMock()),
        patch("core.impostor_harness.bpy", MagicMock()),
        patch("core.impostor_rig.bpy", MagicMock()),
        patch.object(ortho_baker, "Matrix") as mock_mat_cls,
    ):
        mock_mat_cls.return_value.transposed.return_value.to_euler.return_value = (1.57, 0.0, 0.0)
        with pytest.raises(ImpostorBakeError, match="GPU OOM"):
            ortho_baker.bake_ortho_quads_atlas(
                mesh_objs=[mesh_obj],  # type: ignore[list-item]
                target_impostor=imp_obj,  # type: ignore[arg-type]
                base_name="Asset",
                output_dir=str(tmp_path),
                res=64,
                max_span=2.0,
                target_engine="UNITY_6",
                dilation_iterations=1,
                configure_cycles_fn=lambda _s, _c: ("CYCLES", []),
                set_view_transform_fn=lambda _s, _v: None,
                render_still_fn=_failing_render,
                context=None,
                blend_data=bdata,  # type: ignore[arg-type]
            )

    assert list(mesh_obj.data.materials) == [real_mat]
    assert "Asset_OrthoCam" not in bdata.objects
    assert "Asset_OrthoCamData" not in bdata.cameras
    assert not any(k.startswith("OM_Bake_") for k in bdata.materials.keys())


def test_bake_ortho_quads_atlas_writes_unity6_and_ue5_pngs_with_mock_bdata(tmp_path: Path) -> None:
    """Regression test: empty MockBlendData containers do not silently abort orthographic bake."""
    bdata = MockBlendData()
    real_mat = bdata.materials.new("Wing")
    mesh_obj = MockMeshObject("Wing")
    mesh_obj.data.materials = [real_mat]  # type: ignore[assignment]
    imp_obj = _make_six_face_quad_mesh()

    def _fake_render(scene: MockScene, _ctx: object) -> None:
        w = int(scene.render.resolution_x)
        h = int(scene.render.resolution_y)
        filepath = scene.render.filepath
        Path(filepath).write_bytes(b"stub")
        mock_img = MagicMock(size=(w, h))
        px = np.tile(np.array([0.8, 0.4, 0.2, 1.0], dtype=np.float32), w * h)
        mock_img.pixels.foreach_get.side_effect = lambda out: np.copyto(out, px)
        bdata.images._items[os.path.basename(filepath)] = mock_img

    with (
        patch.object(ortho_baker, "bpy", MagicMock()),
        patch("core.impostor_harness.bpy", MagicMock()),
        patch("core.impostor_rig.bpy", MagicMock()),
        patch.object(ortho_baker, "Matrix") as mock_mat_cls,
    ):
        mock_mat_cls.return_value.transposed.return_value.to_euler.return_value = (1.57, 0.0, 0.0)
        res = ortho_baker.bake_ortho_quads_atlas(
            mesh_objs=[mesh_obj],  # type: ignore[list-item]
            target_impostor=imp_obj,  # type: ignore[arg-type]
            base_name="Asset",
            output_dir=str(tmp_path),
            res=64,
            max_span=2.0,
            target_engine="UNITY_6",
            dilation_iterations=1,
            configure_cycles_fn=lambda _s, _c: ("CYCLES", []),
            set_view_transform_fn=lambda _s, _v: None,
            render_still_fn=_fake_render,  # type: ignore[arg-type]
            context=None,
            blend_data=bdata,  # type: ignore[arg-type]
        )

    assert set(res.keys()) == {"BaseColor", "Normal", "ORM"}
    assert all(Path(p).exists() for p in res.values())
