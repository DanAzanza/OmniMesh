"""
Master Engine Export Router & Pre-Flight Quality Gate with PBR Texture, Animation & Live Bridge Integration.
"""

from __future__ import annotations

import logging
from typing import Any

try:
    import bpy
except ImportError:
    bpy = None


logger = logging.getLogger(__name__)


from dataclasses import dataclass, field
import re
from typing import Optional


@dataclass(frozen=True)
class AssetExportPayload:
    """Strongly typed export payload for an asset adhering to Variante A Collection Rules."""

    asset_name: str
    lod_tiers: dict[int, list[Any]]  # 0 -> [LOD0 meshes], 1 -> [LOD1 meshes], ..., k -> [Impostor]
    collider_objects: list[Any] = field(default_factory=list)
    impostor_object: Optional[Any] = None
    armature_obj: Optional[Any] = None
    is_skeletal: bool = False
    has_impostor_tier: bool = False
    role: str = "MODEL_ROOT"  # "MODEL_ROOT", "INTERIOR", or "VARIANT"
    parent_asset_name: Optional[str] = None


class AssetMeshResolver:
    """Centralized resolver that extracts pure geometry LOD meshes from scene collections.

    Adheres strictly to Variante A:
    - Traverses root model collections and nested/sibling LOD collections.
    - Strictly excludes technical sub-collections (_Spatial, _Lights, _Cameras).
    - Routes colliders and impostors to dedicated payload fields.
    - Provides a headless fallback to tier.generated_obj for CLI/mock test environments.
    """

    @classmethod
    def resolve_payload(cls, context: Any, asset_name: str) -> AssetExportPayload:
        clean_name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(asset_name)).strip() or "SM_Asset"
        props = getattr(context.scene, "lod_tool", None) if (context and hasattr(context, "scene")) else None

        has_bpy_collections = bool(bpy and hasattr(bpy, "data") and hasattr(bpy.data, "collections"))

        root_col = None
        if has_bpy_collections:
            root_col = bpy.data.collections.get(clean_name) or bpy.data.collections.get(f"{clean_name}_LOD0")

        lod_tiers: dict[int, list[Any]] = {}
        collider_objects: list[Any] = []
        impostor_object = None
        armature_obj = None
        has_impostor_tier = False

        def is_valid_lod_mesh(obj: Any) -> bool:
            if not obj or getattr(obj, "type", "") != "MESH":
                return False
            name = getattr(obj, "name", "")
            if getattr(obj, "get", lambda *_: False)("_is_collider", False):
                return False
            if getattr(obj, "get", lambda *_: False)("_is_impostor", False):
                return False
            if name.startswith("UCX_") or "_Collider_" in name:
                return False
            # Exclude objects residing in technical auxiliary collections
            users = getattr(obj, "users_collection", [])
            for c in users:
                c_name = getattr(c, "name", "")
                if getattr(c, "get", lambda *_: False)("_omnimesh_role", "") in ("SPATIAL", "LIGHTS", "CAMERAS"):
                    return False
                if any(c_name.endswith(sfx) for sfx in ("_Spatial", "_Lights", "_Cameras", "_Colliders")):
                    return False
            return True

        if has_bpy_collections and root_col:
            max_tiers = len(props.lods) if (props and len(props.lods) > 0) else 10

            # LOD0: inspect child collection, then sibling, then direct objects
            lod0_col = None
            if hasattr(root_col, "children"):
                lod0_col = root_col.children.get(f"{clean_name}_LOD0") or root_col.children.get(f"{clean_name}_Mesh")
            if not lod0_col:
                lod0_col = bpy.data.collections.get(f"{clean_name}_LOD0") or bpy.data.collections.get(
                    f"{clean_name}_Mesh"
                )

            lod0_objs: list[Any] = []
            if lod0_col:
                for obj in getattr(lod0_col, "objects", []):
                    if is_valid_lod_mesh(obj) and obj not in lod0_objs:
                        lod0_objs.append(obj)
            elif root_col.name == clean_name:
                for obj in getattr(root_col, "objects", []):
                    if is_valid_lod_mesh(obj) and obj not in lod0_objs:
                        lod0_objs.append(obj)

            if lod0_objs:
                lod_tiers[0] = lod0_objs

            # LOD1..max_tiers
            for i in range(1, max_tiers + 1):
                tier_col = None
                if hasattr(root_col, "children"):
                    tier_col = root_col.children.get(f"{clean_name}_LOD{i}")
                if not tier_col:
                    tier_col = bpy.data.collections.get(f"{clean_name}_LOD{i}")
                if tier_col:
                    tier_objs: list[Any] = []
                    for obj in getattr(tier_col, "objects", []):
                        if is_valid_lod_mesh(obj) and obj not in tier_objs:
                            tier_objs.append(obj)
                    if tier_objs:
                        lod_tiers[i] = tier_objs

            # Impostor
            imp_col = None
            if hasattr(root_col, "children"):
                imp_col = root_col.children.get(f"{clean_name}_LOD_Impostor")
            if not imp_col:
                imp_col = bpy.data.collections.get(f"{clean_name}_LOD_Impostor")
            if imp_col:
                for obj in getattr(imp_col, "objects", []):
                    if getattr(obj, "type", "") == "MESH":
                        impostor_object = obj
                        break
            if not impostor_object and hasattr(bpy, "data") and hasattr(bpy.data, "objects"):
                for obj in bpy.data.objects:
                    if getattr(obj, "get", lambda *_: False)("_is_impostor", False) and clean_name in obj.name:
                        impostor_object = obj
                        break
            if impostor_object:
                has_impostor_tier = True
                next_tier_idx = max(lod_tiers.keys()) + 1 if lod_tiers else 1
                lod_tiers[next_tier_idx] = [impostor_object]

            # Colliders
            coll_col = None
            if hasattr(root_col, "children"):
                coll_col = root_col.children.get(f"{clean_name}_Colliders")
            if not coll_col:
                coll_col = bpy.data.collections.get(f"{clean_name}_Colliders")
            if coll_col:
                for obj in getattr(coll_col, "objects", []):
                    if getattr(obj, "type", "") == "MESH" and obj not in collider_objects:
                        collider_objects.append(obj)
            elif hasattr(bpy, "data") and hasattr(bpy.data, "objects"):
                for obj in bpy.data.objects:
                    is_col = bool(getattr(obj, "get", lambda *_: False)("_is_collider", False))
                    o_name = getattr(obj, "name", "")
                    if (is_col or o_name.startswith("UCX_")) and clean_name in o_name:
                        if obj not in collider_objects:
                            collider_objects.append(obj)

        # Headless mock / procedural fallback (vital for test_preflight_validator and procedural scenes)
        if not lod_tiers and props and len(props.lods) > 0:
            for i, tier in enumerate(props.lods):
                obj = getattr(tier, "generated_obj", None)
                if obj and (not bpy or (isinstance(getattr(obj, "name", None), str) and obj.name in bpy.data.objects)):
                    lod_tiers[i] = [obj]

        # Detect Armature / Rig
        all_export_objs = [o for objs in lod_tiers.values() for o in objs]
        for obj in all_export_objs:
            if getattr(obj, "parent", None) and getattr(obj.parent, "type", "") == "ARMATURE":
                armature_obj = obj.parent
                break
            for mod in getattr(obj, "modifiers", []):
                if getattr(mod, "type", "") == "ARMATURE" and getattr(mod, "object", None):
                    armature_obj = mod.object
                    break

        role = ""
        parent_asset = None
        if root_col:
            role = str(getattr(root_col, "get", lambda *_: "")("_omnimesh_role", "") or "")
            parent_asset = getattr(root_col, "get", lambda *_: None)("_omnimesh_parent", None)

        if not role or role == "MODEL_ROOT":
            if clean_name.endswith("_Interior"):
                role = "INTERIOR"
                parent_asset = clean_name[:-9]
            elif "_" in clean_name and not any(clean_name.endswith(sfx) for sfx in ("_LOD0", "_Mesh")):
                cand_parent = clean_name.rsplit("_", 1)[0]
                if has_bpy_collections and (
                    bpy.data.collections.get(cand_parent) or bpy.data.collections.get(f"{cand_parent}_LOD0")
                ):
                    role = "VARIANT"
                    parent_asset = cand_parent
                else:
                    role = "MODEL_ROOT"
            else:
                role = "MODEL_ROOT"

        return AssetExportPayload(
            asset_name=clean_name,
            lod_tiers=lod_tiers,
            collider_objects=collider_objects,
            impostor_object=impostor_object,
            armature_obj=armature_obj,
            is_skeletal=bool(armature_obj is not None),
            has_impostor_tier=has_impostor_tier,
            role=role,
            parent_asset_name=parent_asset,
        )


