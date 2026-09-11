"""
Shared UI utilities and context resolvers for OmniMesh operators and panels.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

try:
    import bpy
except ImportError:
    bpy = None


def is_object_valid(obj: Any) -> bool:
    """Safely check if a Blender object exists and is not freed/invalidated."""
    if obj is None:
        return False
    try:
        _ = getattr(obj, "name", None)
        return True
    except (ReferenceError, AttributeError):
        return False


def get_selected_mesh_objects(context: Any) -> list[Any]:
    """Retrieve all valid, non-collider, non-impostor MESH objects from selection or active object."""
    if not context:
        return []
    objs = context.selected_objects if hasattr(context, "selected_objects") else []
    if not objs and getattr(context, "active_object", None):
        objs = [context.active_object]

    raw_meshes = []
    for obj in objs:
        if not is_object_valid(obj):
            continue
        if getattr(obj, "type", "") == "MESH":
            name = getattr(obj, "name", "")
            is_col = bool(getattr(obj, "get", lambda *_: False)("_is_collider", False) is True)
            if not is_col and not name.startswith("UCX_"):
                raw_meshes.append(obj)

    base_meshes = [obj for obj in raw_meshes if not any(f"_LOD{n}" in getattr(obj, "name", "") for n in range(1, 11))]
    return base_meshes if base_meshes else raw_meshes


def get_lod0_mesh_objects(context: Any, base_name: str = "") -> list[Any]:
    """
    Retrieve all true LOD0 source MESH objects for the active asset or selection.

    1. If objects reside in an asset collection ({BaseName}, {BaseName}_LOD0),
       all non-collider, non-impostor MESH objects in that collection are returned,
       even if only a single object or sub-component was selected.
    2. If the user currently has a derivative LOD active (_LOD1.._LOD10), automatically
       resolves back to the primary LOD0 meshes.
    3. Falls back safely to selected base meshes.
    """
    if not context:
        return []

    active_obj = getattr(context, "active_object", None)
    selected_objs = getattr(context, "selected_objects", []) or ([active_obj] if active_obj else [])

    if not base_name:
        props = getattr(getattr(context, "scene", None), "lod_tool", None)
        base_name = getattr(props, "export_base_name", "") or ""

    if not base_name and active_obj:
        raw_name = getattr(active_obj, "name", "")
        base_name = raw_name.split("_LOD")[0].split("_Collider")[0].split("_Impostor")[0]

    if not base_name and selected_objs:
        raw_name = getattr(selected_objs[0], "name", "")
        base_name = raw_name.split("_LOD")[0].split("_Collider")[0].split("_Impostor")[0]

    if not base_name:
        try:
            base_name = resolve_effective_asset_name(context)
        except Exception as exc:
            logger.debug("Failed resolving effective asset name in get_lod0_mesh_objects: %s", exc)

    # 1. Search for asset root collection
    candidate_coll = None
    if bpy and hasattr(bpy, "data") and hasattr(bpy.data, "collections") and base_name:
        for c_name in (f"{base_name}_LOD0", base_name):
            c = bpy.data.collections.get(c_name)
            if c and getattr(context, "scene", None) and c != getattr(context.scene, "collection", None):
                candidate_coll = c
                break

    if not candidate_coll and active_obj and hasattr(active_obj, "users_collection"):
        for c in active_obj.users_collection:
            if getattr(context, "scene", None) and c == getattr(context.scene, "collection", None):
                continue
            c_name = getattr(c, "name", "")
            if "_Colliders" in c_name or "_Impostor" in c_name:
                continue
            root_c_name = c_name
            for n in range(0, 11):
                root_c_name = root_c_name.split(f"_LOD{n}")[0]
            root_c = None
            if bpy and hasattr(bpy, "data") and hasattr(bpy.data, "collections"):
                root_c = bpy.data.collections.get(root_c_name) or bpy.data.collections.get(f"{root_c_name}_LOD0")
            if root_c:
                candidate_coll = root_c
                break
            if not any(f"_LOD{n}" in c_name for n in range(1, 11)):
                candidate_coll = c
                break

    if candidate_coll and hasattr(candidate_coll, "objects"):
        coll_meshes = []
        target_objs = candidate_coll.objects
        if hasattr(candidate_coll, "all_objects") and not hasattr(candidate_coll.all_objects, "_mock_return_value"):
            target_objs = candidate_coll.all_objects
        for obj in target_objs:
            if not is_object_valid(obj) or getattr(obj, "type", "") != "MESH":
                continue
            name = getattr(obj, "name", "")
            is_col = bool(getattr(obj, "get", lambda *_: False)("_is_collider", False) is True)
            is_imp = bool(getattr(obj, "get", lambda *_: False)("_is_impostor", False) is True)
            if is_col or is_imp or name.startswith("UCX_") or "_Collider_" in name:
                continue
            if any(f"_LOD{n}" in name for n in range(1, 11)):
                continue
            coll_meshes.append(obj)
        if coll_meshes:
            return coll_meshes

    # 2. Fallback: inspect selected meshes and resolve any _LOD1..10 back to LOD0
    selected_meshes = get_selected_mesh_objects(context)
    if not selected_meshes:
        return []

    lod0_resolved: list[Any] = []
    if bpy and hasattr(bpy, "data") and hasattr(bpy.data, "objects"):
        for obj in selected_meshes:
            name = getattr(obj, "name", "")
            if any(f"_LOD{n}" in name for n in range(1, 11)):
                stem = name.split("_LOD")[0]
                lod0_obj = bpy.data.objects.get(f"{stem}_LOD0") or bpy.data.objects.get(stem)
                if lod0_obj and getattr(lod0_obj, "type", "") == "MESH" and is_object_valid(lod0_obj):
                    lod0_resolved.append(lod0_obj)
                else:
                    lod0_resolved.append(obj)
            else:
                lod0_resolved.append(obj)
        return lod0_resolved

    return selected_meshes


def resolve_asset_base_name(context: Any, mesh_objs: list[Any] | None = None) -> str:
    """
    Resolve asset root name:
    1. Central state override: props.export_base_name
    2. Sibling/parent asset collection name (excluding Scene Collection, _LOD1..10, _Colliders, _Impostor)
    3. Active mesh object or first mesh object name
    Strips suffixes (_LOD*, _Collider*, _Impostor).
    """
    if not context:
        return "Asset"

    props = getattr(getattr(context, "scene", None), "lod_tool", None)
    base_override = getattr(props, "export_base_name", "") or ""
    if base_override:
        return base_override.split("_LOD")[0].split("_Collider")[0].split("_Impostor")[0]

    active_obj = getattr(context, "active_object", None) or (mesh_objs[0] if mesh_objs else None)
    if active_obj and hasattr(active_obj, "users_collection"):
        for c in active_obj.users_collection:
            if getattr(context, "scene", None) and c == context.scene.collection:
                continue
            c_name = getattr(c, "name", "")
            if "_Colliders" in c_name or "_Impostor" in c_name:
                continue
            stem = c_name
            for n in range(0, 11):
                stem = stem.split(f"_LOD{n}")[0]
            if stem:
                return stem

    if active_obj:
        raw_name = getattr(active_obj, "name", "")
        return raw_name.split("_LOD")[0].split("_Collider")[0].split("_Impostor")[0]

    return "Asset"


def get_associated_armature(mesh_objs: list[Any]) -> Any:
    """Find armature parent or modifier attached to any of the provided mesh objects."""
    for obj in mesh_objs:
        if not is_object_valid(obj):
            continue
        if (
            getattr(obj, "parent", None)
            and is_object_valid(obj.parent)
            and getattr(obj.parent, "type", "") == "ARMATURE"
        ):
            return obj.parent
        for mod in getattr(obj, "modifiers", []):
            if getattr(mod, "type", "") == "ARMATURE" and is_object_valid(getattr(mod, "object", None)):
                return mod.object
    return None


def resolve_lod_context(context: Any) -> tuple[Any, Any | None, bool]:
    """
    Context Resolver: returns (active_settings, master_object_or_coll, is_derivative_lod).
    """
    if not context:
        return None, None, False

    scene_props = getattr(getattr(context, "scene", None), "lod_tool", None)
    active_obj = getattr(context, "active_object", None)

    if not active_obj or getattr(active_obj, "type", "") != "MESH":
        return scene_props, None, False

    obj_props = getattr(active_obj, "lod_tool", None)
    if not obj_props:
        return scene_props, active_obj, False

    if bool(getattr(obj_props, "is_generated_lod", False) is True):
        master_val = getattr(obj_props, "lod_root_object", None)
        if master_val and hasattr(master_val, "name"):
            master_obj = master_val
        elif isinstance(master_val, str) and bpy and master_val:
            master_obj = bpy.data.objects.get(master_val)
        else:
            master_obj = None

        if master_obj and hasattr(master_obj, "lod_tool"):
            m_props = master_obj.lod_tool
            if len(getattr(m_props, "lods", [])) == 0 and scene_props and len(getattr(scene_props, "lods", [])) > 0:
                return scene_props, master_obj, True
            return m_props, master_obj, True
        if len(getattr(obj_props, "lods", [])) == 0 and scene_props and len(getattr(scene_props, "lods", [])) > 0:
            return scene_props, active_obj, True
        return obj_props, active_obj, True

    is_cfg = bool(getattr(obj_props, "is_configured", False) is True)
    if is_cfg and len(getattr(obj_props, "lods", [])) > 0:
        return obj_props, active_obj, False
    return scene_props, active_obj, False


def safe_report(operator: Any, msg_type: set[str], msg: str) -> None:
    """Safely report status message from an operator with headless fallback."""
    if hasattr(operator, "report"):
        try:
            operator.report(msg_type, msg)
        except Exception:
            logger.debug("[%s] %s", msg_type, msg)
    else:
        logger.debug("[%s] %s", msg_type, msg)


# =========================================================================
# Collection-First Asset Resolution & Hierarchy Scanners
# =========================================================================

_CACHED_ASSET_ITEMS: list[tuple[str, str, str]] = []


def get_available_asset_names(context: Any) -> list[str]:
    """
    Scans the scene collection hierarchy to discover candidate root asset collections.
    A collection is recognized as an Asset Collection if:
    1. It is not an internal/derivative collection (_LOD1..10, _Colliders, _Impostor, _Chunks, _HLOD).
    2. It is not the top-level 'Scene Collection'.
    3. It contains at least one mesh object directly or in child collections.
    Base name strips trailing '_LOD0'.
    """
    if not bpy or not hasattr(bpy, "data") or not hasattr(bpy.data, "collections"):
        return []

    asset_names: set[str] = set()
    for coll in bpy.data.collections:
        c_name = getattr(coll, "name", "")
        # Ignore derivative / auxiliary collections
        if any(f"_LOD{n}" in c_name for n in range(1, 11)):
            continue
        if (
            "_Colliders" in c_name
            or "_Impostor" in c_name
            or "_Chunks" in c_name
            or "_HLOD" in c_name
            or "_Spatial" in c_name
            or "_Lights" in c_name
            or "_Cameras" in c_name
        ):
            continue
        if getattr(context, "scene", None) and coll == context.scene.collection:
            continue
        if c_name == "Scene Collection":
            continue

        # Check if collection contains any MESH object
        has_mesh = any(
            getattr(obj, "type", "") == "MESH"
            for obj in getattr(coll, "all_objects", getattr(coll, "objects", []))
            if is_object_valid(obj)
            and not getattr(obj, "get", lambda *_: False)("_is_collider", False)
            and not getattr(obj, "get", lambda *_: False)("_is_impostor", False)
        )
        if has_mesh:
            base_name = c_name.split("_LOD0")[0]
            if base_name and base_name not in {"Collection"}:
                asset_names.add(base_name)

    # Fallback if only default 'Collection' exists and has meshes
    if not asset_names and bpy and hasattr(bpy, "data") and hasattr(bpy.data, "collections"):
        default_c = bpy.data.collections.get("Collection")
        if default_c:
            has_mesh = any(
                getattr(obj, "type", "") == "MESH" for obj in getattr(default_c, "objects", []) if is_object_valid(obj)
            )
            if has_mesh:
                first_mesh = next(
                    (
                        obj.name
                        for obj in default_c.objects
                        if getattr(obj, "type", "") == "MESH" and is_object_valid(obj)
                    ),
                    "Asset",
                )
                asset_names.add(first_mesh.split("_LOD")[0])

    return sorted(list(asset_names))


def resolve_effective_asset_name(context: Any, props: Any = None) -> str:
    """
    Resolves the active asset name deterministically:
    1. If props.active_asset is set and != "AUTO" and != "NONE", returns it.
    2. If "AUTO" (or not set), checks active Outliner collection (active_layer_collection).
    3. Fallback: checks active mesh object's collection or name.
    4. Fallback: first discovered asset from get_available_asset_names(context).
    5. Final fallback: 'Asset'.
    """
    if not context:
        return "Asset"

    if not props:
        props = getattr(getattr(context, "scene", None), "lod_tool", None)

    configured_asset = getattr(props, "active_asset", "") or getattr(props, "export_base_name", "")
    available = get_available_asset_names(context)

    if configured_asset and configured_asset not in {"AUTO", "NONE"} and configured_asset in available:
        return configured_asset

    # AUTO: check active Outliner collection
    vl = getattr(context, "view_layer", None)
    alc = getattr(vl, "active_layer_collection", None)
    if alc and getattr(alc, "collection", None):
        c_name = getattr(alc.collection, "name", "")
        if (
            getattr(context, "scene", None)
            and alc.collection != context.scene.collection
            and c_name != "Scene Collection"
        ):
            stem = c_name
            for n in range(0, 11):
                stem = stem.split(f"_LOD{n}")[0]
            stem = (
                stem.split("_Colliders")[0]
                .split("_Impostor")[0]
                .split("_Chunks")[0]
                .split("_HLOD")[0]
                .split("_Spatial")[0]
                .split("_Lights")[0]
                .split("_Cameras")[0]
            )
            if stem in available:
                return stem

    # Fallback to active mesh object collection or name
    active_obj = getattr(context, "active_object", None)
    if active_obj and getattr(active_obj, "type", "") == "MESH":
        stem = active_obj.name.split("_LOD")[0].split("_Collider")[0].split("_Impostor")[0]
        if stem in available:
            return stem
        if hasattr(active_obj, "users_collection"):
            for uc in active_obj.users_collection:
                u_stem = uc.name
                for n in range(0, 11):
                    u_stem = u_stem.split(f"_LOD{n}")[0]
                u_stem = (
                    u_stem.split("_Colliders")[0]
                    .split("_Impostor")[0]
                    .split("_Chunks")[0]
                    .split("_HLOD")[0]
                    .split("_Spatial")[0]
                    .split("_Lights")[0]
                    .split("_Cameras")[0]
                )
                if u_stem in available:
                    return u_stem

    # Fallback to first available asset
    if available:
        return available[0]

    return resolve_asset_base_name(context)


def get_asset_collection(context: Any, asset_name: str) -> Any | None:
    """Returns the root LOD0 collection for the given asset name."""
    if not bpy or not hasattr(bpy, "data") or not hasattr(bpy.data, "collections") or not asset_name:
        return None
    return bpy.data.collections.get(f"{asset_name}_LOD0") or bpy.data.collections.get(asset_name)


def get_asset_base_meshes(context: Any, asset_name: str) -> list[Any]:
    """Retrieves all non-collider, non-impostor mesh objects belonging to the asset's LOD0."""
    coll = get_asset_collection(context, asset_name)
    if coll:
        meshes = []
        target_objs = getattr(coll, "objects", [])
        if hasattr(coll, "all_objects") and not hasattr(coll.all_objects, "_mock_return_value"):
            target_objs = coll.all_objects
        for obj in target_objs:
            if not is_object_valid(obj) or getattr(obj, "type", "") != "MESH":
                continue
            name = getattr(obj, "name", "")
            is_col = bool(getattr(obj, "get", lambda *_: False)("_is_collider", False) is True)
            is_imp = bool(getattr(obj, "get", lambda *_: False)("_is_impostor", False) is True)
            if is_col or is_imp or name.startswith("UCX_") or "_Collider_" in name:
                continue
            if any(f"_LOD{n}" in name for n in range(1, 11)):
                continue
            meshes.append(obj)
        if meshes:
            return meshes

    return get_lod0_mesh_objects(context, base_name=asset_name)


