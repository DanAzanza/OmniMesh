"""Deep unit and boundary tests for core.impostor, core.impostor_baker, core.impostor_preview, and core.pbr_importer."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import numpy as np

import core.impostor as imp_mod
import core.impostor_baker as baker_mod
import core.impostor_preview as prev_mod
import core.pbr_importer as pbr_mod
from core.impostor import ImpostorManager, ImpostorMeshBuilder, resolve_impostor_export_dir
from core.impostor_baker import ImpostorAtlasBaker
from core.impostor_math import Vector
from core.impostor_preview import (
    create_octahedral_preview_material,
    safe_load_image,
    setup_impostor_preview_rig,
    setup_impostor_tracking,
    setup_preview_turntable,
    teardown_impostor_preview_rig,
)
from core.pbr_importer import BatchMaterialSlotMatcher, OCIOColorSpaceResolver, ShaderGraphBuilder


# =========================================================================
# 1. ImpostorMeshBuilder, ImpostorManager & resolve_impostor_export_dir
# =========================================================================


def test_resolve_impostor_export_dir_and_impostor_manager(tmp_path: Path) -> None:
    """Verify resolve_impostor_export_dir fallbacks, ImpostorMeshBuilder, and ImpostorManager."""
    bdata = MagicMock()
    bdata.filepath = str(tmp_path / "scene.blend")

    out_dir = resolve_impostor_export_dir("//ImpostorOut", blend_data=bdata)
    assert os.path.isdir(out_dir)

    bdata.filepath = ""
    out_unsaved = resolve_impostor_export_dir("", blend_data=bdata)
    assert "Textures" in out_unsaved

    bdata.filepath = str(tmp_path / "scene.blend")
    out_rel = resolve_impostor_export_dir("SubOut", blend_data=bdata)
    assert os.path.isdir(out_rel)

    fake_bmesh_mod = MagicMock()

    def _make_bm() -> Any:
        bm = MagicMock()
        bm.loops.layers.uv.new.return_value = "uv_layer"

        def _new_face(verts: Any) -> Any:
            f = MagicMock()
            f.loops = [{("uv_layer"): MagicMock()} for _ in verts]
            return f

        bm.faces.new.side_effect = _new_face
        return bm

    fake_bmesh_mod.new.side_effect = _make_bm
    fake_bpy = MagicMock()
    fake_bpy.app.background = False

    with (
        patch.object(imp_mod, "bmesh", fake_bmesh_mod),
        patch.object(imp_mod, "bpy", fake_bpy),
    ):
        bm_quads = ImpostorMeshBuilder.build_star_quads(width=2.0, height=3.0)
        assert bm_quads is not None
        bm_oct = ImpostorMeshBuilder.build_single_camera_quad(bevel_pct=0.25)
        assert bm_oct is not None
        bm_oct_flat = ImpostorMeshBuilder.build_octahedral_cutout_polygon(bevel_pct=0.0)
        assert bm_oct_flat is not None

        mat_mock = MagicMock()
        mat_mock.node_tree.nodes = MagicMock()
        bdata.materials.get.return_value = None
        bdata.materials.new.return_value = mat_mock
        for eng in ("UE5", "UNITY_6"):
            m = ImpostorManager.create_impostor_material("Tree", target_engine=eng, blend_data=bdata)
            assert m is mat_mock

        base_f = tmp_path / "base.png"
        norm_f = tmp_path / "norm.png"
        orm_f = tmp_path / "orm.png"
        for f in (base_f, norm_f, orm_f):
            f.write_bytes(b"png")

        tex_node = MagicMock()
        tex_node.type = "TEX_IMAGE"
        mat_mock.node_tree.nodes.get.return_value = tex_node
        ImpostorManager.bind_baked_textures_to_material(
            mat_mock, str(base_f), str(norm_f), str(orm_f), blend_data=bdata
        )
        assert tex_node.mute is False

        mesh_obj = MagicMock()
        mesh_obj.name = "Tree_LOD0"
        mesh_obj.bound_box = [(-1.0, -1.0, 0.0), (1.0, 1.0, 4.0)]
        mesh_obj.matrix_world = None
        bdata.collections.get.return_value = None
        bdata.collections.new.return_value = MagicMock()
        new_obj = MagicMock()
        bdata.objects.new.return_value = new_obj
        ctx = MagicMock()

        imp_res = ImpostorManager.generate_impostor_for_objects(
            [mesh_obj],
            "Tree",
            mode="ORTHO_3_AXES",
            context=ctx,
            blend_data=bdata,
        )
        assert imp_res is new_obj


def test_impostor_atlas_baker_angles_compose_and_cycles_config(tmp_path: Path) -> None:
    """Verify ImpostorAtlasBaker angle tables, atlas composition, Cycles GPU probing, and Selected-to-Active bake."""
    for mode in ("STAR_QUADS", "ORTHO_3_AXES", "OCTAHEDRAL_HEMI", "OCTAHEDRAL_SPHERE", "14_PLANES"):
        angles = ImpostorAtlasBaker.get_view_angles_for_mode(mode)
        cols, rows = ImpostorAtlasBaker.get_grid_dimensions(mode)
        assert len(angles) >= 2
        assert cols >= 2 and rows >= 1

    tile0 = np.zeros((8, 8, 4), dtype=np.uint8)
    tile0[2:6, 2:6] = [200, 100, 50, 255]
    tile1 = np.ones((8, 8, 4), dtype=np.uint8) * 128
    atlas = ImpostorAtlasBaker.compose_atlas_array(
        [(tile0, (0, 0)), (tile1, (1, 0))],
        grid_cols=2,
        grid_rows=1,
        tile_w=8,
        tile_h=8,
        dilation_iterations=2,
    )
    assert atlas.shape == (8, 16, 4)

    fake_bpy = MagicMock()
    scene = MagicMock()
    ctx = MagicMock()
    cpref = MagicMock()
    cpref.get_device_types.return_value = [("OPTIX", "OptiX", "")]
    dev = MagicMock()
    dev.type = "OPTIX"
    dev.name = "RTX 4090"
    cpref.devices = [dev]
    cycles_addon = MagicMock()
    cycles_addon.preferences = cpref
    ctx.preferences.addons.get.return_value = cycles_addon

    with patch.object(baker_mod, "bpy", fake_bpy):
        backend, names = ImpostorAtlasBaker.configure_cycles_compute_device(scene, context=ctx)
        assert backend == "OPTIX"
        assert "RTX 4090" in names
        assert scene.cycles.device == "GPU"

        cpref.get_device_types.return_value = []
        backend_cpu, _ = ImpostorAtlasBaker.configure_cycles_compute_device(scene, context=ctx)
        assert backend_cpu == "CPU"
        assert scene.cycles.device == "CPU"

        bdata = MagicMock()
        bdata.filepath = str(tmp_path / "bake.blend")
        mesh_obj = MagicMock()
        mesh_obj.bound_box = [(-1.0, -1.0, -1.0), (1.0, 1.0, 1.0)]
        mesh_obj.matrix_world = MagicMock()
        mesh_obj.matrix_world.__matmul__.side_effect = lambda v: Vector((v[0], v[1], v[2]))
        mesh_obj.hide_viewport = False

        imp_obj = MagicMock()
        imp_obj.hide_viewport = False
        imp_mat = MagicMock()
        imp_mat.node_tree.nodes = MagicMock()
        unbound_tex_node = MagicMock()
        unbound_tex_node.type = "TEX_IMAGE"
        unbound_tex_node.image = None
        unbound_tex_node.mute = False
        imp_mat.node_tree.nodes.__iter__.return_value = [unbound_tex_node]
        imp_obj.data.materials = [imp_mat]

        def _make_img(name: str, width: int, height: int, alpha: bool = True) -> Any:
            im = MagicMock()
            im.name = name

            def _fget(arr: np.ndarray) -> None:
                arr[:] = 0.5

            im.pixels.foreach_get.side_effect = _fget
            return im

        bdata.images.new.side_effect = _make_img
        ctx.scene = scene

        res = ImpostorAtlasBaker.bake_impostor_textures(
            [mesh_obj],
            "Pine",
            str(tmp_path),
            mode="14_PLANES",
            atlas_resolution=16,
            impostor_obj=imp_obj,
            context=ctx,
            blend_data=bdata,
        )
        assert "BaseColor" in res
        assert "Normal" in res
        assert "ORM" in res
        assert unbound_tex_node.mute is False


# =========================================================================
# 2. Impostor Preview Rig Deep Tests
# =========================================================================


def test_impostor_preview_material_rig_turntable_and_teardown(tmp_path: Path) -> None:
    """Verify safe_load_image, preview material, rig setup, turntable, and teardown."""
    fake_bpy = MagicMock()
    bdata = MagicMock()

    base_tex = tmp_path / "T_Oak_Impostor_BaseColor.png"
    norm_tex = tmp_path / "T_Oak_Impostor_Normal.png"
    orm_tex = tmp_path / "T_Oak_Impostor_ORM.png"
    base_tex.write_bytes(b"png")
    norm_tex.write_bytes(b"png")
    orm_tex.write_bytes(b"png")

    mat = MagicMock()
    mat.node_tree.nodes = MagicMock()
    mat.node_tree.links = MagicMock()
    bdata.materials.get.return_value = None
    bdata.materials.new.return_value = mat
    bdata.images = MagicMock()
    bdata.images.__iter__.return_value = []

    with patch.object(prev_mod, "bpy", fake_bpy):
        assert safe_load_image(str(base_tex), blend_data=None) is None  # type: ignore[arg-type]
        assert create_octahedral_preview_material("M", str(base_tex), blend_data=None) is None  # type: ignore[arg-type]

        loaded_img = safe_load_image(str(base_tex), blend_data=bdata)
        assert loaded_img is not None

        created_mat = create_octahedral_preview_material(
            "M_Oak_Octahedral_Preview",
            str(base_tex),
            normal_path=str(norm_tex),
            orm_path=str(orm_tex),
            target_engine="UNITY_6",
            blend_data=bdata,
        )
        assert created_mat is mat

        proxy_obj = MagicMock()
        cam_obj = MagicMock()
        cam_obj.name = "Oak_Preview_Camera"
        cam_obj.location = Vector((0.0, -5.0, 2.0))

        constraints_mock = MagicMock()
        track_con = MagicMock()
        constraints_mock.new.return_value = track_con
        proxy_obj.constraints = constraints_mock
        assert setup_impostor_tracking(proxy_obj, cam_obj, blend_data=bdata) is track_con
        assert track_con.target is cam_obj

        ctx = MagicMock()
        fcurve = MagicMock()
        kp = MagicMock()
        fcurve.keyframe_points = [kp]
        cam_obj.animation_data.action.fcurves = [fcurve]
        assert (
            setup_preview_turntable(
                cam_obj,
                Vector((0.0, 0.0, 0.0)),
                radius=5.0,
                height=2.0,
                num_frames=8,
                context=ctx,
                blend_data=bdata,
            )
            is True
        )
        assert kp.interpolation == "LINEAR"

        mesh_obj = MagicMock()
        mesh_obj.name = "Oak_LOD0"
        mesh_obj.bound_box = [(-1.0, -1.0, 0.0), (1.0, 1.0, 3.0)]
        mesh_obj.matrix_world = None

        rig_coll = MagicMock()
        rig_coll.objects.__iter__.return_value = [proxy_obj, cam_obj]
        bdata.collections.get.side_effect = [None, rig_coll]
        bdata.collections.new.return_value = rig_coll
        bdata.objects.get.return_value = None
        bdata.objects.new.side_effect = [proxy_obj, cam_obj, MagicMock(), MagicMock()]

        rig_info = setup_impostor_preview_rig(
            ctx,
            [mesh_obj],
            "Oak",
            str(tmp_path),
            mode="SIDE_BY_SIDE",
            create_turntable=True,
            blend_data=bdata,
        )
        assert rig_info["collection"] == "Oak_Preview_Rig"

        torn_down = teardown_impostor_preview_rig(ctx, "Oak", blend_data=bdata)
        assert torn_down is True
        bdata.collections.remove.assert_called_once_with(rig_coll)


# =========================================================================
# 3. PBR Importer Deep Tests (OCIOColorSpaceResolver, ShaderGraphBuilder, BatchMaterialSlotMatcher)
# =========================================================================


def test_ocio_resolver_shader_graph_builder_and_slot_matcher(tmp_path: Path) -> None:
    """Verify OCIOColorSpaceResolver, ShaderGraphBuilder.build_pbr_graph, and BatchMaterialSlotMatcher."""
    OCIOColorSpaceResolver.apply_colorspace(None, is_data=True)
    img = MagicMock()
    img.name = "T_Hero_ORM.png"
    enum_item = MagicMock()
    enum_item.identifier = "Non-Color"
    prop = MagicMock()
    prop.enum_items = [enum_item]
    img.colorspace_settings.bl_rna.properties.get.return_value = prop
    OCIOColorSpaceResolver.apply_colorspace(img, is_data=True)
    assert img.colorspace_settings.name == "Non-Color"

    fake_bpy = MagicMock()
    fake_bpy.path.abspath.side_effect = lambda p: p
    fake_bpy.path.relpath.side_effect = lambda p: "//" + os.path.basename(p)
    bdata = MagicMock()
    bdata.filepath = str(tmp_path / "scene.blend")
    bdata.is_saved = True
    bdata.images.load.return_value = img
    bdata.images.__iter__.return_value = [img]

    albedo_file = tmp_path / "Wood_BaseColor.png"
    orm_file = tmp_path / "Wood_ORM.png"
    norm_file = tmp_path / "Wood_Normal.png"
    disp_file = tmp_path / "Wood_Height.exr"
    for f in (albedo_file, orm_file, norm_file, disp_file):
        f.write_bytes(b"img")

    class FakeLoc:
        def __init__(self, x: float = 0.0, y: float = 0.0) -> None:
            self.x = x
            self.y = y

    class FakeNode(MagicMock):
        def __setattr__(self, name: str, value: Any) -> None:
            if name == "location" and isinstance(value, tuple):
                super().__setattr__(name, FakeLoc(value[0], value[1]))
            else:
                super().__setattr__(name, value)

    def _make_node(type: str = "") -> Any:
        n = FakeNode()
        n.type = type
        n.location = (0.0, 0.0)
        sock_dict: dict[Any, Any] = {
            "BSDF": MagicMock(),
            "Surface": MagicMock(),
            "Displacement": MagicMock(),
            "Vector": MagicMock(is_linked=False),
            "UV": MagicMock(),
            "Color": MagicMock(),
            "Alpha": MagicMock(),
            "Base Color": MagicMock(is_linked=False),
            "Roughness": MagicMock(),
            "Metallic": MagicMock(),
            "Normal": MagicMock(),
            "Height": MagicMock(),
            "Scale": MagicMock(),
            "Result": MagicMock(name="Result", type="RGBA"),
            "A": MagicMock(name="A", type="RGBA"),
            "B": MagicMock(name="B", type="RGBA"),
            "Factor": MagicMock(name="Factor", type="VALUE"),
            "Red": MagicMock(),
            "Green": MagicMock(),
            "Blue": MagicMock(),
            "Value": MagicMock(),
            0: MagicMock(),
            1: MagicMock(),
        }
        inputs_mock = MagicMock()
        inputs_mock.__getitem__.side_effect = lambda k: sock_dict.setdefault(k, MagicMock())
        inputs_mock.get.side_effect = lambda k, d=None: sock_dict.get(k, d)
        inputs_mock.__contains__.side_effect = lambda k: k in sock_dict
        inputs_mock.__iter__.return_value = [sock_dict["Factor"], sock_dict["A"], sock_dict["B"]]
        n.inputs = inputs_mock
        outputs_mock = MagicMock()
        outputs_mock.__getitem__.side_effect = lambda k: sock_dict.setdefault(k, MagicMock())
        outputs_mock.get.side_effect = lambda k, d=None: sock_dict.get(k, d)
        outputs_mock.__contains__.side_effect = lambda k: k in sock_dict
        outputs_mock.__iter__.return_value = [sock_dict["Result"]]
        n.outputs = outputs_mock
        return n

    mat = MagicMock()
    mat.name = "Wood"
    mat.use_nodes = True
    mat.node_tree.nodes.new.side_effect = _make_node
    mat.node_tree.nodes.__iter__.return_value = []

    preset = {
        "name": "UE5 Packed",
        "maps": [
            {
                "id": "base_color",
                "name": "Base Color",
                "suffixes": ["_basecolor"],
                "colorspace": "sRGB",
                "channels": {
                    "RGB": {"target": "Base Color", "invert": True},
                    "A": {"target": "Alpha", "invert": False},
                },
            },
            {
                "id": "orm",
                "name": "ORM",
                "suffixes": ["_orm"],
                "colorspace": "Non-Color",
                "channels": {
                    "R": {"target": "Ambient Occlusion", "invert": False},
                    "G": {"target": "Roughness", "invert": True},
                    "B": {"target": "Metallic", "invert": False},
                },
            },
            {
                "id": "normal",
                "name": "Normal",
                "suffixes": ["_normal"],
                "colorspace": "Non-Color",
                "normal_format": "DIRECTX",
                "channels": {
                    "RGB": {"target": "Normal", "invert": False},
                },
            },
            {
                "id": "displacement",
                "name": "Displacement",
                "suffixes": ["_height"],
                "colorspace": "Non-Color",
                "channels": {
                    "R": {"target": "Displacement", "invert": False},
                },
            },
        ],
    }

    with patch.object(pbr_mod, "bpy", fake_bpy):
        rel_p, is_rel = ShaderGraphBuilder.resolve_texture_path(str(albedo_file), mode="RELATIVE", blend_data=bdata)
        assert is_rel is True
        assert rel_p.startswith("//")

        ok = ShaderGraphBuilder.build_pbr_graph(
            mat,
            {
                "base_color": str(albedo_file),
                "orm": str(orm_file),
                "normal": str(norm_file),
                "displacement": str(disp_file),
            },
            preset=preset,
            preserve_existing=False,
            ao_blend_mode="MULTIPLY",
            path_mode="RELATIVE",
            blend_data=bdata,
        )
        assert ok is True

        # BatchMaterialSlotMatcher
        obj_mesh = MagicMock()
        slot_wood = MagicMock()
        slot_wood.name = "Wood"
        obj_mesh.material_slots = [slot_wood]
        matched = BatchMaterialSlotMatcher.match_directory_to_slots(obj_mesh, str(tmp_path), preset=preset)
        assert "Wood" in matched
        assert "base_color" in matched["Wood"]