class PreFlightValidator:
    @staticmethod
    def run_checks(context: Any) -> list[str]:
        if not context or not getattr(context, "scene", None):
            return ["Blender context not available."]
        props = getattr(context.scene, "lod_tool", None)
        if not props:
            return ["LOD tool properties not initialized on scene."]
        errors: list[str] = []

        if len(props.lods) == 0:
            errors.append("No LOD tiers configured.")
            return errors

        raw_name = ""
        try:
            from core.asset_scanner import resolve_effective_asset_name

            raw_name = resolve_effective_asset_name(context, props)
        except Exception as e:
            logger.debug("Failed resolving effective asset name in PreFlightValidator: %s", e)

        if not raw_name or raw_name in ("AUTO", "NONE", "Asset"):
            raw_name = getattr(props, "export_base_name", "").strip() or "SM_Asset"
        if hasattr(props, "active_asset") and props.active_asset and props.active_asset not in ("AUTO", "NONE"):
            raw_name = props.active_asset

        payload = AssetMeshResolver.resolve_payload(context, raw_name)

        # Verify all configured tiers are generated/present
        missing_tiers = False
        for i in range(len(props.lods)):
            tier_objs = payload.lod_tiers.get(i, [])
            if not tier_objs:
                missing_tiers = True
                break

        if missing_tiers:
            errors.append("Some configured LOD tiers have not been generated yet. Run 'Generate All LODs' first.")
            return errors

        # Empty geometry check
        for i in range(len(props.lods)):
            for obj in payload.lod_tiers.get(i, []):
                if (
                    getattr(obj, "type", "") == "MESH"
                    and getattr(obj, "data", None)
                    and hasattr(obj.data, "polygons")
                    and len(obj.data.polygons) == 0
                ):
                    errors.append(f"LOD{i} ('{obj.name}') has 0 polygons (empty geometry).")

        # Pivot / origin matching (single-object tiers)
        lod0_objs = payload.lod_tiers.get(0, [])
        if lod0_objs and hasattr(lod0_objs[0], "matrix_world") and hasattr(lod0_objs[0].matrix_world, "translation"):
            lod0_pivot = lod0_objs[0].matrix_world.translation
            for i in range(len(props.lods)):
                tier_objs = payload.lod_tiers.get(i, [])
                if len(lod0_objs) == 1 and len(tier_objs) == 1:
                    obj = tier_objs[0]
                    if hasattr(obj, "matrix_world") and hasattr(obj.matrix_world, "translation"):
                        if (obj.matrix_world.translation - lod0_pivot).length > 1e-4:
                            errors.append(f"LOD{i} origin does not match LOD0 pivot.")

        # Scale application check
        for i in range(len(props.lods)):
            for obj in payload.lod_tiers.get(i, []):
                scale = getattr(obj, "scale", None)
                if scale:
                    sx = getattr(scale, "x", scale[0] if isinstance(scale, (list, tuple)) else 1.0)
                    sy = getattr(scale, "y", scale[1] if isinstance(scale, (list, tuple)) else 1.0)
                    sz = getattr(scale, "z", scale[2] if isinstance(scale, (list, tuple)) else 1.0)
                    if abs(sx - 1.0) > 1e-4 or abs(sy - 1.0) > 1e-4 or abs(sz - 1.0) > 1e-4:
                        errors.append(
                            f"LOD{i} has unapplied scale ({round(sx, 2)}, {round(sy, 2)}, {round(sz, 2)}). Apply transforms."
                        )
                        break

        # Material checks
        if len(lod0_objs) == 1:
            lod0_slots = len(getattr(lod0_objs[0], "material_slots", []))
            for i in range(len(props.lods)):
                tier_objs = payload.lod_tiers.get(i, [])
                if len(tier_objs) == 1 and lod0_slots > 0 and len(getattr(tier_objs[0], "material_slots", [])) == 0:
                    errors.append(f"LOD{i} is missing material slots.")

        for i in range(len(props.lods)):
            for obj in payload.lod_tiers.get(i, []):
                for slot_idx, slot in enumerate(getattr(obj, "material_slots", [])):
                    if getattr(slot, "material", None) is None:
                        errors.append(f"LOD{i} has unassigned material in slot {slot_idx}.")

        # Asset name validation
        if props.export_base_name:
            if re.search(r'[<>:"/\\|?*\x00-\x1f]', props.export_base_name):
                errors.append(f"Export asset name '{props.export_base_name}' contains invalid characters.")

        # Export directory validation
        export_dir_str = props.export_directory.strip() if props.export_directory else ""
        if not export_dir_str:
            errors.append("Export directory path is empty.")
        elif "\x00" in export_dir_str:
            errors.append("Export directory path contains invalid null bytes.")

        return errors