def get_asset_existing_lods(context: Any, asset_name: str) -> dict[int, dict[str, Any]]:
    """
    Scans scene collections for existing LODs for asset_name.
    Returns dict mapping tier_index (0..k) to info dict:
    {
        'collection_name': str,
        'meshes': list[Any],
        'actual_tris': int,
        'is_impostor': bool,
    }
    """
    if not bpy or not hasattr(bpy, "data") or not hasattr(bpy.data, "collections") or not asset_name:
        return {}

    existing: dict[int, dict[str, Any]] = {}

    # Check LOD0
    l0_coll = get_asset_collection(context, asset_name)
    if l0_coll:
        l0_meshes = get_asset_base_meshes(context, asset_name)
        l0_tris = sum(
            sum(len(p.vertices) - 2 for p in m.data.polygons)
            for m in l0_meshes
            if hasattr(m, "data") and hasattr(m.data, "polygons")
        )
        existing[0] = {
            "collection_name": l0_coll.name,
            "meshes": l0_meshes,
            "actual_tris": l0_tris,
            "is_impostor": False,
        }

    # Check LOD1..10
    for i in range(1, 11):
        c_name = f"{asset_name}_LOD{i}"
        c = bpy.data.collections.get(c_name)
        if c:
            meshes = [o for o in getattr(c, "objects", []) if is_object_valid(o) and getattr(o, "type", "") == "MESH"]
            t_count = sum(
                sum(len(p.vertices) - 2 for p in m.data.polygons)
                for m in meshes
                if hasattr(m, "data") and hasattr(m.data, "polygons")
            )
            existing[i] = {
                "collection_name": c_name,
                "meshes": meshes,
                "actual_tris": t_count,
                "is_impostor": False,
            }

    # Check Impostor
    imp_name = f"{asset_name}_LOD_Impostor"
    c_imp = bpy.data.collections.get(imp_name)
    if c_imp:
        meshes = [o for o in getattr(c_imp, "objects", []) if is_object_valid(o) and getattr(o, "type", "") == "MESH"]
        t_count = (
            sum(
                sum(len(p.vertices) - 2 for p in m.data.polygons)
                for m in meshes
                if hasattr(m, "data") and hasattr(m.data, "polygons")
            )
            if meshes
            else 0
        )
        existing[-1] = {
            "collection_name": imp_name,
            "meshes": meshes,
            "actual_tris": t_count,
            "is_impostor": True,
        }

    return existing


