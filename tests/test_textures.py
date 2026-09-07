"""
Unit tests for OmniMesh PBR Texture Channel Packer, Thread Safety & Normal Map Converter.
"""

from __future__ import annotations

import concurrent.futures
import os
import tempfile
import numpy as np
from PIL import Image

from core.pbr_presets import PBRImporterPresetManager
from core.textures import TextureChannelPacker, TexturePoolManager, write_png_direct


class DummySocket:
    def __init__(self, default_value: float | list[float], linked_node: object | None = None):
        self.default_value = default_value
        self.is_linked = linked_node is not None
        self.links = []
        if linked_node:

            class DummyLink:
                def __init__(self, node: object):
                    self.from_node = node

            self.links = [DummyLink(linked_node)]


class DummyTexImageNode:
    def __init__(self, image: object, name: str = "Image Texture"):
        self.type = "TEX_IMAGE"
        self.image = image
        self.name = name


class DummyRerouteNode:
    def __init__(self, target_node: object | None = None):
        self.type = "REROUTE"
        self.inputs = [DummySocket(0.0, linked_node=target_node)] if target_node else []


class DummyNormalMapNode:
    def __init__(self, tex_node: object):
        self.type = "NORMAL_MAP"
        self.inputs = {"Color": DummySocket([0.5, 0.5, 1.0, 1.0], linked_node=tex_node)}


class DummyBumpNode:
    def __init__(self, tex_node: object):
        self.type = "BUMP"
        self.inputs = {"Height": DummySocket(0.5, linked_node=tex_node)}


class DummyBSDFNode:
    def __init__(self, normal_node: object | None = None):
        self.type = "BSDF_PRINCIPLED"
        self.inputs = {
            "Base Color": DummySocket([0.8, 0.2, 0.2, 1.0]),
            "Metallic": DummySocket(0.75),
            "Roughness": DummySocket(0.25),
            "Ambient Occlusion": DummySocket(1.0),
            "Normal": DummySocket([0.0, 0.0, 0.0], linked_node=normal_node),
        }


class DummyNodeTree:
    def __init__(self, nodes: list[object] | None = None, normal_node: object | None = None):
        if nodes is not None:
            self.nodes = nodes
        else:
            self.nodes = [DummyBSDFNode(normal_node)]


class DummyMaterial:
    def __init__(self, normal_node: object | None = None, nodes: list[object] | None = None, use_nodes: bool = True):
        self.name = "M_TestPBR"
        self.use_nodes = use_nodes
        self.node_tree = DummyNodeTree(nodes=nodes, normal_node=normal_node) if use_nodes else None


class DummyImage:
    def __init__(self, size: tuple[int, int] = (64, 64), name: str = "T_Texture", fill_val: float = 0.5):
        self.size = size
        self.name = name
        floats = np.full(size[0] * size[1] * 4, fill_val, dtype=np.float32)
        self._pixels = floats

    @property
    def pixels(self):
        class PixelsWrapper:
            def __init__(self, data):
                self.data = data

            def foreach_get(self, dest):
                np.copyto(dest, self.data)

        return PixelsWrapper(self._pixels)


def test_extract_socket_data_fallback():
    mat = DummyMaterial()
    roughness_arr = TextureChannelPacker.extract_socket_data(mat, "Roughness", (64, 64), default_val=0.5)
    assert roughness_arr.shape == (64, 64)
    assert roughness_arr.dtype == np.uint8
    assert np.allclose(roughness_arr, 64, atol=1)

    metal_arr = TextureChannelPacker.extract_socket_data(mat, "Metallic", (64, 64), default_val=0.0)
    assert np.allclose(metal_arr, 191, atol=1)


def test_extract_socket_data_nan_inf_guards():
    # Socket with NaN default value should not crash with int conversion error
    bsdf = DummyBSDFNode()
    bsdf.inputs["Roughness"] = DummySocket(float("nan"))
    mat = DummyMaterial(nodes=[bsdf])

    arr = TextureChannelPacker.extract_socket_data(mat, "Roughness", (32, 32), default_val=0.5)
    assert arr.shape == (32, 32)
    assert np.allclose(arr, 127, atol=1)  # Falls back to default_val (0.5)


