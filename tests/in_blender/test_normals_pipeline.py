"""
In-Blender Integration Tests for Custom Split Normal Management & Transfer.
Blender 4.2+ and 5.2 LTS Compatible.
"""

from __future__ import annotations

from typing import Any
import unittest

try:
    import bmesh
    import bpy
    from core.normals import NormalManager
    from tests.in_blender.fixtures import in_blender_sandbox
except ImportError:
    bmesh = None  # type: ignore
    bpy = None
    NormalManager = None  # type: ignore
    in_blender_sandbox = None  # type: ignore


def create_test_cylinder(name: str, radius: float = 1.0, depth: float = 2.0, segments: int = 16) -> Any:
    """Creates a procedural cylinder object in the active scene collection."""
    bm = bmesh.new()
    bmesh.ops.create_cone(
        bm,
        cap_ends=True,
        cap_tris=False,
        segments=segments,
        radius1=radius,
        radius2=radius,
        depth=depth,
    )
    mesh = bpy.data.meshes.new(f"{name}_Mesh")
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj


class TestNormalsPipeline(unittest.TestCase):
    """Verify Blender 4.2+/5.2 edge attributes, custom normal transfer, and KDTree fallbacks."""

    def setUp(self) -> None:
        if not bpy:
            self.skipTest("Blender bpy runtime not available.")

    def test_ensure_sharp_edge_attribute(self) -> None:
        """Verify sharp_edge boolean edge attribute is created on mesh datablock."""
        with in_blender_sandbox():
            obj = create_test_cylinder("SM_NormalsAttrTest")
            mesh = obj.data

            # If attribute exists from default creation, remove it first to test recreation
            if "sharp_edge" in mesh.attributes:
                mesh.attributes.remove(mesh.attributes["sharp_edge"])

            attr = NormalManager.ensure_sharp_edge_attribute(mesh)
            self.assertIsNotNone(attr, "ensure_sharp_edge_attribute must return the attribute.")
            self.assertIn("sharp_edge", mesh.attributes)
            self.assertEqual(mesh.attributes["sharp_edge"].domain, "EDGE")
            self.assertEqual(mesh.attributes["sharp_edge"].data_type, "BOOLEAN")

    def test_reproject_custom_split_normals(self) -> None:
        """Verify reproject_custom_split_normals transfers split normals from LOD0 to LOD1."""
        with in_blender_sandbox() as scene:
            lod0_obj = create_test_cylinder("SM_NormalsSource", segments=32)
            lod1_obj = create_test_cylinder("SM_NormalsTarget", segments=12)

            scene.view_layers[0].objects.active = lod1_obj
            lod1_obj.select_set(True)

            # Mark top and bottom cap edges as sharp
            bm0 = bmesh.new()
            bm0.from_mesh(lod0_obj.data)
            for edge in bm0.edges:
                if len(edge.link_faces) == 2:
                    dot = edge.link_faces[0].normal.dot(edge.link_faces[1].normal)
                    if abs(dot) < 0.1:  # ~90 degree junction
                        edge.smooth = False
            bm0.to_mesh(lod0_obj.data)
            bm0.free()

            # Execute normal transfer
            success = NormalManager.reproject_custom_split_normals(lod1_obj, lod0_obj)
            self.assertTrue(success, "Normal reprojection must report success.")

            # Target mesh must have sharp_edge attribute and valid normal data
            self.assertIn("sharp_edge", lod1_obj.data.attributes)
            self.assertEqual(len(lod1_obj.modifiers), 0, "DATA_TRANSFER modifier must be applied and purged.")

    def test_kdtree_normal_transfer_fallback(self) -> None:
        """Verify spatial KDTree fallback transfers surface normals when modifiers are bypassed."""
        with in_blender_sandbox():
            lod0_obj = create_test_cylinder("SM_KDTreeSource", segments=24)
            lod1_obj = create_test_cylinder("SM_KDTreeTarget", segments=8)

            success = NormalManager._kdtree_normal_transfer_fallback(lod1_obj, lod0_obj)
            self.assertTrue(success, "KDTree normal fallback must return True.")
            self.assertIn("sharp_edge", lod1_obj.data.attributes)
