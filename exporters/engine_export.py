"""
Master Engine Export Router & Pre-Flight Quality Gate with PBR Texture & Animation Integration.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional, Protocol, cast

from .base import TECHNICAL_COLLECTION_SUFFIXES

if TYPE_CHECKING:
    from collections.abc import Sequence
    import bpy
    from bpy.types import BlendData
else:
    try:
        import bpy
    except ImportError:
        bpy = None
    BlendData = object


logger = logging.getLogger(__name__)


class EngineExportTierProtocol(Protocol):
    generated_obj: bpy.types.Object | None


class EngineExportSettingsProtocol(Protocol):
    lods: Sequence[EngineExportTierProtocol]
    active_asset: str
    export_base_name: str
    export_directory: str


@dataclass(frozen=True)
class AssetExportPayload:
    """Strongly typed export payload for an asset adhering to Variante A Collection Rules."""

    asset_name: str
    lod_tiers: dict[int, list[bpy.types.Object]]  # 0 -> [LOD0 meshes], 1 -> [LOD1 meshes], ..., k -> [Impostor]
    collider_objects: list[bpy.types.Object] = field(default_factory=list)
    impostor_object: Optional[bpy.types.Object] = None
    armature_obj: Optional[bpy.types.Object] = None
    is_skeletal: bool = False
    has_impostor_tier: bool = False
    role: str = "MODEL_ROOT"  # "MODEL_ROOT", "INTERIOR", or "VARIANT"
    parent_asset_name: Optional[str] = None
    attachment_nodes: list[bpy.types.Object] = field(
        default_factory=list
    )  # ATTACH_POINT_, fx_, eye_ empties for LOD0 glTF export


def _get_lod_tool_props(scene: bpy.types.Scene | None) -> EngineExportSettingsProtocol | None:
    """Extracts the OmniMesh scene PropertyGroup safely across headless/registered contexts."""
    if scene is None:
        return None
    return cast("EngineExportSettingsProtocol | None", getattr(scene, "lod_tool", None))


class AssetMeshResolver:
    """Centralized resolver that extracts pure geometry LOD meshes from scene collections.

    Adheres strictly to Variante A:
    - Traverses root model collections and nested/sibling LOD collections.
    - Strictly excludes technical sub-collections (_Spatial, _Lights, _Cameras).
    - Routes colliders and impostors to dedicated payload fields.
    - Provides a headless fallback to tier.generated_obj for CLI/mock test environments.
    """

    @classmethod
    def resolve_payload(
        cls,
        context: bpy.types.Context | None,
        asset_name: str,
        *,
        blend_data: BlendData | None = None,
    ) -> AssetExportPayload:
        clean_name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(asset_name)).strip() or "SM_Asset"
        props = _get_lod_tool_props(context.scene if context else None)

        effective_bdata = blend_data or (context.blend_data if context else None)
        has_collections = bool(effective_bdata)

        root_col = None
        if has_collections and effective_bdata:
            root_col = effective_bdata.collections.get(clean_name) or effective_bdata.collections.get(
                f"{clean_name}_LOD0"
            )

        lod_tiers: dict[int, list[bpy.types.Object]] = {}
        collider_objects: list[bpy.types.Object] = []
        impostor_object = None
        armature_obj = None
        has_impostor_tier = False

        scene_objs = context.scene.objects if (context and context.scene) else None

        def is_in_active_scene(obj: bpy.types.Object | None) -> bool:
            if obj is None:
                return False
            if scene_objs is None:
                return True
            return obj.name in scene_objs

        def is_valid_lod_mesh(obj: bpy.types.Object | None) -> bool:
            if not obj or obj.type != "MESH" or not is_in_active_scene(obj):
                return False
            name = obj.name
            if obj.get("_is_collider", False):
                return False
            if obj.get("_is_impostor", False):
                return False
            if obj.get("_is_trigger", False):
                return False
            if obj.get("_omnimesh_role", "") == "INTERACTION_VOLUME":
                return False
            if name.startswith("UCX_") or "_Collider_" in name:
                return False
            # Exclude objects residing in technical auxiliary collections
            users = obj.users_collection
            for c in users:
                c_name = c.name
                if c.get("_omnimesh_role", "") in (
                    "SPATIAL",
                    "LIGHTS",
                    "CAMERAS",
                    "CONFIG",
                    "HELPERS",
                    "INTERACTIONS",
                    "ATTACHMENTS",
                    "PREVIEW",
                ):
                    return False
                if c_name.endswith(TECHNICAL_COLLECTION_SUFFIXES):
                    return False
            return True

        if has_collections and root_col:
            max_tiers = len(props.lods) if (props and len(props.lods) > 0) else 10

            # LOD0: inspect child collection, then sibling, then direct objects
            lod0_col = None
            if root_col.children is not None:
                lod0_col = (
                    root_col.children.get(f"{clean_name}_LOD0")
                    or root_col.children.get(f"{clean_name}_Mesh")
                    or root_col.children.get("x0")
                    or root_col.children.get(f"x0_{clean_name}")
                )
            if not lod0_col and has_collections and effective_bdata:
                lod0_col = (
                    effective_bdata.collections.get(f"{clean_name}_LOD0")
                    or effective_bdata.collections.get(f"{clean_name}_Mesh")
                    or effective_bdata.collections.get("x0")
                    or effective_bdata.collections.get(f"x0_{clean_name}")
                )

            lod0_objs: list[bpy.types.Object] = []
            if lod0_col:
                for obj in lod0_col.objects:
                    if is_valid_lod_mesh(obj) and obj not in lod0_objs:
                        lod0_objs.append(obj)
            elif root_col.name == clean_name:
                for obj in root_col.objects:
                    if is_valid_lod_mesh(obj) and obj not in lod0_objs:
                        lod0_objs.append(obj)

            if lod0_objs:
                lod_tiers[0] = lod0_objs

            # LOD1..max_tiers (supporting both _LOD{i}, _HLOD_LOD{i}, _Chunks_LOD{i}, and x{i} aliases)
            for i in range(1, max_tiers + 1):
                tier_col = None
                aliases = (
                    f"{clean_name}_LOD{i}",
                    f"{clean_name}_HLOD_LOD{i}",
                    f"{clean_name}_Chunks_LOD{i}",
                    f"x{i}",
                    f"x{i}_{clean_name}",
                )
                if root_col.children is not None:
                    for alias in aliases:
                        tier_col = root_col.children.get(alias)
                        if tier_col:
                            break
                if not tier_col and has_collections and effective_bdata:
                    for alias in aliases:
                        tier_col = effective_bdata.collections.get(alias)
                        if tier_col:
                            break
                if tier_col:
                    tier_objs: list[bpy.types.Object] = []
                    for obj in tier_col.objects:
                        if is_valid_lod_mesh(obj) and obj not in tier_objs:
                            tier_objs.append(obj)
                    if tier_objs:
                        lod_tiers[i] = tier_objs

            # Impostor
            imp_col = None
            if root_col.children is not None:
                imp_col = root_col.children.get(f"{clean_name}_LOD_Impostor")
            if not imp_col and has_collections and effective_bdata:
                imp_col = effective_bdata.collections.get(f"{clean_name}_LOD_Impostor")
            if imp_col:
                for obj in imp_col.objects:
                    if obj.type == "MESH" and is_in_active_scene(obj):
                        impostor_object = obj
                        break
            if not impostor_object and effective_bdata:
                for obj in effective_bdata.objects:
                    o_name = obj.name
                    matches_asset = (
                        o_name == clean_name
                        or o_name.startswith(f"{clean_name}_")
                        or obj.get("_omnimesh_parent") == clean_name
                    )
                    if obj.get("_is_impostor", False) and matches_asset and is_in_active_scene(obj):
                        impostor_object = obj
                        break
            if impostor_object:
                has_impostor_tier = True
                next_tier_idx = max(lod_tiers.keys()) + 1 if lod_tiers else 1
                lod_tiers[next_tier_idx] = [impostor_object]

            # Colliders
            coll_col = None
            if root_col.children is not None:
                coll_col = root_col.children.get(f"{clean_name}_Colliders")
            if not coll_col and has_collections and effective_bdata:
                coll_col = effective_bdata.collections.get(f"{clean_name}_Colliders")
            if coll_col:
                for obj in coll_col.objects:
                    if obj.type == "MESH" and is_in_active_scene(obj) and obj not in collider_objects:
                        collider_objects.append(obj)
            elif effective_bdata:
                for obj in effective_bdata.objects:
                    is_col = bool(obj.get("_is_collider", False))
                    o_name = obj.name
                    matches_asset = (
                        o_name == clean_name
                        or o_name.startswith((f"{clean_name}_", f"UCX_{clean_name}_"))
                        or obj.get("_omnimesh_parent") == clean_name
                    )
                    if (is_col or o_name.startswith("UCX_")) and matches_asset and is_in_active_scene(obj):
                        if obj not in collider_objects:
                            collider_objects.append(obj)

        # Headless mock / procedural fallback (vital for test_preflight_validator and procedural scenes)
        if not lod_tiers and props and len(props.lods) > 0:
            bdata_objects = effective_bdata.objects if effective_bdata else None
            for i, tier in enumerate(props.lods):
                obj = tier.generated_obj
                if (
                    obj
                    and is_in_active_scene(obj)
                    and (not bpy or bdata_objects is None or (isinstance(obj.name, str) and obj.name in bdata_objects))
                ):
                    lod_tiers[i] = [obj]

        # Detect Armature / Rig
        all_export_objs = [o for objs in lod_tiers.values() for o in objs]
        for obj in all_export_objs:
            parent = obj.parent
            if parent and parent.type == "ARMATURE":
                armature_obj = parent
                break
            for mod in obj.modifiers:
                if mod.type == "ARMATURE":
                    mod_obj = cast("bpy.types.ArmatureModifier", mod).object
                    if mod_obj:
                        armature_obj = mod_obj
                        break
            if armature_obj:
                break

        role = ""
        parent_asset = None
        if root_col:
            role = str(root_col.get("_omnimesh_role", "") or "")
            parent_asset = root_col.get("_omnimesh_parent", None)

        if not role or role == "MODEL_ROOT":
            if clean_name.endswith("_Interior"):
                role = "INTERIOR"
                parent_asset = clean_name[:-9]
            elif "_" in clean_name and not any(clean_name.endswith(sfx) for sfx in ("_LOD0", "_Mesh")):
                cand_parent = clean_name.rsplit("_", 1)[0]
                if (
                    has_collections
                    and effective_bdata
                    and (
                        effective_bdata.collections.get(cand_parent)
                        or effective_bdata.collections.get(f"{cand_parent}_LOD0")
                    )
                ):
                    role = "VARIANT"
                    parent_asset = cand_parent
                else:
                    role = "MODEL_ROOT"
            else:
                role = "MODEL_ROOT"

        # Discover Attachment Nodes (ATTACH_POINT_, ATTACH_FX_, eye_, socket_)
        # Vital for MSFS glTF LOD0 runtime attachments, cameras, and effect positioning
        attachment_nodes: list[bpy.types.Object] = []
        if has_collections and root_col:
            candidate_cols = []
            if root_col.children is not None:
                h_col = root_col.children.get(f"{clean_name}_Helpers")
                if h_col:
                    candidate_cols.append(h_col)
                l0_col = root_col.children.get(f"{clean_name}_LOD0")
                if l0_col:
                    candidate_cols.append(l0_col)
            if not candidate_cols and effective_bdata:
                h_col = effective_bdata.collections.get(f"{clean_name}_Helpers")
                if h_col:
                    candidate_cols.append(h_col)
                l0_col = effective_bdata.collections.get(f"{clean_name}_LOD0")
                if l0_col:
                    candidate_cols.append(l0_col)
            candidate_cols.append(root_col)

            for col in candidate_cols:
                for obj in col.objects:
                    o_name = obj.name.upper()
                    if o_name.startswith(("ATTACH_", "FX_", "SOCKET_", "EYE_")) or "ATTACH_POINT" in o_name:
                        if obj.type == "EMPTY" and is_in_active_scene(obj) and obj not in attachment_nodes:
                            attachment_nodes.append(obj)

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
            attachment_nodes=attachment_nodes,
        )


def resolve_export_asset_name(context: bpy.types.Context | None, props: object = None) -> str:
    """Resolves the unified asset name for preflight validation and engine export."""
    props_obj: EngineExportSettingsProtocol | None = cast("EngineExportSettingsProtocol | None", props)
    if not props_obj and context:
        props_obj = _get_lod_tool_props(context.scene)
    active_asset = getattr(props_obj, "active_asset", None) if props_obj else None
    if active_asset and active_asset not in ("AUTO", "NONE"):
        return str(active_asset)
    raw_name = ""
    try:
        try:
            from ..core.asset_scanner import resolve_effective_asset_name
        except ImportError:
            from core.asset_scanner import resolve_effective_asset_name

        bdata = context.blend_data if context else None
        if bdata is not None:
            raw_name = resolve_effective_asset_name(context, props_obj, blend_data=bdata)
    except (ImportError, AttributeError, TypeError, ValueError) as e:
        logger.debug("Failed resolving effective asset name: %s", e)
    if not raw_name or raw_name in ("AUTO", "NONE", "Asset"):
        raw_name = str(props_obj.export_base_name).strip() if props_obj else ""
    return raw_name or "SM_Asset"


class PreFlightValidator:
    @staticmethod
    def run_checks(
        context: bpy.types.Context | None,
        *,
        blend_data: BlendData | None = None,
    ) -> list[str]:
        if not context or not context.scene:
            return ["Blender context not available."]
        props = _get_lod_tool_props(context.scene)
        if not props:
            return ["LOD tool properties not initialized on scene."]
        errors: list[str] = []

        if len(props.lods) == 0:
            errors.append("No LOD tiers configured.")
            return errors

        raw_name = resolve_export_asset_name(context, props)
        bdata = blend_data or context.blend_data
        payload = AssetMeshResolver.resolve_payload(context, raw_name, blend_data=bdata)

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
                mesh_data = cast("bpy.types.Mesh | None", obj.data)
                polys = mesh_data.polygons if mesh_data else None
                if obj.type == "MESH" and polys is not None and len(polys) == 0:
                    errors.append(f"LOD{i} ('{obj.name}') has 0 polygons (empty geometry).")

        # Pivot / origin matching (single-object tiers)
        lod0_objs = payload.lod_tiers.get(0, [])
        if len(lod0_objs) == 1 and lod0_objs[0] is not None and lod0_objs[0].matrix_world is not None:
            lod0_pivot = lod0_objs[0].matrix_world.translation
            for i in range(len(props.lods)):
                tier_objs = payload.lod_tiers.get(i, [])
                if len(tier_objs) != 1:
                    continue
                obj = tier_objs[0]
                if obj is None or obj.matrix_world is None:
                    continue
                if (obj.matrix_world.translation - lod0_pivot).length > 1e-4:
                    errors.append(f"LOD{i} origin does not match LOD0 pivot.")

        # Scale application check
        for i in range(len(props.lods)):
            for obj in payload.lod_tiers.get(i, []):
                if obj is not None and obj.scale is not None:
                    try:
                        sx, sy, sz = float(obj.scale.x), float(obj.scale.y), float(obj.scale.z)
                    except AttributeError:
                        try:
                            sx, sy, sz = float(obj.scale[0]), float(obj.scale[1]), float(obj.scale[2])
                        except (IndexError, TypeError, ValueError):
                            continue
                    except (TypeError, ValueError):
                        continue
                    if abs(sx - 1.0) > 1e-4 or abs(sy - 1.0) > 1e-4 or abs(sz - 1.0) > 1e-4:
                        errors.append(
                            f"LOD{i} has unapplied scale ({round(sx, 2)}, {round(sy, 2)}, {round(sz, 2)}). Apply transforms."
                        )
                        break

        # Material checks
        if len(lod0_objs) == 1:
            lod0_slots = len(lod0_objs[0].material_slots)
            for i in range(len(props.lods)):
                tier_objs = payload.lod_tiers.get(i, [])
                if len(tier_objs) == 1 and lod0_slots > 0 and len(tier_objs[0].material_slots) == 0:
                    errors.append(f"LOD{i} is missing material slots.")

        for i in range(len(props.lods)):
            for obj in payload.lod_tiers.get(i, []):
                for slot_idx, slot in enumerate(obj.material_slots):
                    if slot.material is None:
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


def register_exporters() -> None:
    """Delegates exporter registration (operators are centrally registered in ui.operators)."""


def unregister_exporters() -> None:
    """Delegates exporter unregistration (operators are centrally unregistered in ui.operators)."""