def get_asset_enum_items(self: Any, context: Any) -> list[tuple[str, str, str]]:
    """Dynamic EnumProperty callback listing available scene asset collections."""
    global _CACHED_ASSET_ITEMS
    names = get_available_asset_names(context)
    items = [("AUTO", "AUTO (Follow Outliner)", "Dynamically follows active collection in the Outliner")]

    base_names = {n for n in names if not n.endswith("_Interior")}

    for n in names:
        if n.endswith("_Interior"):
            parent_base = n[:-9]
            label = f"{n} [Cockpit / Interior]"
            desc = f"Cockpit / flight deck model for '{parent_base}'"
        else:
            has_submodels = any(other != n and other.startswith(f"{n}_") for other in names)
            is_variant = any(n != b and n.startswith(f"{b}_") for b in base_names)
            if is_variant:
                matching_base = next(b for b in base_names if n != b and n.startswith(f"{b}_"))
                variant_name = n[len(matching_base) + 1 :]
                label = f"{n} [Variant: {variant_name}]"
                desc = f"Geometry variant '{variant_name}' for '{matching_base}'"
            elif has_submodels:
                label = f"{n} [Base / Exterior]"
                desc = f"Main exterior airframe model for '{n}'"
            else:
                label = n
                desc = f"Asset model collection: {n}"

        items.append((n, label, desc))

    if len(items) == 1:
        items.append(("NONE", "No Assets Found", "Create a root collection with meshes"))
    _CACHED_ASSET_ITEMS = items
    return _CACHED_ASSET_ITEMS


