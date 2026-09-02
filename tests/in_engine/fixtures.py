"""
Synthetic Mockup Mesh & Armature Fixtures and Scene Sandbox for In-Engine Testing.
"""

from __future__ import annotations

import contextlib
import logging
from typing import Generator

logger = logging.getLogger(__name__)

try:
    import bmesh
    import bpy
    import mathutils
except ImportError:
    bpy = None
    bmesh = None
    mathutils = None

try:
    from core.simulator import LODSimulatorEngine
except (ImportError, ValueError):
    from ...core.simulator import LODSimulatorEngine


@contextlib.contextmanager
def in_engine_sandbox() -> Generator[bpy.types.Scene, None, None]:
    """Isolate in-engine test execution within a transient Blender scene.

    Protects developer workspace/artwork in live MCP sessions from deletion.
    """
    if not bpy:
        yield None
        return

    orig_scene = (
        bpy.context.window.scene if hasattr(bpy.context, "window") and bpy.context.window else bpy.context.scene
    )
    test_scene = bpy.data.scenes.new("OmniMesh_Test_Sandbox")

    if hasattr(bpy.context, "window") and bpy.context.window:
        bpy.context.window.scene = test_scene

    # Reset add-on scene props
    if hasattr(test_scene, "lod_tool"):
        test_scene.lod_tool.lods.clear()
        test_scene.lod_tool.is_configured = False

    try:
        yield test_scene
    finally:
        # Restore active workspace scene first
        if hasattr(bpy.context, "window") and bpy.context.window:
            bpy.context.window.scene = orig_scene

        # Clear global simulator engine class state (prevent dead RNA Object pointers)
        try:
            LODSimulatorEngine._tracked_assets.clear()
        except Exception as exc:
            logger.debug("Failed clearing simulator state: %s", exc)

        # Purge test scene datablocks
        test_objects = list(test_scene.objects)
        for obj in test_objects:
            mesh_data = obj.data if getattr(obj, "type", "") == "MESH" else None
            bpy.data.objects.remove(obj, do_unlink=True)
            if mesh_data and getattr(mesh_data, "users", 0) == 0:
                bpy.data.meshes.remove(mesh_data, do_unlink=True)

        for coll in list(test_scene.collection.children):
            for sub_obj in list(coll.objects):
                bpy.data.objects.remove(sub_obj, do_unlink=True)
            bpy.data.collections.remove(coll)

        bpy.data.scenes.remove(test_scene, do_unlink=True)

        if hasattr(bpy.data, "orphans_purge"):
            try:
                bpy.data.orphans_purge(do_local_ids=True, do_linked_ids=True, do_recursive=True)
            except Exception as exc:
                logger.debug("Orphans purge exception: %s", exc)


def create_dirty_mesh(name: str = "SM_DirtyMesh") -> bpy.types.Object:
    """Generate a synthetic test mesh with 4 specific defects:
    1. Unapplied scale (0.01, 0.01, 0.01)
    2. 2 loose vertices in space
    3. 1 degenerate zero-area triangle
    4. 1 non-manifold bowtie pinch point
    """
    mesh = bpy.data.meshes.new(f"{name}_Mesh")
    bm = bmesh.new()

    # 1. Base Cube
    bmesh.ops.create_cube(bm, size=2.0)

    # 2. Loose Vertices (2 floating vertices)
    bm.verts.new(mathutils.Vector((5.0, 5.0, 5.0)))
    bm.verts.new(mathutils.Vector((6.0, 6.0, 6.0)))

    # 3. Degenerate Zero-Area Triangle (3 coincident vertices)
    v_deg1 = bm.verts.new(mathutils.Vector((0.0, 0.0, 10.0)))
    v_deg2 = bm.verts.new(mathutils.Vector((0.0, 0.0, 10.0)))
    v_deg3 = bm.verts.new(mathutils.Vector((0.0, 0.0, 10.0)))
    bm.faces.new((v_deg1, v_deg2, v_deg3))

    # 4. Bowtie Non-Manifold Pinch Point (2 triangles sharing only 1 vertex)
    v_center = bm.verts.new(mathutils.Vector((10.0, 0.0, 0.0)))
    v_l1 = bm.verts.new(mathutils.Vector((9.0, 1.0, 0.0)))
    v_l2 = bm.verts.new(mathutils.Vector((9.0, -1.0, 0.0)))
    v_r1 = bm.verts.new(mathutils.Vector((11.0, 1.0, 0.0)))
    v_r2 = bm.verts.new(mathutils.Vector((11.0, -1.0, 0.0)))
    bm.faces.new((v_center, v_l1, v_l2))
    bm.faces.new((v_center, v_r1, v_r2))

    bm.to_mesh(mesh)
    bm.free()
    mesh.update()

    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)

    # Apply unapplied scale
    obj.scale = (0.01, 0.01, 0.01)

    # Assign a dummy material
    mat = bpy.data.materials.new(name=f"M_{name}")
    obj.data.materials.append(mat)

    return obj


