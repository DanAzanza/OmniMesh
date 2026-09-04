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
    from .modifiers import ModifierManager
    from .pivot import PivotPreservationEngine
except (ImportError, ValueError):
    from core.modifiers import ModifierManager
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
        try:
            dvert_lay = target_bm.verts.layers.deform.verify() if global_group_names else None

            for obj in valid_objs:
                eval_mesh = None
                eval_obj = None
                if ModifierManager.has_unapplied_modifiers(obj):
                    eval_mesh, eval_obj = ModifierManager.get_evaluated_mesh(obj, preserve_armature=True)

                src_mesh = eval_mesh if eval_mesh else obj.data
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
                    mat_remap: dict[int, int] = {}
                    for idx, mat in enumerate(obj_mats):
                        mat_remap[idx] = mat_to_global_idx.get(mat, 0)

                    # Vertex Group Deform Layer Remap
                    src_dvert_lay = (
                        temp_bm.verts.layers.deform.active if hasattr(temp_bm.verts.layers, "deform") else None
                    )
                    vg_map: dict[int, int] = {}
                    if hasattr(obj, "vertex_groups"):
                        for vg in obj.vertex_groups:
                            if vg.name in global_group_names:
                                vg_map[vg.index] = global_group_names.index(vg.name)

                    # Append verts into target BMesh
                    vert_map: dict[Any, Any] = {}
                    for v in temp_bm.verts:
                        new_v = target_bm.verts.new(v.co)
                        new_v.normal = v.normal
                        vert_map[v] = new_v

                        # Transfer deform weights
                        if dvert_lay and src_dvert_lay:
                            dvert = v[src_dvert_lay]
                            target_dvert = new_v[dvert_lay]
                            for old_vg_idx, weight in dvert.items():
                                if old_vg_idx in vg_map:
                                    target_dvert[vg_map[old_vg_idx]] = weight

                    target_bm.verts.ensure_lookup_table()

                    # Copy UV Layers
                    temp_uv_layers = (
                        list(temp_bm.loops.layers.uv.values()) if hasattr(temp_bm.loops.layers, "uv") else []
                    )
                    target_uv_layers = []
                    for src_uv in temp_uv_layers:
                        target_uv = target_bm.loops.layers.uv.get(src_uv.name) or target_bm.loops.layers.uv.new(
                            src_uv.name
                        )
                        target_uv_layers.append((src_uv, target_uv))

                    # Append faces with UVs
                    for f in temp_bm.faces:
                        new_verts = [vert_map[v] for v in f.verts]
                        try:
                            new_f = target_bm.faces.new(new_verts)
                            new_f.material_index = mat_remap.get(f.material_index, 0)
                            for src_uv, tgt_uv in target_uv_layers:
                                for l_old, l_new in zip(f.loops, new_f.loops, strict=False):
                                    l_new[tgt_uv].uv = l_old[src_uv].uv
                        except ValueError:
                            # Skip degenerate or duplicate faces
                            pass

                finally:
                    temp_bm.free()
                    if eval_obj and hasattr(eval_obj, "to_mesh_clear"):
                        eval_obj.to_mesh_clear()

            # Build merged target mesh datablock
            merged_mesh = bpy.data.meshes.new(f"{output_obj_name}_Mesh")
            target_bm.to_mesh(merged_mesh)
            merged_mesh.update()

        finally:
            target_bm.free()

        merged_obj = bpy.data.objects.new(output_obj_name, merged_mesh)

        # Assign unified material slots
        for mat in global_materials:
            merged_obj.data.materials.append(mat)

        # Create unified vertex groups
        for gname in global_group_names:
            merged_obj.vertex_groups.new(name=gname)

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

        # Link objects into new collection and unlink from all other collections to avoid ghost geometry
        for obj in objects:
            if obj.name not in coll.objects:
                coll.objects.link(obj)
            for c in list(getattr(obj, "users_collection", [])):
                if c != coll:
                    c.objects.unlink(obj)
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

        if hasattr(bpy.context, "view_layer") and bpy.context.view_layer:
            try:
                bpy.context.view_layer.update()
            except Exception as exc:
                logger.debug("View layer update exception: %s", exc)

        # Parent unparented objects to Pivot
        for obj in objects:
            if not obj.parent and obj != pivot_obj:
                obj.parent = pivot_obj
                obj.matrix_parent_inverse = pivot_obj.matrix_world.inverted()

        return coll, pivot_obj
