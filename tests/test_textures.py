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
    def __init__(self, image: object, name: str = "Image Texture"):
        self.type = "TEX_IMAGE"
        self.image = image
        self.name = name


class DummyRerouteNode:
    def __init__(self, target_node: object):
        self.type = "REROUTE"
        self.inputs = [DummySocket(0.0, linked_node=target_node)]


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


def test_memory_compaction():
    TextureChannelPacker.compact_memory()


def test_texture_pool_manager_submit_and_wait_all():
    from core.textures import TexturePoolManager

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
    from core.textures import TexturePoolManager

    assert TexturePoolManager.wait_all([]) == []