def create_skinned_mesh(name: str = "SM_SkinnedMesh") -> tuple[bpy.types.Object, bpy.types.Object]:
    """Generate a synthetic skinned cylinder rigged to a 6-bone Armature.
    Each vertex is assigned 6 bone weights to test max influence clamping and pruning.
    """
    # 1. Create Armature
    arm_data = bpy.data.armatures.new(f"{name}_Armature")
    arm_obj = bpy.data.objects.new(f"{name}_Rig", arm_data)
    bpy.context.scene.collection.objects.link(arm_obj)

    bpy.context.view_layer.objects.active = arm_obj
    bpy.ops.object.mode_set(mode="EDIT")
    edit_bones = arm_data.edit_bones
    bone_names = []
    parent_bone = None

    for b_idx in range(6):
        b_name = f"Bone_{b_idx}"
        bone_names.append(b_name)
        b = edit_bones.new(b_name)
        b.head = (0.0, 0.0, b_idx * 0.5)
        b.tail = (0.0, 0.0, (b_idx + 1) * 0.5)
        if parent_bone:
            b.parent = parent_bone
        parent_bone = b

    bpy.ops.object.mode_set(mode="OBJECT")

    # 2. Create Cylinder Mesh
    mesh = bpy.data.meshes.new(f"{name}_Mesh")
    bm = bmesh.new()
    bmesh.ops.create_cone(
        bm,
        cap_ends=True,
        cap_tris=False,
        segments=8,
        radius1=0.5,
        radius2=0.5,
        depth=3.0,
    )
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()

    mesh_obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(mesh_obj)

    # 3. Add Armature Modifier and Parent
    mesh_obj.parent = arm_obj
    mod = mesh_obj.modifiers.new(name="Armature", type="ARMATURE")
    mod.object = arm_obj

    # 4. Assign 6 Bone Weights per Vertex
    for b_name in bone_names:
        vg = mesh_obj.vertex_groups.new(name=b_name)
        weight_val = 1.0 / 6.0
        vert_indices = list(range(len(mesh_obj.data.vertices)))
        vg.add(vert_indices, weight_val, "REPLACE")

    # 5. Add Shape Keys (Basis + Smile)
    mesh_obj.shape_key_add(name="Basis", from_mix=False)
    sk = mesh_obj.shape_key_add(name="Key_Smile", from_mix=False)
    # Deform key vertex slightly
    if len(sk.data) > 0:
        sk.data[0].co.z += 0.2

    mat = bpy.data.materials.new(name=f"M_{name}")
    mesh_obj.data.materials.append(mat)

    return mesh_obj, arm_obj


def create_hierarchy_fixture(base_name: str = "SM_CompoundProp") -> list[bpy.types.Object]:
    """Generate 2 submesh objects in the active scene collection to test multi-mesh LOD wrapping."""
    body_mesh = bpy.data.meshes.new(f"{base_name}_Body_Mesh")
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.5)
    bm.to_mesh(body_mesh)
    bm.free()
    body_obj = bpy.data.objects.new(f"{base_name}_Body", body_mesh)
    bpy.context.scene.collection.objects.link(body_obj)

    lid_mesh = bpy.data.meshes.new(f"{base_name}_Lid_Mesh")
    bm2 = bmesh.new()
    bmesh.ops.create_uvsphere(bm2, u_segments=12, v_segments=8, radius=0.8)
    bm2.to_mesh(lid_mesh)
    bm2.free()
    lid_obj = bpy.data.objects.new(f"{base_name}_Lid", lid_mesh)
    lid_obj.location = (0.0, 0.0, 1.2)
    bpy.context.scene.collection.objects.link(lid_obj)

    mat = bpy.data.materials.new(name=f"M_{base_name}")
    body_obj.data.materials.append(mat)
    lid_obj.data.materials.append(mat)

    return [body_obj, lid_obj]