def test_extract_socket_data_unlinked_ao_node_search():
    # Principled BSDF does not have "Ambient Occlusion" socket, but an unlinked AO texture node is in the tree
    bsdf = DummyBSDFNode()
    del bsdf.inputs["Ambient Occlusion"]
    ao_img = DummyImage(size=(32, 32), name="T_Character_AO", fill_val=0.8)
    ao_node = DummyTexImageNode(ao_img, name="AO Texture")
    mat = DummyMaterial(nodes=[bsdf, ao_node])

    ao_arr = TextureChannelPacker.extract_socket_data(mat, "Ambient Occlusion", (32, 32), default_val=1.0)
    assert np.allclose(ao_arr, int(0.8 * 255), atol=1)


def test_get_material_normal_image_reroute_and_bump():
    dummy_img = object()
    tex_node = DummyTexImageNode(dummy_img)

    # Direct normal map
    norm_node = DummyNormalMapNode(tex_node)
    mat1 = DummyMaterial(normal_node=norm_node)
    assert TextureChannelPacker.get_material_normal_image(mat1) is dummy_img

    # Normal map through REROUTE node
    reroute_node = DummyRerouteNode(norm_node)
    mat2 = DummyMaterial(normal_node=reroute_node)
    assert TextureChannelPacker.get_material_normal_image(mat2) is dummy_img

    # Bump node
    bump_node = DummyBumpNode(tex_node)
    mat3 = DummyMaterial(normal_node=bump_node)
    assert TextureChannelPacker.get_material_normal_image(mat3) is dummy_img

    # No nodes or None
    assert TextureChannelPacker.get_material_normal_image(None) is None
    assert TextureChannelPacker.get_material_normal_image(DummyMaterial(use_nodes=False)) is None


def test_reroute_cycle_protection():
    # Create cyclic reroutes A -> B -> A
    reroute_a = DummyRerouteNode(None)
    reroute_b = DummyRerouteNode(reroute_a)
    reroute_a.inputs = [DummySocket(0.0, linked_node=reroute_b)]

    mat_cycle = DummyMaterial(normal_node=reroute_a)
    # Should safely break cycle and return None without hanging in infinite loop
    assert TextureChannelPacker.get_material_normal_image(mat_cycle) is None


def test_pack_orm_ue5():
    mat = DummyMaterial()
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = os.path.join(tmpdir, "T_Test_ORM.png")
        success = TextureChannelPacker.pack_orm_ue5(mat, out_path, (128, 128))
        assert success is True
        assert os.path.exists(out_path)

        img = Image.open(out_path)
        assert img.size == (128, 128)
        assert img.mode == "RGBA"
        arr = np.asarray(img)
        assert np.all(arr[:, :, 0] == 255)
        assert np.allclose(arr[:, :, 1], 64, atol=1)
        assert np.allclose(arr[:, :, 2], 191, atol=1)
        assert np.all(arr[:, :, 3] == 255)
        img.close()


def test_pack_maskmap_unity_smoothness():
    mat = DummyMaterial()
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = os.path.join(tmpdir, "T_Test_MaskMap.png")
        success = TextureChannelPacker.pack_maskmap_unity(mat, out_path, (64, 64))
        assert success is True
        assert os.path.exists(out_path)

        img = Image.open(out_path)
        arr = np.asarray(img)
        assert np.allclose(arr[:, :, 0], 191, atol=1)
        assert np.all(arr[:, :, 1] == 255)
        assert np.all(arr[:, :, 2] == 0)
        assert np.allclose(arr[:, :, 3], 191, atol=1)
        img.close()