def get_or_create_engine_import_collection(
    context: Any,
    asset_name: str,
    role: str,
    use_lod0_suffix: bool = True,
) -> Any | None:
    """Finds or creates a collection adhering to OmniMesh's neutral engine package hierarchy.

    Structure:
    {AssetName} (Root Package Collection)
       ├── {AssetName}_LOD0 (or {AssetName})
       │    ├── {AssetName}_Spatial
       │    ├── {AssetName}_Lights
       │    └── {AssetName}_Cameras
       ├── {AssetName}_LOD1
       └── {AssetName}_LODN
    """
    if not bpy or not context:
        return None

    clean_asset = asset_name.strip() or "Asset"
    scene = context.scene

    # 1. Root Model Collection
    root_col = bpy.data.collections.get(clean_asset)
    if not root_col:
        root_col = bpy.data.collections.new(clean_asset)
        scene.collection.children.link(root_col)
    elif root_col.name not in scene.collection.children:
        try:
            scene.collection.children.link(root_col)
        except RuntimeError:
            pass

    if clean_asset.endswith("_Interior"):
        root_col["_omnimesh_role"] = "INTERIOR"
        root_col["_omnimesh_parent"] = clean_asset[:-9]
    elif role.upper() == "VARIANT" or (
        "_" in clean_asset
        and not any(clean_asset.endswith(f"_LOD{n}") for n in range(11))
        and any(
            getattr(c, "name", "") != clean_asset and clean_asset.startswith(f"{getattr(c, 'name', '')}_")
            for c in getattr(scene.collection, "children", [])
        )
    ):
        root_col["_omnimesh_role"] = "VARIANT"
        matching_parent = next(
            (
                getattr(c, "name", "")
                for c in getattr(scene.collection, "children", [])
                if getattr(c, "name", "") != clean_asset and clean_asset.startswith(f"{getattr(c, 'name', '')}_")
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
    if role_upper == "LOD0":
        sub_name = f"{clean_asset}_LOD0" if use_lod0_suffix else f"{clean_asset}_Mesh"
    elif role_upper.startswith("LOD"):
        sub_name = f"{clean_asset}_{role_upper}"
    elif role_upper == "SPATIAL":
        sub_name = f"{clean_asset}_Spatial"
    elif role_upper == "LIGHTS":
        sub_name = f"{clean_asset}_Lights"
    elif role_upper == "CAMERAS":
        sub_name = f"{clean_asset}_Cameras"
    else:
        sub_name = f"{clean_asset}_{role}"

    # Configuration collections (Spatial, Lights, Cameras) reside under LOD0
    parent_col = root_col
    if role_upper in ("SPATIAL", "LIGHTS", "CAMERAS"):
        lod0_name = f"{clean_asset}_LOD0" if use_lod0_suffix else f"{clean_asset}_Mesh"
        lod0_col = bpy.data.collections.get(lod0_name)
        if not lod0_col:
            lod0_col = bpy.data.collections.new(lod0_name)
            root_col.children.link(lod0_col)
            lod0_col["_omnimesh_role"] = "LOD0"
        parent_col = lod0_col

    sub_col = bpy.data.collections.get(sub_name)
    if not sub_col:
        sub_col = bpy.data.collections.new(sub_name)
        parent_col.children.link(sub_col)
    else:
        if sub_col.name not in parent_col.children:
            try:
                parent_col.children.link(sub_col)
            except RuntimeError:
                pass
        # If misplaced directly under root_col, unlink
        if parent_col != root_col and sub_col.name in root_col.children:
            try:
                root_col.children.unlink(sub_col)
            except RuntimeError:
                pass

    sub_col["_omnimesh_role"] = role_upper
    return sub_col