try:
    from ui.export_ops import (
        EXPORT_OPS_CLASSES,
        LOD_OT_bake_rig_animation,
        LOD_OT_export_engine_package,
        LOD_OT_pack_pbr_textures,
        LOD_OT_sync_live_bridge,
        LOD_OT_toggle_live_bridge,
        register_export_ops,
        unregister_export_ops,
    )
except (ImportError, ValueError):
    try:
        from ..ui.export_ops import (
            EXPORT_OPS_CLASSES,
            LOD_OT_bake_rig_animation,
            LOD_OT_export_engine_package,
            LOD_OT_pack_pbr_textures,
            LOD_OT_sync_live_bridge,
            LOD_OT_toggle_live_bridge,
            register_export_ops,
            unregister_export_ops,
        )
    except (ImportError, ValueError):
        EXPORT_OPS_CLASSES = ()  # type: ignore
        LOD_OT_bake_rig_animation = None  # type: ignore
        LOD_OT_export_engine_package = None  # type: ignore
        LOD_OT_pack_pbr_textures = None  # type: ignore
        LOD_OT_sync_live_bridge = None  # type: ignore
        LOD_OT_toggle_live_bridge = None  # type: ignore
        register_export_ops = None  # type: ignore
        unregister_export_ops = None  # type: ignore


def register_exporters() -> None:
    """Delegates exporter registration (operators are centrally registered in ui.operators)."""
    pass


def unregister_exporters() -> None:
    """Delegates exporter unregistration (operators are centrally unregistered in ui.operators)."""
    pass