def test_pack_comp_msfs_and_godot():
    mat = DummyMaterial()
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path_msfs = os.path.join(tmpdir, "T_Test_COMP.png")
        assert TextureChannelPacker.pack_comp_msfs(mat, out_path_msfs, (64, 64)) is True
        img1 = Image.open(out_path_msfs)
        arr1 = np.asarray(img1)
        assert np.all(arr1[:, :, 0] == 255)
        assert np.allclose(arr1[:, :, 1], 64, atol=1)
        assert np.allclose(arr1[:, :, 2], 191, atol=1)
        img1.close()

        out_path_godot = os.path.join(tmpdir, "T_Test_Godot_ORM.png")
        assert TextureChannelPacker.pack_orm_godot(mat, out_path_godot, (64, 64)) is True
        img2 = Image.open(out_path_godot)
        arr2 = np.asarray(img2)
        assert np.all(arr2[:, :, 0] == 255)
        assert np.allclose(arr2[:, :, 1], 64, atol=1)
        assert np.allclose(arr2[:, :, 2], 191, atol=1)
        img2.close()


def test_convert_normal_directx():
    class DummyNormalImage:
        def __init__(self):
            self.size = (64, 64)
            self.name = "T_Normal"
            floats = np.zeros(64 * 64 * 4, dtype=np.float32)
            floats[0::4] = 0.5
            floats[1::4] = 0.75
            floats[2::4] = 1.0
            floats[3::4] = 1.0
            self._pixels = floats

        @property
        def pixels(self):
            class PixelsWrapper:
                def __init__(self, data):
                    self.data = data

                def foreach_get(self, dest):
                    np.copyto(dest, self.data)

            return PixelsWrapper(self._pixels)

    src_img = DummyNormalImage()
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = os.path.join(tmpdir, "T_Normal_DirectX.png")
        success = TextureChannelPacker.convert_normal_directx(src_img, out_path, (64, 64))
        assert success is True
        assert os.path.exists(out_path)

        img = Image.open(out_path)
        arr = np.asarray(img)
        assert np.allclose(arr[:, :, 0], 128, atol=1)
        assert np.allclose(arr[:, :, 1], 64, atol=1)
        assert np.all(arr[:, :, 2] == 255)
        assert np.all(arr[:, :, 3] == 255)
        img.close()

    # Null / zero size image returns False
    assert TextureChannelPacker.convert_normal_directx(None, "dummy.png") is False


def test_convert_normal_directx_nan_inf_sanitization():
    class CorruptNormalImage:
        def __init__(self):
            self.size = (32, 32)
            self.name = "T_Corrupt_Normal"
            floats = np.zeros(32 * 32 * 4, dtype=np.float32)
            floats[0::4] = float("nan")
            floats[1::4] = float("inf")
            floats[2::4] = float("-inf")
            floats[3::4] = float("nan")
            self._pixels = floats

        @property
        def pixels(self):
            class PixelsWrapper:
                def __init__(self, data):
                    self.data = data

                def foreach_get(self, dest):
                    np.copyto(dest, self.data)

            return PixelsWrapper(self._pixels)

    src_img = CorruptNormalImage()
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = os.path.join(tmpdir, "T_Normal_Sanitized.png")
        success = TextureChannelPacker.convert_normal_directx(src_img, out_path, (32, 32))
        assert success is True
        assert os.path.exists(out_path)

        img = Image.open(out_path)
        arr = np.asarray(img)
        # NaN in Red -> 0.5 -> 128
        assert np.allclose(arr[:, :, 0], 128, atol=1)
        # Inf in Green -> 1.0 -> inverted for DirectX (255 - 255 = 0)
        assert np.allclose(arr[:, :, 1], 0, atol=1)
        # -Inf in Blue -> 0.0 -> 0
        assert np.all(arr[:, :, 2] == 0)
        img.close()


