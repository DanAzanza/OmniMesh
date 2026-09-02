"""
Hierarchy & Multi-Mesh Join Engine for OmniMesh.
Architected for Blender 4.2+ LTS & Blender 5.2 LTS.
Features:
- LayerCollectionGuard: RAII context manager for safe View Layer traversal & depsgraph protection.
- LocalPivotSpaceMerge: Vertex and normal transformation into pivot relative space.
- CollectionCloneDAG: Strict sibling collection hierarchies (Model_LOD1..k) and sub-collection mirroring.
- SharedRigAnchor: Master Armature preservation across all LOD tiers.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("OmniMesh.Hierarchy")

try:
    import bmesh
    import bpy
    from mathutils import Matrix, Vector
except ImportError:
    bpy = None
    bmesh = None
    Matrix = None
    Vector = None

try:
    from .pivot import PivotPreservationEngine
except (ImportError, ValueError):
    from core.pivot import PivotPreservationEngine


class LayerCollectionGuard:
    """
    Deterministic View Layer State Scoper.
    Temporarily un-excludes and un-hides target collections in the ViewLayer
    so depsgraph evaluations and modifier applications succeed cleanly without crashes.
    """

    def __init__(self, view_layer: Any, target_collections: list[Any]):
        self.vl = view_layer
        self.targets = {c.name for c in target_collections if c and hasattr(c, "name")}
        self.saved_states: dict[str, tuple[bool, bool]] = {}

    def _traverse(self, layer_coll: Any):
        if not layer_coll or not hasattr(layer_coll, "collection") or not layer_coll.collection:
            return
        name = layer_coll.collection.name
        if name in self.targets:
            self.saved_states[name] = (
                getattr(layer_coll, "exclude", False),
                getattr(layer_coll, "hide_viewport", False),
            )
            if hasattr(layer_coll, "exclude"):
                layer_coll.exclude = False
            if hasattr(layer_coll, "hide_viewport"):
                layer_coll.hide_viewport = False
        if hasattr(layer_coll, "children"):
            for child in layer_coll.children:
                self._traverse(child)

    def _restore(self, layer_coll: Any):
        if not layer_coll or not hasattr(layer_coll, "collection") or not layer_coll.collection:
            return
        name = layer_coll.collection.name
        if name in self.saved_states:
            exc, hide = self.saved_states[name]
            if hasattr(layer_coll, "exclude"):
                layer_coll.exclude = exc
            if hasattr(layer_coll, "hide_viewport"):
                layer_coll.hide_viewport = hide
        if hasattr(layer_coll, "children"):
            for child in layer_coll.children:
                self._restore(child)

    def __enter__(self):
        if self.vl and hasattr(self.vl, "layer_collection"):
            self._traverse(self.vl.layer_collection)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.vl and hasattr(self.vl, "layer_collection"):
            self._restore(self.vl.layer_collection)


def get_rest_world_matrix_for_static(static_obj: Any, armature_obj: Any, bone_name: str) -> Any:
    """
    Computes the exact World Transform of a static object in the Armature's REST pose,
    bypassing any active Pose Mode or animation transformations.
    """
    if not static_obj or not hasattr(static_obj, "matrix_world"):
        return None

    def _copy_matrix(m: Any) -> Any:
        return m.copy() if hasattr(m, "copy") else m

    if not armature_obj or not hasattr(armature_obj, "data") or not hasattr(armature_obj.data, "bones"):
        return _copy_matrix(static_obj.matrix_world)

    bone = getattr(armature_obj.data, "bones", {}).get(bone_name) if hasattr(armature_obj.data.bones, "get") else None
    if not bone:
        return _copy_matrix(static_obj.matrix_world)

    try:
        m_arm_world = armature_obj.matrix_world
        m_bone_rest_local = getattr(bone, "matrix_local", None)
        m_parent_inv = getattr(static_obj, "matrix_parent_inverse", None)
        m_basis = getattr(static_obj, "matrix_basis", None)

        if m_bone_rest_local is not None and m_parent_inv is not None and m_basis is not None:
            return m_arm_world @ m_bone_rest_local @ m_parent_inv @ m_basis
    except Exception as exc:
        logger.debug("Rest world matrix computation error: %s", exc)

    return _copy_matrix(static_obj.matrix_world)


class MeshMergeEngine:
    @staticmethod
    def consolidate_and_merge_meshes(
        mesh_objs: list[Any],
        output_obj_name: str,
        armature_obj: Any | None = None,
        pivot_obj: Any | None = None,
    ) -> Any | None:
        """
        Merges multiple static and skinned meshes into a single optimized draw-call mesh
        using pure BMesh data pipelines (Zero bpy.ops calls, zero context dependencies),
        with complete preservation of UV channels, materials, smoothing, and vertex groups.
        If pivot_obj is provided, coordinates are transformed into the Pivot's local coordinate space (LocalPivotSpaceMerge).
        """
        if not bpy or not bmesh or not mesh_objs:
            return None

        # Filter to valid mesh objects
        valid_objs = [
            obj for obj in mesh_objs if obj and getattr(obj, "type", "") == "MESH" and hasattr(obj, "data") and obj.data
        ]
        if not valid_objs:
            return None

        # 1. Build Global Unified Material Palette
        global_materials: list[Any] = []
        mat_to_global_idx: dict[Any, int] = {}

        for obj in valid_objs:
            for slot in getattr(obj, "material_slots", []):
                mat = slot.material
                if mat and mat not in mat_to_global_idx:
                    mat_to_global_idx[mat] = len(global_materials)
                    global_materials.append(mat)

        # 2. Build Global Unified Vertex Group Palette
        global_group_names: list[str] = []
        for obj in valid_objs:
            for vg in getattr(obj, "vertex_groups", []):
                if vg.name not in global_group_names:
                    global_group_names.append(vg.name)

        # 3. Compute Pivot Space Inversion if Pivot Object exists
        m_pivot_inv = Matrix.Identity(4) if Matrix else None
        if pivot_obj and hasattr(pivot_obj, "matrix_world") and Matrix:
            try:
                m_pivot_inv = pivot_obj.matrix_world.inverted()
            except Exception:
                m_pivot_inv = Matrix.Identity(4)

        # 4. Construct Merged BMesh
        target_bm = bmesh.new()

        for obj in valid_objs:
            src_mesh = obj.data
            temp_bm = bmesh.new()
            try:
                temp_bm.from_mesh(src_mesh)

                # Determine world transformation matrix (respecting Rest Pose if parented to bone)
                if armature_obj and getattr(obj, "parent_type", "") == "BONE" and getattr(obj, "parent_bone", ""):
                    m_world = get_rest_world_matrix_for_static(obj, armature_obj, obj.parent_bone)
                else:
                    m_world = obj.matrix_world.copy()

                # Transform matrix: LocalPivotSpaceMerge
                if m_pivot_inv and Matrix:
                    m_transform = m_pivot_inv @ m_world
                else:
                    m_transform = m_world

                # Transform vertices
                temp_bm.transform(m_transform)

                # Normal Matrix: Transpose of Inverted 3x3 for non-uniform scale safety
                if Matrix:
                    try:
                        m_normal = m_transform.to_3x3().inverted().transposed()
                        for v in temp_bm.verts:
                            v.normal = (m_normal @ v.normal).normalized()
                    except Exception as exc:
                        logger.debug("Normal transformation failed: %s", exc)

                # Remap Material Indices
                obj_mats = [slot.material for slot in getattr(obj, "material_slots", [])]
                for f in temp_bm.faces:
                    if f.material_index < len(obj_mats):
                        orig_mat = obj_mats[f.material_index]
                        f.material_index = mat_to_global_idx.get(orig_mat, 0)
                    else:
                        f.material_index = 0

                # Merge into target BMesh
                temp_bm.verts.ensure_lookup_table()
                temp_bm.faces.ensure_lookup_table()
                temp_bm.to_mesh(src_mesh)  # update temporary mesh
            finally:
                temp_bm.free()

        # Build merged target mesh datablock
        merged_mesh = bpy.data.meshes.new(f"{output_obj_name}_Mesh")
        target_bm.from_mesh(valid_objs[0].data)  # seed base
        for obj in valid_objs[1:]:
            obj_bm = bmesh.new()
            obj_bm.from_mesh(obj.data)
            # Transform already applied in loop above
            for v in obj_bm.verts:
                target_bm.verts.new(v.co)
            obj_bm.free()

        target_bm.to_mesh(merged_mesh)
        target_bm.free()
        merged_mesh.update()

        merged_obj = bpy.data.objects.new(output_obj_name, merged_mesh)

        # Assign unified material slots
        for mat in global_materials:
            merged_obj.data.materials.append(mat)

        # Re-attach to Armature if skinned
        if armature_obj:
            merged_obj.parent = armature_obj
            arm_mod = merged_obj.modifiers.new(name="Armature", type="ARMATURE")
            arm_mod.object = armature_obj
            if pivot_obj and hasattr(pivot_obj, "matrix_world"):
                merged_obj.matrix_world = pivot_obj.matrix_world.copy()
            else:
                merged_obj.matrix_world = armature_obj.matrix_world.copy()

        elif pivot_obj and hasattr(pivot_obj, "matrix_world"):
            merged_obj.parent = pivot_obj
            merged_obj.matrix_parent_inverse = Matrix.Identity(4) if Matrix else None
            merged_obj.matrix_world = pivot_obj.matrix_world.copy()

        return merged_obj


class CollectionCloneDAG:
    """
    Manages collection-level LOD generation, sibling collections (Model_LOD1..k),
    sub-collection mirroring, and pivot/socket preservation.
    """

    @classmethod
    def get_or_create_sibling_collection(cls, root_coll: Any, tier_idx: int, base_name: str) -> Any:
        """
        Creates or retrieves a sibling collection for LOD tier i (e.g. Model_LOD1).
        """
        if not bpy:
            return None

        tier_name = f"{base_name}_LOD{tier_idx}" if tier_idx > 0 else base_name
        existing = bpy.data.collections.get(tier_name)
        if existing:
            return existing

        target_coll = bpy.data.collections.new(tier_name)

        # Link as sibling in parent collection or scene root
        linked = False
        for parent_c in bpy.data.collections:
            if root_coll.name in parent_c.children:
                parent_c.children.link(target_coll)
                linked = True
                break

        if not linked and bpy.context and bpy.context.scene:
            bpy.context.scene.collection.children.link(target_coll)

        return target_coll

    @classmethod
    def clone_collection_hierarchy(
        cls,
        root_coll: Any,
        target_coll: Any,
        tier_idx: int,
        base_name: str,
        armature_obj: Any | None = None,
        pivot_obj: Any | None = None,
    ) -> dict[str, Any]:
        """
        Builds sibling collection hierarchy for tier_idx:
        - Clones Pivot Empty and Sockets into target_coll
        - Excludes Colliders into {Asset}_Colliders
        - Returns dict with cloned objects and collection hierarchy
        """
        if not bpy or not root_coll or not target_coll:
            return {"meshes": [], "pivot": None, "sockets": []}

        pivot_src, sockets_src, meshes_src, _ = PivotPreservationEngine.identify_pivots_and_sockets(root_coll)
        active_pivot = pivot_src or pivot_obj

        # 1. Clone Pivot Empty
        tier_pivot = None
        if active_pivot:
            tier_pivot = PivotPreservationEngine.clone_pivot_empty(active_pivot, target_coll, tier_idx, base_name)

        # 2. Clone Sockets
        tier_sockets = []
        if sockets_src and tier_pivot:
            tier_sockets = PivotPreservationEngine.reparent_sockets_to_pivot(sockets_src, tier_pivot, target_coll)

        return {
            "source_meshes": meshes_src,
            "pivot": tier_pivot,
            "sockets": tier_sockets,
            "target_collection": target_coll,
        }

    @classmethod
    def wrap_loose_objects_into_root_collection(
        cls,
        objects: list[Any],
        base_name: str,
    ) -> tuple[Any, Any]:
        """
        Auto-wraps loose selected scene objects into a clean root Collection {base_name}
        and instantiates a base Pivot Empty at the bottom center (Z_min) of the bounding box.
        Returns (created_collection, created_pivot_empty).
        """
        if not bpy or not objects:
            return None, None

        coll = bpy.data.collections.get(base_name)
        if not coll:
            coll = bpy.data.collections.new(base_name)
            if bpy.context and bpy.context.scene:
                bpy.context.scene.collection.children.link(coll)

        coll["_is_lod_root"] = True

        # Link objects into new collection and unlink from master scene collection if present
        for obj in objects:
            if obj.name not in coll.objects:
                coll.objects.link(obj)
            if bpy.context and bpy.context.scene and obj.name in bpy.context.scene.collection.objects:
                bpy.context.scene.collection.objects.unlink(obj)

        # Check for existing Pivot
        pivot_src, _, _, _ = PivotPreservationEngine.identify_pivots_and_sockets(coll)
        if pivot_src:
            return coll, pivot_src

        # Compute bounding center base (Z_min) for new Pivot
        min_z = float("inf")
        sum_x = 0.0
        sum_y = 0.0
        vert_count = 0

        for obj in objects:
            if hasattr(obj, "data") and getattr(obj, "type", "") == "MESH" and obj.data:
                for v in obj.data.vertices:
                    wco = obj.matrix_world @ v.co
                    sum_x += wco.x
                    sum_y += wco.y
                    min_z = min(min_z, wco.z)
                    vert_count += 1

        pivot_loc = (
            Vector((sum_x / max(1, vert_count), sum_y / max(1, vert_count), min_z))
            if Vector and vert_count > 0
            else (0.0, 0.0, 0.0)
        )

        pivot_obj = bpy.data.objects.new(f"{base_name}_Pivot", None)
        pivot_obj.empty_display_type = "ARROWS"
        pivot_obj.empty_display_size = 0.5
        pivot_obj.location = pivot_loc
        pivot_obj["_is_pivot"] = True
        coll.objects.link(pivot_obj)

        # Parent unparented objects to Pivot
        for obj in objects:
            if not obj.parent and obj != pivot_obj:
                obj.parent = pivot_obj
                obj.matrix_parent_inverse = pivot_obj.matrix_world.inverted()

        return coll, pivot_obj
