"""
Asset and scene collection scanner for OmniMesh.
Identifies root asset collections, inspects current scene state, and computes LOD sync states.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Protocol, cast

from .compat import count_mesh_triangles

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    import bpy
    from bpy.types import BlendData, Collection, Context, Mesh, Object
else:
    try:
        import bpy
        from bpy.types import Collection, Context, Mesh, Object
    except ImportError:
        bpy = None
        Collection = object
        Context = object
        Mesh = object
        Object = object
    BlendData = object


class AssetScannerPropsProtocol(Protocol):
    active_asset: str


def _strip_collection_suffixes(name: str) -> str:
    """Safely strips known OmniMesh technical and LOD suffixes from a collection or object stem."""
    stem = name
    for n in range(11):
        if stem.endswith(f"_LOD{n}"):
            stem = stem[: -len(f"_LOD{n}")]
            break
    for sfx in (
        "_Colliders",
        "_Impostor",
        "_Chunks",
        "_HLOD",
        "_Spatial",
        "_Lights",
        "_Cameras",
        "_Config",
        "_Helpers",
    ):
        if stem.endswith(sfx):
            stem = stem[: -len(sfx)]
            break
    return stem


def get_available_asset_names(
    context: bpy.types.Context | None,
    *,
    blend_data: BlendData,
) -> list[str]:
    """Discovers available asset base names by scanning scene collections."""
    if not bpy or not context:
        return []

    scene = context.scene
    if not scene or not scene.collection:
        return []

    if blend_data:
        bdata_cols = blend_data.collections
    elif scene.collection:
        stack = [scene.collection]
        bdata_cols = []
        while stack:
            curr = stack.pop()
            for child in curr.children:
                bdata_cols.append(child)
                stack.append(child)
    else:
        bdata_cols = None

    asset_names = []
    for coll in bdata_cols or []:
        if coll == scene.collection or coll.name.startswith("."):
            continue

        name = coll.name
        try:
            role_val = coll.get("_omnimesh_role", "")
        except AttributeError:
            role_val = ""
        if (
            any(f"_LOD{n}" in name for n in range(1, 11))
            or any(
                name.endswith(sfx)
                for sfx in (
                    "_Colliders",
                    "_Impostor",
                    "_Chunks",
                    "_HLOD",
                    "_Spatial",
                    "_Lights",
                    "_Cameras",
                    "_Config",
                    "_Helpers",
                )
            )
            or role_val in ("CONFIG", "HELPERS")
        ):
            continue

        has_mesh = False
        try:
            coll_objs = coll.all_objects
        except AttributeError:
            coll_objs = coll.objects
        for obj in coll_objs or ():
            if obj.type == "MESH":
                has_mesh = True
                break

        if has_mesh:
            base_name = name[:-5] if name.endswith("_LOD0") else name
            if base_name not in asset_names:
                asset_names.append(base_name)

    return asset_names


def resolve_effective_asset_name(
    context: bpy.types.Context | None, props: object = None, *, blend_data: BlendData
) -> str:
    """
    Resolves the active asset name to display or operate on:
    1. If props.active_asset is set and != 'AUTO' and != 'NONE': returns props.active_asset.
    2. Otherwise, inspects active layer collection in the Outliner.
    3. If active layer collection is derivative or root, resolves base name.
    4. Otherwise, inspects active object or first available asset.
    5. Falls back to 'Asset' or empty string if no collections exist.
    """
    if props:
        selected_asset = getattr(props, "active_asset", "AUTO")
        if selected_asset and selected_asset not in ("AUTO", "NONE"):
            return str(selected_asset)

    available = get_available_asset_names(context, blend_data=blend_data)

    if context and context.view_layer and context.view_layer.active_layer_collection:
        active_lc = context.view_layer.active_layer_collection
        if active_lc and active_lc.collection:
            coll_name = active_lc.collection.name
            scene_coll = context.scene.collection if context.scene else None
            if coll_name and coll_name != scene_coll:
                stem = _strip_collection_suffixes(coll_name)
                if stem and stem != "Collection" and (not available or stem in available):
                    return stem

    active_obj = getattr(context, "active_object", None) if context else None
    if active_obj:
        raw_name = active_obj.name
        stem = _strip_collection_suffixes(raw_name)
        if stem and (not available or stem in available):
            return stem
        if active_obj.users_collection:
            for uc in active_obj.users_collection:
                u_stem = _strip_collection_suffixes(uc.name)
                if u_stem and (not available or u_stem in available):
                    return u_stem

    if available:
        return available[0]

    return "Asset"


def get_asset_collection(
    context: bpy.types.Context | None,
    asset_name: str,
    *,
    blend_data: BlendData,
) -> bpy.types.Collection | None:
    """Finds the root collection for asset_name (either '{BaseName}' or '{BaseName}_LOD0')."""
    bdata_cols = blend_data.collections if blend_data else None
    if not bdata_cols:
        scene = context.scene if context else None
        if scene and scene.collection and asset_name:
            stack = [scene.collection]
            while stack:
                curr = stack.pop()
                if curr.name in (asset_name, f"{asset_name}_LOD0"):
                    return curr
                for child in curr.children or ():
                    stack.append(child)
        return None

    for candidate in (asset_name, f"{asset_name}_LOD0"):
        c = bdata_cols.get(candidate)
        if c:
            return c
    return None


def get_asset_base_meshes(
    context: bpy.types.Context | None,
    asset_name: str,
    *,
    blend_data: BlendData,
) -> list[bpy.types.Object]:
    """Retrieves all non-collider, non-impostor MESH objects from the root asset collection."""
    coll = get_asset_collection(context, asset_name, blend_data=blend_data)
    if not coll:
        selected = (context.selected_objects or []) if context else []
        meshes = [o for o in selected if o.type == "MESH"]
        act_obj = getattr(context, "active_object", None) if context else None
        if not meshes and act_obj:
            if act_obj.type == "MESH":
                meshes = [act_obj]
        return meshes

    meshes = []
    try:
        all_objs = coll.all_objects
    except AttributeError:
        all_objs = coll.objects
    for obj in all_objs or ():
        if obj.type != "MESH":
            continue
        name = obj.name
        try:
            is_col = bool(obj.get("_is_collider", False))
            is_imp = bool(obj.get("_is_impostor", False))
        except AttributeError:
            is_col = False
            is_imp = False
        if is_col or is_imp or name.startswith("UCX_") or "_Collider_" in name:
            continue
        if any(f"_LOD{n}" in name for n in range(1, 11)):
            continue
        meshes.append(obj)

    return meshes


def scan_asset_state(
    context: bpy.types.Context | None,
    asset_name: str,
    *,
    blend_data: BlendData,
) -> dict[str, Any]:
    """
    Scans scene collections for existing LODs and geometry for asset_name.
    Returns:
    {
        'base_meshes': list[Any],
        'base_tris': int,
        'material_slots_count': int,
        'existing_tiers': dict[int, dict[str, Any]], # maps 0..k to {collection_name, meshes, actual_tris, is_impostor}
    }
    """
    bdata = blend_data
    base_meshes = get_asset_base_meshes(context, asset_name, blend_data=bdata)
    base_tris = sum(count_mesh_triangles(cast("bpy.types.Mesh | None", m.data)) for m in base_meshes)
    mat_slots = sum(len(m.material_slots) for m in base_meshes)

    existing_tiers: dict[int, dict[str, Any]] = {}

    l0_coll = get_asset_collection(context, asset_name, blend_data=bdata)
    if l0_coll:
        existing_tiers[0] = {
            "collection_name": l0_coll.name,
            "meshes": base_meshes,
            "actual_tris": base_tris,
            "is_impostor": False,
        }

    bdata_cols = bdata.collections if bdata else None

    if bdata_cols and asset_name:
        for i in range(1, 11):
            c_name = f"{asset_name}_LOD{i}"
            c = bdata_cols.get(c_name)
            if c:
                meshes = [o for o in list(c.objects) if o.type == "MESH"]
                t_count = sum(count_mesh_triangles(cast("bpy.types.Mesh | None", m.data)) for m in meshes)
                existing_tiers[i] = {
                    "collection_name": c_name,
                    "meshes": meshes,
                    "actual_tris": t_count,
                    "is_impostor": False,
                }

        imp_name = f"{asset_name}_LOD_Impostor"
        c_imp = bdata_cols.get(imp_name)
        if c_imp:
            meshes = [o for o in list(c_imp.objects) if o.type == "MESH"]
            t_count = sum(count_mesh_triangles(cast("bpy.types.Mesh | None", m.data)) for m in meshes)
            existing_tiers[-1] = {
                "collection_name": imp_name,
                "meshes": meshes,
                "actual_tris": t_count,
                "is_impostor": True,
            }

    return {
        "base_meshes": base_meshes,
        "base_tris": base_tris,
        "material_slots_count": mat_slots,
        "existing_tiers": existing_tiers,
    }
