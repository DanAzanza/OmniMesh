"""
In-Blender Integration Tests for Material AST Hashing, Compaction & Deduplication.
Blender 4.2+ and 5.2 LTS Compatible.
"""

from __future__ import annotations

import unittest

try:
    import bmesh
    import bpy
    from core.materials import DeepMaterialHasher, HeadlessSlotCompactor, MaterialOptimizer
    from tests.in_blender.fixtures import in_blender_sandbox
except ImportError:
    bpy = None
    bmesh = None  # type: ignore
    DeepMaterialHasher = None  # type: ignore
    HeadlessSlotCompactor = None  # type: ignore
    MaterialOptimizer = None  # type: ignore
    in_blender_sandbox = None  # type: ignore


class TestMaterialPipeline(unittest.TestCase):
    """Verify cryptographic shader graph hashing, slot compaction, and scene material deduplication."""

    def setUp(self) -> None:
        if not bpy:
            self.skipTest("Blender bpy runtime not available.")

    def test_deep_material_hasher_invariance_and_distinction(self) -> None:
        """Verify AST hasher is invariant to cosmetic UI node coordinates but sensitive to shader inputs."""
        with in_blender_sandbox():
            # Material A
            mat_a = bpy.data.materials.new("M_Shader_A")
            mat_a.use_nodes = True
            bsdf_a = next(n for n in mat_a.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
            bsdf_a.location = (100, 200)
            if "Base Color" in bsdf_a.inputs:
                bsdf_a.inputs["Base Color"].default_value = (0.5, 0.5, 0.5, 1.0)
            if "Roughness" in bsdf_a.inputs:
                bsdf_a.inputs["Roughness"].default_value = 0.3

            # Material B (Identical shading, but placed far away in UI graph)
            mat_b = bpy.data.materials.new("M_Shader_B")
            mat_b.use_nodes = True
            bsdf_b = next(n for n in mat_b.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
            bsdf_b.location = (-9999, -5555)  # Wildly different UI position
            if "Base Color" in bsdf_b.inputs:
                bsdf_b.inputs["Base Color"].default_value = (0.5, 0.5, 0.5, 1.0)
            if "Roughness" in bsdf_b.inputs:
                bsdf_b.inputs["Roughness"].default_value = 0.3

            hash_a = DeepMaterialHasher.hash_material(mat_a)
            hash_b = DeepMaterialHasher.hash_material(mat_b)
            self.assertEqual(hash_a, hash_b, "Identical shader graphs must produce identical hashes.")

            # Material C (Different roughness value)
            mat_c = bpy.data.materials.new("M_Shader_C")
            mat_c.use_nodes = True
            bsdf_c = next(n for n in mat_c.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
            if "Base Color" in bsdf_c.inputs:
                bsdf_c.inputs["Base Color"].default_value = (0.5, 0.5, 0.5, 1.0)
            if "Roughness" in bsdf_c.inputs:
                bsdf_c.inputs["Roughness"].default_value = 0.85  # Changed

            hash_c = DeepMaterialHasher.hash_material(mat_c)
            self.assertNotEqual(hash_a, hash_c, "Differing shader input values must yield distinct hashes.")

    def test_merge_duplicate_materials_scene(self) -> None:
        """Verify merge_duplicate_materials_scene collapses duplicate datablocks and remaps slots."""
        with in_blender_sandbox() as scene:
            mat_orig = bpy.data.materials.new("M_Wood")
            mat_orig.use_nodes = True
            bsdf_orig = next(n for n in mat_orig.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
            bsdf_orig.inputs["Base Color"].default_value = (0.7, 0.35, 0.15, 1.0)

            mat_dup = bpy.data.materials.new("M_Wood.001")
            mat_dup.use_nodes = True
            bsdf_dup = next(n for n in mat_dup.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
            bsdf_dup.inputs["Base Color"].default_value = (0.7, 0.35, 0.15, 1.0)

            # Create test mesh object using the duplicate material
            mesh = bpy.data.meshes.new("TestCube_Mesh")
            bm = bmesh.new()
            bmesh.ops.create_cube(bm, size=1.0)
            bm.to_mesh(mesh)
            bm.free()

            obj = bpy.data.objects.new("SM_WoodBox", mesh)
            scene.collection.objects.link(obj)
            obj.data.materials.append(mat_dup)
            self.assertEqual(obj.material_slots[0].material, mat_dup)

            merged = MaterialOptimizer.merge_duplicate_materials_scene()
            self.assertGreaterEqual(merged, 1, "At least 1 duplicate material must be merged.")

            # Slot must now point to the canonical master material
            self.assertEqual(obj.material_slots[0].material, mat_orig)
            # Duplicate material must be pruned
            self.assertIsNone(bpy.data.materials.get("M_Wood.001"))

    def test_merge_duplicate_materials_out_of_order_clusters(self) -> None:
        """Verify out-of-order duplicate materials (e.g. .002, .001 before root) rebind to root and never unbind."""
        with in_blender_sandbox() as scene:
            # Create in reverse order: .002, .001, then root
            m_dup2 = bpy.data.materials.new("M_Metal.002")
            m_dup2.use_nodes = True
            bsdf2 = next(n for n in m_dup2.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
            bsdf2.inputs["Base Color"].default_value = (0.2, 0.2, 0.8, 1.0)

            m_dup1 = bpy.data.materials.new("M_Metal.001")
            m_dup1.use_nodes = True
            bsdf1 = next(n for n in m_dup1.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
            bsdf1.inputs["Base Color"].default_value = (0.2, 0.2, 0.8, 1.0)

            m_root = bpy.data.materials.new("M_Metal")
            m_root.use_nodes = True
            bsdf_root = next(n for n in m_root.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
            bsdf_root.inputs["Base Color"].default_value = (0.2, 0.2, 0.8, 1.0)

            # Object 1 assigned to .002, Object 2 assigned to .001
            mesh1 = bpy.data.meshes.new("Cube1")
            obj1 = bpy.data.objects.new("Obj1", mesh1)
            scene.collection.objects.link(obj1)
            obj1.data.materials.append(m_dup2)

            mesh2 = bpy.data.meshes.new("Cube2")
            obj2 = bpy.data.objects.new("Obj2", mesh2)
            scene.collection.objects.link(obj2)
            obj2.data.materials.append(m_dup1)

            merged = MaterialOptimizer.merge_duplicate_materials_scene()
            self.assertEqual(merged, 2, "Both .002 and .001 duplicates must be merged.")

            # Both objects must now point strictly to canonical m_root, NOT None
            self.assertEqual(obj1.material_slots[0].material, m_root)
            self.assertEqual(obj2.material_slots[0].material, m_root)

            # Duplicates must be purged
            self.assertIsNone(bpy.data.materials.get("M_Metal.002"))
            self.assertIsNone(bpy.data.materials.get("M_Metal.001"))
            self.assertIsNotNone(bpy.data.materials.get("M_Metal"))

    def test_compact_slots_deduplicates_repeated_materials(self) -> None:
        """Verify HeadlessSlotCompactor removes redundant identical material slots on an object."""
        with in_blender_sandbox() as scene:
            mat = bpy.data.materials.new("M_SingleMat")
            mesh = bpy.data.meshes.new("MultiSlotCube_Mesh")
            bm = bmesh.new()
            bmesh.ops.create_cube(bm, size=1.0)
            bm.to_mesh(mesh)
            bm.free()

            obj = bpy.data.objects.new("SM_MultiSlotBox", mesh)
            scene.collection.objects.link(obj)

            # Append same material multiple times
            obj.data.materials.append(mat)
            obj.data.materials.append(mat)
            obj.data.materials.append(mat)
            self.assertEqual(len(obj.material_slots), 3)

            res = HeadlessSlotCompactor.compact_slots(obj, purge_empty=True, deduplicate_identical=True)
            self.assertEqual(res.get("slots_removed", 0), 2)
            self.assertEqual(len(obj.material_slots), 1, "Redundant material slots must be compacted to 1.")
