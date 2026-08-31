"""
Unit tests for OmniMesh PBR Texture Channel Packer & Normal Map Converter.
"""

from __future__ import annotations

import os
import tempfile
import numpy as np
from PIL import Image

from core.textures import TextureChannelPacker


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
    def __init__(self, image: object):
        self.type = "TEX_IMAGE"
        self.image = image


class DummyNormalMapNode:
    def __init__(self, tex_node: object):
        self.type = "NORMAL_MAP"
        self.inputs = {"Color": DummySocket([0.5, 0.5, 1.0, 1.0], linked_node=tex_node)}


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
    def __init__(self, normal_node: object | None = None):
        self.nodes = [DummyBSDFNode(normal_node)]


class DummyMaterial:
    def __init__(self, normal_node: object | None = None):
        self.name = "M_TestPBR"
        self.use_nodes = True
        self.node_tree = DummyNodeTree(normal_node)


def test_extract_socket_data_fallback():
    mat = DummyMaterial()
    roughness_arr = TextureChannelPacker.extract_socket_data(mat, "Roughness", (64, 64), default_val=0.5)
    assert roughness_arr.shape == (64, 64)
    assert roughness_arr.dtype == np.uint8
    assert np.allclose(roughness_arr, 64, atol=1)

    metal_arr = TextureChannelPacker.extract_socket_data(mat, "Metallic", (64, 64), default_val=0.0)
    assert np.allclose(metal_arr, 191, atol=1)


def test_get_material_normal_image():
    dummy_img = object()
    tex_node = DummyTexImageNode(dummy_img)
    norm_node = DummyNormalMapNode(tex_node)
    mat = DummyMaterial(normal_node=norm_node)

    found_img = TextureChannelPacker.get_material_normal_image(mat)
    assert found_img is dummy_img


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


def test_pack_comp_msfs():
    mat = DummyMaterial()
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = os.path.join(tmpdir, "T_Test_COMP.png")
        success = TextureChannelPacker.pack_comp_msfs(mat, out_path, (64, 64))
        assert success is True
        assert os.path.exists(out_path)

        img = Image.open(out_path)
        arr = np.asarray(img)
        assert np.all(arr[:, :, 0] == 255)
        assert np.allclose(arr[:, :, 1], 64, atol=1)
        assert np.allclose(arr[:, :, 2], 191, atol=1)


def test_convert_normal_directx():
    class DummyImage:
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

    src_img = DummyImage()
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


def test_memory_compaction():
    TextureChannelPacker.compact_memory()
