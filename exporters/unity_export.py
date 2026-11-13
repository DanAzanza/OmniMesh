"""
Unity 6 Exporter for LOD Meshes and Collision Hulls.
"""

from __future__ import annotations

try:
    from ..core.exceptions import OmniMeshError
except (ImportError, ValueError):
    from core.exceptions import OmniMeshError

import logging
import os
import re
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    import bpy
    from bpy.types import BlendData
    from .base import EngineExporterBase, scoped_export_visibility
    from .engine_export import AssetExportPayload, AssetMeshResolver
else:
    try:
        import bpy
    except ImportError:
        bpy = None
    BlendData = object

    from .base import EngineExporterBase, scoped_export_visibility
    from .engine_export import AssetExportPayload, AssetMeshResolver


def _normalize_unity_lod_names(
    payload: AssetExportPayload,
    clean_name: str,
) -> dict[bpy.types.Object, str]:
    """Applies Unity's _LOD0..N suffix convention transactionally across LODs and impostors."""
    orig_names: dict[bpy.types.Object, str] = {}
    multi_tier = len(payload.lod_tiers) > 1
    imp_tier_idx = max(payload.lod_tiers.keys()) if payload.has_impostor_tier else None

    for tier_idx, tier_objs in payload.lod_tiers.items():
        if imp_tier_idx is not None and tier_idx == imp_tier_idx:
            for sub_idx, obj in enumerate(tier_objs):
                orig_names[obj] = obj.name
                prefix = clean_name if len(tier_objs) == 1 else f"{clean_name}_{sub_idx:02d}"
                obj.name = f"{prefix}_LOD{tier_idx}"
            continue

        if not multi_tier:
            continue

        expected_sfx = f"_LOD{tier_idx}"
        for obj in tier_objs:
            if re.search(rf"_LOD{tier_idx}$", obj.name, flags=re.IGNORECASE):
                continue
            orig_names[obj] = obj.name
            stem = re.sub(r"_LOD\d+$", "", obj.name, flags=re.IGNORECASE)
            obj.name = f"{stem}{expected_sfx}"

    return orig_names