def test_save_array_to_disk_dimensions():
    with tempfile.TemporaryDirectory() as tmpdir:
        # 2D Grayscale
        arr_2d = np.full((32, 32), 100, dtype=np.uint8)
        p_2d = os.path.join(tmpdir, "test_2d.png")
        assert TextureChannelPacker._save_array_to_disk(arr_2d, p_2d) is True
        img_2d = Image.open(p_2d)
        assert img_2d.mode == "L"
        img_2d.close()

        # 3D 1-channel
        arr_3d_1 = np.full((32, 32, 1), 150, dtype=np.uint8)
        p_3d_1 = os.path.join(tmpdir, "test_3d_1.png")
        assert TextureChannelPacker._save_array_to_disk(arr_3d_1, p_3d_1) is True
        img_3d_1 = Image.open(p_3d_1)
        assert img_3d_1.mode == "L"
        img_3d_1.close()

        # 3D 3-channel RGB
        arr_rgb = np.full((32, 32, 3), 200, dtype=np.uint8)
        p_rgb = os.path.join(tmpdir, "test_rgb.png")
        assert TextureChannelPacker._save_array_to_disk(arr_rgb, p_rgb) is True
        img_rgb = Image.open(p_rgb)
        assert img_rgb.mode == "RGB"
        img_rgb.close()

        # 3D 4-channel RGBA
        arr_rgba = np.full((32, 32, 4), 255, dtype=np.uint8)
        p_rgba = os.path.join(tmpdir, "test_rgba.png")
        assert TextureChannelPacker._save_array_to_disk(arr_rgba, p_rgba) is True
        img_rgba = Image.open(p_rgba)
        assert img_rgba.mode == "RGBA"
        img_rgba.close()

        # Invalid arrays
        assert TextureChannelPacker._save_array_to_disk(None, p_rgba) is False  # type: ignore
        assert TextureChannelPacker._save_array_to_disk(np.empty((0, 0), dtype=np.uint8), p_rgba) is False


def test_texture_pool_manager_worker_exception_handling():
    # Future that raises an exception
    f_err: concurrent.futures.Future[bool] = concurrent.futures.Future()
    f_err.set_exception(IOError("Simulated disk error"))

    # Future that succeeds
    f_ok: concurrent.futures.Future[bool] = concurrent.futures.Future()
    f_ok.set_result(True)

    results = TexturePoolManager.wait_all([f_err, f_ok], timeout=5.0)
    assert len(results) == 2
    assert results[0] is False  # Handled without throwing unhandled exception
    assert results[1] is True


def test_memory_compaction():
    TextureChannelPacker.compact_memory()


def test_texture_pool_manager_submit_and_wait_all():
    with tempfile.TemporaryDirectory() as tmpdir:
        arr1 = np.full((32, 32, 4), 128, dtype=np.uint8)
        arr2 = np.full((32, 32, 4), 255, dtype=np.uint8)
        p1 = os.path.join(tmpdir, "pool_test1.png")
        p2 = os.path.join(tmpdir, "pool_test2.png")

        f1 = TexturePoolManager.submit_save(arr1, p1)
        f2 = TexturePoolManager.submit_save(arr2, p2)

        results = TexturePoolManager.wait_all([f1, f2], timeout=10.0)
        assert len(results) == 2
        assert all(results)
        assert os.path.exists(p1)
        assert os.path.exists(p2)


def test_texture_pool_manager_wait_empty():
    assert TexturePoolManager.wait_all([]) == []
    TexturePoolManager.shutdown()


def test_write_png_direct_8bit_and_16bit():
    with tempfile.TemporaryDirectory() as tmpdir:
        # 8-bit RGB
        arr_8_rgb = np.full((32, 32, 3), 128, dtype=np.uint8)
        p_8_rgb = os.path.join(tmpdir, "test_8_rgb.png")
        assert write_png_direct(p_8_rgb, arr_8_rgb, bit_depth=8) is True
        assert os.path.exists(p_8_rgb)
        with Image.open(p_8_rgb) as img_read:
            assert img_read.size == (32, 32)
            assert img_read.mode == "RGB"

        # 16-bit RGBA
        arr_16_rgba = np.full((16, 16, 4), 32768, dtype=np.uint16)
        p_16_rgba = os.path.join(tmpdir, "test_16_rgba.png")
        assert write_png_direct(p_16_rgba, arr_16_rgba, bit_depth=16) is True
        assert os.path.exists(p_16_rgba)

        # Verify 16-bit PNG header directly (byte 24 in PNG stream is bit depth)
        with open(p_16_rgba, "rb") as f:
            header = f.read(30)
            assert header[:8] == b"\x89PNG\r\n\x1a\n"
            # IHDR chunk: 4 bytes length, 4 bytes "IHDR", 4 bytes width, 4 bytes height, 1 byte bit depth
            bit_depth_byte = header[24]
            assert bit_depth_byte == 16

        # Invalid array
        assert write_png_direct(os.path.join(tmpdir, "invalid.png"), None) is False


