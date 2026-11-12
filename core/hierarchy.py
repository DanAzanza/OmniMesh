"""
Hierarchy & Multi-Mesh Join Engine for OmniMesh.
Architected for Blender 5.0+ & Blender 5.2 LTS.
Features:
- LayerCollectionGuard: RAII context manager for safe View Layer traversal & depsgraph protection.
- LocalPivotSpaceMerge: Vertex and normal transformation into pivot relative space.
- CollectionCloneDAG: Strict sibling collection hierarchies (Model_LOD1..k) and sub-collection mirroring.
- SharedRigAnchor: Master Armature preservation across all LOD tiers.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Callable, cast

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    import bmesh
    import bpy
    from bpy.types import BlendData, Collection, Context, Object, Scene
    from mathutils import Matrix, Vector
else:
    try:
        import bmesh
        import bpy
        from bpy.types import BlendData, Collection, Context, Object, Scene
        from mathutils import Matrix, Vector
    except ImportError:
        bpy = None
        bmesh = None
        BlendData = object
        Collection = object
        Context = object
        Object = object
        Scene = object
        Matrix = None
        Vector = None

from .exceptions import CollectionHierarchyError
from .mesh_merge import MeshMergeEngine, get_rest_world_matrix_for_static
from .pivot import PivotPreservationEngine

__all__ = [
    "LayerCollectionGuard",
    "CollectionCloneDAG",
    "get_or_create_engine_import_collection",
    "safe_remove_collection_objects",
    "MeshMergeEngine",
    "get_rest_world_matrix_for_static",
]


class LayerCollectionGuard:
    """
    Deterministic View Layer State Scoper.
    Temporarily un-excludes and un-hides target collections in the ViewLayer
    so depsgraph evaluations and modifier applications succeed cleanly without crashes.
    """

    def __init__(self, view_layer: bpy.types.ViewLayer | None, target_collections: list[bpy.types.Collection]):
        self.vl = view_layer
        self.targets = {c.name for c in target_collections if c and c.name}
        self.saved_states: dict[str, tuple[bool, bool]] = {}

    def _traverse(self, layer_coll: bpy.types.LayerCollection | None) -> bool:
        if not layer_coll or not layer_coll.collection:
            return False
        name = layer_coll.collection.name
        is_target = name in self.targets

        has_target_child = False
        if layer_coll.children:
            for child in layer_coll.children:
                if self._traverse(child):
                    has_target_child = True

        if is_target or has_target_child:
            if name not in self.saved_states:
                self.saved_states[name] = (layer_coll.exclude, layer_coll.hide_viewport)
            layer_coll.exclude = False
            if is_target:
                layer_coll.hide_viewport = False
            return True

        return False

    def _restore(self, layer_coll: bpy.types.LayerCollection | None):
        if not layer_coll or not layer_coll.collection:
            return
        name = layer_coll.collection.name
        if name in self.saved_states:
            exc, hide = self.saved_states[name]
            layer_coll.exclude = exc
            layer_coll.hide_viewport = hide
        if layer_coll.children:
            for child in layer_coll.children:
                self._restore(child)

    def __enter__(self):
        if self.vl and self.vl.layer_collection:
            self._traverse(self.vl.layer_collection)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.vl and self.vl.layer_collection:
            self._restore(self.vl.layer_collection)


class CollectionCloneDAG:
    """
    Manages collection-level LOD generation, sibling collections (Model_LOD1..k),
    sub-collection mirroring, and pivot/socket preservation.
    """

    @classmethod
    def get_or_create_sibling_collection(
        cls,
        root_coll: bpy.types.Collection | None,
        tier_idx: int,
        base_name: str,
        scene: bpy.types.Scene | None = None,
        *,
        blend_data: BlendData,
    ) -> bpy.types.Collection | None:
        """
        Creates or retrieves a sibling collection for LOD tier i (e.g. Model_LOD1).
        """
        if not blend_data:
            return None

        tier_name = f"{base_name}_LOD{tier_idx}" if tier_idx > 0 else base_name
        existing = blend_data.collections.get(tier_name)
        if existing:
            return existing

        target_coll = blend_data.collections.new(tier_name)

        # Check if base_name collection exists as a container for LOD tiers
        base_container = blend_data.collections.get(base_name)
        if base_container and base_container != target_coll and tier_idx > 0:
            if target_coll.name not in base_container.children:
                base_container.children.link(target_coll)
            return target_coll

        # Link as sibling in parent collection or scene root
        linked = False
        if root_coll:
            for parent_c in blend_data.collections:
                if root_coll.name in parent_c.children:
                    parent_c.children.link(target_coll)
                    linked = True
                    break

        if not linked:
            sc = scene or (blend_data.scenes[0] if len(blend_data.scenes) > 0 else None)
            if sc and sc.collection and sc.collection.children is not None:
                sc.collection.children.link(target_coll)

        return target_coll

    @classmethod
    def clone_collection_hierarchy(
        cls,
        root_coll: bpy.types.Collection | None,
        target_coll: bpy.types.Collection | None,
        tier_idx: int,
        base_name: str,
        armature_obj: bpy.types.Object | None = None,
        pivot_obj: bpy.types.Object | None = None,
        context: bpy.types.Context | None = None,
        *,
        blend_data: BlendData,
    ) -> dict[str, Any]:
        """
        Builds sibling collection hierarchy for tier_idx:
        - Clones Pivot Empty and Sockets into target_coll
        - Excludes Colliders into {Asset}_Colliders
        - Returns dict with cloned objects and collection hierarchy
        """
        if not bpy or not root_coll or not target_coll:
            return {"meshes": [], "pivot": None, "sockets": []}

        bdata = blend_data
        pivot_src, sockets_src, meshes_src, _ = PivotPreservationEngine.identify_pivots_and_sockets(root_coll)
        active_pivot = pivot_src or pivot_obj

        # 1. Clone Pivot Empty
        tier_pivot = None
        if active_pivot:
            tier_pivot = PivotPreservationEngine.clone_pivot_empty(
                active_pivot, target_coll, tier_idx, base_name, blend_data=bdata
            )

        # 2. Clone Sockets
        tier_sockets = []
        if sockets_src and tier_pivot:
            tier_sockets = PivotPreservationEngine.reparent_sockets_to_pivot(
                sockets_src, tier_pivot, target_coll, context=context
            )

        return {
            "source_meshes": meshes_src,
            "pivot": tier_pivot,
            "sockets": tier_sockets,
            "target_collection": target_coll,
        }

    @classmethod
    def wrap_loose_objects_into_root_collection(
        cls,
        objects: list[bpy.types.Object],
        base_name: str,
        scene: bpy.types.Scene | None = None,
        context: bpy.types.Context | None = None,
        *,
        blend_data: BlendData,
    ) -> tuple[bpy.types.Collection | None, bpy.types.Object | None]:
        """
        Auto-wraps loose selected scene objects into a clean root Collection {base_name}
        and instantiates a base Pivot Empty at the bottom center (Z_min) of the bounding box.
        Returns (created_collection, created_pivot_empty).
        """
        effective_blend_data = blend_data
        if not objects or not effective_blend_data:
            return None, None

        sc = scene or (effective_blend_data.scenes[0] if len(effective_blend_data.scenes) > 0 else None)

        coll = effective_blend_data.collections.get(base_name)
        if not coll:
            coll = effective_blend_data.collections.new(base_name)
            if sc and sc.collection and sc.collection.children is not None:
                sc.collection.children.link(coll)

        coll["_is_lod_root"] = True

        # Link objects into new collection and unlink from all other collections to avoid ghost geometry
        for obj in objects:
            if obj.name not in coll.objects:
                coll.objects.link(obj)
            for c in list(obj.users_collection or []):
                if c != coll:
                    c.objects.unlink(obj)
            if sc and sc.collection and obj.name in sc.collection.objects:
                sc.collection.objects.unlink(obj)

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
            if obj.type == "MESH" and obj.data:
                obj_mesh = cast("bpy.types.Mesh", obj.data)
                for v in obj_mesh.vertices:
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

        pivot_obj = effective_blend_data.objects.new(f"{base_name}_Pivot", None)
        pivot_obj.empty_display_type = "ARROWS"
        pivot_obj.empty_display_size = 0.5
        pivot_obj.location = pivot_loc
        pivot_obj["_is_pivot"] = True
        coll.objects.link(pivot_obj)

        vl = context.view_layer if context else None
        if not vl and sc and sc.view_layers and len(sc.view_layers) > 0:
            vl = sc.view_layers[0]
        if vl:
            try:
                vl.update()
            except (RuntimeError, AttributeError) as exc:
                logger.error("View layer update failed: %s", exc)
                raise CollectionHierarchyError(f"View layer update failed: {exc}") from exc

        # Parent unparented objects to Pivot
        for obj in objects:
            if not obj.parent and obj != pivot_obj:
                obj.parent = pivot_obj
                obj.matrix_parent_inverse = pivot_obj.matrix_world.inverted()

        return coll, pivot_obj


def get_or_create_engine_import_collection(
    context_or_scene: bpy.types.Context | bpy.types.Scene | None,
    asset_name: str,
    role: str,
    use_lod0_suffix: bool = True,
    bpy_module: object = None,
    *,
    blend_data: BlendData,
) -> bpy.types.Collection | None:
    """Finds or creates a collection adhering to OmniMesh's neutral engine package hierarchy:
    {AssetName} -> {_Config (Spatial, Lights, Cameras), _LOD0..N, _Colliders}.
    """
    if not context_or_scene or not blend_data:
        return None
    bpy_data = blend_data

    clean_asset = asset_name.strip() or "Asset"
    try:
        scene = cast("bpy.types.Context", context_or_scene).scene
    except AttributeError:
        scene = cast("bpy.types.Scene", context_or_scene)

    # 1. Root Model Collection
    root_col = bpy_data.collections.get(clean_asset)
    if not root_col:
        root_col = bpy_data.collections.new(clean_asset)
    if root_col.name not in scene.collection.children:
        try:
            scene.collection.children.link(root_col)
        except RuntimeError as exc:
            logger.error("Root collection link failed for '%s': %s", clean_asset, exc)
            raise CollectionHierarchyError(f"Root collection link failed for '{clean_asset}': {exc}") from exc

    if clean_asset.endswith("_Interior"):
        root_col["_omnimesh_role"] = "INTERIOR"
        root_col["_omnimesh_parent"] = clean_asset[:-9]
    elif role.upper() == "VARIANT" or (
        "_" in clean_asset
        and not any(clean_asset.endswith(f"_LOD{n}") for n in range(11))
        and any(c.name != clean_asset and clean_asset.startswith(f"{c.name}_") for c in scene.collection.children)
    ):
        root_col["_omnimesh_role"] = "VARIANT"
        matching_parent = next(
            (
                c.name
                for c in scene.collection.children
                if c.name != clean_asset and clean_asset.startswith(f"{c.name}_")
            ),
            "",
        )
        if matching_parent:
            root_col["_omnimesh_parent"] = matching_parent
            root_col["_omnimesh_variant_id"] = clean_asset[len(matching_parent) + 1 :]
    else:
        root_col["_omnimesh_role"] = "MODEL_ROOT"

    if role.upper() in ("ROOT", "PACKAGE_ROOT", "MODEL_ROOT"):
        return root_col

    # 2. Determine Sub-Collection Name
    role_upper = role.upper()
    role_suffixes = {
        "CONFIG": "_Config",
        "HELPERS": "_Helpers",
        "COLLIDERS": "_Colliders",
        "SPATIAL": "_Spatial",
        "LIGHTS": "_Lights",
        "CAMERAS": "_Cameras",
        "ATTACHMENTS": "_Attachments",
        "INTERACTIONS": "_Interactions",
        "TRIGGERS": "_Interactions",
        "PREVIEW": "_Submodel_Previews",
        "PREVIEWS": "_Submodel_Previews",
    }
    if role_upper == "LOD0":
        sub_name = f"{clean_asset}_LOD0" if use_lod0_suffix else f"{clean_asset}_Mesh"
    elif role_upper.startswith("LOD"):
        sub_name = f"{clean_asset}_{role_upper}"
    elif role_upper in role_suffixes:
        sub_name = f"{clean_asset}{role_suffixes[role_upper]}"
    else:
        sub_name = f"{clean_asset}_{role}"

    # Configuration collections (Spatial, Lights, Cameras, Attachments, Interactions) reside under {clean_asset}_Config
    parent_col = root_col
    if role_upper in ("SPATIAL", "LIGHTS", "CAMERAS", "ATTACHMENTS", "INTERACTIONS", "TRIGGERS"):
        config_name = f"{clean_asset}_Config"
        config_col = bpy_data.collections.get(config_name)
        if not config_col:
            config_col = bpy_data.collections.new(config_name)
            config_col["_omnimesh_role"] = "CONFIG"
            root_col.children.link(config_col)
        elif config_col.name not in root_col.children:
            try:
                root_col.children.link(config_col)
            except RuntimeError as exc:
                logger.error("Config collection link failed for '%s': %s", config_name, exc)
                raise CollectionHierarchyError(f"Config collection link failed for '{config_name}': {exc}") from exc
        parent_col = config_col

        # Legacy migration: check if sub_col was previously linked under _LOD0
        lod0_name = f"{clean_asset}_LOD0" if use_lod0_suffix else f"{clean_asset}_Mesh"
        lod0_col = bpy_data.collections.get(lod0_name)
        if lod0_col and lod0_col.children is not None:
            has_old = False
            old_sub = None
            try:
                if sub_name in lod0_col.children:
                    has_old = True
                    old_sub = lod0_col.children.get(sub_name) or bpy_data.collections.get(sub_name)
            except (AttributeError, TypeError, ReferenceError):
                has_old = False
            if has_old and old_sub:
                if old_sub.name not in config_col.children:
                    try:
                        config_col.children.link(old_sub)
                    except (RuntimeError, ReferenceError, AttributeError) as e:
                        logger.error("Could not link legacy subcollection to config: %s", e)
                        raise CollectionHierarchyError(f"Could not link legacy subcollection to config: {e}") from e
                try:
                    lod0_col.children.unlink(old_sub)
                except (RuntimeError, ReferenceError, AttributeError, ValueError) as e:
                    logger.error("Could not unlink legacy subcollection from LOD0: %s", e)
                    raise CollectionHierarchyError(f"Could not unlink legacy subcollection from LOD0: {e}") from e
    sub_col = bpy_data.collections.get(sub_name)
    if not sub_col:
        sub_col = bpy_data.collections.new(sub_name)
        parent_col.children.link(sub_col)
    else:
        if sub_col.name not in parent_col.children:
            try:
                parent_col.children.link(sub_col)
            except RuntimeError as exc:
                logger.error("Subcollection link to parent failed for '%s': %s", sub_name, exc)
                raise CollectionHierarchyError(f"Subcollection link to parent failed for '{sub_name}': {exc}") from exc
        # If misplaced directly under root_col (and not supposed to be), unlink
        if parent_col != root_col and sub_col.name in root_col.children:
            try:
                root_col.children.unlink(sub_col)
            except RuntimeError as exc:
                logger.error("Subcollection unlink from root failed for '%s': %s", sub_name, exc)
                raise CollectionHierarchyError(
                    f"Subcollection unlink from root failed for '{sub_name}': {exc}"
                ) from exc

    sub_col["_omnimesh_role"] = role_upper
    return sub_col


def safe_remove_collection_objects(
    col: bpy.types.Collection | None,
    bpy_module: object = None,
    predicate: Callable[[bpy.types.Object], bool] | None = None,
    *,
    blend_data: BlendData,
) -> int:
    """
    Safely and cleanly removes objects belonging to a collection and their unshared datablocks.
    Guards against RNA pointer invalidation and collection mutation during iteration.
    """
    if not col or not blend_data:
        return 0

    effective_data = blend_data

    removed = 0
    deselect_failed_count = 0
    last_deselect_err: str | None = None
    # Create shallow snapshot of objects to prevent mutation during iteration
    objs_to_remove = [o for o in list(col.objects) if o is not None and (predicate is None or predicate(o))]

    for obj in objs_to_remove:
        try:
            # Unparent children safely
            for child in list(obj.children or []):
                if child:
                    child.parent = None
            if obj.parent:
                obj.parent = None

            # Deselect if selected
            try:
                obj.select_set(False)
            except (RuntimeError, ReferenceError) as deselect_err:
                deselect_failed_count += 1
                last_deselect_err = f"{obj.name}: {deselect_err}"

            # Capture unshared data block
            data_to_remove: bpy.types.ID | None = None
            data = obj.data
            if data:
                users = data.users
                if isinstance(users, (int, float)) and users <= 1:
                    data_to_remove = data

            # Unlink and remove object from blend_data.objects
            effective_data.objects.remove(obj, do_unlink=True)
            removed += 1

            # Remove orphaned datablock
            if data_to_remove is not None:
                try:
                    if effective_data.meshes is not None and data_to_remove in effective_data.meshes.values():
                        effective_data.meshes.remove(cast("bpy.types.Mesh", data_to_remove))
                    elif effective_data.lights is not None and data_to_remove in effective_data.lights.values():
                        effective_data.lights.remove(cast("bpy.types.Light", data_to_remove))
                    elif effective_data.cameras is not None and data_to_remove in effective_data.cameras.values():
                        effective_data.cameras.remove(cast("bpy.types.Camera", data_to_remove))
                except (RuntimeError, ReferenceError, AttributeError) as exc:
                    logger.error("Failed removing orphaned datablock %s: %s", data_to_remove, exc)
                    raise CollectionHierarchyError(f"Failed removing orphaned datablock: {exc}") from exc
        except (ReferenceError, AttributeError, RuntimeError) as exc:
            logger.error("Safe object removal exception: %s", exc)
            raise CollectionHierarchyError(
                f"Safe object removal failed for '{getattr(obj, 'name', '<unnamed>')}': {exc}"
            ) from exc

    if deselect_failed_count > 0:
        logger.warning(
            "safe_remove_collection_objects completed with %d deselection warning(s); last: %s",
            deselect_failed_count,
            last_deselect_err,
        )

    return removed