class UnityExporter(EngineExporterBase):
    @staticmethod
    def generate_postprocessor_cs() -> str:
        """Generates a self-contained Unity 6 Editor AssetPostprocessor for colliders and PBR textures."""
        return """// OmniMesh Generated Unity 6 AssetPostprocessor
// Place inside any Editor/ folder under Assets/ to automate Collider & Texture import setup.
#if UNITY_EDITOR
using System.Text.RegularExpressions;
using UnityEditor;
using UnityEngine;

public class OmniMeshPostprocessor : AssetPostprocessor
{
    private static readonly Regex ColliderPattern = new Regex(
        @"(_Collider(_?\\d+)?$|^UCX_)",
        RegexOptions.IgnoreCase | RegexOptions.Compiled
    );

    private void OnPreprocessTexture()
    {
        var importer = assetImporter as TextureImporter;
        if (importer == null)
        {
            return;
        }

        string lowerPath = assetPath.ToLowerInvariant();
        if (lowerPath.EndsWith("_normal.png") && !lowerPath.Contains("_impostor_normal"))
        {
            importer.textureType = TextureImporterType.NormalMap;
        }
        else if (lowerPath.Contains("_maskmap") || lowerPath.Contains("_orm") || lowerPath.Contains("_comp"))
        {
            importer.sRGBTexture = false;
        }
    }

    private void OnPostprocessModel(GameObject root)
    {
        if (root == null)
        {
            return;
        }

        foreach (Transform child in root.GetComponentsInChildren<Transform>(true))
        {
            if (!ColliderPattern.IsMatch(child.name))
            {
                continue;
            }

            var meshFilter = child.GetComponent<MeshFilter>();
            if (meshFilter != null && meshFilter.sharedMesh != null)
            {
                var collider = child.gameObject.GetComponent<MeshCollider>();
                if (collider == null)
                {
                    collider = child.gameObject.AddComponent<MeshCollider>();
                }
                collider.sharedMesh = meshFilter.sharedMesh;
                collider.convex = true;
            }

            var renderer = child.GetComponent<MeshRenderer>();
            if (renderer != null)
            {
                Object.DestroyImmediate(renderer);
            }
            if (meshFilter != null)
            {
                Object.DestroyImmediate(meshFilter);
            }
        }
    }
}
#endif
"""

    @classmethod
    def _write_postprocessor_helper(cls, export_dir: str, warnings: list[str]) -> None:
        """Writes Editor/OmniMeshPostprocessor.cs alongside the exported FBX."""
        editor_dir = os.path.join(export_dir, "Editor")
        cs_path = os.path.join(editor_dir, "OmniMeshPostprocessor.cs")
        try:
            os.makedirs(editor_dir, exist_ok=True)
            with open(cs_path, "w", encoding="utf-8") as f:
                f.write(cls.generate_postprocessor_cs())
        except OSError as exc:
            warnings.append(f"unity_postprocessor: {exc}")
            logger.warning("Could not write Unity Editor helper '%s': %s", cs_path, exc)

    @classmethod
    def export_asset(
        cls,
        context: bpy.types.Context | None,
        export_dir: str,
        asset_name: str,
        **kwargs: object,
    ) -> tuple[bool, str]:
        if not bpy or not context:
            return False, "Blender bpy not available."
        clean_name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(asset_name)).strip() or "SM_Asset"

        try:
            os.makedirs(export_dir, exist_ok=True)
        except OSError as exc:
            return False, f"Failed creating export directory '{export_dir}': {exc}"

        bdata_in = kwargs.get("blend_data")
        bdata: BlendData | None = (
            bdata_in if (bdata_in is not None and isinstance(bdata_in, BlendData)) else context.blend_data
        )
        payload = (
            AssetMeshResolver.resolve_payload(context, clean_name, blend_data=bdata) if AssetMeshResolver else None
        )
        if not payload or not payload.lod_tiers:
            return False, f"No generated LOD objects found for '{asset_name}'"

        if context.mode != "OBJECT":
            try:
                bpy.ops.object.mode_set(mode="OBJECT")
            except (RuntimeError, AttributeError, TypeError) as exc:
                logger.debug("Mode set to OBJECT skipped: %s", exc)

        export_objects: list[bpy.types.Object] = []
        for tier_idx in sorted(payload.lod_tiers.keys()):
            for obj in payload.lod_tiers[tier_idx]:
                if obj not in export_objects:
                    export_objects.append(obj)

        if not export_objects:
            return False, f"No generated LOD objects found for '{asset_name}'"

        collider_objects = list(payload.collider_objects)
        armature_obj = payload.armature_obj
        all_export_items = export_objects + collider_objects + ([armature_obj] if armature_obj else [])

        vl = context.view_layer
        orig_active = vl.objects.active if (vl and vl.objects is not None) else None
        orig_selected = list(context.selected_objects or ())
        visibility_warnings: list[str] = []

        orig_collider_names: dict[bpy.types.Object, str] = {}
        orig_lod_names: dict[bpy.types.Object, str] = {}
        fbx_path = os.path.join(export_dir, f"{clean_name}.fbx")

        try:
            # Normalize collider names for Unity C# postprocessor regex (_Collider\d*|UCX_)
            for idx, c_obj in enumerate(collider_objects, start=1):
                orig_collider_names[c_obj] = c_obj.name
                if not (c_obj.name.startswith("UCX_") or "_Collider" in c_obj.name):
                    c_obj.name = f"{clean_name}_Collider_{idx:02d}"

            orig_lod_names = _normalize_unity_lod_names(payload, clean_name)

            with scoped_export_visibility(context, all_export_items, warnings=visibility_warnings):
                bpy.ops.object.select_all(action="DESELECT")
                for obj in export_objects:
                    obj.select_set(True)
                for c_obj in collider_objects:
                    c_obj.select_set(True)
                if armature_obj:
                    armature_obj.select_set(True)

                if armature_obj and vl and vl.objects is not None:
                    vl.objects.active = armature_obj
                elif export_objects and vl and vl.objects is not None:
                    vl.objects.active = export_objects[0]

                bpy.ops.export_scene.fbx(
                    filepath=fbx_path,
                    use_selection=True,
                    apply_unit_scale=True,
                    apply_scale_options="FBX_SCALE_ALL",
                    bake_space_transform=False if armature_obj else True,
                    add_leaf_bones=False if armature_obj else True,
                    object_types={"MESH", "ARMATURE", "EMPTY"},
                    mesh_smooth_type="FACE",
                    primary_bone_axis="Y",
                    secondary_bone_axis="X",
                    armature_nodetype="NULL",
                )
                cls._write_postprocessor_helper(export_dir, visibility_warnings)
                return True, f"Unity FBX package exported to: {fbx_path}"
        except (
            OmniMeshError,
            RuntimeError,
            ValueError,
            TypeError,
            AttributeError,
            LookupError,
            OSError,
            ReferenceError,
            ZeroDivisionError,
        ) as e:
            return False, f"Failed to export Unity FBX: {str(e)}"
        finally:
            for obj, orig_name in orig_lod_names.items():
                try:
                    obj.name = orig_name
                except (RuntimeError, AttributeError, ReferenceError) as exc:
                    visibility_warnings.append(f"lod name {orig_name}: {exc}")
                    logger.debug("Could not restore LOD name for %s: %s", orig_name, exc)

            for c_obj, orig_name in orig_collider_names.items():
                try:
                    c_obj.name = orig_name
                except (RuntimeError, AttributeError, ReferenceError) as exc:
                    visibility_warnings.append(f"collider name {orig_name}: {exc}")
                    logger.debug("Could not restore collider name for %s: %s", orig_name, exc)

            # Restore original selection and active object
            if bpy:
                try:
                    bpy.ops.object.select_all(action="DESELECT")
                    for o in orig_selected:
                        o.select_set(True)
                    if vl and vl.objects is not None and orig_active:
                        vl.objects.active = orig_active
                except (RuntimeError, AttributeError, ReferenceError) as exc:
                    visibility_warnings.append(f"selection: {exc}")
                    logger.debug("Could not restore selection state: %s", exc)
            if visibility_warnings:
                logger.warning(
                    "Unity export visibility/cleanup warnings (%d): %s",
                    len(visibility_warnings),
                    "; ".join(visibility_warnings),
                )