def test_pack_material_preset_ue5():
    preset = PBRImporterPresetManager.get_preset("unreal_engine_5")
    mat = DummyMaterial()
    with tempfile.TemporaryDirectory() as tmpdir:
        futures = TextureChannelPacker.pack_material_preset(
            material=mat,
            preset=preset,
            export_dir=tmpdir,
            asset_name="SM_Hero",
            target_size=(64, 64),
            bit_depth=8,
            strategy="CONVERT_PNG",
            naming_pattern="{asset}_{material}{suffix}",
        )
        assert len(futures) > 0
        results = TexturePoolManager.wait_all(futures, timeout=10.0)
        assert all(results)

        orm_file = os.path.join(tmpdir, "SM_Hero_M_TestPBR_ORM.png")
        assert os.path.exists(orm_file)
        with Image.open(orm_file) as img:
            arr = np.asarray(img)
            # In DummyMaterial: AO = 1.0 (255), Roughness = 0.25 (64), Metallic = 0.75 (191)
            assert np.allclose(arr[:, :, 0], 255, atol=1)
            assert np.allclose(arr[:, :, 1], 64, atol=1)
            assert np.allclose(arr[:, :, 2], 191, atol=1)


def test_pack_material_preset_16bit():
    preset = PBRImporterPresetManager.get_preset("unreal_engine_5")
    mat = DummyMaterial()
    with tempfile.TemporaryDirectory() as tmpdir:
        futures = TextureChannelPacker.pack_material_preset(
            material=mat,
            preset=preset,
            export_dir=tmpdir,
            asset_name="SM_Prop",
            target_size=(32, 32),
            bit_depth=16,
            strategy="CONVERT_PNG",
            naming_pattern="{material}{suffix}",
        )
        assert len(futures) > 0
        results = TexturePoolManager.wait_all(futures, timeout=10.0)
        assert all(results)

        orm_file = os.path.join(tmpdir, "M_TestPBR_ORM.png")
        assert os.path.exists(orm_file)
        with open(orm_file, "rb") as f:
            header = f.read(30)
            assert header[24] == 16  # Bit depth is 16


def test_pack_material_preset_passthrough():
    preset = PBRImporterPresetManager.get_preset("godot_4_orm")
    mat = DummyMaterial()
    with tempfile.TemporaryDirectory() as tmpdir:
        futures = TextureChannelPacker.pack_material_preset(
            material=mat,
            preset=preset,
            export_dir=tmpdir,
            asset_name="SM_Hero",
            target_size=(32, 32),
            bit_depth=8,
            strategy="PASSTHROUGH",
        )
        assert len(futures) > 0
        results = TexturePoolManager.wait_all(futures, timeout=10.0)
        assert all(results)


def test_trace_upstream_channel_decouple_ao():
    # Build node graph with ShaderNodeMix (MULTIPLY): Socket A = BaseColor image, Socket B = AO image
    base_img = DummyImage(size=(32, 32), name="T_Character_BaseColor", fill_val=0.9)
    base_tex_node = DummyTexImageNode(base_img, name="BaseColor Node")

    ao_img = DummyImage(size=(32, 32), name="T_Character_AO", fill_val=0.4)
    ao_tex_node = DummyTexImageNode(ao_img, name="AO Node")

    class DummyMixNode:
        def __init__(self, node_a: object, node_b: object):
            self.type = "MIX"
            self.blend_type = "MULTIPLY"
            self.inputs = {
                "A": DummySocket([0.0, 0.0, 0.0, 1.0], linked_node=node_a),
                "B": DummySocket(1.0, linked_node=node_b),
            }

    mix_node = DummyMixNode(base_tex_node, ao_tex_node)
    bsdf = DummyBSDFNode()
    bsdf.inputs["Base Color"] = DummySocket([0.0, 0.0, 0.0, 1.0], linked_node=mix_node)
    mat = DummyMaterial(nodes=[bsdf, mix_node, base_tex_node, ao_tex_node])

    # Tracing Base Color must extract clean BaseColor node, bypassing the AO multiply
    img_bc, ch_bc, inv_bc, _ = TextureChannelPacker.trace_upstream_channel(mat, "Base Color")
    assert img_bc is base_img

    # Tracing Ambient Occlusion must extract the AO image from Socket B of the mix node
    img_ao, ch_ao, inv_ao, _ = TextureChannelPacker.trace_upstream_channel(mat, "Ambient Occlusion")
    assert img_ao is ao_img


