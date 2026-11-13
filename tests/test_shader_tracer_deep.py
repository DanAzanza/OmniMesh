"""
Deep tests for core/shader_tracer.py covering normal image resolution,
upstream channel tracing, procedural detection, bilinear resampling,
and Cycles socket bake fallbacks.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import numpy as np
import pytest

from core import shader_tracer as tracer_mod
from core.shader_tracer import ShaderTracer


class _FakeSocket:
    def __init__(self, name: str, default_value: Any = None) -> None:
        self.name = name
        self.default_value = default_value
        self.links: list[Any] = []

    @property
    def is_linked(self) -> bool:
        return len(self.links) > 0


class _SocketCollection(list):
    def __contains__(self, item: object) -> bool:
        if isinstance(item, str):
            return any(s.name == item for s in self)
        return super().__contains__(item)

    def __getitem__(self, key: Any) -> Any:
        if isinstance(key, str):
            for sock in self:
                if sock.name == key:
                    return sock
            raise KeyError(key)
        return super().__getitem__(key)

    def get(self, name: str, default: Any = None) -> Any:
        for sock in self:
            if sock.name == name:
                return sock
        return default


class _FakeNode:
    def __init__(self, node_type: str, name: str = "", **attrs: Any) -> None:
        self.type = node_type
        self.name = name or node_type
        self.inputs = _SocketCollection()
        self.outputs = _SocketCollection()
        for key, value in attrs.items():
            setattr(self, key, value)


class _FakeLink:
    def __init__(self, from_node: Any, from_socket: Any, to_node: Any, to_socket: Any) -> None:
        self.from_node = from_node
        self.from_socket = from_socket
        self.to_node = to_node
        self.to_socket = to_socket


class _FakeLinks(list):
    def new(self, from_socket: _FakeSocket, to_socket: _FakeSocket) -> _FakeLink:
        from_node = getattr(from_socket, "_owner", None)
        to_node = getattr(to_socket, "_owner", None)
        link = _FakeLink(from_node, from_socket, to_node, to_socket)
        from_socket.links.append(link)
        to_socket.links.append(link)
        self.append(link)
        return link

    def remove(self, link: Any) -> None:
        if link in self:
            super().remove(link)
        for sock in (getattr(link, "from_socket", None), getattr(link, "to_socket", None)):
            if sock is not None and link in sock.links:
                sock.links.remove(link)


class _FakeNodes(list):
    def __init__(self) -> None:
        super().__init__()
        self.active: Any = None

    def new(self, *, type: str) -> _FakeNode:
        node_type_map = {
            "ShaderNodeEmission": "EMISSION",
            "ShaderNodeTexImage": "TEX_IMAGE",
        }
        node = _FakeNode(node_type_map.get(type, type), name=f"{type}_{len(self)}")
        if type == "ShaderNodeEmission":
            _add_in(node, "Color", (1.0, 1.0, 1.0, 1.0))
            _add_out(node, "Emission")
        self.append(node)
        return node

    def remove(self, node: Any) -> None:
        if node in self:
            super().remove(node)


class _FakeNodeTree:
    def __init__(self) -> None:
        self.nodes = _FakeNodes()
        self.links = _FakeLinks()


def _add_in(node: _FakeNode, name: str, default: Any = None) -> _FakeSocket:
    sock = _FakeSocket(name, default)
    sock._owner = node  # type: ignore[attr-defined]
    node.inputs.append(sock)
    return sock


def _add_out(node: _FakeNode, name: str) -> _FakeSocket:
    sock = _FakeSocket(name, None)
    sock._owner = node  # type: ignore[attr-defined]
    node.outputs.append(sock)
    return sock


def _connect(tree: _FakeNodeTree, from_node: _FakeNode, from_out: str, to_node: _FakeNode, to_in: str) -> _FakeLink:
    link = _FakeLink(from_node, from_node.outputs[from_out], to_node, to_node.inputs[to_in])
    from_node.outputs[from_out].links.append(link)
    to_node.inputs[to_in].links.append(link)
    tree.links.append(link)
    return link


def _make_image(
    name: str = "tex.png",
    *,
    width: int = 2,
    height: int = 2,
    pixels: np.ndarray | None = None,
    colorspace: str = "Non-Color",
    raise_foreach: bool = False,
    raise_buffers_free: bool = False,
) -> Any:
    arr = pixels if pixels is not None else np.zeros(width * height * 4, dtype=np.float32)

    class _Pixels:
        def foreach_get(self, out: np.ndarray) -> None:
            if raise_foreach:
                raise RuntimeError("Pixel read error")
            out[:] = arr

    def _buffers_free() -> None:
        if raise_buffers_free:
            raise RuntimeError("Buffer lock")

    return SimpleNamespace(
        name=name,
        size=[width, height],
        pixels=_Pixels(),
        buffers_free=_buffers_free,
        colorspace_settings=SimpleNamespace(name=colorspace),
    )


def _make_material(name: str = "Mat", *, use_nodes: bool = True, tree: _FakeNodeTree | None = None) -> Any:
    return SimpleNamespace(name=name, use_nodes=use_nodes, node_tree=tree)


class TestShaderTracerDeep:
    def test_get_material_normal_image_paths(self) -> None:
        assert ShaderTracer.get_material_normal_image(None) is None

        tree = _FakeNodeTree()
        bsdf = _FakeNode("BSDF_PRINCIPLED", "BSDF")
        _add_in(bsdf, "Normal")

        img = _make_image("Normal.png", width=2, height=2)
        tex = _FakeNode("TEX_IMAGE", "TexN", image=img)
        _add_out(tex, "Color")

        sep = _FakeNode("SEPARATE_COLOR", "Sep")
        _add_in(sep, "Color")
        _add_out(sep, "Red")
        comb = _FakeNode("COMBINE_COLOR", "Comb")
        _add_in(comb, "Red")
        _add_out(comb, "Color")

        rr1 = _FakeNode("REROUTE", "RR1")
        _add_in(rr1, "Input")
        _add_out(rr1, "Output")
        nmap = _FakeNode("NORMAL_MAP", "NMap")
        _add_in(nmap, "Color")
        _add_out(nmap, "Normal")
        rr2 = _FakeNode("REROUTE", "RR2")
        _add_in(rr2, "Input")
        _add_out(rr2, "Output")

        tree.nodes.extend([bsdf, tex, sep, comb, rr1, nmap, rr2])
        _connect(tree, tex, "Color", sep, "Color")
        _connect(tree, sep, "Red", comb, "Red")
        _connect(tree, comb, "Color", rr1, "Input")
        _connect(tree, rr1, "Output", nmap, "Color")
        _connect(tree, nmap, "Normal", rr2, "Input")
        _connect(tree, rr2, "Output", bsdf, "Normal")

        mat = _make_material("NormMat", tree=tree)
        assert ShaderTracer.get_material_normal_image(mat) is img

        # Direct TEX_IMAGE on Normal
        tree2 = _FakeNodeTree()
        bsdf2 = _FakeNode("BSDF_PRINCIPLED", "BSDF2")
        _add_in(bsdf2, "Normal")
        tex2 = _FakeNode("TEX_IMAGE", "Tex2", image=img)
        _add_out(tex2, "Color")
        tree2.nodes.extend([bsdf2, tex2])
        _connect(tree2, tex2, "Color", bsdf2, "Normal")
        assert ShaderTracer.get_material_normal_image(_make_material("DirectNorm", tree=tree2)) is img

    def test_trace_upstream_channel_disp_ao_aliases_and_invert(self) -> None:
        assert ShaderTracer.trace_upstream_channel(None, "Roughness") == (None, 0, False, None)

        tree = _FakeNodeTree()
        out = _FakeNode("OUTPUT_MATERIAL", "Out", is_active_output=True)
        _add_in(out, "Displacement")
        disp = _FakeNode("DISPLACEMENT", "Disp")
        _add_in(disp, "Height")
        _add_out(disp, "Displacement")
        bsdf = _FakeNode("BSDF_PRINCIPLED", "BSDF")
        _add_in(bsdf, "Base Color", [0.4, 0.5, 0.6, 1.0])
        _add_in(bsdf, "Roughness", 0.35)
        _add_in(bsdf, "Alpha", 1.0)
        _add_in(bsdf, "Specular", 0.5)

        img_disp = _make_image("Height.png")
        tex_disp = _FakeNode("TEX_IMAGE", "TexDisp", image=img_disp)
        _add_out(tex_disp, "Color")

        img_base = _make_image("BaseColor.png")
        tex_base = _FakeNode("TEX_IMAGE", "TexBase", image=img_base)
        _add_out(tex_base, "Color")

        img_orm = _make_image("Metal_ORM.png")
        tex_orm = _FakeNode("TEX_IMAGE", "TexORM", image=img_orm)
        _add_out(tex_orm, "Color")

        sep = _FakeNode("SEPARATE_COLOR", "Sep")
        _add_in(sep, "Color")
        _add_out(sep, "Red")
        _add_out(sep, "Green")
        _add_out(sep, "Blue")

        mix = _FakeNode("MIX", "MixAO", blend_type="MULTIPLY")
        _add_in(mix, "A")
        _add_in(mix, "B")
        _add_out(mix, "Result")

        math_inv = _FakeNode("MATH", "InvSmooth", operation="SUBTRACT")
        _add_in(math_inv, "Value0", 1.0)
        _add_in(math_inv, "Value1", 0.0)
        _add_out(math_inv, "Value")

        tree.nodes.extend([out, disp, bsdf, tex_disp, tex_base, tex_orm, sep, mix, math_inv])
        _connect(tree, tex_disp, "Color", disp, "Height")
        _connect(tree, disp, "Displacement", out, "Displacement")
        _connect(tree, tex_base, "Color", mix, "A")
        _connect(tree, tex_orm, "Color", sep, "Color")
        _connect(tree, sep, "Red", mix, "B")
        _connect(tree, mix, "Result", bsdf, "Base Color")
        _connect(tree, sep, "Green", bsdf, "Roughness")
        _connect(tree, sep, "Blue", math_inv, "Value1")
        _connect(tree, math_inv, "Value", bsdf, "Alpha")

        mat = _make_material("PBR", tree=tree)
        assert ShaderTracer.trace_upstream_channel(mat, "Displacement") == (img_disp, 0, False, 0.0)
        assert ShaderTracer.trace_upstream_channel(mat, "Ambient Occlusion") == (img_orm, 0, False, 1.0)
        assert ShaderTracer.trace_upstream_channel(mat, "Base Color")[0] is img_base
        assert ShaderTracer.trace_upstream_channel(mat, "Roughness") == (img_orm, 1, False, 0.35)
        assert ShaderTracer.trace_upstream_channel(mat, "Alpha") == (img_orm, 0, True, 1.0)
        assert ShaderTracer.trace_upstream_channel(mat, "Specular IOR Level") == (None, 0, False, 0.5)

        # Procedural socket check (Noise linked directly to Metallic -> no TEX_IMAGE -> True)
        _add_in(bsdf, "Metallic", 0.0)
        noise = _FakeNode("TEX_NOISE", "Noise")
        _add_out(noise, "Fac")
        tree.nodes.append(noise)
        _connect(tree, noise, "Fac", bsdf, "Metallic")
        assert ShaderTracer.is_procedural_socket(mat, "Metallic") is True
        assert ShaderTracer.is_procedural_socket(mat, "Roughness") is False
        assert ShaderTracer.is_procedural_socket(mat, "Unlinked") is False

    def test_extract_socket_data_resample_and_colorspace_oetf(self) -> None:
        # Box downsample 4x4 -> 2x2
        src = np.full((4, 4), 100, dtype=np.uint8)
        box = ShaderTracer.resample_channel_bilinear_numpy(src, 2, 2, bit_depth=8)
        assert box.shape == (2, 2)
        assert int(box[0, 0]) == 100

        # Non-integer bilinear upsample 2x2 -> 3x3 at 16-bit
        src16 = np.array([[0, 65535], [65535, 0]], dtype=np.uint16)
        up16 = ShaderTracer.resample_channel_bilinear_numpy(src16, 3, 3, bit_depth=16)
        assert up16.shape == (3, 3) and up16.dtype == np.uint16

        # sRGB linear recovery & inverted channel extraction
        pix = np.zeros(2 * 2 * 4, dtype=np.float32)
        pix[0::4] = 0.214041  # ~0.5 in sRGB EOTF
        pix[1::4] = np.nan  # tests nan_to_num
        img = _make_image("Rough_sRGB.png", width=2, height=2, pixels=pix, colorspace="sRGB")

        tree = _FakeNodeTree()
        bsdf = _FakeNode("BSDF_PRINCIPLED", "BSDF")
        _add_in(bsdf, "Roughness", 0.4)
        _add_in(bsdf, "Base Color", (0.2, 0.2, 0.2, 1.0))
        tex = _FakeNode("TEX_IMAGE", "Tex", image=img)
        _add_out(tex, "Color")
        math_inv = _FakeNode("MATH", "Inv", operation="SUBTRACT")
        _add_in(math_inv, "Value0", 1.0)
        _add_in(math_inv, "Value1")
        _add_out(math_inv, "Value")
        tree.nodes.extend([bsdf, tex, math_inv])
        _connect(tree, tex, "Color", math_inv, "Value1")
        _connect(tree, math_inv, "Value", bsdf, "Roughness")
        _connect(tree, tex, "Color", bsdf, "Base Color")

        mat = _make_material("OETFMat", tree=tree)
        rough_arr = ShaderTracer.extract_socket_data(mat, "Roughness", (2, 2), bit_depth=8, apply_srgb_oetf=False)
        assert rough_arr.shape == (2, 2)
        assert 120 <= int(rough_arr[0, 0]) <= 135  # 255 - ~128 = ~127

        albedo_arr = ShaderTracer.extract_socket_data(mat, "Base Color", (4, 4), bit_depth=8, apply_srgb_oetf=True)
        assert albedo_arr.shape == (4, 4)

        # Error fallback when foreach_get raises
        bad_img = _make_image("Broken", width=2, height=2, raise_foreach=True, raise_buffers_free=True)
        fb = np.full((2, 2), 42, dtype=np.uint8)
        out_fb = ShaderTracer._extract_from_image(bad_img, (2, 2), 0, fb)
        assert np.all(out_fb == 42)

    def test_bake_material_socket_success_and_cleanup(self, monkeypatch: pytest.MonkeyPatch) -> None:
        assert ShaderTracer.bake_material_socket(None, "Base Color", (4, 4), blend_data=cast(Any, None)) is None

        tree = _FakeNodeTree()
        out = _FakeNode("OUTPUT_MATERIAL", "Out", is_active_output=True)
        _add_in(out, "Surface")
        bsdf = _FakeNode("BSDF_PRINCIPLED", "BSDF")
        _add_in(bsdf, "Base Color")
        _add_out(bsdf, "BSDF")
        noise = _FakeNode("TEX_NOISE", "Noise")
        _add_out(noise, "Color")
        tree.nodes.extend([out, bsdf, noise])
        _connect(tree, bsdf, "BSDF", out, "Surface")
        _connect(tree, noise, "Color", bsdf, "Base Color")
        mat = _make_material("BakeMat", tree=tree)

        created_images: list[Any] = []
        removed_images: list[Any] = []

        class _Images:
            def new(self, name: str, *, width: int, height: int, alpha: bool, float_buffer: bool) -> Any:
                arr = np.full(width * height * 4, 0.5, dtype=np.float32)
                img = _make_image(name, width=width, height=height, pixels=arr)
                created_images.append(img)
                return img

            def remove(self, img: Any, *, do_unlink: bool = True) -> None:
                removed_images.append(img)

        scene: Any = SimpleNamespace(
            render=SimpleNamespace(engine="BLENDER_EEVEE_NEXT"),
            cycles=SimpleNamespace(samples=64),
            objects=[],
        )
        mesh_obj: Any = SimpleNamespace(type="MESH", data=SimpleNamespace(materials=[mat]))
        scene.objects.append(mesh_obj)
        bdata: Any = SimpleNamespace(scenes=[scene], images=_Images())

        monkeypatch.setattr(
            tracer_mod,
            "bpy",
            SimpleNamespace(ops=SimpleNamespace(object=SimpleNamespace(bake=lambda **_kw: None))),
        )

        baked = ShaderTracer.bake_material_socket(
            mat, "Base Color", (2, 2), bit_depth=8, scene=scene, active_obj=mesh_obj, blend_data=bdata
        )
        assert baked is not None and baked.shape == (2, 2, 3) and baked.dtype == np.uint8
        assert scene.render.engine == "BLENDER_EEVEE_NEXT"
        assert scene.cycles.samples == 64
        assert len(removed_images) == 1
        # Temp nodes removed and BSDF link restored on Surface
        assert out.inputs["Surface"].links[0].from_node is bsdf

        # Negative branch: bake op raises RuntimeError -> still cleans up and returns None
        monkeypatch.setattr(
            tracer_mod,
            "bpy",
            SimpleNamespace(
                ops=SimpleNamespace(
                    object=SimpleNamespace(bake=lambda **_kw: (_ for _ in ()).throw(RuntimeError("no GPU")))
                )
            ),
        )
        assert (
            ShaderTracer.bake_material_socket(
                mat, "Base Color", (2, 2), bit_depth=16, scene=scene, active_obj=mesh_obj, blend_data=bdata
            )
            is None
        )
        assert scene.render.engine == "BLENDER_EEVEE_NEXT"
