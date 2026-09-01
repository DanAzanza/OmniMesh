"""
Unit tests for OmniMesh Occlusion & Interior Geometry Removal Engine with Material Transparency.
"""

from __future__ import annotations

import math
from typing import Any
import numpy as np

from core.occlusion import HardenedOcclusionCuller, RobustTransparencyEvaluator, Vector


class DummySocket:
    def __init__(self, default_value: Any = 1.0, is_linked: bool = False, links: list[Any] | None = None):
        self.default_value = default_value
        self.is_linked = is_linked
        self.links = links or []


class DummyNode:
    def __init__(self, node_type: str, inputs: dict[str, Any] | None = None, image: Any = None):
        self.type = node_type
        self.inputs = inputs or {}
        self.image = image


class DummyImage:
    def __init__(self, width: int = 16, height: int = 16, channels: int = 4, alpha_values: np.ndarray | None = None):
        self.size = (width, height)
        self.channels = channels
        self.depth = 32
        self.alpha_mode = "STRAIGHT"
        if alpha_values is None:
            data = np.ones((width * height, 4), dtype=np.float32)
        else:
            data = np.ones((width * height, 4), dtype=np.float32)
            data[:, 3] = alpha_values
        self._pixels = data.flatten()

        class PixelsProxy:
            def __init__(self, parent_data: np.ndarray):
                self.data = parent_data

            def foreach_get(self, buf: np.ndarray):
                buf[:] = self.data[:]

        self.pixels = PixelsProxy(self._pixels)


class DummyNodeTree:
    def __init__(self, nodes: list[Any]):
        self.nodes = nodes


class DummyMaterial:
    def __init__(
        self,
        name: str = "Material",
        use_nodes: bool = True,
        node_tree: Any = None,
        blend_method: str = "OPAQUE",
        surface_render_method: str = "OPAQUE",
        diffuse_color: tuple[float, float, float, float] = (1.0, 1.0, 1.0, 1.0),
    ):
        self.name = name
        self.use_nodes = use_nodes
        self.node_tree = node_tree
        self.blend_method = blend_method
        self.surface_render_method = surface_render_method
        self.diffuse_color = diffuse_color


def test_transparency_evaluator_blend_modes():
    mat_blend = DummyMaterial(blend_method="BLEND")
    assert RobustTransparencyEvaluator.is_material_transparent(mat_blend) is True

    mat_clip = DummyMaterial(blend_method="CLIP")
    assert RobustTransparencyEvaluator.is_material_transparent(mat_clip) is True

    mat_dithered = DummyMaterial(surface_render_method="DITHERED")
    assert RobustTransparencyEvaluator.is_material_transparent(mat_dithered) is True

    mat_opaque = DummyMaterial(blend_method="OPAQUE")
    assert RobustTransparencyEvaluator.is_material_transparent(mat_opaque) is False


def test_transparency_evaluator_glass_and_transparent_bsdf():
    node_glass = DummyNode("BSDF_GLASS")
    mat_glass = DummyMaterial(node_tree=DummyNodeTree([node_glass]))
    assert RobustTransparencyEvaluator.is_material_transparent(mat_glass) is True

    node_trans = DummyNode("BSDF_TRANSPARENT")
    mat_trans = DummyMaterial(node_tree=DummyNodeTree([node_trans]))
    assert RobustTransparencyEvaluator.is_material_transparent(mat_trans) is True


def test_transparency_evaluator_principled_transmission():
    node_p = DummyNode("BSDF_PRINCIPLED", inputs={"Transmission Weight": DummySocket(default_value=0.5)})
    mat_p = DummyMaterial(node_tree=DummyNodeTree([node_p]))
    assert RobustTransparencyEvaluator.is_material_transparent(mat_p) is True

    node_p_opaque = DummyNode("BSDF_PRINCIPLED", inputs={"Transmission Weight": DummySocket(default_value=0.0)})
    mat_p_opaque = DummyMaterial(node_tree=DummyNodeTree([node_p_opaque]))
    assert RobustTransparencyEvaluator.is_material_transparent(mat_p_opaque) is False


def test_transparency_evaluator_alpha_cutout_vs_opaque_32bit():
    alpha_mask = np.ones(256, dtype=np.float32)
    alpha_mask[10:30] = 0.0
    img_cutout = DummyImage(16, 16, 4, alpha_values=alpha_mask)

    assert RobustTransparencyEvaluator.fast_sample_image_alpha(img_cutout) is True

    img_opaque_32 = DummyImage(16, 16, 4, alpha_values=None)
    assert RobustTransparencyEvaluator.fast_sample_image_alpha(img_opaque_32) is False

    tex_node = DummyNode("TEX_IMAGE", image=img_cutout)

    class DummyLink:
        def __init__(self, from_node: Any):
            self.from_node = from_node

    alpha_sock = DummySocket(is_linked=True, links=[DummyLink(tex_node)])
    node_p_tex = DummyNode("BSDF_PRINCIPLED", inputs={"Alpha": alpha_sock})
    mat_cutout = DummyMaterial(node_tree=DummyNodeTree([node_p_tex]))

    assert RobustTransparencyEvaluator.is_material_transparent(mat_cutout) is True


def test_fibonacci_sphere_distribution():
    center = Vector((0.0, 0.0, 0.0))
    radius = 5.0
    pts = HardenedOcclusionCuller._generate_fibonacci_sphere(center, radius, 32)
    assert len(pts) == 32
    for p in pts:
        assert math.isclose((p - center).length, radius, rel_tol=1e-3)


def test_stratified_hemisphere_dirs():
    norm = Vector((0.0, 0.0, 1.0))
    dirs = HardenedOcclusionCuller._stratified_hemisphere_dirs(norm, 16)
    assert len(dirs) == 16
    for d in dirs:
        assert math.isclose(d.length, 1.0, rel_tol=1e-3)
        assert d.dot(norm) >= -1e-4


def test_occlusion_culler_null_mesh_safety():
    res = HardenedOcclusionCuller.cull_interior_faces(None, None)
    assert res == {"culled_faces": 0, "culled_islands": 0}