def test_bake_material_socket_graceful_fallback():
    mat = DummyMaterial()
    # In headless non-interactive mode without active MESH object, bake must safely return None
    result = TextureChannelPacker.bake_material_socket(mat, "Roughness", (32, 32))
    assert result is None


def test_is_procedural_socket():
    # Socket linked to a TexImage node -> NOT procedural
    img = DummyImage(size=(32, 32), name="T_Noise_Map")
    tex_node = DummyTexImageNode(img)
    bsdf = DummyBSDFNode()
    bsdf.inputs["Roughness"] = DummySocket(0.5, linked_node=tex_node)
    mat = DummyMaterial(nodes=[bsdf, tex_node])
    assert TextureChannelPacker.is_procedural_socket(mat, "Roughness") is False

    # Socket linked to non-image node (e.g. ColorRamp or Math) -> IS procedural
    class DummyColorRampNode:
        def __init__(self):
            self.type = "VALTORGB"
            self.inputs = []

    ramp = DummyColorRampNode()
    bsdf2 = DummyBSDFNode()
    bsdf2.inputs["Roughness"] = DummySocket(0.5, linked_node=ramp)
    mat2 = DummyMaterial(nodes=[bsdf2, ramp])
    assert TextureChannelPacker.is_procedural_socket(mat2, "Roughness") is True

    # Unlinked socket -> NOT procedural
    bsdf3 = DummyBSDFNode()
    mat3 = DummyMaterial(nodes=[bsdf3])
    assert TextureChannelPacker.is_procedural_socket(mat3, "Roughness") is False


def test_pack_material_preset_dominant_resolution():
    """Verify channels with mismatched resolutions adopt the dominant maximum resolution."""
    # AO image is 64x64, Roughness image is 128x128
    ao_img = DummyImage(size=(64, 64), name="T_AO", fill_val=1.0)
    ao_node = DummyTexImageNode(ao_img)
    rough_img = DummyImage(size=(128, 128), name="T_Roughness", fill_val=0.5)
    rough_node = DummyTexImageNode(rough_img)

    bsdf = DummyBSDFNode()
    bsdf.inputs["Ambient Occlusion"] = DummySocket(1.0, linked_node=ao_node)
    bsdf.inputs["Roughness"] = DummySocket(0.5, linked_node=rough_node)
    mat = DummyMaterial(nodes=[bsdf, ao_node, rough_node])

    preset = {
        "id": "test_dominant",
        "name": "Dominant Res Preset",
        "maps": [
            {
                "id": "orm",
                "export": True,
                "export_suffix": "_ORM",
                "channels": {
                    "r": {"target": "Ambient Occlusion", "invert": False},
                    "g": {"target": "Roughness", "invert": False},
                    "b": {"target": "Metallic", "default": 0.0},
                },
            }
        ],
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        futures = TextureChannelPacker.pack_material_preset(
            material=mat,
            preset=preset,
            export_dir=tmpdir,
            asset_name="SM_Dominant",
            target_size=(32, 32),  # Target size is 32, but dominant image is 128!
            strategy="SMART_AUTO",
        )
        assert len(futures) > 0
        results = TexturePoolManager.wait_all(futures, timeout=10.0)
        assert all(results)

        orm_file = os.path.join(tmpdir, "M_TestPBR_ORM.png")
        assert os.path.exists(orm_file)
        with Image.open(orm_file) as img:
            # Dominant resolution rule: must match maximum linked texture size (128x128)
            assert img.size == (128, 128)
